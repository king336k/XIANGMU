"""Uploaded feedback versions remain scoped to their verified defect package."""

import hashlib
import io
import json
from uuid import uuid4
import zipfile

import pytest
from plane.db.models import Project, ProjectMember
from plane.quality.models import Defect, PackageFile, ProblemPackage
from plane.tests.contract.app.test_quality import endpoint, quality_project
from rest_framework.test import APIClient

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def snapshots_case(quality_project, create_user, settings, tmp_path):
    root = tmp_path / "attachments"
    root.mkdir()
    settings.QUALITY_ATTACHMENT_ROOT = str(root)
    defect = Defect.objects.create(
        project=quality_project, created_by=create_user, title="反馈现场"
    )

    def add(document, *, project=None, target=None, verified=True, name=None):
        project = project or quality_project
        target = target or defect
        event = document.get("eventId", str(uuid4()))
        name = name or f"feedback-{event}.json"
        raw = json.dumps(document).encode()
        digest = hashlib.sha256(raw).hexdigest()
        package = ProblemPackage.objects.create(
            project=project,
            defect=target,
            created_by=create_user,
            name="反馈",
            source_system="ENGRAM_TELEOP_DAQ",
            external_id=str(uuid4()),
            files=[{"path": name, "size": len(raw), "sha256": digest}],
            status="files_verified" if verified else "manifest_registered",
        )
        key = uuid4().hex + ".bin"
        (root / key).write_bytes(raw)
        row = PackageFile.objects.create(
            project=project,
            package=package,
            created_by=create_user,
            name=name,
            size=len(raw),
            sha256=digest,
            storage_key=key,
        )
        return row

    return quality_project, defect, root, add


def document(event=None, captured="2026-11-11T01:00:00Z"):
    event = event or str(uuid4())
    return {
        "eventId": event,
        "untrustedTopLevel": "must never leak",
        "deploymentSnapshot": {
            "schemaVersion": 1,
            "capturedAt": captured,
            "eventId": event,
            "source": "combined_client_info",
            "components": [
                {
                    "key": "project",
                    "label": "合并主程序",
                    "location": "host",
                    "status": "available",
                    "version": "v1",
                    "commit": "a" * 40,
                    "commitMessage": "built",
                    "generatedAt": "2026-11-11T00:00:00Z",
                    "builtAt": "",
                    "secret": "must never leak",
                    "submodules": [
                        {"key": "core", "branch": "main", "commit": "b" * 40}
                    ],
                }
            ],
            "comparison": {"status": "unknown", "items": []},
            "private": "must never leak",
        },
    }


def get(client, project, defect):
    return client.get(endpoint(project, f"defects/{defect.id}/deployment-snapshots/"))


def test_versions_are_whitelisted_and_keep_distinct_history(
    session_client, snapshots_case
):
    project, defect, _, add = snapshots_case
    first = document()
    row = add(first)
    second = document(captured="2026-11-11T02:00:00Z")
    add(second)
    response = get(session_client, project, defect)
    assert response.status_code == 200
    assert response.data["count"] == 2
    assert response.data["results"][0]["snapshot"]["eventId"] == second["eventId"]
    assert response.data["results"][1]["file"]["id"] == str(row.id)
    assert (
        response.data["results"][1]["snapshot"]["components"][0]["generatedAt"]
        == "2026-11-11T00:00:00Z"
    )
    assert response.data["results"][1]["snapshot"]["components"][0]["builtAt"] == ""
    assert "must never leak" not in json.dumps(response.data)


def test_git_submodule_relative_paths_survive_snapshot_projection(
    session_client, snapshots_case
):
    project, defect, _, add = snapshots_case
    payload = document()
    paths = [
        "src/engram_DAQ",
        "src/engram_Teleop_DAQ_interfaces/teleop_interface_msgs",
        "src/" + "/".join(f"nested_component_{index:02d}" for index in range(7)),
    ]
    payload["deploymentSnapshot"]["components"][0]["submodules"] = [
        {"key": path, "branch": "main", "commit": "b" * 40} for path in paths
    ]
    add(payload)
    response = get(session_client, project, defect)
    assert response.status_code == 200
    assert [
        child["key"]
        for child in response.data["results"][0]["snapshot"]["components"][0][
            "submodules"
        ]
    ] == paths


@pytest.mark.parametrize(
    "path",
    [
        "/src/core",
        "src//core",
        "./core",
        "src/./core",
        "src/../core",
        "src\\core",
        "C:/core",
        "src/\x7fcore",
        "src/" + "x" * 253,
    ],
)
def test_submodule_path_rejects_unsafe_forms(session_client, snapshots_case, path):
    project, defect, _, add = snapshots_case
    payload = document()
    payload["deploymentSnapshot"]["components"][0]["submodules"][0]["key"] = path
    add(payload)
    assert get(session_client, project, defect).status_code == 409


def test_unverified_legacy_and_other_defect_are_not_displayed(
    session_client, snapshots_case
):
    project, defect, _, add = snapshots_case
    add(document(), verified=False)
    add({"eventId": str(uuid4()), "feedback": {"description": "old"}})
    other = Defect.objects.create(project=project, title="other")
    add(document(), target=other)
    response = get(session_client, project, defect)
    assert response.status_code == 200
    assert response.data == {"count": 0, "results": []}


def test_same_event_at_distinct_capture_times_is_preserved(
    session_client, snapshots_case
):
    project, defect, _, add = snapshots_case
    event = str(uuid4())
    add(document(event, "2026-11-11T01:00:00Z"))
    add(document(event, "2026-11-11T02:00:00Z"))
    response = get(session_client, project, defect)
    assert response.status_code == 200
    assert [row["snapshot"]["capturedAt"] for row in response.data["results"]] == [
        "2026-11-11T02:00:00Z",
        "2026-11-11T01:00:00Z",
    ]


def test_feedback_file_count_is_bounded(session_client, snapshots_case, monkeypatch):
    from plane.quality import deployment_snapshots

    project, defect, _, add = snapshots_case
    monkeypatch.setattr(deployment_snapshots, "MAX_FEEDBACK_FILES", 2)
    for _ in range(3):
        add(document())
    assert get(session_client, project, defect).status_code == 409


def test_other_project_and_nonmember_cannot_read(
    session_client, snapshots_case, workspace, create_user
):
    project, defect, _, add = snapshots_case
    add(document())
    other = Project.objects.create(workspace=workspace, name="other", identifier="OTH")
    ProjectMember.objects.create(project=other, member=create_user, role=20)
    assert get(session_client, other, defect).status_code == 404
    assert get(APIClient(), project, defect).status_code in (401, 403)


def test_existing_attachment_bundle_includes_feedback_json(
    session_client, snapshots_case
):
    project, defect, _, add = snapshots_case
    row = add(document())
    response = session_client.get(
        endpoint(project, f"defects/{defect.id}/attachments/download/")
    )
    assert response.status_code == 200
    archive_bytes = b"".join(response.streaming_content)
    response.close()
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        feedback = next(name for name in archive.namelist() if name.endswith(row.name))
        assert hashlib.sha256(archive.read(feedback)).hexdigest() == row.sha256


@pytest.mark.parametrize(
    "failure",
    [
        "digest",
        "size",
        "symlink",
        "traversal",
        "oversize",
        "invalid_status",
        "invalid_location",
        "invalid_key",
        "duplicate_key",
        "too_many_components",
        "too_many_submodules",
        "manifest_sha_type",
        "invalid_captured_at",
    ],
)
def test_invalid_feedback_is_rejected(
    session_client, snapshots_case, failure, tmp_path
):
    project, defect, root, add = snapshots_case
    payload = document()
    if failure == "invalid_status":
        payload["deploymentSnapshot"]["components"][0]["status"] = "unknown"
    if failure == "invalid_location":
        payload["deploymentSnapshot"]["components"][0]["location"] = "cloud"
    if failure == "invalid_key":
        payload["deploymentSnapshot"]["components"][0]["key"] = "../project"
    if failure == "duplicate_key":
        payload["deploymentSnapshot"]["components"] *= 2
    if failure == "too_many_components":
        payload["deploymentSnapshot"]["components"] *= 65
    if failure == "too_many_submodules":
        payload["deploymentSnapshot"]["components"][0]["submodules"] *= 51
    if failure == "invalid_captured_at":
        payload["deploymentSnapshot"]["capturedAt"] = "yesterday"
    row = add(payload)
    path = root / row.storage_key
    if failure == "digest":
        path.write_bytes(path.read_bytes() + b"changed")
    if failure == "size":
        row.size += 1
        row.save(update_fields=["size"])
    if failure == "symlink":
        target = tmp_path / "target.json"
        path.rename(target)
        path.symlink_to(target)
    if failure == "traversal":
        row.storage_key = "../target.json"
        row.save(update_fields=["storage_key"])
    if failure == "oversize":
        row.size = 1024 * 1024 + 1
        row.save(update_fields=["size"])
    if failure == "manifest_sha_type":
        row.package.files[0]["sha256"] = 1
        row.package.save(update_fields=["files"])
    assert get(session_client, project, defect).status_code == 409


@pytest.mark.parametrize("prefix", ["feedback-", "feedback-version-"])
def test_version_filename_and_legacy_name_are_readable(session_client, snapshots_case, prefix):
    project, defect, _, add = snapshots_case
    payload = document()
    filename = f"{prefix}{payload['eventId']}.json"
    add(payload, name=filename)
    response = get(session_client, project, defect)
    assert response.status_code == 200
    assert response.data["count"] == 1
    assert response.data["results"][0]["file"]["name"] == filename


@pytest.mark.parametrize("prefix", ["feedback-", "feedback-version-"])
def test_version_filename_must_match_document_event(session_client, snapshots_case, prefix):
    project, defect, _, add = snapshots_case
    add(document(), name=f"{prefix}{uuid4()}.json")
    assert get(session_client, project, defect).status_code == 409


def test_source_snapshot_identity_is_preserved(session_client, snapshots_case):
    project, defect, _, add = snapshots_case
    payload = document()
    identity = {"dirty": True, "sourceSnapshotSha256": "a" * 64, "sourceFileCount": 321}
    payload["deploymentSnapshot"]["components"][0].update(identity)
    payload["deploymentSnapshot"]["components"][0]["submodules"][0].update(identity)
    add(payload)
    response = get(session_client, project, defect)
    assert response.status_code == 200
    row = response.data["results"][0]["snapshot"]["components"][0]
    for key, expected in identity.items():
        assert row[key] == expected
        assert row["submodules"][0][key] == expected


def test_system_username_is_kept_in_immutable_snapshot(session_client, snapshots_case):
    project, defect, _, add = snapshots_case
    original = document()
    original['deploymentSnapshot']['components'][0]['hostUsername'] = 'engram-test'
    add(original)
    response = get(session_client, project, defect)
    assert response.status_code == 200
    assert response.data['results'][0]['snapshot']['components'][0]['hostUsername'] == 'engram-test'
