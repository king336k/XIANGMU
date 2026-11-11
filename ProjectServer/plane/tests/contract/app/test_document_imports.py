"""Document imports are previewed and create drafts, never auto-published business objects."""

import json
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from plane.db.models import Project, ProjectMember
from plane.knowledge.models import Article
from plane.quality.models import Requirement

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def doc_imports(workspace, create_user):
    p = Project.objects.create(workspace=workspace, name="文档导入", identifier="DOC")
    ProjectMember.objects.create(project=p, member=create_user, role=20)
    return f"/api/workspaces/{workspace.slug}/projects/{p.id}/quality/", p


def test_markdown_preview_and_confirm_create_knowledge_draft_once(session_client, doc_imports):
    base, p = doc_imports
    file = SimpleUploadedFile(
        "采集排查.md", "# 采集排查\n先检查网络，再检查日志。".encode(), content_type="text/markdown"
    )
    preview = session_client.post(
        base + "document-imports/", {"resource": "knowledge", "file": file}, format="multipart"
    )
    assert preview.status_code == 201 and preview.data["valid"], preview.content
    assert not Article.objects.filter(project=p).exists()
    confirmed = session_client.post(base + f"document-imports/{preview.data['id']}/confirm/", {}, format="json")
    assert confirmed.status_code == 201, confirmed.content
    assert Article.objects.filter(project=p, status="draft", publication_active=False).count() == 1
    retry = session_client.post(base + f"document-imports/{preview.data['id']}/confirm/", {}, format="json")
    assert retry.status_code == 200 and retry.data["object_ids"] == confirmed.data["object_ids"]


def test_requirements_json_has_row_errors_and_cannot_write_until_corrected(session_client, doc_imports):
    base, p = doc_imports
    file = SimpleUploadedFile(
        "requirements.json",
        json.dumps(
            [{"title": "页面增加提示", "acceptance": "内容正确"}, {"title": "", "acceptance": "不应写入"}]
        ).encode(),
        content_type="application/json",
    )
    preview = session_client.post(
        base + "document-imports/", {"resource": "requirements", "file": file}, format="multipart"
    )
    assert preview.status_code == 201 and not preview.data["valid"] and preview.data["errors"][0]["row"] == 2, (
        preview.content
    )
    assert (
        session_client.post(base + f"document-imports/{preview.data['id']}/confirm/", {}, format="json").status_code
        == 400
    )
    assert not Requirement.objects.filter(project=p).exists()


def test_feishu_source_is_official_and_unconfigured_is_explicit(session_client, doc_imports):
    base, p = doc_imports
    bad = session_client.post(
        base + "document-imports/feishu/",
        {"resource": "knowledge", "source_instance": "feishu-main", "url": "http://169.254.169.254/wiki/secret"},
        format="json",
    )
    assert bad.status_code == 400, bad.content
    absent = session_client.post(
        base + "document-imports/feishu/",
        {
            "resource": "knowledge",
            "source_instance": "feishu-main",
            "url": "https://engram-ai.feishu.cn/wiki/OkIlww1y7ilDO9koyFPcLie3n7f",
        },
        format="json",
    )
    assert absent.status_code == 503, absent.content


def test_feishu_text_is_previewed_and_never_published_automatically(session_client, doc_imports, mocker):
    base, p = doc_imports
    mocker.patch(
        "plane.quality.document_imports.read_connection",
        return_value={"kind": "feishu", "base_url": "https://open.feishu.cn", "service_token": "test-only"},
    )
    mocker.patch(
        "plane.quality.document_imports.feishu_get",
        return_value={"node": {"obj_type": "docx", "obj_token": "docToken123", "title": "飞书需求说明"}},
    )
    mocker.patch("plane.quality.feishu_document_blocks.read_document",return_value={
        'format':'feishu_docx','document_id':'docToken123','blocks':[{'block_id':'b1','kind':'text'}],
        'segments':[{'block_id':'b1','kind':'text','locator':'飞书正文块 b1',
                     'text':'本地接口模拟：测试员提交证据后，经理复核。'}],
        'attachments':[],'failures':[],'valid':True,
    })
    response = session_client.post(
        base + "document-imports/feishu/",
        {"resource": "knowledge", "source_instance": "feishu-main", "url": "https://engram-ai.feishu.cn/wiki/token123"},
        format="json",
    )
    assert response.status_code == 201 and response.data["valid"], response.content
    assert not Article.objects.filter(project=p).exists()
