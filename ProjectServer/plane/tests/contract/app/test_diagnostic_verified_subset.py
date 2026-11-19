"""Read-only analysis of verified subsets cannot grant full-coverage decisions."""
import hashlib
import io
import json
from pathlib import Path
from uuid import uuid4
import zipfile

import pytest

from plane.quality.models import PackageFile, ProblemPackage
from plane.quality.tasks import run_diagnostic
from plane.tests.contract.app.test_diagnostic_finalization import diagnostic

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def prepare(workspace, create_user, settings, tmp_path, mocker):
    from plane.quality.diagnostic_materials import inspect
    project, job = diagnostic(workspace, create_user, mocker)
    settings.QUALITY_ATTACHMENT_ROOT = str(tmp_path)
    job.defect.severity = ''; job.defect.save(update_fields=['severity'])
    mocker.patch('plane.quality.tasks.inspect', side_effect=inspect)
    def add(raw, name, digest=None):
        package = ProblemPackage.objects.create(project=project, defect=job.defect,
            name=name, source_system='ENGRAM_TELEOP_DAQ', external_id=uuid4().hex,
            status='files_verified', files=[])
        row = PackageFile.objects.create(project=project, package=package, name=name, size=len(raw),
            sha256=digest or hashlib.sha256(raw).hexdigest(), storage_key=uuid4().hex)
        (tmp_path/row.storage_key).write_bytes(raw)
        return row
    return job, add


def test_real_zip_verified_but_partial_semantic_scan_still_analyzes_observed_json(workspace, create_user, settings, tmp_path, mocker):
    from plane.quality.diagnostic_materials import collect
    job, add = prepare(workspace, create_user, settings, tmp_path, mocker)
    root = 'joint limit violation'
    add(json.dumps({'sourceSystem': 'ENGRAM_TELEOP_DAQ', 'evidence': {'observations': {
        'teleop': {'data': {'observations': {'nodes': {'data': {'processes': [
            {'name': 'solver', 'lines': ['2026-11-19 20:44:14 ERROR '+root]}]}}}}}}}}).encode(), 'feedback.json')
    fixture = Path('/test-artifacts/uploaded-d498.zip')
    assert fixture.exists(), 'the supplied verified incident ZIP is required for this regression'
    row = add(fixture.read_bytes(), 'diagnostics.zip')
    def partial(stream, size, *args, **kwargs):
        if size > 100*1024*1024:
            return stream.read(65536), 65536, True
        return collect(stream, size, *args, **kwargs)
    mocker.patch('plane.quality.diagnostic_materials.collect', side_effect=partial)
    model = mocker.patch('plane.quality.tasks.analyze_diagnostic', return_value={
        'answer': '已读取日志确认关节限位异常；其余材料未完整扫描。', 'citations': [],
        'severity_assessment': {'severity': 'major', 'basis': 'model assertion'}, 'repaired': True})
    from types import SimpleNamespace
    clock = iter([0, 21, 22])
    mocker.patch('plane.quality.tasks.time', SimpleNamespace(monotonic=lambda: next(clock)))
    route = mocker.patch('plane.quality.module_routing.route_completed')
    severity = mocker.patch('plane.quality.diagnostic_severity_apply.apply_severity')
    run_diagnostic(job.id)
    job.refresh_from_db(); job.defect.refresh_from_db()
    assert model.call_count == 1
    config, text, sources, references, _ = model.call_args.args
    assert config['analysis_scope'] == 'verified_read_subset' and config['material_coverage'] == 'partial'
    assert config['partial_source_warning']['unread_sources']
    assert root in text and any(ref['reference']=='MATERIAL-COVERAGE' for ref in references)
    partial_source = next(source for source in sources if source.get('file_bytes') == 194189145)
    assert partial_source['integrity_verified'] and partial_source['scan_incomplete']
    assert partial_source['semantic_scan_complete'] is False
    assert job.result['model_status'] == 'completed' and job.result['materials_status'] == 'partial'
    assert job.result['analysis_scope'] == 'verified_read_subset'
    assert job.result['semantic_scan_complete'] is False and job.result['integrity_verified'] is True
    assert job.result['repaired'] is False and job.result['severity_assessment']['severity'] == ''
    route.assert_not_called(); severity.assert_not_called()
    assert job.defect.severity == ''


@pytest.mark.parametrize('invalid', ['sha', 'crc', 'unsafe_zip', 'size'])
def test_integrity_failure_blocks_model_even_with_good_feedback(workspace, create_user, settings, tmp_path, mocker, invalid):
    job, add = prepare(workspace, create_user, settings, tmp_path, mocker)
    add(b'ERROR verified complete fault\n', 'good.log')
    stream=io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('../escape.log' if invalid=='unsafe_zip' else 'bad.log', b'ERROR corrupt_payload\n')
    raw=stream.getvalue()
    if invalid=='crc': raw=raw.replace(b'corrupt_payload', b'changed_payload')
    row=add(raw, 'bad.zip', digest='0'*64 if invalid=='sha' else None)
    if invalid=='size': (tmp_path/row.storage_key).write_bytes(raw+b'x')
    model=mocker.patch('plane.quality.tasks.analyze_diagnostic')
    route=mocker.patch('plane.quality.module_routing.route_completed')
    severity=mocker.patch('plane.quality.diagnostic_severity_apply.apply_severity')
    run_diagnostic(job.id);job.refresh_from_db()
    model.assert_not_called(); route.assert_not_called(); severity.assert_not_called()
    assert job.result['model_status']=='material_integrity_failed'
    bad=next(value for value in job.result['material_coverage'] if value['file_id']==str(row.id))
    assert bad['verified'] is False and bad['integrity_verified'] is False
