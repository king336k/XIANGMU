"""Only report-only APIs accept DAQ transport signatures; native project APIs reject them."""

import json
import pytest
from rest_framework.test import APIClient
from plane.db.models import Project
from plane.quality.models import PackageFile, ProblemPackage
from plane.tests.contract.app.test_daq_incidents import signature

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def test_legacy_signature_cannot_reenter_native_project_material_endpoints(workspace):
    project = Project.objects.create(workspace=workspace, name="材料访问边界", identifier="SIGOLD")
    path = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/" + "packages/"
    body = json.dumps({"name": "不得创建"})
    response = APIClient().post(path, body, content_type="application/json", **signature(path, body))
    assert response.status_code in {403, 405}, response.content
    assert not PackageFile.objects.filter(project=project).exists()
    assert not ProblemPackage.objects.filter(project=project).exists()
