"""Integration administration displays safe state and preserves explicit identity mapping."""

import pytest
from plane.db.models import Project, ProjectMember
from plane.quality.models import PlatformProject, PlatformIdentity

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def integrations(workspace, create_user):
    p = Project.objects.create(workspace=workspace, name="集成管理", identifier="INT")
    ProjectMember.objects.create(project=p, member=create_user, role=20)
    mapping = PlatformProject.objects.create(project=p, source_instance="test-platform", external_project_id=3)
    identity = PlatformIdentity.objects.create(
        project=p, source_instance="test-platform", external_user_id=16, user=create_user
    )
    return f"/api/workspaces/{workspace.slug}/projects/{p.id}/quality/", p, mapping, identity


def test_integration_overview_hides_credentials_and_disabling_mapping_revokes_bridge(
    session_client, integrations, settings
):
    base, p, mapping, identity = integrations
    settings.QUALITY_PLATFORM_SOURCES = {
        "test-platform": {
            "base_url": "http://10.10.10.157:8090",
            "allowed_hosts": ["10.10.10.157"],
            "allow_http_local": True,
            "service_token": "not-real-secret-for-test",
        }
    }
    view = session_client.get(base + "integrations/")
    assert view.status_code == 200, view.content
    assert "not-real-secret-for-test" not in str(view.data)
    assert view.data["projects"][0]["source_instance"] == "test-platform"
    disabled = session_client.post(
        base + "integrations/",
        {"kind": "identity", "id": str(identity.id), "expected_active": True, "active": False},
        format="json",
    )
    assert disabled.status_code == 200 and disabled.data["active"] is False, disabled.content
    identity.refresh_from_db()
    assert not identity.active
    assert (
        session_client.post(
            base + "integrations/",
            {"kind": "identity", "id": str(identity.id), "expected_active": True, "active": True},
            format="json",
        ).status_code
        == 409
    )


def test_project_member_cannot_administer_or_view_identity_catalog(session_client, integrations, create_user):
    base, p, mapping, identity = integrations
    ProjectMember.objects.filter(project=p, member=create_user).update(role=15)
    assert session_client.get(base + "integrations/").status_code == 403
    assert (
        session_client.post(
            base + "integrations/",
            {"kind": "project", "id": str(mapping.id), "expected_active": True, "active": False},
            format="json",
        ).status_code
        == 403
    )


def test_integration_check_requires_mapping_and_real_authority_project_match(session_client, integrations, mocker):
    base, p, mapping, identity = integrations
    mocker.patch("plane.quality.platform.fetch", return_value={"projectId": 999, "taskId": 24})
    denied = session_client.post(
        base + "integrations/check/", {"source_instance": "test-platform", "task_id": 24}, format="json"
    )
    assert denied.status_code == 400, denied.content
