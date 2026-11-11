"""Large diagnostic files keep their full manifest and are verified after the last chunk."""

import hashlib
import io
import os
import zipfile
from types import SimpleNamespace
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from plane.db.models import Project, ProjectMember
from plane.quality.models import Defect, ProblemPackage

pytestmark = [pytest.mark.contract, pytest.mark.django_db]
CHUNK = 4 * 1024 * 1024


@pytest.fixture
def upload_case(session_client, workspace, create_user, settings, tmp_path, mocker):
    settings.QUALITY_ATTACHMENT_ROOT = str(tmp_path)
    project = Project.objects.create(workspace=workspace, name="完整材料", identifier="LARGE")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    defect = Defect.objects.create(project=project, title="大文件尾部故障", created_by=create_user)
    schedule = mocker.patch("plane.quality.diagnostics.schedule_automatic")
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    return session_client, base, project, defect, schedule


def register(case, raw, name="diagnostics.zip", digest=None):
    client, base, _, defect, _ = case
    response = client.post(
        base + "packages/",
        {
            "name": "完整材料",
            "defect_id": str(defect.id),
            "source_system": "ENGRAM_DAQ",
            "external_id": name,
            "files": [{"path": name, "size": len(raw), "sha256": digest or hashlib.sha256(raw).hexdigest()}],
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    return base + f"packages/{response.data['id']}/files/", response.data["id"]


def send(case, url, raw, index, count, name="diagnostics.zip"):
    return case[0].post(
        url,
        {
            "file": SimpleUploadedFile("chunk.bin", raw),
            "manifest_path": name,
            "chunk_index": index,
            "chunk_count": count,
        },
        format="multipart",
    )


def test_incompressible_zip_chunk_retry_readback_and_full_tail_scan(upload_case):
    # Store random bytes without compression so the regression exceeds 20 MiB on the wire.
    log = os.urandom(24 * 1024 * 1024) + b"\nERROR connection refused E-COMPLETE-TAIL\n"
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("logs/system.log", log)
        archive.writestr("environment.json", '{"runtime":"complete"}')
        archive.writestr("manifest.json", '{"complete":true}')
    raw = stream.getvalue()
    url, package_id = register(upload_case, raw)
    chunks = [raw[offset : offset + CHUNK] for offset in range(0, len(raw), CHUNK)]
    # Accept out of order and duplicate chunks without exposing a partial PackageFile.
    for index in [1, 1, 0, *range(2, len(chunks) - 1)]:
        result = send(upload_case, url, chunks[index], index, len(chunks))
        assert result.status_code == 202, result.content
        assert not ProblemPackage.objects.get(pk=package_id).uploaded_files.exists()
        upload_case[4].assert_not_called()
    result = send(upload_case, url, chunks[-1], len(chunks) - 1, len(chunks))
    assert result.status_code == 201, result.content
    retry = send(upload_case, url, chunks[-1], len(chunks) - 1, len(chunks))
    assert retry.status_code == 200 and retry.data["id"] == result.data["id"]
    upload_case[4].assert_called_once()
    downloaded = upload_case[0].get(upload_case[1] + f"files/{result.data['id']}/download/")
    digest = hashlib.sha256()
    for piece in downloaded.streaming_content:
        digest.update(piece)
    assert digest.hexdigest() == hashlib.sha256(raw).hexdigest()
    assert ProblemPackage.objects.get(pk=package_id).status == "files_verified"
    from plane.quality.diagnostic_materials import inspect

    job = SimpleNamespace(
        result={"input": {"files": [result.data["id"]]}}, project=upload_case[2], defect=upload_case[3]
    )
    _, sources, _ = inspect(job)
    evidence = next(row for row in sources if row.get("archive_entry") == "logs/system.log")
    assert evidence["scanned_bytes"] == len(log)
    assert "E-COMPLETE-TAIL" in evidence["excerpt"]
    assert not evidence["scan_incomplete"]


def test_chunk_shape_conflicts_and_corrupt_final_digest_do_not_register(upload_case):
    raw = b"x" * (CHUNK + 10)
    url, package_id = register(upload_case, raw, name="system.log", digest="0" * 64)
    assert send(upload_case, url, raw[:CHUNK], 0, 3, "system.log").status_code == 400
    assert send(upload_case, url, raw[:10], 0, 2, "system.log").status_code == 400
    assert send(upload_case, url, raw[:CHUNK], 0, 2, "system.log").status_code == 202
    assert send(upload_case, url, b"y" * CHUNK, 0, 2, "system.log").status_code == 409
    assert send(upload_case, url, raw[CHUNK:], 1, 2, "system.log").status_code == 400
    assert not ProblemPackage.objects.get(pk=package_id).uploaded_files.exists()
    upload_case[4].assert_not_called()


def test_zip_over_100mib_expanded_has_streaming_validation():
    from plane.quality.attachments import validate_archive

    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        with archive.open("logs/full.log", "w") as log:
            for _ in range(105):
                log.write(b"a" * 1024 * 1024)
    stream.seek(0)
    validate_archive(stream, "diagnostics.zip")


def test_range_readback_is_bounded_validated_and_project_scoped(upload_case, workspace):
    from plane.quality.attachments import directory
    from plane.quality.models import PackageFile
    from uuid import uuid4

    raw = os.urandom(5 * 1024 * 1024 + 17)
    url, package_id = register(upload_case, raw, name="range.log")
    row = PackageFile.objects.create(
        project=upload_case[2],
        package_id=package_id,
        name="range.log",
        size=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        storage_key=uuid4().hex + ".bin",
    )
    (directory() / row.storage_key).write_bytes(raw)
    endpoint = upload_case[1] + f"files/{row.id}/download/"
    meta = upload_case[0].get(endpoint + "?metadata=1")
    assert meta.status_code == 200 and meta.data["size"] == len(raw)
    response = upload_case[0].get(endpoint, HTTP_RANGE="bytes=1048576-2097151")
    assert response.status_code == 206
    assert response["Content-Range"] == f"bytes 1048576-2097151/{len(raw)}"
    assert response["Accept-Ranges"] == "bytes"
    assert b"".join(response.streaming_content) == raw[1048576:2097152]
    response = upload_case[0].get(endpoint + f"?offset={4 * 1024 * 1024}&length={4 * 1024 * 1024}")
    assert response.status_code == 206 and b"".join(response.streaming_content) == raw[4 * 1024 * 1024 :]
    for value in [
        "bytes=-1",
        "bytes=0-999999999",
        "bytes=0-1,4-5",
        "bytes=-5-1",
        "bytes=7-2",
        "bad",
        "bytes=" + ("9" * 5000) + "-1",
    ]:
        result = upload_case[0].get(endpoint, HTTP_RANGE=value)
        assert result.status_code == 416 and result["Content-Range"] == f"bytes */{len(raw)}"
    for query in ["?offset=" + ("9" * 5000) + "&length=1", "?offset=0&length=" + ("9" * 5000)]:
        assert upload_case[0].get(endpoint + query).status_code == 416
    other = Project.objects.create(workspace=workspace, name="其他项目", identifier="OTHERFILE")
    other_base = upload_case[1].replace(str(upload_case[2].id), str(other.id))
    assert upload_case[0].get(other_base + f"files/{row.id}/download/", HTTP_RANGE="bytes=0-10").status_code == 403
