"""Near-limit diagnostic transport and full scan; not a production throughput benchmark."""
import hashlib
import os
import time
import zipfile
from types import SimpleNamespace
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from plane.db.models import Project, ProjectMember
from plane.quality.models import Defect, ProblemPackage

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def test_near_200mib_stored_zip_complete_upload_retry_readback_and_scan(
    session_client, workspace, create_user, settings, tmp_path, mocker
):
    settings.QUALITY_ATTACHMENT_ROOT = str(tmp_path / 'attachments')
    project = Project.objects.create(workspace=workspace, name='V07 大包边界', identifier='CAP162')
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    defect = Defect.objects.create(project=project, title='接近材料上限的分块与全量扫描', created_by=create_user)
    scheduled = mocker.patch('plane.quality.diagnostics.schedule_automatic')
    base = f'/api/workspaces/{workspace.slug}/projects/{project.id}/quality/'
    log = tmp_path / 'full.log'
    target_bytes = 196 * 1024 * 1024
    # Exact-size ASCII log blocks with random payloads, stored without compression.
    with log.open('wb') as f:
        while f.tell() < target_bytes:
            block = b''.join(
                b'2026-11-10T12:00:00+08:00 INFO record=' + os.urandom(48).hex().encode() + b'\n'
                for _ in range(4096)
            )
            f.write(block[:target_bytes - f.tell()])
        f.write(b'\n2026-11-10T12:01:00+08:00 ERROR ConnectionRefusedError errno=111 E-CAPACITY-TAIL\n')
    archive = tmp_path / 'diagnostics.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as z:
        z.write(log, 'logs/system.log')
        z.writestr('environment.json', '{"isolated_capacity_test":true}')
    digest = hashlib.sha256()
    with archive.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(block)
    total = archive.stat().st_size
    request = session_client.post(base+'packages/', {'name':'大包容量验收','defect_id':str(defect.id),
        'source_system':'capacity-test','external_id':'one-off-196mib',
        'files':[{'path':'diagnostics.zip','size':total,'sha256':digest.hexdigest()}]},format='json')
    assert request.status_code == 201, request.content
    package_id = request.data['id']
    url = base+f'packages/{package_id}/files/'
    started = time.monotonic()
    chunk = 4 * 1024 * 1024
    count=(total+chunk-1)//chunk
    with archive.open('rb') as f:
        for index in range(count):
            payload = f.read(chunk)
            response = session_client.post(url, {'file':SimpleUploadedFile('chunk.bin',payload),
                'manifest_path':'diagnostics.zip','chunk_index':index,'chunk_count':count},format='multipart')
            assert response.status_code == (201 if index==count-1 else 202), response.content
            if index==0:
                duplicate=session_client.post(url, {'file':SimpleUploadedFile('chunk.bin',payload),
                    'manifest_path':'diagnostics.zip','chunk_index':index,'chunk_count':count},format='multipart')
                assert duplicate.status_code==202
                assert not ProblemPackage.objects.get(pk=package_id).uploaded_files.exists()
                scheduled.assert_not_called()
    scheduled.assert_called_once()
    transfer_seconds=time.monotonic()-started
    response_id=response.data['id']
    got=session_client.get(base+f'files/{response_id}/download/')
    actual=hashlib.sha256()
    read_bytes=0
    for part in got.streaming_content:
        actual.update(part)
        read_bytes+=len(part)
    assert read_bytes==total and actual.hexdigest()==digest.hexdigest()
    from plane.quality.diagnostic_materials import inspect
    began=time.monotonic()
    _,sources,_=inspect(SimpleNamespace(result={'input':{'files':[response_id]}},project=project,defect=defect))
    scan_seconds=time.monotonic()-began
    evidence=next(row for row in sources if row.get('archive_entry')=='logs/system.log')
    print({'wire_bytes':total,'log_bytes':log.stat().st_size,'chunks':count,'transfer_seconds':transfer_seconds,
        'scan_seconds':scan_seconds,'scanned_bytes':evidence.get('scanned_bytes'),'incomplete':evidence.get('scan_incomplete'),
        'tail_found':'E-CAPACITY-TAIL' in evidence.get('excerpt',''),'sha256_equal':True})
    assert evidence['scanned_bytes']==log.stat().st_size
    assert not evidence['scan_incomplete']
    assert 'E-CAPACITY-TAIL' in evidence['excerpt']
