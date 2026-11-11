"""Company size is optional legacy metadata, never required for creating or updating workspaces."""

import pytest
from plane.app.serializers.workspace import WorkSpaceSerializer

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def test_workspace_name_url_creation_does_not_require_company_size():
    form = WorkSpaceSerializer(data={"name": "项目管理", "slug": "no-company-size"})
    assert form.is_valid(), form.errors
    assert "organization_size" not in form.validated_data


def test_workspace_update_does_not_reset_existing_company_size(workspace):
    before = workspace.organization_size
    form = WorkSpaceSerializer(workspace, data={"name": "新的工作空间名称"}, partial=True)
    assert form.is_valid(), form.errors
    form.save()
    workspace.refresh_from_db()
    assert workspace.organization_size == before
