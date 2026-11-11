"""Optional routing, private notes, and explicit rate-limited in-app reminders."""

from datetime import timedelta
import pytest
from django.utils import timezone
from plane.db.models import Project, ProjectMember, User, WorkspaceMember, Notification
from plane.quality.models import (
    BusinessRole,
    ProjectRolePolicy,
    Defect,
    DefectCollaborator,
)

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def team152(workspace, create_user):
    project = Project.objects.create(
        workspace=workspace, name="职责协作", identifier="C152"
    )
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    ProjectRolePolicy.objects.create(project=project, enabled=True)
    BusinessRole.objects.create(
        project=project, user=create_user, role="PROJECT_MANAGER"
    )
    people = {}
    for key, duty in [
        ("owner", "TECHNICIAN"),
        ("helper", "REGRESSION_TESTER"),
        ("collector", "REPORTER"),
        ("other", "TECHNICIAN"),
    ]:
        user = User.objects.create(
            username=f"c152-{key}", email=f"c152-{key}@local.test", display_name=key
        )
        WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
        ProjectMember.objects.create(project=project, member=user, role=15)
        BusinessRole.objects.create(project=project, user=user, role=duty)
        people[key] = user
    defect = Defect.objects.create(
        project=project,
        created_by=people["collector"],
        title="隔离协作",
        assignee=people["owner"],
    )
    DefectCollaborator.objects.create(
        project=project, defect=defect, user=people["helper"]
    )
    return (
        f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/",
        project,
        defect,
        people,
        create_user,
    )


def test_routing_is_optional_project_config_and_versioned_assignment(
    session_client, team152
):
    base, project, defect, people, manager = team152
    config = session_client.get(base + "collaboration-settings/")
    assert config.status_code == 200 and config.data["enabled"] is False, config.content
    settings = session_client.put(
        base + "collaboration-settings/",
        {
            "enabled": True,
            "departments": ["采集组", "算法组"],
            "components": ["相机", "驱动"],
            "expected_version": config.data["version"],
        },
        format="json",
    )
    assert settings.status_code == 200, settings.content
    url = base + f"defects/{defect.id}/routing/"
    session_client.force_authenticate(people["owner"])
    updated = session_client.patch(
        url,
        {
            "department": "采集组",
            "component": "相机",
            "expected_version": defect.edit_version,
        },
        format="json",
    )
    assert updated.status_code == 200, updated.content
    defect.refresh_from_db()
    assert defect.assignee_id == people["owner"].id
    assert session_client.get(url).data["department"] == "采集组"
    assert (
        session_client.patch(
            url,
            {"department": "未配置", "expected_version": defect.edit_version},
            format="json",
        ).status_code
        == 400
    )
    assert (
        session_client.patch(
            url, {"component": "驱动", "expected_version": 1}, format="json"
        ).status_code
        == 409
    )
    session_client.force_authenticate(people["helper"])
    assert (
        session_client.patch(
            url,
            {"department": "算法组", "expected_version": defect.edit_version},
            format="json",
        ).status_code
        == 403
    )
    assert (
        session_client.put(
            base + "collaboration-settings/",
            {
                "enabled": False,
                "departments": [],
                "components": [],
                "expected_version": settings.data["version"],
            },
            format="json",
        ).status_code
        == 403
    )


def test_internal_notes_never_reach_collectors_guests_or_notification_body(
    session_client, team152
):
    base, project, defect, people, manager = team152
    url = base + f"defects/{defect.id}/collaboration/"
    session_client.force_authenticate(people["owner"])
    internal = session_client.post(
        url,
        {
            "action": "comment",
            "visibility": "internal",
            "content": "内部排查细节 C152private",
        },
        format="json",
    )
    assert (
        internal.status_code == 201 and internal.data["visibility"] == "internal"
    ), internal.content
    public = session_client.post(
        url,
        {"action": "comment", "visibility": "public", "content": "请补充现场日志"},
        format="json",
    )
    assert public.status_code == 201, public.content
    assert session_client.get(url).data["count"] == 2
    session_client.force_authenticate(people["collector"])
    result = session_client.get(url)
    assert result.status_code == 200 and result.data["count"] == 1, result.content
    assert "C152private" not in str(result.data)
    assert (
        session_client.post(
            url,
            {"action": "comment", "visibility": "internal", "content": "不得升级"},
            format="json",
        ).status_code
        == 403
    )
    assert (
        session_client.post(
            url,
            {"action": "comment", "visibility": "public", "content": "日志已补充"},
            format="json",
        ).status_code
        == 201
    )
    assert not Notification.objects.filter(
        project=project, message__text__contains="C152private"
    ).exists()
    ProjectMember.objects.filter(project=project, member=people["collector"]).update(
        role=5
    )
    assert session_client.get(url).data["count"] == 2
    session_client.force_authenticate(people["owner"])
    ProjectMember.objects.filter(project=project, member=people["owner"]).update(
        is_active=False
    )
    assert session_client.get(url).status_code == 403


def test_internal_notes_fail_closed_when_business_policy_disabled(
    session_client, team152
):
    base, project, defect, people, manager = team152
    url = base + f"defects/{defect.id}/collaboration/"
    session_client.post(
        url,
        {"action": "comment", "visibility": "internal", "content": "仅供内部"},
        format="json",
    )
    ProjectRolePolicy.objects.filter(project=project).update(enabled=False)
    session_client.force_authenticate(people["collector"])
    assert session_client.get(url).data["count"] == 0
    assert (
        session_client.post(
            url,
            {"action": "comment", "visibility": "internal", "content": "越权"},
            format="json",
        ).status_code
        == 403
    )


def test_mapped_collector_without_duty_never_reads_internal_notes(
    session_client, team152
):
    from plane.quality.models import PlatformIdentity

    base, project, defect, people, manager = team152
    url = base + f"defects/{defect.id}/collaboration/"
    session_client.post(
        url,
        {"action": "comment", "visibility": "internal", "content": "仅供项目内部"},
        format="json",
    )
    ProjectRolePolicy.objects.filter(project=project).update(enabled=False)
    BusinessRole.objects.filter(project=project, user=people["collector"]).delete()
    PlatformIdentity.objects.create(
        project=project,
        user=people["collector"],
        source_instance="dp",
        external_user_id=152,
    )
    session_client.force_authenticate(people["collector"])
    assert session_client.get(url).data["count"] == 0


@pytest.mark.django_db(transaction=True)
def test_simultaneous_reminders_send_once_for_the_same_defect_recipient(team152):
    from concurrent.futures import ThreadPoolExecutor
    from django.db import close_old_connections
    from rest_framework.test import APIClient

    base, project, defect, people, manager = team152

    def send():
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(people["helper"])
            return client.post(
                base + f"defects/{defect.id}/reminders/",
                {"target": "assignee"},
                format="json",
            ).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: send(), range(2)))
    assert sorted(statuses) == [201, 429], statuses
    assert (
        Notification.objects.filter(
            project=project, receiver=people["owner"], title__startswith="请跟进缺陷"
        ).count()
        == 1
    )


def test_reminders_derive_receivers_and_throttle_per_defect_and_recipient(
    session_client, team152
):
    base, project, defect, people, manager = team152
    url = base + f"defects/{defect.id}/reminders/"
    session_client.force_authenticate(people["helper"])
    assert (
        session_client.post(
            url,
            {"target": "assignee", "user_id": str(people["other"].id)},
            format="json",
        ).status_code
        == 400
    )
    first = session_client.post(url, {"target": "assignee"}, format="json")
    assert first.status_code == 201 and first.data["sent"] == 1, first.content
    count = Notification.objects.filter(
        project=project, receiver=people["owner"], title__startswith="请跟进缺陷"
    ).count()
    assert count == 1
    retry = session_client.post(url, {"target": "assignee"}, format="json")
    assert retry.status_code == 429, retry.content
    assert (
        Notification.objects.filter(
            project=project, receiver=people["owner"], title__startswith="请跟进缺陷"
        ).count()
        == count
    )
    from plane.quality.models import DefectReminder

    DefectReminder.objects.filter(defect=defect).update(
        sent_at=timezone.now() - timedelta(minutes=11)
    )
    assert (
        session_client.post(url, {"target": "assignee"}, format="json").status_code
        == 201
    )
    session_client.force_authenticate(people["other"])
    assert (
        session_client.post(url, {"target": "assignee"}, format="json").status_code
        == 403
    )
    session_client.force_authenticate(people["collector"])
    assert (
        session_client.post(url, {"target": "assignee"}, format="json").status_code
        == 403
    )


def test_reminders_recheck_current_membership_and_do_not_expand_duties(
    session_client, team152
):
    base, project, defect, people, manager = team152
    url = base + f"defects/{defect.id}/reminders/"
    session_client.force_authenticate(people["owner"])
    assert (
        session_client.post(url, {"target": "managers"}, format="json").status_code
        == 201
    )
    before = Notification.objects.filter(project=project).count()
    WorkspaceMember.objects.filter(workspace=project.workspace, member=manager).update(
        is_active=False
    )
    assert (
        session_client.post(url, {"target": "managers"}, format="json").status_code
        == 400
    )
    assert Notification.objects.filter(project=project).count() == before
    stranger = Project.objects.create(
        workspace=project.workspace, name="无权限", identifier="NO152"
    )
    foreign = Defect.objects.create(project=stranger, title="不可读")
    assert (
        session_client.post(
            base + f"defects/{foreign.id}/reminders/",
            {"target": "assignee"},
            format="json",
        ).status_code
        == 404
    )
