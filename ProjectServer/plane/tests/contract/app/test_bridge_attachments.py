"""Trusted DAQ identity reaches the actual manifest/upload/read endpoints with membership checks."""

import base64
import hashlib
import hmac
import json
import time
from uuid import uuid4
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test.client import encode_multipart, BOUNDARY, MULTIPART_CONTENT
from plane.db.models import Project, ProjectMember
from plane.quality.models import Defect, PlatformIdentity
from plane.quality.identity import multipart_digest

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def test_signed_daq_upload_download_and_tamper_guard(api_client, workspace, create_user, settings, mocker, tmp_path):
    settings.QUALITY_ATTACHMENT_ROOT = str(tmp_path)
    settings.QUALITY_BRIDGE_KEYS = {
        "attachment-test": {"secret": "fixture-only", "audience": "quality", "source_instance": "fixture"}
    }
    project = Project.objects.create(workspace=workspace, name="签名附件", identifier="SIGNEDFILES")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    PlatformIdentity.objects.create(project=project, source_instance="fixture", external_user_id=42, user=create_user)
    mocker.patch("plane.quality.platform.verify_identity")
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    defect = Defect.objects.create(project=project, title="日志附件", created_by=create_user)

    def signed(method, path, body=b"", content_type="application/json", tamper=False):
        def enc(value):
            return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")

        stamp, nonce = str(int(time.time())), uuid4().hex
        digest = (
            "-"
            if method == "GET"
            else multipart_digest(body, content_type)
            if content_type.startswith("multipart/")
            else hashlib.sha256(body).hexdigest()
        )
        principal = json.dumps({"id": 42, "username": "collector"}, separators=(",", ":"))
        signature = enc("")
        canonical = "\n".join(
            [
                "ISSUE-IDENTITY-V2",
                enc("quality"),
                enc("attachment-test"),
                stamp,
                enc(nonce),
                method,
                enc(path),
                digest,
                enc(principal),
            ]
        )
        signature = (
            base64.urlsafe_b64encode(hmac.new(b"fixture-only", canonical.encode(), hashlib.sha256).digest())
            .decode()
            .rstrip("=")
        )
        return api_client.generic(
            method,
            path,
            data=body + b"tampered" if tamper else body,
            content_type=content_type,
            **{
                "HTTP_X_ISSUE_IDENTITY_VERSION": "2",
                "HTTP_X_ISSUE_KEY_ID": "attachment-test",
                "HTTP_X_ISSUE_AUDIENCE": "quality",
                "HTTP_X_ISSUE_PRINCIPAL": principal,
                "HTTP_X_ISSUE_PRINCIPAL_TIMESTAMP": stamp,
                "HTTP_X_ISSUE_PRINCIPAL_NONCE": nonce,
                "HTTP_X_ISSUE_CONTENT_SHA256": digest,
                "HTTP_X_ISSUE_PRINCIPAL_SIGNATURE": signature,
            },
        )

    raw = b"full actual diagnostic log\n"
    body = json.dumps(
        {
            "name": "日志",
            "defect_id": str(defect.id),
            "source_system": "ENGRAM_DAQ",
            "external_id": "signed-file",
            "files": [{"path": "recording.log", "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}],
        }
    ).encode()
    created = signed("POST", base + "packages/", body)
    assert created.status_code == 201, created.content
    upload = encode_multipart(BOUNDARY, {"file": SimpleUploadedFile("recording.log", raw, content_type="text/plain")})
    uploaded = signed("POST", base + f"packages/{created.data['id']}/files/", upload, MULTIPART_CONTENT)
    assert uploaded.status_code == 201, uploaded.content
    for action in ["download", "preview"]:
        response = signed("GET", base + f"files/{uploaded.data['id']}/{action}/")
        assert response.status_code == 200
        assert b"".join(response.streaming_content) == raw
    assert signed("POST", base + "packages/", body, tamper=True).status_code == 403
    ProjectMember.objects.filter(project=project, member=create_user).update(is_active=False)
    assert signed("GET", base + f"files/{uploaded.data['id']}/download/").status_code == 403
