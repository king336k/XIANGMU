"""A model interpretation is a bounded, cited preview; only a signed human application edits drafts."""

import pytest
from django.urls import path
from django.test import override_settings
from plane.db.models import Project, ProjectMember, WorkspaceMember
from plane.quality.models import BusinessRole, ProjectRolePolicy
from plane.knowledge.models import Article, ArticleEvent
from plane.knowledge.document_analysis import ArticleAnalysis, ArticleAnalysisApply

urlpatterns = [
    path(
        "api/workspaces/<slug:slug>/projects/<uuid:project_id>/knowledge/articles/<uuid:pk>/analysis/",
        ArticleAnalysis.as_view(),
    ),
    path(
        "api/workspaces/<slug:slug>/projects/<uuid:project_id>/knowledge/articles/<uuid:pk>/analysis/apply/",
        ArticleAnalysisApply.as_view(),
    ),
]
pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def imported_article(article, source_segments):
    from plane.quality.models import DocumentImport
    parts = []
    for item in source_segments:
        locator = f"PDF 第{item['page']}页" if "page" in item else f"DOCX {item['part']}，第{item['paragraph']}段"
        parts.append(f"【来源：{locator}】\n{item['text']}")
    article.content = "\n\n".join(parts).strip()
    article.save()
    DocumentImport.objects.create(
        project=article.project, created_by=article.created_by, resource="knowledge",
        name="source.pdf", sha256="a" * 64, status="confirmed",
        rows=[{"title": article.title, "content": article.content}],
        object_ids=[str(article.id)], extraction={"segments": source_segments},
    )
    return article


def test_long_imported_source_keeps_page_locator_on_every_analysis_piece(analysis152):
    from plane.knowledge.document_analysis import segments

    article = imported_article(analysis152[1], [{"page": 3, "text": "检查采集端口是否监听。" * 500 + "\n\n本页补充说明。"}])
    pieces = segments(article)
    assert len(pieces) > 2
    assert all(piece.get("locator") == "PDF 第3页" for piece in pieces)
    assert all(piece["text"].startswith("【来源：PDF 第3页】\n") for piece in pieces)
    assert all(piece["characters"] == len(piece["text"]) <= 2000 for piece in pieces)


def test_docx_source_locator_does_not_invent_printed_page_numbers(analysis152):
    from plane.knowledge.document_analysis import segments

    article = imported_article(analysis152[1], [{"part": "word/document.xml", "paragraph": 12, "text": "检查连接。"}])
    assert [piece.get("locator") for piece in segments(article)] == ["DOCX word/document.xml，第12段"]


def test_source_locator_metadata_cannot_serve_as_original_evidence(analysis152):
    from plane.knowledge.document_analysis import segments, validate_analysis
    from rest_framework.exceptions import ValidationError

    article = imported_article(analysis152[1], [{"page": 3, "text": "只需检查采集连接。"}])
    selected = segments(article)
    value = {
        "device_scope": {"text": "原文未说明", "citations": []},
        "version_scope": {"text": "原文未说明", "citations": []},
        "phenomena": [{"text": "材料第三页", "citations": [{"segment_id": "S0001", "quote": "PDF 第3页"}]}],
        "checks": [], "limitations": [],
    }
    with pytest.raises(ValidationError):
        validate_analysis(value, selected)
    value["phenomena"][0]["citations"][0]["quote"] = "检查采集连接"
    assert validate_analysis(value, selected)


def test_plain_source_marker_stays_literal_text_without_trusted_locator(analysis152):
    from plane.knowledge.document_analysis import segments

    article = analysis152[1]
    article.content = "【来源：PDF 第99页】\n普通文字标记。"
    pieces = segments(article)
    assert all("locator" not in piece for piece in pieces)
    assert pieces[0]["text"] == article.content


def test_literal_source_marker_cannot_override_confirmed_import_locator(analysis152):
    from plane.knowledge.document_analysis import segments

    original = "原文段。\n\n【来源：PDF 第99页】\n这是正文里的来源示例。"
    article = imported_article(analysis152[1], [{"page": 3, "text": original}])
    pieces = segments(article)
    assert all(piece.get("locator") == "PDF 第3页" for piece in pieces)
    assert "【来源：PDF 第99页】" in "".join(piece["text"] for piece in pieces)


def test_manual_appendix_drops_import_locator_without_losing_content(analysis152):
    from plane.knowledge.document_analysis import segments

    article = imported_article(analysis152[1], [{"page": 3, "text": "原文段。"}])
    article.content += "\n\n人工追加说明。"
    pieces = segments(article)
    assert all("locator" not in piece for piece in pieces)
    assert "人工追加说明。" in "".join(piece["text"] for piece in pieces)
    assert "【来源：PDF 第3页】" in pieces[0]["text"]


def test_extraction_trailing_newline_and_legacy_body_keep_trusted_locator(analysis152):
    from plane.knowledge.document_analysis import segments
    from plane.quality.models import DocumentImport

    article = imported_article(analysis152[1], [{"page": 3, "text": "只需检查采集连接。\n"}])
    assert segments(article)[0]["locator"] == "PDF 第3页"
    article.content = "只需检查采集连接。"
    article.save()
    DocumentImport.objects.filter(object_ids__contains=[str(article.id)]).update(
        rows=[{"title": article.title, "content": article.content}]
    )
    assert segments(article)[0]["locator"] == "PDF 第3页"


@pytest.mark.parametrize("mismatch", ["preview", "foreign_article", "foreign_project", "changed_row"])
def test_unconfirmed_or_mismatched_import_cannot_attest_locator(analysis152, mismatch):
    from plane.knowledge.document_analysis import segments
    from plane.quality.models import DocumentImport

    article = imported_article(analysis152[1], [{"page": 3, "text": "原文段。"}])
    row = DocumentImport.objects.get(object_ids__contains=[str(article.id)])
    if mismatch == "preview":
        row.status = "preview"
    elif mismatch == "foreign_article":
        row.object_ids = []
    elif mismatch == "foreign_project":
        row.project = Project.objects.create(workspace=article.project.workspace, name="Other", identifier="OTHER160")
    else:
        row.rows = [{"title": article.title, "content": "另一段正文。"}]
    row.save()
    assert all("locator" not in piece for piece in segments(article))


def test_rendered_reference_keeps_confirmed_locator_and_complete_original(analysis152):
    from plane.knowledge.document_analysis import segments, render_analysis, validate_analysis

    article = imported_article(analysis152[1], [{
        "page": 3,
        "text": "设备：R2，版本：2.1。\n\n现象：采集停止。\n\n检查步骤：重启采集服务，预期恢复采集。",
    }])
    selected = segments(article)
    rendered = render_analysis(validate_analysis(result(), selected), selected, article.content)
    assert "[S0003]（PDF 第3页）「重启采集服务，预期恢复采集」" in rendered
    assert rendered.endswith(article.content)


def test_oversized_source_locator_cannot_silently_omit_body(analysis152):
    from plane.knowledge.document_analysis import segments
    from rest_framework.exceptions import ValidationError

    article = imported_article(analysis152[1], [
        {"page": 1, "text": "可分析正文。"},
        {"part": "word/header" + "1" * 2000 + ".xml", "paragraph": 1, "text": "不可静默省略正文。"},
    ])
    with pytest.raises(ValidationError):
        segments(article)


@pytest.fixture
def analysis152(workspace, create_user, mocker):
    WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(
        role=15
    )
    project = Project.objects.create(
        workspace=workspace, name="解读验收", identifier="AN52"
    )
    ProjectMember.objects.create(project=project, member=create_user, role=15)
    ProjectRolePolicy.objects.create(project=project, enabled=True)
    BusinessRole.objects.create(project=project, user=create_user, role="TECHNICIAN")
    article = Article.objects.create(
        project=project,
        created_by=create_user,
        title="设备采集",
        content="设备：R2，版本：2.1。\n\n现象：采集停止。\n\n检查步骤：重启采集服务，预期恢复采集。",
    )
    config = mocker.patch(
        "plane.knowledge.document_analysis.assistant.provider_config",
        return_value={
            "configured": True,
            "model": "test-model",
            "api_key": "not-a-real-key",
            "base_url": "https://example.org",
        },
    )
    complete = mocker.patch("plane.knowledge.document_analysis.complete_analysis")
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/knowledge/articles/{article.id}/analysis/"
    return base, article, complete, config


def result():
    cite = lambda sid, quote: [{"segment_id": sid, "quote": quote}]
    return {
        "device_scope": {"text": "R2", "citations": cite("S0001", "设备：R2")},
        "version_scope": {"text": "2.1", "citations": cite("S0001", "版本：2.1")},
        "phenomena": [
            {"text": "采集停止", "citations": cite("S0002", "现象：采集停止")}
        ],
        "checks": [
            {
                "action": "重启采集服务",
                "expected": "恢复采集",
                "citations": cite("S0003", "重启采集服务，预期恢复采集"),
            }
        ],
        "limitations": [],
    }


def preview(client, base, complete):
    source = client.get(base)
    assert source.status_code == 200, source.content
    complete.return_value = result()
    response = client.post(
        base,
        {
            "expected_version": source.data["version"],
            "source_hash": source.data["source_hash"],
            "segment_ids": ["S0001", "S0002", "S0003"],
        },
        format="json",
    )
    return source, response


@override_settings(ROOT_URLCONF=__name__)
def test_signed_preview_applies_once_preserves_source_and_requires_rescan(
    session_client, analysis152
):
    base, article, complete, _ = analysis152
    before = article.content
    source, response = preview(session_client, base, complete)
    assert response.status_code == 201, response.content
    article.refresh_from_db()
    assert article.content == before
    assert response.data["analysis"] == result() and response.data["token"]
    applied = session_client.post(
        base + "apply/",
        {"token": response.data["token"], "confirmed": True},
        format="json",
    )
    assert applied.status_code == 200, applied.content
    article.refresh_from_db()
    assert (
        before in article.content
        and "结构化解读" in article.content
        and "S0003" in article.content
    )
    assert (
        article.status == "draft"
        and article.edit_version == 2
        and article.scanned_version == 0
    )
    assert (
        not article.publication_active
        and ArticleEvent.objects.filter(article=article, action="edit").count() == 1
    )
    retry = session_client.post(
        base + "apply/",
        {"token": response.data["token"], "confirmed": True},
        format="json",
    )
    assert retry.status_code == 409
    assert ArticleEvent.objects.filter(article=article).count() == 1


@override_settings(ROOT_URLCONF=__name__)
@pytest.mark.parametrize(
    "bad",
    [
        {"segment_id": "S9999", "quote": "不存在的引用"},
        {"segment_id": "S0001", "quote": "这不是原文中的摘录"},
    ],
)
def test_fabricated_segment_or_quote_blocks_preview(session_client, analysis152, bad):
    base, article, complete, _ = analysis152
    source = session_client.get(base).data
    answer = result()
    answer["checks"][0]["citations"] = [bad]
    complete.return_value = answer
    response = session_client.post(
        base,
        {
            "expected_version": 1,
            "source_hash": source["source_hash"],
            "segment_ids": ["S0001", "S0002", "S0003"],
        },
        format="json",
    )
    assert response.status_code == 502, response.content
    article.refresh_from_db()
    assert (
        article.edit_version == 1
        and not ArticleEvent.objects.filter(article=article).exists()
    )


@override_settings(ROOT_URLCONF=__name__)
def test_long_document_requires_explicit_bounded_selection(session_client, analysis152):
    base, article, complete, _ = analysis152
    article.content = "正文段落。" * 5000
    article.save()
    source = session_client.get(base).data
    assert source["characters"] > 20000 and len(source["segments"]) > 1
    response = session_client.post(
        base,
        {
            "expected_version": 1,
            "source_hash": source["source_hash"],
            "segment_ids": [s["id"] for s in source["segments"]],
        },
        format="json",
    )
    assert response.status_code == 400, response.content
    assert not complete.called


@override_settings(ROOT_URLCONF=__name__)
def test_tamper_expiry_cas_and_permission_rechecked(
    session_client, analysis152, create_user, mocker
):
    base, article, complete, _ = analysis152
    source, response = preview(session_client, base, complete)
    token = response.data["token"]
    assert (
        session_client.post(
            base + "apply/", {"token": token + "x", "confirmed": True}, format="json"
        ).status_code
        == 400
    )
    assert (
        session_client.post(
            base + "apply/", {"token": token, "confirmed": False}, format="json"
        ).status_code
        == 400
    )
    article.content += "\n人工修改"
    article.edit_version += 1
    article.save()
    assert (
        session_client.post(
            base + "apply/", {"token": token, "confirmed": True}, format="json"
        ).status_code
        == 409
    )
    BusinessRole.objects.filter(project=article.project, user=create_user).update(
        role="REPORTER"
    )
    assert session_client.get(base).status_code == 403
    assert (
        session_client.post(
            base + "apply/", {"token": token, "confirmed": True}, format="json"
        ).status_code
        == 403
    )


@override_settings(ROOT_URLCONF=__name__)
def test_model_failure_and_sensitive_source_preserve_original(
    session_client, analysis152
):
    base, article, complete, _ = analysis152
    source = session_client.get(base).data
    complete.side_effect = RuntimeError("provider unavailable")
    data = {
        "expected_version": 1,
        "source_hash": source["source_hash"],
        "segment_ids": ["S0001"],
    }
    assert session_client.post(base, data, format="json").status_code == 502
    article.refresh_from_db()
    assert article.edit_version == 1
    article.content = "password=Sensitive123456"
    article.save()
    data["source_hash"] = session_client.get(base).data["source_hash"]
    assert session_client.post(base, data, format="json").status_code == 400


@override_settings(ROOT_URLCONF=__name__)
def test_imported_source_prefix_does_not_hide_sensitive_text_from_analysis(session_client, analysis152):
    base, article, complete, _ = analysis152
    article.content = "【来源：PDF 第3页】\npassword=SYNTHETIC_VALUE_160"
    article.save()
    source = session_client.get(base).data
    response = session_client.post(
        base,
        {"expected_version": 1, "source_hash": source["source_hash"], "segment_ids": ["S0001"]},
        format="json",
    )
    assert response.status_code == 400, response.content
    assert not complete.called


@override_settings(ROOT_URLCONF=__name__)
def test_permission_or_version_changed_during_model_call_blocks_token(
    session_client, analysis152, create_user
):
    base, article, complete, _ = analysis152
    source = session_client.get(base).data

    def revoked(*args):
        ProjectMember.objects.filter(
            project=article.project, member=create_user
        ).update(is_active=False)
        return result()

    complete.side_effect = revoked
    response = session_client.post(
        base,
        {
            "expected_version": 1,
            "source_hash": source["source_hash"],
            "segment_ids": ["S0001", "S0002", "S0003"],
        },
        format="json",
    )
    assert response.status_code == 403, response.content


@override_settings(ROOT_URLCONF=__name__)
def test_expired_and_foreign_user_tokens_are_rejected(
    session_client, analysis152, mocker, create_user, workspace
):
    import time
    from unittest.mock import patch
    from rest_framework.test import APIClient
    from plane.db.models import User

    base, article, complete, _ = analysis152
    _, response = preview(session_client, base, complete)
    token = response.data["token"]
    with patch("django.core.signing.time.time", return_value=time.time() + 601):
        assert (
            session_client.post(
                base + "apply/", {"token": token, "confirmed": True}, format="json"
            ).status_code
            == 400
        )
    other = User.objects.create(
        email="other-analysis@example.invalid", username="other-analysis-152"
    )
    WorkspaceMember.objects.create(workspace=workspace, member=other, role=15)
    ProjectMember.objects.create(project=article.project, member=other, role=15)
    BusinessRole.objects.create(project=article.project, user=other, role="TECHNICIAN")
    other_client = APIClient()
    other_client.force_authenticate(other)
    assert (
        other_client.post(
            base + "apply/", {"token": token, "confirmed": True}, format="json"
        ).status_code
        == 403
    )
    article.refresh_from_db()
    assert article.edit_version == 1


@override_settings(ROOT_URLCONF=__name__)
def test_edit_during_provider_call_and_unknown_output_fields_are_rejected(
    session_client, analysis152
):
    base, article, complete, _ = analysis152
    source = session_client.get(base).data
    data = {
        "expected_version": 1,
        "source_hash": source["source_hash"],
        "segment_ids": ["S0001", "S0002", "S0003"],
    }

    def edit(*args):
        Article.objects.filter(pk=article.id).update(
            content="人工修改的正文。", edit_version=2
        )
        return result()

    complete.side_effect = edit
    assert session_client.post(base, data, format="json").status_code == 409
    article.refresh_from_db()
    assert article.content == "人工修改的正文。"
    assert not ArticleEvent.objects.filter(article=article).exists()


def test_provider_boundary_sends_only_selected_text_without_tools(mocker):
    from plane.knowledge.document_analysis import complete_analysis
    from types import SimpleNamespace

    client = mocker.MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(content="{}"), finish_reason="stop")
        ]
    )
    factory = mocker.patch("plane.knowledge.document_analysis.OpenAI")
    factory.return_value.__enter__.return_value = client
    assert (
        complete_analysis(
            {
                "api_key": "test-only",
                "base_url": "https://example.invalid",
                "model": "test",
            },
            "标题",
            [{"id": "S0002", "text": "选中的正文。"}],
            "关注点",
        )
        == {}
    )
    kwargs = client.chat.completions.create.call_args.kwargs
    assert "tools" not in kwargs and "functions" not in kwargs
    assert "S0002" in kwargs["messages"][1]["content"]
    assert (
        factory.call_args.kwargs["max_retries"] == 0
        and factory.call_args.kwargs["timeout"] == 45
    )


@override_settings(ROOT_URLCONF=__name__)
def test_uncited_limitations_cannot_introduce_model_facts(session_client, analysis152):
    base, article, complete, _ = analysis152
    source = session_client.get(base).data
    value = result()
    value["limitations"] = ["任何版本均可使用这个步骤"]
    complete.return_value = value
    response = session_client.post(
        base,
        {
            "expected_version": 1,
            "source_hash": source["source_hash"],
            "segment_ids": ["S0001", "S0002", "S0003"],
        },
        format="json",
    )
    assert response.status_code == 502, response.content


@override_settings(ROOT_URLCONF=__name__)
def test_archiving_project_during_analysis_revokes_result(session_client, analysis152):
    from django.utils import timezone

    base, article, complete, _ = analysis152
    source = session_client.get(base).data

    def archived(*args):
        Project.objects.filter(pk=article.project_id).update(archived_at=timezone.now())
        return result()

    complete.side_effect = archived
    response = session_client.post(
        base,
        {
            "expected_version": 1,
            "source_hash": source["source_hash"],
            "segment_ids": ["S0001", "S0002", "S0003"],
        },
        format="json",
    )
    assert response.status_code == 403, response.content


@override_settings(ROOT_URLCONF=__name__)
def test_applying_published_article_preserves_existing_publication(
    session_client, analysis152, create_user
):
    from plane.knowledge.models import PublishedRevision

    base, article, complete, _ = analysis152
    original = article.content
    publication = PublishedRevision.objects.create(
        article=article,
        project=article.project,
        created_by=create_user,
        version=1,
        title=article.title,
        content=original,
        tags=[],
    )
    article.status = "published"
    article.publication_active = True
    article.published_version = 1
    article.save()
    _, response = preview(session_client, base, complete)
    assert (
        session_client.post(
            base + "apply/",
            {"token": response.data["token"], "confirmed": True},
            format="json",
        ).status_code
        == 200
    )
    article.refresh_from_db()
    publication.refresh_from_db()
    assert (
        article.status == "draft"
        and article.publication_active
        and article.published_version == 1
    )
    assert (
        publication.content == original
        and PublishedRevision.objects.filter(article=article).count() == 1
    )


@override_settings(ROOT_URLCONF=__name__)
def test_many_short_segments_fit_same_total_character_budget(session_client,analysis152):
    base,article,complete,_=analysis152
    article.content += "\n\n" + "\n\n".join("补充段落"+str(n) for n in range(125))
    article.save()
    source=session_client.get(base)
    complete.return_value=result()
    response=session_client.post(base,{"expected_version":source.data["version"],"source_hash":source.data["source_hash"],"segment_ids":[s["id"] for s in source.data["segments"]]},format="json")
    assert response.status_code==201,response.content
