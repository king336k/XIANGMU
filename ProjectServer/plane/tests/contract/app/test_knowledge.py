"""Knowledge lifecycle and controlled answers never cross project/publication boundaries."""

from uuid import uuid4
from unittest.mock import patch

import pytest
from plane.db.models import Project, ProjectMember, User, WorkspaceMember

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def kb(session_client, workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="知识项目", identifier="KN")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/knowledge/"
    return base, project, create_user


def draft(client, base, **extra):
    r = client.post(
        base + "articles/",
        {
            "title": "采集启动失败排查",
            "content": "检查机器人网络，确认Topic连接，重新启动采集。",
            "tags": ["采集", "网络"],
            **extra,
        },
        format="json",
    )
    assert r.status_code == 201, r.content
    return r.data


def change(client, base, article, action, **extra):
    return client.post(
        base + f"articles/{article['id']}/workflow/",
        {"action": action, "expected_version": article["edit_version"], **extra},
        format="json",
    )


def publish(client, base, article):
    scanned = change(client, base, article, "scan")
    assert scanned.status_code == 200, scanned.data
    article = scanned.data
    submitted = change(client, base, article, "submit")
    assert submitted.status_code == 200, submitted.data
    result = change(client, base, submitted.data, "publish")
    assert result.status_code == 200, result.data
    return result.data


def test_draft_not_searchable_until_scan_review_publish(session_client, kb):
    base, project, user = kb
    article = draft(session_client, base)
    assert session_client.get(base + "search/?q=采集").data["results"] == []
    assert change(session_client, base, article, "submit").status_code == 400
    published = publish(session_client, base, article)
    assert published["published_version"] == 1
    hits = session_client.get(base + "search/?q=采集").data["results"]
    assert len(hits) == 1 and hits[0]["version"] == 1
    assert hits[0]["article_id"] == article["id"]


def test_reviewer_can_publish_own_scanned_draft_and_update_version(session_client, kb):
    base, project, user = kb
    article = draft(session_client, base)
    scanned = change(session_client, base, article, "scan").data
    published = change(session_client, base, scanned, "publish")
    assert published.status_code == 200, published.data
    assert published.data["status"] == "published"
    assert published.data["published_version"] == 1
    assert [event["action"] for event in published.data["events"]].count("submit") == 0
    assert session_client.get(base + "search/?q=采集").data["count"] == 1
    assert change(session_client, base, published.data, "publish").status_code == 409

    edited = session_client.patch(
        base + f"articles/{article['id']}/",
        {"expected_version": published.data["edit_version"], "content": "采集修复后使用新Session验证。"},
        format="json",
    )
    assert edited.status_code == 200, edited.data
    assert "Topic" in session_client.get(base + "search/?q=采集").data["results"][0]["content"]
    scanned = change(session_client, base, edited.data, "scan").data
    updated = change(session_client, base, scanned, "publish")
    assert updated.status_code == 200, updated.data
    assert updated.data["published_version"] == 2
    assert len(updated.data["versions"]) == 2
    hit = session_client.get(base + "search/?q=采集").data["results"][0]
    assert hit["version"] == 2 and "新Session" in hit["content"]


@pytest.mark.parametrize("state", ["unscanned", "sensitive", "edited_after_scan"])
def test_direct_publish_requires_current_clean_scan(session_client, kb, state):
    from plane.knowledge.models import PublishedRevision

    base, project, user = kb
    article = draft(
        session_client,
        base,
        **({"content": "password=SYNTHETIC_TEST_ONLY"} if state == "sensitive" else {}),
    )
    if state != "unscanned":
        article = change(session_client, base, article, "scan").data
    if state == "edited_after_scan":
        article = session_client.patch(
            base + f"articles/{article['id']}/",
            {"expected_version": article["edit_version"], "content": "采集步骤已更新，需要重新检查。"},
            format="json",
        ).data
    result = change(session_client, base, article, "publish")
    assert result.status_code == 400, result.data
    assert not PublishedRevision.objects.filter(article_id=article["id"]).exists()
    assert session_client.get(base + "search/?q=采集").data["count"] == 0


def test_edit_creates_draft_but_published_snapshot_remains(session_client, kb):
    base, project, user = kb
    article = publish(session_client, base, draft(session_client, base))
    changed = session_client.patch(
        base + f"articles/{article['id']}/",
        {"expected_version": article["edit_version"], "content": "新草稿未审核，不得参与检索"},
        format="json",
    )
    assert changed.status_code == 200
    hits = session_client.get(base + "search/?q=采集").data["results"]
    assert "Topic" in hits[0]["content"] and "新草稿" not in hits[0]["content"]
    stale = session_client.patch(
        base + f"articles/{article['id']}/",
        {"expected_version": article["edit_version"], "title": "过期覆盖"},
        format="json",
    )
    assert stale.status_code == 409
    offline = change(session_client, base, changed.data, "offline", comment="版本不再适用")
    assert offline.status_code == 200
    assert session_client.get(base + "search/?q=采集").data["results"] == []


def test_member_cannot_publish_and_other_project_isolated(session_client, kb, workspace):
    base, project, user = kb
    article = draft(session_client, base)
    member = User.objects.create(email="writer@kb.local", username="writer", display_name="作者")
    WorkspaceMember.objects.create(workspace=workspace, member=member, role=15)
    ProjectMember.objects.create(project=project, member=member, role=15)
    session_client.force_authenticate(user=member)
    scanned = change(session_client, base, article, "scan").data
    assert change(session_client, base, scanned, "publish").status_code == 403
    submitted = change(session_client, base, scanned, "submit").data
    assert change(session_client, base, submitted, "publish").status_code == 403
    other = Project.objects.create(workspace=workspace, name="隔离项目", identifier="OTHER")
    otherbase = f"/api/workspaces/{workspace.slug}/projects/{other.id}/knowledge/"
    assert session_client.get(otherbase + "search/?q=采集").status_code == 403


def test_sanitization_requires_fix_and_rescan(session_client, kb):
    base, project, user = kb
    article = draft(session_client, base, content="password=EXAMPLE_NOT_A_REAL_CREDENTIAL")
    scanned = change(session_client, base, article, "scan")
    assert scanned.status_code == 200 and scanned.data["scan_findings"]
    assert "EXAMPLE_NOT_A_REAL_CREDENTIAL" not in str(scanned.data["scan_findings"])
    assert change(session_client, base, scanned.data, "submit").status_code == 400


def test_chat_without_provider_does_not_fabricate_answer(session_client, kb):
    base, project, user = kb
    publish(session_client, base, draft(session_client, base))
    with patch("plane.knowledge.assistant.provider_config", return_value={"configured": False}):
        result = session_client.post(
            base + "chat/", {"query": "采集失败怎么办", "request_id": str(uuid4())}, format="json"
        )
    assert result.status_code == 503 and result.data["code"] == "AI_NOT_CONFIGURED"
    assert session_client.get(base + "search/?q=采集").data["count"] == 1


def test_chat_citations_replay_and_private_conversations(session_client, kb, workspace):
    base, project, user = kb
    article = publish(session_client, base, draft(session_client, base))
    request_id = str(uuid4())
    answer = {
        "answer": "检查网络与Topic连接。",
        "suggested_actions": ["检查网络"],
        "verification_steps": ["重试采集"],
        "citations": [f"KN-{article['id']}-v1"],
    }
    with (
        patch("plane.knowledge.assistant.provider_config", return_value={"configured": True}),
        patch("plane.knowledge.assistant.complete_answer", return_value=answer) as provider,
    ):
        r = session_client.post(base + "chat/", {"query": "采集网络失败", "request_id": request_id}, format="json")
        assert r.status_code == 201, r.data
        assert len(r.data["citations"]) == 1 and r.data["status"] == "completed"
        retry = session_client.post(base + "chat/", {"query": "采集网络失败", "request_id": request_id}, format="json")
        assert retry.status_code == 200 and retry.data["id"] == r.data["id"]
        assert provider.call_count == 1
        other = User.objects.create(email="reader@kb.local", username="reader")
        WorkspaceMember.objects.create(workspace=workspace, member=other, role=15)
        ProjectMember.objects.create(project=project, member=other, role=15)
        session_client.force_authenticate(user=other)
        assert session_client.get(base + f"conversations/{r.data['conversation_id']}/").status_code == 404


def test_unknown_citation_rejected_and_no_knowledge_skips_model(session_client, kb):
    base, project, user = kb
    with (
        patch("plane.knowledge.assistant.provider_config", return_value={"configured": True}),
        patch("plane.knowledge.assistant.complete_answer") as provider,
    ):
        r = session_client.post(base + "chat/", {"query": "没有可用知识", "request_id": str(uuid4())}, format="json")
        assert r.status_code == 201 and r.data["status"] == "no_knowledge"
        provider.assert_not_called()
    publish(session_client, base, draft(session_client, base))
    invalid = {
        "answer": "不受支持的答案",
        "suggested_actions": [],
        "verification_steps": [],
        "citations": ["KN-unknown-v99"],
    }
    with (
        patch("plane.knowledge.assistant.provider_config", return_value={"configured": True}),
        patch("plane.knowledge.assistant.complete_answer", return_value=invalid),
    ):
        r = session_client.post(base + "chat/", {"query": "采集", "request_id": str(uuid4())}, format="json")
        assert r.status_code == 502 and r.data["code"] == "AI_INVALID_RESPONSE"


def test_guest_cannot_read_unpublished_drafts(session_client, kb):
    base, project, user = kb
    article = draft(session_client, base)
    ProjectMember.objects.filter(project=project, member=user).update(role=5)
    assert session_client.get(base + "articles/").status_code == 403
    assert session_client.get(base + f"articles/{article['id']}/").status_code == 403
    assert session_client.get(base + "search/?q=采集").data["count"] == 0


def test_scan_rejects_sensitive_tags(session_client, kb):
    base, project, user = kb
    article = draft(session_client, base, tags=["token=EXAMPLE_NOT_A_REAL_TOKEN"])
    scanned = change(session_client, base, article, "scan").data
    assert scanned["scan_findings"]
    assert change(session_client, base, scanned, "submit").status_code == 400


def test_offline_while_answering_never_returns_stale_reference(session_client, kb):
    base, project, user = kb
    article = publish(session_client, base, draft(session_client, base))

    def complete(*args):
        from plane.knowledge.models import Article

        Article.objects.filter(pk=article["id"]).update(publication_active=False)
        return {
            "answer": "应被拒绝",
            "suggested_actions": [],
            "verification_steps": [],
            "citations": [f"KN-{article['id']}-v1"],
        }

    with (
        patch("plane.knowledge.assistant.provider_config", return_value={"configured": True}),
        patch("plane.knowledge.assistant.complete_answer", side_effect=complete),
    ):
        response = session_client.post(base + "chat/", {"query": "采集", "request_id": str(uuid4())}, format="json")
    assert response.status_code == 502 and "应被拒绝" not in str(response.data)


def test_followup_uses_owned_bounded_history_and_current_publications(session_client, kb):
    base, project, user = kb
    article = publish(session_client, base, draft(session_client, base))
    answer = {
        "answer": "先检查机器人网络，再核对Topic连接。",
        "suggested_actions": [],
        "verification_steps": [],
        "citations": [f"KN-{article['id']}-v1"],
    }
    with (
        patch("plane.knowledge.assistant.provider_config", return_value={"configured": True}),
        patch("plane.knowledge.assistant.complete_answer", return_value=answer) as provider,
    ):
        first = session_client.post(
            base + "chat/", {"query": "采集启动失败", "request_id": str(uuid4())}, format="json"
        )
        assert first.status_code == 201
        second = session_client.post(
            base + "chat/",
            {"query": "然后呢", "conversation_id": first.data["conversation_id"], "request_id": str(uuid4())},
            format="json",
        )
        assert second.status_code == 201 and second.data["status"] == "completed"
        history = provider.call_args.args[3]
        assert history == [{"question": "采集启动失败", "answer": answer["answer"]}]
        assert provider.call_args.args[2][0]["reference"] == f"KN-{article['id']}-v1"
        from plane.knowledge.models import Article

        Article.objects.filter(pk=article["id"]).update(publication_active=False)
        offline = session_client.post(
            base + "chat/",
            {"query": "再解释", "conversation_id": first.data["conversation_id"], "request_id": str(uuid4())},
            format="json",
        )
        assert offline.data["status"] == "no_knowledge" and provider.call_count == 2


def test_workspace_guest_cannot_read_unpublished_editorial_content(session_client, kb, workspace):
    base, project, user = kb
    article = draft(session_client, base)
    WorkspaceMember.objects.filter(workspace=workspace, member=user).update(role=5)
    assert session_client.get(base + "articles/").status_code == 403
    assert session_client.get(base + f"articles/{article['id']}/").status_code == 403


def test_offline_knowledge_is_redacted_on_history_replay_and_feedback(session_client, kb):
    base, project, user = kb
    article = publish(session_client, base, draft(session_client, base))
    request = {"query": "采集", "request_id": str(uuid4())}
    answer = {
        "answer": "不能在下线后继续显示的旧答案",
        "suggested_actions": ["旧建议"],
        "verification_steps": ["旧步骤"],
        "citations": [f"KN-{article['id']}-v1"],
    }
    with (
        patch("plane.knowledge.assistant.provider_config", return_value={"configured": True}),
        patch("plane.knowledge.assistant.complete_answer", return_value=answer),
    ):
        saved = session_client.post(base + "chat/", request, format="json")
        assert saved.status_code == 201
        from plane.knowledge.models import Article, ChatMessage

        Article.objects.filter(pk=article["id"]).update(publication_active=False)
        replay = session_client.post(base + "chat/", request, format="json")
        history = session_client.get(base + f"conversations/{saved.data['conversation_id']}/")
        feedback = session_client.post(
            base + f"messages/{saved.data['id']}/feedback/", {"feedback": "unhelpful"}, format="json"
        )
        for data in [replay.data, history.data["results"][0], feedback.data]:
            assert data["status"] == "reference_unavailable"
            assert not data["citations"] and not data["suggested_actions"] and not data["verification_steps"]
            assert "旧答案" not in str(data) and "Topic" not in str(data)
        assert ChatMessage.objects.get(pk=saved.data["id"]).answer == answer["answer"]


def test_provider_request_contains_bounded_history_as_untrusted_context():
    import json
    from types import SimpleNamespace
    from plane.knowledge.assistant import complete_answer

    result = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"answer":"示例"}'))])
    with patch("plane.knowledge.assistant.OpenAI") as factory:
        client = factory.return_value.__enter__.return_value
        client.chat.completions.create.return_value = result
        history = [{"question": "前一个问题", "answer": "已核对的回答"}]
        complete_answer(
            {"api_key": "test-placeholder", "base_url": "https://api.openai.com/v1", "model": "test-model"},
            "然后呢",
            [],
            history,
        )
        sent = client.chat.completions.create.call_args.kwargs["messages"]
        assert json.loads(sent[-1]["content"])["history"] == history
        assert "不能替代" in sent[0]["content"]


def test_history_reference_offline_during_model_call_rejects_answer(session_client, kb):
    from plane.knowledge.models import ChatMessage, Conversation, Article

    base, project, user = kb
    first = publish(session_client, base, draft(session_client, base, title="旧排障知识"))
    # Make history depend on a publication outside this call's top-five retrieval results.
    for index in range(5):
        publish(session_client, base, draft(session_client, base, title=f"采集知识{index}"))
    conversation = Conversation.objects.create(project=project, created_by=user, title="采集上下文")
    ChatMessage.objects.create(
        project=project,
        created_by=user,
        conversation=conversation,
        request_id=uuid4(),
        query="采集",
        status="completed",
        answer="历史答案",
        citations=[{"reference": f"KN-{first['id']}-v1"}],
    )

    def complete(config, query, references, history):
        assert history and f"KN-{first['id']}-v1" not in [r["reference"] for r in references]
        Article.objects.filter(pk=first["id"]).update(publication_active=False)
        return {
            "answer": "不应显示",
            "suggested_actions": [],
            "verification_steps": [],
            "citations": [references[0]["reference"]],
        }

    with (
        patch("plane.knowledge.assistant.provider_config", return_value={"configured": True}),
        patch("plane.knowledge.assistant.complete_answer", side_effect=complete),
    ):
        response = session_client.post(
            base + "chat/",
            {"query": "继续采集", "conversation_id": str(conversation.id), "request_id": str(uuid4())},
            format="json",
        )
    assert response.status_code == 502 and response.data["code"] == "AI_INVALID_RESPONSE"
