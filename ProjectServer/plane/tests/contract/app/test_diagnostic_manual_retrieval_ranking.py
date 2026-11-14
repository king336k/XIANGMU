"""Real diagnostic task ranks authorized candidates without narrowing knowledge access."""

from uuid import UUID
import pytest
from plane.db.models import Project
from plane.knowledge.models import Article, PublishedRevision
from plane.knowledge.sharing_models import KnowledgeShare
from plane.knowledge.assistant import reference_payload as real_reference_payload
from plane.knowledge.retrieval import search as real_search
from plane.quality.tasks import run_diagnostic
from plane.tests.contract.app.test_diagnostic_finalization import diagnostic
from plane.tests.contract.app.test_automatic_diagnostics import current as current
from plane.tests.contract.app.test_automatic_diagnostics import material
from plane.tests.contract.app.test_daq_reporting import reporting as reporting

pytestmark = [pytest.mark.contract, pytest.mark.django_db]
APPROVED = "daq-diagnostic-approved"
QUERY = "RuntimeError topic_type_mismatch"


def publication(project, number, title, content, tags=()):
    article = Article.objects.create(
        project=project,
        title=title,
        content=content,
        tags=list(tags),
        publication_active=True,
        status="published",
        published_version=1,
        scanned_version=1,
        scan_findings=[],
    )
    revision = PublishedRevision.objects.create(
        id=UUID(int=number),
        project=project,
        article=article,
        version=1,
        title=title,
        content=content,
        tags=list(tags),
    )
    return revision


def capture_task(job, mocker):
    observed = []
    mocker.patch("plane.quality.tasks.assistant.provider_config", return_value={"configured": True})
    mocker.patch("plane.quality.tasks.diagnostic_search_query", return_value=QUERY)
    mocker.patch("plane.quality.tasks.assistant.reference_payload", side_effect=real_reference_payload)
    mocker.patch("plane.quality.tasks.search", side_effect=real_search)
    mocker.patch("plane.quality.diagnostic_context.diagnostic_context", return_value=[])

    def analyze(config, text, sources, references, materials):
        observed.extend(references)
        return {"answer": "仅限当前材料的类型契约诊断。", "citations": []}

    mocker.patch("plane.quality.tasks.analyze_diagnostic", side_effect=analyze)
    run_diagnostic(job.id)
    job.refresh_from_db()
    assert job.result["model_status"] == "completed", job.result
    return [r for r in observed if r["reference"].startswith("KN-")]


def test_manual_task_prioritizes_exact_mechanism_over_id_order(workspace, create_user, mocker):
    project, job = diagnostic(workspace, create_user, mocker)
    for number in range(1, 7):
        publication(project, number, "RuntimeError 通用观察", "仅记录通用 RuntimeError，不包含消息类型机制。")
    target = publication(
        project, 99, "topic_type_mismatch 消息契约", "topic_type_mismatch 需要核对有效配置及发布端实际类型。"
    )
    mocker.patch("plane.knowledge.semantic.ranked_ids", return_value=[target.id])
    refs = capture_task(job, mocker)
    assert refs[0]["reference"] == f"KN-{target.article_id}-v1"
    assert len(refs) == 5


def test_manual_task_keeps_unapproved_ordinary_knowledge_candidate(workspace, create_user, mocker):
    project, job = diagnostic(workspace, create_user, mocker)
    revision = publication(project, 101, "topic_type_mismatch 普通项目知识", "RuntimeError 对应项目消息契约。")
    assert revision.tags == []
    mocker.patch("plane.knowledge.semantic.ranked_ids", return_value=[])
    refs = capture_task(job, mocker)
    assert [r["reference"] for r in refs] == [f"KN-{revision.article_id}-v1"]


def test_manual_task_retains_semantic_only_candidates_when_rank_has_room(workspace, create_user, mocker):
    project, job = diagnostic(workspace, create_user, mocker)
    weak = publication(project, 1, "RuntimeError 通用", "通用观测。")
    target = publication(project, 99, "topic_type_mismatch", "当前精确机制。")
    semantic = publication(project, 100, "消息接口恢复", "描述兼容性与订阅关系。")
    mocker.patch("plane.knowledge.semantic.ranked_ids", return_value=[target.id, semantic.id])
    refs = capture_task(job, mocker)
    assert refs[0]["reference"] == f"KN-{target.article_id}-v1"
    assert {r["reference"] for r in refs} == {f"KN-{r.article_id}-v1" for r in [weak, target, semantic]}


def test_report_only_task_still_uses_only_approved_current_scope(current, mocker):
    project, *_ = current
    approved = publication(project, 10, "topic_type_mismatch approved", "RuntimeError 类型契约。", [APPROVED])
    ordinary = publication(project, 11, "topic_type_mismatch 普通项目知识", "RuntimeError 普通候选。")
    _, job = material(current, raw=b"ERROR topic_type_mismatch")
    mocker.patch("plane.knowledge.semantic.ranked_ids", return_value=[ordinary.id])
    mocker.patch("plane.knowledge.diagnostic_retrieval.semantic_ids", return_value=[])
    refs = capture_task(job, mocker)
    assert [r["reference"] for r in refs] == [f"KN-{approved.article_id}-v1"]
    assert f"KN-{ordinary.article_id}-v1" not in {r["reference"] for r in refs}


def test_manual_task_with_no_literal_hit_keeps_authorized_semantic_recall(workspace, create_user, mocker):
    project, job = diagnostic(workspace, create_user, mocker)
    semantic = publication(project, 201, "消息接口恢复", "描述兼容性与订阅关系。")
    mocker.patch("plane.knowledge.semantic.ranked_ids", return_value=[semantic.id])
    refs = capture_task(job, mocker)
    assert [r["reference"] for r in refs] == [f"KN-{semantic.article_id}-v1"]


@pytest.mark.parametrize("revoked", [False, True])
def test_manual_ranking_keeps_existing_share_permission_scope(workspace, create_user, mocker, revoked):
    project, job = diagnostic(workspace, create_user, mocker)
    local = publication(project, 1, "RuntimeError 通用", "本项目候选。")
    source = Project.objects.create(workspace=workspace, name="共享源", identifier="RANKSHARE")
    shared = publication(source, 299, "topic_type_mismatch", "精确共享机制。")
    KnowledgeShare.objects.create(
        project=source,
        article=shared.article,
        revision=shared,
        target_project=project,
        reason="隔离回归",
        active=not revoked,
    )
    mocker.patch("plane.knowledge.semantic.ranked_ids", return_value=[shared.id])
    refs = capture_task(job, mocker)
    actual = [r["reference"] for r in refs]
    if revoked:
        assert actual == [f"KN-{local.article_id}-v1"]
    else:
        assert actual[0] == f"KN-{shared.article_id}-v1"


def test_empty_legacy_iterable_candidate_does_not_fail_before_model(workspace, create_user, mocker):
    project, job = diagnostic(workspace, create_user, mocker)
    # Existing task fixtures and callers can provide a concrete empty candidate list.
    mocker.patch("plane.quality.tasks.assistant.provider_config", return_value={"configured": True})
    mocker.patch("plane.quality.tasks.search", return_value=[])
    called = mocker.patch(
        "plane.quality.tasks.analyze_diagnostic", return_value={"answer": "材料不足", "citations": []}
    )
    run_diagnostic(job.id)
    job.refresh_from_db()
    assert job.result["model_status"] == "completed"
    called.assert_called_once()
