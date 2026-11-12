"""Retired project-bound DAQ routes remain inaccessible; report-only flow is in test_daq_reporting."""

import base64
import hashlib
import hmac
import json
import time
from uuid import uuid4
import pytest
from rest_framework.test import APIClient
from plane.db.models import Project, ProjectMember
from plane.quality.models import Defect, PlatformIdentity, PlatformProject

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def signature(path, body, actor=16, method="POST"):
    stamp, nonce = str(int(time.time())), str(uuid4())
    principal = json.dumps({"id": actor, "username": "test-collector"}, separators=(",", ":"))

    def enc(v):
        return base64.urlsafe_b64encode(v.encode()).decode().rstrip("=")

    digest = "-" if method == "GET" else hashlib.sha256(body.encode()).hexdigest()
    canonical = "\n".join(
        [
            "ISSUE-IDENTITY-V2",
            enc("plane-quality"),
            enc("test-incidents"),
            stamp,
            enc(nonce),
            method,
            enc(path),
            digest,
            enc(principal),
        ]
    )
    sig = (
        base64.urlsafe_b64encode(hmac.new(b"synthetic-incidents-only", canonical.encode(), hashlib.sha256).digest())
        .decode()
        .rstrip("=")
    )
    return {
        "HTTP_X_ISSUE_IDENTITY_VERSION": "2",
        "HTTP_X_ISSUE_KEY_ID": "test-incidents",
        "HTTP_X_ISSUE_AUDIENCE": "plane-quality",
        "HTTP_X_ISSUE_PRINCIPAL": principal,
        "HTTP_X_ISSUE_PRINCIPAL_TIMESTAMP": stamp,
        "HTTP_X_ISSUE_PRINCIPAL_NONCE": nonce,
        "HTTP_X_ISSUE_CONTENT_SHA256": digest,
        "HTTP_X_ISSUE_PRINCIPAL_SIGNATURE": sig,
    }


@pytest.mark.parametrize(
    "suffix",
    ["", "context/", "00000000-0000-0000-0000-000000000001/", "00000000-0000-0000-0000-000000000001/sessions/"],
)
@pytest.mark.parametrize("signed", [False, True])
def test_retired_project_incident_routes_cannot_create_platform_identity(workspace, create_user, suffix, signed):
    project = Project.objects.create(workspace=workspace, name="旧入口禁用", identifier="RETIRED")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    path = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/daq/incidents/" + suffix
    client = APIClient()
    if not signed:
        client.force_authenticate(create_user)
    body = json.dumps({"eventId": str(uuid4()), "title": "旧接口不可写入"})
    response = client.post(path, body, content_type="application/json", **(signature(path, body) if signed else {}))
    assert response.status_code in {403, 404}, response.content
    assert not Defect.objects.filter(project=project).exists()
    assert not PlatformIdentity.objects.filter(project=project).exists()
    assert not PlatformProject.objects.filter(project=project).exists()
