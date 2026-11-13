"""Reviewer-owned isolated DB contract checks; never target production settings.
Copy into the isolated test checkout's plane/tests/contract/app/ before pytest.
Fixtures use synthetic signed reports and local attachment files only.
"""

import json

import pytest
from rest_framework.test import APIClient
from plane.db.models import Project
from plane.knowledge.models import Article, PublishedRevision
from plane.knowledge.sharing_models import KnowledgeShare
from plane.quality.diagnostics import DiagnosticSerializer
from plane.tests.contract.app.test_automatic_diagnostics import material, run
from plane.tests.contract.app.test_automatic_diagnostics import current as current
from plane.tests.contract.app.test_daq_reporting import reporting as reporting

pytestmark = [pytest.mark.contract, pytest.mark.django_db]
APPROVED = "daq-diagnostic-approved"


def publication(project, *, content="录制与遥操独立；idle不能当作离线。"):
    article = Article.objects.create(
        project=project,
        title="DAQ RuntimeError idle录制诊断知识",
        content=content,
        tags=[APPROVED],
        publication_active=True,
        status="published",
        published_version=1,
        scanned_version=2,
        edit_version=4,
    )
    revision = PublishedRevision.objects.create(
        project=project,
        article=article,
        version=1,
        title=article.title,
        content=article.content,
        tags=article.tags,
    )
    return article, revision


def execute(current, mocker):
    _, job = material(current, raw=b"RuntimeError: idle recording state observed")
    mocker.patch("plane.knowledge.assistant.provider_config", return_value={"configured": True})
    observed = {}

    def analyze(config, text, sources, references, materials):
        observed["references"] = references
        knowledge = [r for r in references if r["reference"].startswith("KN-")]
        return {
            "answer": "当前状态需结合当前模式判断，尚未证明故障。",
            "suggested_actions": ["只读核对当前模式"],
            "verification_steps": ["核对同一时间窗状态"],
            "citations": knowledge or [{"reference": "DESCRIPTION", "title": "上报描述"}],
            "model_confidence": 0.4,
            "evidence_assessment": "partial",
            "confidence_basis": "输入不足以确认根因。",
            "confidence_references": knowledge,
        }

    mocker.patch("plane.quality.tasks.analyze_diagnostic", side_effect=analyze)
    run(job)
    assert job.result["model_status"] == "completed", job.result.get("model_error_code")
    return job, observed["references"]


def knowledge_ids(references):
    return {r["reference"] for r in references if r["reference"].startswith("KN-")}


def test_report_only_receives_explicitly_approved_same_project_current_publication(current, mocker):
    project, *_ = current
    article, _ = publication(project)
    job, refs = execute(current, mocker)
    assert knowledge_ids(refs) == {f"KN-{article.id}-v1"}
    assert any(r["reference"] == "PLATFORM-RECEIPT" for r in refs)
    # Publication workflow increments edit_version after scan: do not incorrectly require equality.
    assert article.scanned_version != article.edit_version
    assert job.result["assignment"]["module"] is None, "Knowledge/model prose is not failure module evidence"


@pytest.mark.parametrize(
    "condition",
    [
        "revision_untagged",
        "article_untagged",
        "unscanned",
        "draft",
        "offline",
        "superseded",
        "sensitive_current_revision",
        "sensitive_current_article",
    ],
)
def test_report_only_excludes_nonapproved_and_stale_publications(current, mocker, condition):
    project, *_ = current
    article, revision = publication(project)
    if condition == "revision_untagged":
        revision.tags = []
        revision.save()
    elif condition == "article_untagged":
        article.tags = []
        article.save()
    elif condition == "unscanned":
        article.scanned_version = 0
        article.save()
    elif condition == "draft":
        article.status = "draft"
        article.save()
    elif condition == "offline":
        article.publication_active = False
        article.save()
    elif condition == "superseded":
        article.published_version = 2
        article.save()
    elif condition == "sensitive_current_revision":
        revision.content = "password=synthetic-reviewer-sentinel"
        revision.save()
    elif condition == "sensitive_current_article":
        article.scan_findings = [{"kind": "credential", "line": 1}]
        article.save()
    _, refs = execute(current, mocker)
    assert not knowledge_ids(refs)
    assert "synthetic-reviewer-sentinel" not in json.dumps(refs)


def test_only_explicit_current_share_is_eligible_and_preserves_scope(current, mocker):
    project, *_ = current
    source = Project.objects.create(workspace=project.workspace, name="合成知识源", identifier="SYNTHKB")
    article, revision = publication(source)
    unrelated = Project.objects.create(workspace=project.workspace, name="合成未共享", identifier="SYNTHNO")
    publication(unrelated)
    KnowledgeShare.objects.create(
        project=source,
        article=article,
        revision=revision,
        target_project=project,
        reason="隔离测试",
        device_scope="合成设备类型",
        version_scope="固定合成版本",
    )
    _, refs = execute(current, mocker)
    knowledge = [r for r in refs if r["reference"].startswith("KN-")]
    assert len(knowledge) == 1 and knowledge[0]["reference"] == f"KN-{article.id}-v1"
    assert knowledge[0]["device_scope"] == "合成设备类型"
    assert knowledge[0]["version_scope"] == "固定合成版本"


@pytest.mark.parametrize("revocation", ["article_tag", "revision_tag", "offline", "new_version", "share"])
def test_revocation_hides_report_only_history_and_confidence(current, mocker, revocation):
    project, *_ = current
    source = Project.objects.create(workspace=project.workspace, name="合成撤回源", identifier="SYNTHREV")
    article, revision = publication(source)
    share = KnowledgeShare.objects.create(
        project=source,
        article=article,
        revision=revision,
        target_project=project,
        reason="隔离测试",
    )
    job, refs = execute(current, mocker)
    assert f"KN-{article.id}-v1" in knowledge_ids(refs)
    if revocation == "article_tag":
        article.tags = []
        article.save()
    elif revocation == "revision_tag":
        revision.tags = []
        revision.save()
    elif revocation == "offline":
        article.publication_active = False
        article.save()
    elif revocation == "new_version":
        article.published_version = 2
        article.save()
    else:
        share.active = False
        share.save()
    result = DiagnosticSerializer(job).data["result"]
    assert result["model_status"] == "reference_unavailable"
    assert result["answer"] == "" and result["citations"] == []
    assert result["model_confidence"] is None
    assert result["confidence_basis"] == "" and result["confidence_references"] == []
    assert result["suggested_actions"] == [] and result["verification_steps"] == []


def test_report_only_knowledge_injection_does_not_grant_editorial_api_access(current, mocker):
    project, actor, *_ = current
    article, _ = publication(project)
    execute(current, mocker)
    client = APIClient()
    client.force_authenticate(user=actor)
    base = f"/api/workspaces/{project.workspace.slug}/projects/{project.id}/knowledge/"
    for suffix in ["search/?q=DAQ", "articles/", f"articles/{article.id}/"]:
        assert client.get(base + suffix).status_code == 403


def test_knowledge_excerpts_are_bounded_in_model_input_and_serialized_result(current, mocker):
    project, *_ = current
    publication(project, content=("录制idle需要模式证据，不可直接确认故障。\n" * 1200))
    job, refs = execute(current, mocker)
    knowledge = [r for r in refs if r["reference"].startswith("KN-")]
    assert knowledge, "Baseline must fail here because report_only previously supplied no knowledge"
    assert len(knowledge) <= 5
    assert all(len(r.get("content", "")) <= 5000 for r in knowledge)
    result = DiagnosticSerializer(job).data["result"]
    assert all(len(r.get("content", "")) <= 5000 for r in result["citations"])
