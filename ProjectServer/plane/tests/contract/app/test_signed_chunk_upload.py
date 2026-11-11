"""Each large-file chunk is independently bound to the existing V2 identity signature."""

import base64
import hashlib
import hmac
import json
import os
import time
from uuid import uuid4
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test.client import encode_multipart, BOUNDARY, MULTIPART_CONTENT
from plane.db.models import Project, ProjectMember
from plane.quality.identity import multipart_digest
from plane.quality.models import Defect, PlatformIdentity

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def test_signed_incompressible_chunks_replay_tamper_and_complete_readback(
    api_client, workspace, create_user, settings, mocker, tmp_path
):
    settings.QUALITY_ATTACHMENT_ROOT = str(tmp_path)
    settings.QUALITY_BRIDGE_KEYS = {
        "chunk-test": {"secret": "fixture-only", "audience": "quality", "source_instance": "fixture"}
    }
    project = Project.objects.create(workspace=workspace, name="签名分块", identifier="SIGNEDCHUNK")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    PlatformIdentity.objects.create(project=project, source_instance="fixture", external_user_id=42, user=create_user)
    mocker.patch("plane.quality.platform.verify_identity")
    mocker.patch("plane.quality.diagnostics.schedule_automatic")
    defect = Defect.objects.create(project=project, title="完整日志", created_by=create_user)
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"

    def enc(value):
        return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")

    def signed(method, path, body=b"", content_type="application/json", tamper=False, headers=None):
        if headers is None:
            stamp, nonce = str(int(time.time())), uuid4().hex
            digest = (
                "-"
                if method == "GET"
                else multipart_digest(body, content_type)
                if content_type.startswith("multipart/")
                else hashlib.sha256(body).hexdigest()
            )
            principal = '{"id":42,"username":"collector"}'
            canonical = "\n".join(
                [
                    "ISSUE-IDENTITY-V2",
                    enc("quality"),
                    enc("chunk-test"),
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
            headers = {
                "HTTP_X_ISSUE_IDENTITY_VERSION": "2",
                "HTTP_X_ISSUE_KEY_ID": "chunk-test",
                "HTTP_X_ISSUE_AUDIENCE": "quality",
                "HTTP_X_ISSUE_PRINCIPAL": principal,
                "HTTP_X_ISSUE_PRINCIPAL_TIMESTAMP": stamp,
                "HTTP_X_ISSUE_PRINCIPAL_NONCE": nonce,
                "HTTP_X_ISSUE_CONTENT_SHA256": digest,
                "HTTP_X_ISSUE_PRINCIPAL_SIGNATURE": signature,
            }
        if tamper:
            body = body.replace(b'chunk_index"\r\n\r\n0', b'chunk_index"\r\n\r\n1')
        return api_client.generic(method, path, data=body, content_type=content_type, **headers), headers

    original = os.urandom(24 * 1024 * 1024 + 101)
    digest = hashlib.sha256(original).hexdigest()
    request = {
        "name": "完整日志",
        "defect_id": str(defect.id),
        "source_system": "ENGRAM_DAQ",
        "external_id": "signed-large",
        "files": [{"path": "system.log", "size": len(original), "sha256": digest}],
    }
    package, _ = signed("POST", base + "packages/", json.dumps(request).encode())
    assert package.status_code == 201, package.content
    url = base + f"packages/{package.data['id']}/files/"
    count = (len(original) + 4 * 1024 * 1024 - 1) // (4 * 1024 * 1024)
    for index in range(count):
        body = encode_multipart(
            BOUNDARY,
            {
                "file": SimpleUploadedFile(
                    "chunk.bin", original[index * 4 * 1024 * 1024 : (index + 1) * 4 * 1024 * 1024]
                ),
                "manifest_path": "system.log",
                "chunk_index": index,
                "chunk_count": count,
            },
        )
        if index == 0:
            rejected, _ = signed("POST", url, body, MULTIPART_CONTENT, tamper=True)
            assert rejected.status_code == 403, rejected.content
        response, headers = signed("POST", url, body, MULTIPART_CONTENT)
        assert response.status_code == (201 if index == count - 1 else 202), response.content
        replay, _ = signed("POST", url, body, MULTIPART_CONTENT, headers=headers)
        assert replay.status_code == 403
    readback, _ = signed("GET", base + f"files/{response.data['id']}/download/")
    check = hashlib.sha256()
    for block in readback.streaming_content:
        check.update(block)
    assert check.hexdigest() == digest
