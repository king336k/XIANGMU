from uuid import uuid4
import pytest
from plane.db.models import Project, ProjectMember, User, WorkspaceMember

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def flow(session_client, workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="技术审核", identifier="RV")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    reviewer = User.objects.create(email="review@solutions.local", username="reviewer")
    WorkspaceMember.objects.create(workspace=workspace, member=reviewer, role=15)
    ProjectMember.objects.create(project=project, member=reviewer, role=15)
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    defect = session_client.post(base + "defects/", {"title": "待解决缺陷"}, format="json").data
    payload = {
        "defect_id": defect["id"],
        "title": "修复方案",
        "root_cause": "调用顺序不正确",
        "steps": "调整顺序并保留失败证据",
        "verification": "回归验证同场景",
        "risk": "影响账号流程",
        "rollback": "回退本次配置",
        "repository": "",
        "commit_sha": "",
    }
    return base, defect, payload, reviewer, create_user


def test_review_freezes_version_and_forbids_self_approval(session_client, flow):
    base, defect, payload, reviewer, author = flow
    response = session_client.post(base + "solutions/", payload, format="json")
    assert response.status_code == 201, response.content
    solution = response.data
    submitted = session_client.post(
        base + f"solutions/{solution['id']}/submit/",
        {"expected_version": 1, "reviewer_ids": [str(reviewer.id)], "required_count": 1},
        format="json",
    )
    assert submitted.status_code == 200, submitted.data
    revision = submitted.data["revisions"][0]
    frozen = revision["snapshot"]
    denied = session_client.post(
        base + f"solutions/{solution['id']}/review/",
        {"revision_id": revision["id"], "decision": "approve", "comment": "自审"},
        format="json",
    )
    assert denied.status_code == 403
    patch = session_client.patch(
        base + f"solutions/{solution['id']}/",
        {"expected_version": submitted.data["edit_version"], "root_cause": "偷偷改"},
        format="json",
    )
    assert patch.status_code == 409
    session_client.force_authenticate(user=reviewer)
    reviewed = session_client.post(
        base + f"solutions/{solution['id']}/review/",
        {"revision_id": revision["id"], "decision": "approve", "comment": "确认处理及回滚方案"},
        format="json",
    )
    assert reviewed.status_code == 200 and reviewed.data["status"] == "approved"
    assert reviewed.data["revisions"][0]["snapshot"] == frozen


def test_rejection_requires_reason_and_new_version_preserves_history(session_client, flow):
    base, defect, payload, reviewer, author = flow
    solution = session_client.post(base + "solutions/", payload, format="json").data
    submitted = session_client.post(
        base + f"solutions/{solution['id']}/submit/",
        {"expected_version": 1, "reviewer_ids": [str(reviewer.id)], "required_count": 1},
        format="json",
    ).data
    revision = submitted["revisions"][0]
    session_client.force_authenticate(user=reviewer)
    url = base + f"solutions/{solution['id']}/review/"
    assert (
        session_client.post(url, {"revision_id": revision["id"], "decision": "reject"}, format="json").status_code
        == 400
    )
    rejected = session_client.post(
        url, {"revision_id": revision["id"], "decision": "reject", "comment": "缺少边界验证"}, format="json"
    ).data
    assert rejected["status"] == "rejected"
    session_client.force_authenticate(user=author)
    edited = session_client.patch(
        base + f"solutions/{solution['id']}/",
        {"expected_version": rejected["edit_version"], "verification": "补全边界"},
        format="json",
    )
    assert edited.status_code == 200 and edited.data["status"] == "draft"
    assert edited.data["revisions"][0]["snapshot"]["verification"] == "回归验证同场景"


def test_cross_project_defect_and_invalid_reviewers_rejected(session_client, flow):
    base, defect, payload, reviewer, author = flow
    stranger = User.objects.create(email="stranger@solutions.local", username="stranger-solution")
    solution = session_client.post(base + "solutions/", payload, format="json").data
    url = base + f"solutions/{solution['id']}/submit/"
    assert (
        session_client.post(
            url, {"expected_version": 1, "reviewer_ids": [str(stranger.id)], "required_count": 1}, format="json"
        ).status_code
        == 400
    )
    assert (
        session_client.post(
            url, {"expected_version": 1, "reviewer_ids": [str(author.id)], "required_count": 1}, format="json"
        ).status_code
        == 400
    )
    bad = {**payload, "defect_id": str(uuid4())}
    assert session_client.post(base + "solutions/", bad, format="json").status_code == 404


def test_review_quorum_requires_multiple_distinct_reviewers(session_client, flow, workspace):
    base, defect, payload, first, author = flow
    project = Project.objects.get(name="技术审核")
    second = User.objects.create(email="review2@solutions.local", username="reviewer2")
    WorkspaceMember.objects.create(workspace=workspace, member=second, role=15)
    ProjectMember.objects.create(project=project, member=second, role=15)
    solution = session_client.post(base + "solutions/", payload, format="json").data
    submitted = session_client.post(
        base + f"solutions/{solution['id']}/submit/",
        {"expected_version": 1, "reviewer_ids": [str(first.id), str(second.id)], "required_count": 2},
        format="json",
    ).data
    revision = submitted["revisions"][0]
    url = base + f"solutions/{solution['id']}/review/"
    session_client.force_authenticate(user=first)
    first_vote = session_client.post(url, {"revision_id": revision["id"], "decision": "approve"}, format="json")
    assert first_vote.status_code == 200 and first_vote.data["status"] == "review"
    retry = session_client.post(url, {"revision_id": revision["id"], "decision": "approve"}, format="json")
    assert len(retry.data["revisions"][0]["reviews"]) == 1
    session_client.force_authenticate(user=second)
    final = session_client.post(url, {"revision_id": revision["id"], "decision": "approve"}, format="json")
    assert final.data["status"] == "approved"
