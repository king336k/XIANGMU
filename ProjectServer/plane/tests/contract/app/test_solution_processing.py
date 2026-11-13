"""Successful owner work starts processing without inventing past transitions."""

import pytest
from plane.quality.models import Defect, DefectEvent, Solution
from plane.tests.contract.app.test_solution_action_flags import solution_scope as scope_fixture

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture(name="scope")
def processing_scope(workspace, create_user):
    return scope_fixture.__wrapped__(workspace, create_user)


def payload(defect):
    return {
        "defect_id": str(defect.id),
        "title": "真实处理方案",
        "root_cause": "原因",
        "steps": "修复",
        "verification": "验证",
    }


def started(defect):
    return DefectEvent.objects.filter(defect=defect, previous_status="open", status="in_progress")


@pytest.mark.parametrize("action", ["create", "edit", "submit"])
def test_owner_successfully_working_on_solution_starts_processing_once(session_client, scope, action):
    _, base, people, defect, solution, _ = scope
    solution.created_by = people["new"]
    solution.save(update_fields=["created_by"])
    old_version = defect.edit_version
    old_updated = defect.updated_at
    session_client.force_authenticate(people["new"])
    if action == "create":
        response = session_client.post(base + "solutions/", payload(defect), format="json")
    elif action == "edit":
        response = session_client.patch(
            base + f"solutions/{solution.id}/", {"expected_version": 1, "title": "开始修复"}, format="json"
        )
    else:
        response = session_client.post(
            base + f"solutions/{solution.id}/submit/",
            {"expected_version": 1, "reviewer_ids": [str(people["reviewer"].id)], "required_count": 1},
            format="json",
        )
    assert response.status_code in [200, 201], response.content
    defect.refresh_from_db()
    assert defect.status == "in_progress"
    assert defect.edit_version == old_version + 1
    assert defect.updated_at > old_updated
    assert started(defect).count() == 1
    assert started(defect).get().created_by_id == people["new"].id
    assert started(defect).get().note == "维护技术方案，开始处理缺陷。"
    again = session_client.post(base + "solutions/", payload(defect), format="json")
    assert again.status_code == 201
    defect.refresh_from_db()
    assert defect.edit_version == old_version + 1 and started(defect).count() == 1


def test_original_author_after_transfer_does_not_start_for_new_owner(session_client, scope):
    _, base, people, defect, solution, _ = scope
    session_client.force_authenticate(people["old"])
    response = session_client.patch(
        base + f"solutions/{solution.id}/", {"expected_version": 1, "title": "补充原方案"}, format="json"
    )
    assert response.status_code == 200
    sent = session_client.post(
        base + f"solutions/{solution.id}/submit/",
        {"expected_version": 2, "reviewer_ids": [str(people["reviewer"].id)], "required_count": 1},
        format="json",
    )
    assert sent.status_code == 200
    defect.refresh_from_db()
    assert defect.status == "open" and defect.edit_version == 1 and not started(defect).exists()


def test_canonical_admin_solution_work_starts_processing(session_client, scope):
    from uuid import uuid4
    from django.utils import timezone
    from plane.license.models import Instance, InstanceAdmin

    _, base, _, defect, solution, administrator = scope
    instance = Instance.objects.create(
        instance_name="处理管理员", instance_id=str(uuid4()), current_version="test", last_checked_at=timezone.now()
    )
    InstanceAdmin.objects.create(instance=instance, user=administrator)
    session_client.force_authenticate(administrator)
    response = session_client.patch(
        base + f"solutions/{solution.id}/", {"expected_version": 1, "title": "管理员处理"}, format="json"
    )
    assert response.status_code == 200
    defect.refresh_from_db()
    assert defect.status == "in_progress" and started(defect).get().created_by_id == administrator.id


@pytest.mark.parametrize("failure", ["unauthorized", "stale", "invalid", "bad_reviewer"])
def test_failed_solution_write_does_not_start_processing(session_client, scope, failure):
    _, base, people, defect, solution, _ = scope
    solution.created_by = people["new"]
    solution.save(update_fields=["created_by"])
    session_client.force_authenticate(people["old"] if failure == "unauthorized" else people["new"])
    if failure == "invalid":
        response = session_client.post(base + "solutions/", {"defect_id": str(defect.id)}, format="json")
        assert response.status_code == 400
    elif failure == "bad_reviewer":
        response = session_client.post(
            base + f"solutions/{solution.id}/submit/",
            {"expected_version": 1, "reviewer_ids": [str(people["new"].id)], "required_count": 1},
            format="json",
        )
        assert response.status_code == 400
    else:
        response = session_client.patch(
            base + f"solutions/{solution.id}/",
            {"expected_version": 99 if failure == "stale" else 1, "title": "禁止"},
            format="json",
        )
        assert response.status_code == (403 if failure == "unauthorized" else 409)
    defect.refresh_from_db()
    assert defect.status == "open" and defect.edit_version == 1 and not started(defect).exists()


@pytest.mark.parametrize("status", ["resolved", "closed"])
def test_solution_work_does_not_rewind_later_status(session_client, scope, status):
    _, base, people, defect, solution, _ = scope
    Defect.objects.filter(pk=defect.pk).update(status=status)
    solution.created_by = people["new"]
    solution.save(update_fields=["created_by"])
    session_client.force_authenticate(people["new"])
    response = session_client.patch(
        base + f"solutions/{solution.id}/", {"expected_version": 1, "title": "更新"}, format="json"
    )
    assert response.status_code == (200 if status == "resolved" else 409)
    defect.refresh_from_db()
    assert defect.status == status and not started(defect).exists()


@pytest.mark.parametrize("previous", ["closed", "resolved"])
def test_old_draft_starts_new_processing_after_reopen_or_return(session_client, scope, previous):
    _, base, people, defect, solution, _ = scope
    DefectEvent.objects.create(
        project=defect.project,
        defect=defect,
        previous_status=previous,
        status="open",
        created_by=people["new"],
        note="重开或退回修复",
    )
    solution.created_by = people["new"]
    solution.save(update_fields=["created_by"])
    session_client.force_authenticate(people["new"])
    response = session_client.patch(
        base + f"solutions/{solution.id}/", {"expected_version": 1, "title": "继续修复"}, format="json"
    )
    assert response.status_code == 200
    defect.refresh_from_db()
    assert defect.status == "in_progress" and started(defect).count() == 1


def test_manager_can_start_without_solution(session_client, scope):
    _, base, _, defect, _, manager = scope
    session_client.force_authenticate(manager)
    response = session_client.patch(
        base + f"defects/{defect.id}/", {"expected_version": 1, "status": "in_progress"}, format="json"
    )
    assert response.status_code == 200, response.content
    defect.refresh_from_db()
    assert defect.status == "in_progress" and started(defect).count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_solution_creation_starts_defect_once(scope):
    from concurrent.futures import ThreadPoolExecutor
    from django.db import close_old_connections
    from rest_framework.test import APIClient

    _, base, people, defect, _, _ = scope

    def create(_):
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(people["new"])
            return client.post(base + "solutions/", payload(defect), format="json").status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(create, range(2))) == [201, 201]
    defect.refresh_from_db()
    assert defect.status == "in_progress" and defect.edit_version == 2
    assert started(defect).count() == 1
    assert Solution.objects.filter(defect=defect, created_by=people["new"]).count() == 2


def test_solution_start_notifies_the_real_reporter(session_client, scope):
    from plane.db.models import Notification

    _, base, people, defect, _, manager = scope
    session_client.force_authenticate(people["new"])
    assert session_client.post(base + "solutions/", payload(defect), format="json").status_code == 201
    notice = Notification.objects.get(entity_identifier=defect.id, receiver=manager, title__startswith="缺陷已开始处理")
    assert notice.triggered_by_id == people["new"].id


def test_archived_solution_work_is_rejected_without_start(session_client, scope):
    from django.utils import timezone

    _, base, people, defect, _, _ = scope
    Defect.objects.filter(pk=defect.pk).update(archived_at=timezone.now())
    session_client.force_authenticate(people["new"])
    assert session_client.post(base + "solutions/", payload(defect), format="json").status_code == 409
    assert not started(defect).exists()


def test_failed_notification_rolls_back_start_and_solution(session_client, scope, monkeypatch):
    from plane.quality import notifications

    _, base, people, defect, _, _ = scope
    before = Solution.objects.filter(defect=defect).count()

    def fail(*args, **kwargs):
        raise RuntimeError("CONTROLLED_NOTIFICATION_FAILURE")

    monkeypatch.setattr(notifications, "defect_notice", fail)
    session_client.force_authenticate(people["new"])
    response = session_client.post(base + "solutions/", payload(defect), format="json")
    assert response.status_code == 500
    defect.refresh_from_db()
    assert defect.status == "open" and defect.edit_version == 1
    assert not started(defect).exists() and Solution.objects.filter(defect=defect).count() == before


def test_review_decision_alone_does_not_start_processing(session_client, scope):
    from plane.quality.models import SolutionRevision

    project, base, people, defect, solution, _ = scope
    solution.status, solution.submitted_version = "review", 1
    solution.save()
    revision = SolutionRevision.objects.create(
        project=project,
        solution=solution,
        created_by=people["old"],
        version=1,
        snapshot={},
        reviewer_ids=[str(people["reviewer"].id)],
        required_count=1,
    )
    session_client.force_authenticate(people["reviewer"])
    response = session_client.post(
        base + f"solutions/{solution.id}/review/",
        {"revision_id": str(revision.id), "decision": "approve"},
        format="json",
    )
    assert response.status_code == 200
    defect.refresh_from_db()
    assert defect.status == "open" and defect.edit_version == 1 and not started(defect).exists()


def test_start_resumes_deferred_defect_like_explicit_status_action(session_client, scope):
    from django.utils import timezone

    _, base, people, defect, _, _ = scope
    Defect.objects.filter(pk=defect.pk).update(resolution_kind="deferred", defer_until=timezone.now().date())
    session_client.force_authenticate(people["new"])
    assert session_client.post(base + "solutions/", payload(defect), format="json").status_code == 201
    defect.refresh_from_db()
    assert defect.status == "in_progress" and defect.resolution_kind == "fixed" and defect.defer_until is None


@pytest.mark.django_db(transaction=True)
def test_concurrent_create_and_edit_use_same_lock_order_and_start_once(scope):
    from concurrent.futures import ThreadPoolExecutor
    from django.db import close_old_connections
    from rest_framework.test import APIClient

    _, base, people, defect, solution, _ = scope
    solution.created_by = people["new"]
    solution.save(update_fields=["created_by"])

    def work(action):
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(people["new"])
            if action == "create":
                return client.post(base + "solutions/", payload(defect), format="json").status_code
            return client.patch(
                base + f"solutions/{solution.id}/", {"expected_version": 1, "title": "并发编辑"}, format="json"
            ).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(work, ["create", "edit"])) == [201, 200]
    defect.refresh_from_db()
    assert defect.status == "in_progress" and defect.edit_version == 2 and started(defect).count() == 1
