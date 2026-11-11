import io
import zipfile
import hashlib
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from plane.db.models import Project, ProjectMember

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture(autouse=True)
def clean_test_attachment_storage():
    from pathlib import Path
    import shutil

    root = Path("/code/.test-quality-attachments")
    yield
    if root.exists():
        shutil.rmtree(root)


def test_real_diagnostic_upload_hash_download_and_bad_archive(session_client, workspace, create_user, settings):
    settings.QUALITY_ATTACHMENT_ROOT = str(__import__("pathlib").Path("/code/.test-quality-attachments"))
    project = Project.objects.create(workspace=workspace, name="诊断文件", identifier="FILES")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    defect = session_client.post(base + "defects/", {"title": "诊断文件"}, format="json").data
    manifest = {
        "name": "诊断",
        "source_system": "daq",
        "external_id": "pkg-local",
        "defect_id": defect["id"],
        "files": [{"path": "recording.log", "size": 5, "sha256": hashlib.sha256(b"hello").hexdigest()}],
    }
    package = session_client.post(base + "packages/", manifest, format="json").data
    uploaded = session_client.post(
        base + f"packages/{package['id']}/files/",
        {"file": SimpleUploadedFile("recording.log", b"hello", content_type="text/plain")},
        format="multipart",
    )
    assert uploaded.status_code == 201, uploaded.content
    assert uploaded.data["sha256"] == manifest["files"][0]["sha256"]
    download = session_client.get(base + f"files/{uploaded.data['id']}/download/")
    assert download.status_code == 200 and b"".join(download.streaming_content) == b"hello"
    bad = session_client.post(
        base + f"packages/{package['id']}/files/",
        {"file": SimpleUploadedFile("recording.log", b"changed", content_type="text/plain")},
        format="multipart",
    )
    assert bad.status_code == 400
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("../../escape.txt", "bad")
    raw = archive.getvalue()
    manifest["external_id"] = "zip-local"
    manifest["files"] = [{"path": "diagnostic.zip", "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}]
    pkg = session_client.post(base + "packages/", manifest, format="json").data
    assert (
        session_client.post(
            base + f"packages/{pkg['id']}/files/",
            {"file": SimpleUploadedFile("diagnostic.zip", raw, content_type="application/zip")},
            format="multipart",
        ).status_code
        == 400
    )


def test_manifest_relative_path_can_be_uploaded_without_using_it_as_disk_path(
    session_client, workspace, create_user, settings
):
    settings.QUALITY_ATTACHMENT_ROOT = "/code/.test-quality-attachments"
    project = Project.objects.create(workspace=workspace, name="嵌套路径", identifier="NEST")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    defect = session_client.post(base + "defects/", {"title": "嵌套文件"}, format="json").data
    package = session_client.post(
        base + "packages/",
        {
            "name": "目录清单",
            "source_system": "daq",
            "external_id": "nested",
            "defect_id": defect["id"],
            "files": [{"path": "logs/recording.log", "size": 5, "sha256": hashlib.sha256(b"hello").hexdigest()}],
        },
        format="json",
    ).data
    response = session_client.post(
        base + f"packages/{package['id']}/files/",
        {"manifest_path": "logs/recording.log", "file": SimpleUploadedFile("recording.log", b"hello")},
        format="multipart",
    )
    assert response.status_code == 201, response.content
    assert response.data["name"] == "logs/recording.log"


def test_direct_defect_file_and_safe_image_preview(session_client, workspace, create_user, settings):
    settings.QUALITY_ATTACHMENT_ROOT = "/code/.test-quality-attachments"
    project = Project.objects.create(workspace=workspace, name="手工附件", identifier="DIRECT")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    defect = session_client.post(base + "defects/", {"title": "手工附件"}, format="json").data
    url = base + f"defects/{defect['id']}/attachments/"
    log = session_client.post(url, {"file": SimpleUploadedFile("recording.log", b"diagnostic log")}, format="multipart")
    assert log.status_code == 201, log.content
    png = __import__("base64").b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl1sAAAAASUVORK5CYII="
    )
    picture = session_client.post(
        url, {"file": SimpleUploadedFile("screenshot.png", png, content_type="image/png")}, format="multipart"
    )
    assert picture.status_code == 201
    preview = session_client.get(base + f"files/{picture.data['id']}/preview/")
    assert preview.status_code == 200 and preview["Content-Type"] == "image/png"
    assert b"".join(preview.streaming_content) == png
    rows = session_client.get(url).data
    assert len(rows) == 2 and {r["name"] for r in rows} == {"recording.log", "screenshot.png"}
    assert (
        session_client.post(
            url, {"file": SimpleUploadedFile("unsafe.svg", b'<svg onload="alert(1)"/>')}, format="multipart"
        ).status_code
        == 400
    )


def test_log_preview_returns_complete_file_beyond_old_limit(session_client, workspace, create_user, settings):
    settings.QUALITY_ATTACHMENT_ROOT = "/code/.test-quality-attachments"
    project = Project.objects.create(workspace=workspace, name="完整日志", identifier="FULLLOG")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    defect = session_client.post(base + "defects/", {"title": "完整日志"}, format="json").data
    raw = ("采集诊断记录\n" * 30000 + "日志末尾验收标记").encode()
    uploaded = session_client.post(
        base + f"defects/{defect['id']}/attachments/", {"file": SimpleUploadedFile("full.log", raw)}, format="multipart"
    )
    assert uploaded.status_code == 201
    preview = session_client.get(base + f"files/{uploaded.data['id']}/preview/")
    assert preview.status_code == 200, preview.content if not preview.streaming else ""
    assert b"".join(preview.streaming_content) == raw
