"""Diagnostic semantic recall supplements keywords within current approved visibility."""

from uuid import uuid4

import pytest

from plane.db.models import Project
from plane.knowledge import diagnostic_retrieval as retrieval
from plane.knowledge.models import Article, PublishedRevision
from plane.knowledge.sharing_models import KnowledgeShare
from plane.knowledge.semantic_models import SemanticProjectIndex, SemanticRevisionIndex
from plane.knowledge import semantic as ranking

pytestmark = [pytest.mark.contract, pytest.mark.django_db]
APPROVED = retrieval.APPROVED_TAG


@pytest.fixture
def project(workspace):
    return Project.objects.create(workspace=workspace, name="诊断混合检索", identifier="DHYBRID")


def publication(project, title="编码资源准入", content="共享会话容量耗尽", tags=None):
    tags = [APPROVED] if tags is None else tags
    article = Article.objects.create(
        project=project,
        title=title,
        content=content,
        tags=tags,
        status="published",
        publication_active=True,
        published_version=1,
        scanned_version=2,
        scan_findings=[],
    )
    revision = PublishedRevision.objects.create(
        project=project,
        article=article,
        version=1,
        title=title,
        content=content,
        tags=tags,
    )
    return article, revision


def semantic(mocker, ids):
    # Patch the optional adapter so fixture writes remain in this test's transaction.
    return mocker.patch.object(retrieval, "semantic_ids", return_value=ids, create=True)


def test_semantic_only_match_can_supplement_current_approved_publication(project, mocker):
    _, revision = publication(project)
    call = semantic(mocker, [revision.id])
    assert [row.id for row in retrieval.search(project, "并行处理数量不足")] == [revision.id]
    call.assert_called_once()


def test_literal_error_code_remains_first_before_other_keyword_and_semantic_matches(project, mocker):
    _, literal = publication(project, "错误定位", "topic_rate_too_low")
    _, broad = publication(project, "采集 采集 采集", "采集", tags=[APPROVED, "采集"])
    _, related = publication(project, "发布节奏", "消息间隔异常")
    semantic(mocker, [related.id, broad.id, literal.id])
    rows = retrieval.search(project, "topic_rate_too_low 采集", limit=5)
    assert [row.id for row in rows] == [literal.id, broad.id, related.id]


@pytest.mark.parametrize(
    "condition", ["unapproved", "unscanned", "sensitive", "draft", "offline", "superseded", "unshared"]
)
def test_semantic_ids_cannot_admit_currently_ineligible_knowledge(project, workspace, mocker, condition):
    source = project
    if condition == "unshared":
        source = Project.objects.create(workspace=workspace, name="未授权源", identifier="HIDDEN")
    article, revision = publication(source)
    if condition == "unapproved":
        article.tags = []
    elif condition == "unscanned":
        article.scanned_version = 0
    elif condition == "sensitive":
        article.scan_findings = [{"kind": "credential"}]
    elif condition == "draft":
        article.status = "draft"
    elif condition == "offline":
        article.publication_active = False
    elif condition == "superseded":
        article.published_version = 2
    article.save()
    semantic(mocker, [revision.id, uuid4()])
    assert retrieval.search(project, "并行处理数量不足") == []


def test_shared_semantic_match_preserves_scope_and_revocation(project, workspace, mocker):
    source = Project.objects.create(workspace=workspace, name="共享源", identifier="SHARED")
    article, revision = publication(source)
    share = KnowledgeShare.objects.create(
        project=source,
        target_project=project,
        article=article,
        revision=revision,
        reason="synthetic",
        device_scope="设备类型范围",
        version_scope="版本范围",
    )
    semantic(mocker, [revision.id])
    result = retrieval.search(project, "并行处理数量不足")
    assert result[0].share_device_scope == "设备类型范围"
    assert result[0].share_version_scope == "版本范围"
    share.active = False
    share.save()
    assert retrieval.search(project, "并行处理数量不足") == []


def test_revocation_while_semantic_call_is_in_flight_is_rechecked(project, mocker):
    article, revision = publication(project, content="topic_rate_too_low")

    def revoke(*args):
        Article.objects.filter(pk=article.id).update(publication_active=False)
        return [revision.id]

    mocker.patch.object(retrieval, "semantic_ids", side_effect=revoke, create=True)
    assert retrieval.search(project, "topic_rate_too_low", limit=5) == []


def test_semantic_duplicates_and_limit_do_not_replace_or_expand_keyword_results(project, mocker):
    _, keyword = publication(project, content="stable_native_error")
    others = [publication(project, title=f"额外知识{index}", content="资源信息")[1] for index in range(7)]
    semantic(mocker, [keyword.id, others[0].id, others[0].id, *[row.id for row in others[1:]]])
    result = retrieval.search(project, "stable_native_error", limit=100)
    assert len(result) == 5 and result[0].id == keyword.id
    assert len({row.id for row in result}) == 5


def test_semantic_failure_keeps_keyword_matches(project, mocker):
    _, revision = publication(project, content="stable_native_error")
    mocker.patch.object(retrieval, "semantic_ids", side_effect=TimeoutError("synthetic"), create=True)
    assert [row.id for row in retrieval.search(project, "stable_native_error")] == [revision.id]


@pytest.mark.parametrize("source,completed", [("external", True), ("shared", True), ("builtin", False)])
def test_optional_semantic_path_never_embeds_externally_or_without_ready_index(project, mocker, source, completed):
    config = {"source": source, "configured": True, "enabled": True, "fingerprint": "synthetic"}
    mocker.patch("plane.knowledge.semantic_provider.configuration", return_value=config)
    embed = mocker.patch("plane.knowledge.semantic_provider.embed")
    build = mocker.patch("plane.knowledge.semantic.request_build")
    if completed:
        SemanticProjectIndex.objects.create(
            project=project, token=uuid4(), fingerprint=config["fingerprint"], status="completed"
        )
    assert retrieval.semantic_ids(project, "当前查询") == []
    embed.assert_not_called()
    build.assert_not_called()


def test_builtin_cache_uses_one_captured_local_configuration_and_current_content_hash(project, mocker):
    _, revision = publication(project)
    config = {"source": "builtin", "configured": True, "enabled": True, "fingerprint": "synthetic"}
    setup = mocker.patch(
        "plane.knowledge.semantic_provider.configuration",
        side_effect=[config, {"source": "external", "configured": True}],
    )
    SemanticProjectIndex.objects.create(
        project=project, token=uuid4(), fingerprint=config["fingerprint"], status="completed"
    )
    SemanticRevisionIndex.objects.create(
        project=project,
        revision=revision,
        fingerprint=config["fingerprint"],
        content_hash=ranking.content_hash(revision),
        vectors=[[1.0, 0.0]],
    )
    embed = mocker.patch("plane.knowledge.semantic_provider.embed", return_value=[[1.0, 0.0]])
    assert retrieval.semantic_ids(project, "当前查询") == [revision.id]
    setup.assert_called_once()
    embed.assert_called_once_with(["当前查询"], config)


def test_full_keyword_limit_and_blank_query_do_not_invoke_semantic(project, mocker):
    for index in range(5):
        publication(project, title=f"native_code_{index}", content="stable_native_error")
    call = semantic(mocker, [])
    assert len(retrieval.search(project, "stable_native_error")) == 5
    assert retrieval.search(project, " ") == []
    call.assert_not_called()


def test_stale_vector_content_never_calls_embed_or_returns_knowledge(project, mocker):
    _, revision = publication(project)
    config = {"source": "builtin", "configured": True, "enabled": True, "fingerprint": "synthetic"}
    mocker.patch("plane.knowledge.semantic_provider.configuration", return_value=config)
    SemanticProjectIndex.objects.create(
        project=project, token=uuid4(), fingerprint=config["fingerprint"], status="completed"
    )
    SemanticRevisionIndex.objects.create(
        project=project,
        revision=revision,
        fingerprint=config["fingerprint"],
        content_hash="stale-content",
        vectors=[[1.0, 0.0]],
    )
    embed = mocker.patch("plane.knowledge.semantic_provider.embed")
    assert retrieval.semantic_ids(project, "当前查询") == []
    embed.assert_not_called()


def test_local_embedding_timeout_does_not_hide_keyword_hit_or_retry(project, mocker):
    _, revision = publication(project, content="stable_native_error")
    config = {"source": "builtin", "configured": True, "enabled": True, "fingerprint": "synthetic"}
    mocker.patch("plane.knowledge.semantic_provider.configuration", return_value=config)
    SemanticProjectIndex.objects.create(
        project=project, token=uuid4(), fingerprint=config["fingerprint"], status="completed"
    )
    SemanticRevisionIndex.objects.create(
        project=project,
        revision=revision,
        fingerprint=config["fingerprint"],
        content_hash=ranking.content_hash(revision),
        vectors=[[1.0, 0.0]],
    )
    embed = mocker.patch("plane.knowledge.semantic_provider.embed", side_effect=TimeoutError("synthetic"))
    assert [row.id for row in retrieval.search(project, "stable_native_error")] == [revision.id]
    embed.assert_called_once()


def test_complete_error_token_is_prioritized_above_longer_code_prefix_match(project, mocker):
    _, exact = publication(project, title="对应规则", content="topic_rate_too_low")
    _, prefix = publication(
        project,
        title="topic_rate_too_low_extra",
        content="topic_rate_too_low_extra",
        tags=[APPROVED, "topic_rate_too_low_extra"],
    )
    semantic(mocker, [])
    assert [row.id for row in retrieval.search(project, "topic_rate_too_low")] == [exact.id, prefix.id]
