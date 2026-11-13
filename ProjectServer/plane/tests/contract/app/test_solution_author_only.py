"""A solution belongs to its author even if the defect is later reassigned."""

import pytest
from plane.quality.models import SolutionRevision
from plane.tests.contract.app.test_solution_action_flags import solution_scope as solution_fixture

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture(name="solution_scope")
def authors_context(session_client, workspace, create_user):
    return solution_fixture.__wrapped__(workspace, create_user)


def test_original_author_keeps_edit_and_submit_after_defect_transfer(session_client, solution_scope):
    _, base, people, _, solution, _ = solution_scope
    session_client.force_authenticate(people["old"])
    detail = session_client.get(base + f"solutions/{solution.id}/")
    assert detail.status_code == 200 and detail.data["can_edit"] and detail.data["can_submit"]
    edited = session_client.patch(
        base + f"solutions/{solution.id}/", {"title": "作者补充", "expected_version": 1}, format="json"
    )
    assert edited.status_code == 200
    sent = session_client.post(
        base + f"solutions/{solution.id}/submit/",
        {
            "expected_version": edited.data["edit_version"],
            "reviewer_ids": [str(people["reviewer"].id)],
            "required_count": 1,
        },
        format="json",
    )
    assert sent.status_code == 200 and sent.data["status"] == "review"
    assert SolutionRevision.objects.get(solution=solution).created_by_id == people["old"].id


def test_new_defect_owner_and_manager_cannot_edit_or_submit_another_authors_solution(session_client, solution_scope):
    _, base, people, _, solution, manager = solution_scope
    for user in [people["new"], manager]:
        session_client.force_authenticate(user)
        detail = session_client.get(base + f"solutions/{solution.id}/")
        assert detail.status_code == 200 and not detail.data["can_edit"] and not detail.data["can_submit"]
        denied = session_client.patch(
            base + f"solutions/{solution.id}/", {"title": "不能替别人改", "expected_version": 1}, format="json"
        )
        assert denied.status_code == 403
        sent = session_client.post(
            base + f"solutions/{solution.id}/submit/",
            {"expected_version": 1, "reviewer_ids": [str(people["reviewer"].id)], "required_count": 1},
            format="json",
        )
        assert sent.status_code == 403


def test_canonical_administrator_can_manage_another_authors_solution(session_client, solution_scope):
    from uuid import uuid4
    from django.utils import timezone
    from plane.license.models import Instance, InstanceAdmin

    _, base, _, _, solution, administrator = solution_scope
    instance = Instance.objects.create(
        instance_name="方案管理员", instance_id=str(uuid4()), current_version="test", last_checked_at=timezone.now()
    )
    InstanceAdmin.objects.create(instance=instance, user=administrator)
    session_client.force_authenticate(administrator)
    detail = session_client.get(base + f"solutions/{solution.id}/")
    assert detail.status_code == 200 and detail.data["can_edit"] and detail.data["can_submit"]
    edited = session_client.patch(
        base + f"solutions/{solution.id}/", {"title": "管理员处理", "expected_version": 1}, format="json"
    )
    assert edited.status_code == 200 and edited.data["title"] == "管理员处理"
