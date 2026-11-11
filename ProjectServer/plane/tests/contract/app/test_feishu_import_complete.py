"""Feishu block imports preserve order/materials and refuse partial documents."""

import hashlib
import json
from unittest.mock import Mock
import pytest
from plane.db.models import Project, ProjectMember
from plane.quality.models import DocumentImport
from plane.knowledge.models import Article

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def fs_import(session_client, workspace, create_user, settings, tmp_path, mocker):
    settings.QUALITY_ATTACHMENT_ROOT = str(tmp_path / "private")
    project = Project.objects.create(workspace=workspace, name="飞书完整资料", identifier="FS164")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    mocker.patch(
        "plane.quality.document_imports.read_connection",
        return_value={
            "kind": "feishu",
            "base_url": "https://open.feishu.cn",
            "service_token": "test-only-service-token",
        },
    )
    return session_client, f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/", project


def data_url():
    return {"resource": "knowledge", "source_instance": "fs-test", "url": "https://engram.feishu.cn/docx/document123"}


PNG = __import__("base64").b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
)


def result(failures=None, raw=PNG):
    return {
        "format": "feishu_docx",
        "document_id": "document123",
        "blocks": [{"block_id": "p1", "kind": "page", "order": 0}],
        "segments": [
            {"block_id": "text1", "kind": "heading1", "locator": "飞书 标题块 text1", "text": "采集排查"},
            {"block_id": "cell1", "kind": "table_cell", "locator": "飞书 单元格 cell1", "text": "检查端口监听"},
        ],
        "attachments": [
            {
                "block_id": "img1",
                "kind": "image",
                "name": "img1.png",
                "token": "media123",
                "size": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "raw": raw,
            }
        ],
        "failures": failures or [],
        "valid": not failures,
    }


def test_complete_block_preview_saves_snapshot_images_sha_and_private_source(fs_import, mocker):
    client, base, project = fs_import
    block_result = result()
    mocker.patch("plane.quality.feishu_document_blocks.read_document", return_value=block_result)
    response = client.post(base + "document-imports/feishu/", data_url(), format="json")
    assert response.status_code == 201 and response.data["valid"], response.content
    assert response.data["extraction"]["format"] == "feishu_docx"
    assert response.data["extraction"]["files_complete"] is True
    assert "检查端口监听" in response.data["rows"][0]["content"]
    assert "cell1" in response.data["rows"][0]["content"]
    row = DocumentImport.objects.get(pk=response.data["id"])
    assert row.files.count() == 2 and set(row.files.values_list("kind", flat=True)) == {"original", "image"}
    image = row.files.get(kind="image")
    assert image.sha256 == hashlib.sha256(PNG).hexdigest()
    original = row.files.get(kind="original")
    downloaded = client.get(base + f"document-files/{original.id}/")
    snapshot = json.loads(b"".join(downloaded.streaming_content))
    assert snapshot["document_id"] == "document123" and "blocks" in snapshot
    assert "test-only-service-token" not in json.dumps(snapshot)
    assert not Article.objects.filter(project=project).exists()
    confirmed = client.post(base + f"document-imports/{row.id}/confirm/", {}, format="json")
    assert confirmed.status_code == 201, confirmed.content
    article = Article.objects.get(pk=confirmed.data["object_ids"][0])
    assert article.status == "draft"
    analysis = client.get(base.replace("quality/", "knowledge/") + f"articles/{article.id}/analysis/")
    assert analysis.status_code == 200, analysis.content
    assert all(s.get("locator", "").startswith("飞书") for s in analysis.data["segments"])


def test_missing_block_or_file_keeps_invalid_preview_and_blocks_confirm(fs_import, mocker):
    client, base, p = fs_import
    mocker.patch(
        "plane.quality.feishu_document_blocks.read_document",
        return_value=result([{"block_id": "missing-file", "stage": "download", "error": "附件无权限，尚未完整读取"}]),
    )
    response = client.post(base + "document-imports/feishu/", data_url(), format="json")
    assert response.status_code == 201 and not response.data["valid"], response.content
    assert response.data["extraction"]["files_complete"] is False
    assert response.data["errors"][0]["range"]["block_id"] == "missing-file"
    assert client.post(base + f"document-imports/{response.data['id']}/confirm/", {}, format="json").status_code == 400
    assert not Article.objects.filter(project=p).exists()


def test_media_change_updates_import_identity_even_when_text_is_unchanged(fs_import, mocker):
    client, base, p = fs_import
    mocker.patch(
        "plane.quality.feishu_document_blocks.read_document",
        side_effect=[result(raw=PNG + b"v1"), result(raw=PNG + b"v2")],
    )
    first = client.post(base + "document-imports/feishu/", data_url(), format="json")
    second = client.post(base + "document-imports/feishu/", data_url(), format="json")
    assert first.status_code == second.status_code == 201
    assert first.data["id"] != second.data["id"]
    assert DocumentImport.objects.filter(project=p).count() == 2


def test_binary_download_fixed_path_sha_limits_and_no_redirect(mocker):
    from plane.quality.feishu_document_blocks import FeishuTransport

    response = Mock()
    response.status_code = 200
    response.headers = {"Content-Type": "image/png", "Content-Length": "3"}
    response.iter_content.return_value = [b"abc"]
    session = Mock()
    session.get.return_value = response
    transport = FeishuTransport("never-output", session=session)
    value = transport.download("/open-apis/drive/v1/medias/media123/download", 10)
    assert value["raw"] == b"abc" and value["sha256"] == hashlib.sha256(b"abc").hexdigest()
    assert session.get.call_args.args[0] == "https://open.feishu.cn/open-apis/drive/v1/medias/media123/download"
    assert session.get.call_args.kwargs["allow_redirects"] is False
    with pytest.raises(Exception):
        transport.download("https://evil.invalid/read", 10)
    assert session.get.call_count == 1


def test_actual_transport_rejects_html_or_official_error_bytes(mocker):
    from plane.quality.feishu_document_blocks import FeishuTransport

    for payload, kind in [
        (b"<html>Permission denied</html>", "text/html"),
        (b'{"code":99991663,"msg":"permission denied"}', "application/json"),
    ]:
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Type": kind, "Content-Length": str(len(payload))}
        response.iter_content.return_value = [payload]
        session = Mock()
        session.get.return_value = response
        transport = FeishuTransport("test-token", session=session)
        with pytest.raises(Exception):
            transport.download("/open-apis/drive/v1/medias/media123/download", 1024)
