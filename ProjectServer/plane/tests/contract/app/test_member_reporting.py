"""Reporting follows active project membership, not a separate reporter duty."""

from uuid import uuid4
import pytest
from plane.db.models import User, Project, ProjectMember, WorkspaceMember
from plane.quality.models import BusinessRole, ProjectRolePolicy
from plane.quality.permissions import capable, capabilities_for

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def member_reporting(workspace, session_client, create_user):
    project = Project.objects.create(workspace=workspace, name="成员反馈", identifier="MEMREPORT")
    ProjectRolePolicy.objects.create(project=project, enabled=True)
    person = User.objects.create(username="member-reporting", email=f"{uuid4()}@member.invalid")
    WorkspaceMember.objects.create(workspace=workspace, member=person, role=15)
    ProjectMember.objects.create(project=project, member=person, role=15)
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    session_client.force_authenticate(person)
    return session_client, project, person, base


def test_member_without_duty_reports_and_adds_evidence_but_cannot_manage(member_reporting):
    client, project, person, base = member_reporting
    context = client.get(base + "context/")
    assert context.status_code == 200
    for cap in ["report", "package", "chat"]:
        assert capable(project.id, person.id, cap)
        assert context.data["capabilities"][cap]
    defect = client.post(base + "defects/", {"title": "普通成员发现的问题"}, format="json")
    assert defect.status_code == 201, defect.data
    assert not capable(project.id, person.id, "manage_defect")
    assert (
        client.patch(base + f"defects/{defect.data['id']}/", {"status": "resolved"}, format="json").status_code == 403
    )
    assert client.post(base + "cases/", {"title": "越权"}, format="json").status_code == 403


@pytest.mark.parametrize(
    "boundary",
    [
        "project_readonly",
        "workspace_readonly",
        "project_removed",
        "workspace_removed",
        "disabled",
        "outsider",
        "archived",
    ],
)
def test_reporting_never_crosses_membership_boundaries(member_reporting, boundary):
    client, project, person, base = member_reporting
    if boundary == "project_readonly":
        ProjectMember.objects.filter(project=project, member=person).update(role=5)
    elif boundary == "workspace_readonly":
        WorkspaceMember.objects.filter(workspace=project.workspace, member=person).update(role=5)
    elif boundary == "project_removed":
        ProjectMember.objects.filter(project=project, member=person).update(is_active=False)
    elif boundary == "workspace_removed":
        WorkspaceMember.objects.filter(workspace=project.workspace, member=person).update(is_active=False)
    elif boundary == "disabled":
        person.is_active = False
        person.save()
    elif boundary == "outsider":
        ProjectMember.objects.filter(project=project, member=person).delete()
    elif boundary == "archived":
        from django.utils import timezone

        project.archived_at = timezone.now()
        project.save()
    for cap in ["report", "package", "chat"]:
        assert not capable(project.id, person.id, cap)
        assert not capabilities_for(project.id, person.id)[cap]
    assert client.post(base + "defects/", {"title": "无权上报"}, format="json").status_code in {401, 403}


def test_reporter_not_a_selectable_role():
    from plane.quality.roles import RoleInput
    from plane.quality.permissions import ROLE_NAMES

    assert "REPORTER" not in ROLE_NAMES
    assert not RoleInput(data={"user_id": str(uuid4()), "roles": ["REPORTER"]}).is_valid()
    assert RoleInput(data={"user_id": str(uuid4()), "roles": []}).is_valid()


def test_reporter_cleanup_preserves_accounts_defects_audit_and_other_duties(member_reporting):
    from importlib import import_module
    from types import SimpleNamespace
    from django.apps import apps
    from plane.quality.models import BusinessRoleEvent, Defect

    client, project, person, base = member_reporting
    binding = BusinessRole.objects.create(
        project=project, user=person, role="REPORTER", additional_roles=["TECHNICIAN"]
    )
    ws = WorkspaceMember.objects.get(workspace=project.workspace, member=person)
    ws.business_roles = ["REPORTER", "REGRESSION_TESTER"]
    ws.save()
    defect = Defect.objects.create(project=project, created_by=person, title="清理前问题")
    audit = BusinessRoleEvent.objects.create(project=project, user=person, role="REPORTER", action="assign")
    migrate = import_module("plane.quality.migrations.0049_remove_reporter_duty").remove_reporter
    migrate(apps, SimpleNamespace(connection=SimpleNamespace(alias="default")))
    migrate(apps, SimpleNamespace(connection=SimpleNamespace(alias="default")))
    binding.refresh_from_db()
    ws.refresh_from_db()
    assert binding.role == "TECHNICIAN" and binding.additional_roles == []
    assert ws.business_roles == ["REGRESSION_TESTER"]
    assert User.objects.filter(pk=person.pk).exists()
    assert Defect.objects.filter(pk=defect.pk, created_by=person).exists()
    assert BusinessRoleEvent.objects.filter(pk=audit.pk).exists()
    binding.role = "REPORTER"
    binding.save()
    migrate(apps, SimpleNamespace(connection=SimpleNamespace(alias="default")))
    assert not BusinessRole.objects.filter(pk=binding.pk).exists()


def test_future_projects_inherit_explicit_workspace_access_without_duty(member_reporting):
    client, project, person, base = member_reporting
    workspace_member = WorkspaceMember.objects.get(workspace=project.workspace, member=person)
    workspace_member.has_workspace_access = True
    workspace_member.save()
    inherited = Project.objects.create(workspace=project.workspace, name="未来项目", identifier="FUTUREMEM")
    assert ProjectMember.objects.filter(project=inherited, member=person, is_active=True, role=15).exists()
    workspace_member.has_workspace_access = False
    workspace_member.save()
    excluded = Project.objects.create(workspace=project.workspace, name="其他项目", identifier="OTHERONLY")
    assert not ProjectMember.objects.filter(project=excluded, member=person).exists()
