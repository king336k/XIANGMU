"""Complete, private attachment bundles never hide missing or altered bytes."""

import hashlib
import io
from uuid import uuid4
import zipfile

import pytest
from django.utils import timezone

from plane.db.models import Project, ProjectMember
from plane.quality.models import Defect, PackageFile, ProblemPackage
from plane.tests.contract.app.test_quality import endpoint, quality_project as quality_project

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def archive_case(quality_project, create_user, settings, tmp_path):
    settings.QUALITY_ATTACHMENT_ROOT = str(tmp_path / "attachments")
    root = tmp_path / "attachments"
    root.mkdir()
    defect = Defect.objects.create(project=quality_project, created_by=create_user, title="附件打包")

    def add(name="logs/run.log", content=b"complete log", package=None):
        digest = hashlib.sha256(content).hexdigest()
        if package is None:
            package = ProblemPackage.objects.create(
                project=quality_project,
                created_by=create_user,
                defect=defect,
                name="诊断包",
                source_system="ENGRAM_DAQ",
                external_id=str(uuid4()),
                files=[],
                status="files_verified",
            )
        package.files.append({"path": name, "size": len(content), "sha256": digest})
        package.save(update_fields=["files"])
        key = uuid4().hex + ".bin"
        (root / key).write_bytes(content)
        return PackageFile.objects.create(
            project=quality_project,
            created_by=create_user,
            package=package,
            name=name,
            size=len(content),
            sha256=digest,
            storage_key=key,
        )

    return quality_project, defect, root, add


def download(client, project, defect):
    return client.get(endpoint(project, f"defects/{defect.id}/attachments/download/"))


def test_bundle_preserves_all_bytes_nested_archives_and_cross_package_duplicate_names(
    session_client, archive_case, mocker
):
    project, defect, root, add = archive_case
    add()
    add(content=b"second log")
    inside = io.BytesIO()
    with zipfile.ZipFile(inside, "w") as nested:
        nested.writestr("keep.log", b"nested unchanged")
    add("diagnostics.zip", inside.getvalue())
    from plane.quality import attachment_archive

    real_tempfile = attachment_archive.tempfile.TemporaryFile
    opened = []

    def track(*args, **kwargs):
        result = real_tempfile(*args, **kwargs)
        opened.append(result)
        return result

    mocker.patch("plane.quality.attachment_archive.tempfile.TemporaryFile", side_effect=track)
    response = download(session_client, project, defect)
    assert response.status_code == 200
    assert response["Content-Type"] == "application/zip"
    assert "no-store" in response["Cache-Control"]
    raw = b"".join(response.streaming_content)
    response.close()
    assert opened and all(handle.closed for handle in opened)
    with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
        names = bundle.namelist()
        assert len(names) == len(set(names)) == 3
        assert sum(name.endswith("logs/run.log") for name in names) == 2
        assert any(bundle.read(name) == inside.getvalue() for name in names)
        assert sorted(bundle.read(name) for name in names) == sorted(
            [b"complete log", b"second log", inside.getvalue()]
        )
    assert not list(root.glob("attachment-bundle-*"))


@pytest.mark.parametrize(
    "failure",
    ["missing", "altered", "size", "symlink", "key_traversal", "name_traversal", "duplicate_normalized", "incomplete"],
)
def test_bundle_refuses_partial_or_unsafe_archive(session_client, archive_case, failure, tmp_path):
    project, defect, root, add = archive_case
    row = add()
    if failure == "missing":
        (root / row.storage_key).unlink()
    elif failure == "altered":
        (root / row.storage_key).write_bytes(b"modified log")
    elif failure == "size":
        row.size += 1
        row.save(update_fields=["size"])
    elif failure == "symlink":
        (root / row.storage_key).unlink()
        target = tmp_path / "outside.log"
        target.write_bytes(b"complete log")
        (root / row.storage_key).symlink_to(target)
    elif failure == "key_traversal":
        row.storage_key = "../outside.log"
        row.save(update_fields=["storage_key"])
    elif failure == "name_traversal":
        row.name = "../outside.log"
        row.save(update_fields=["name"])
    elif failure == "duplicate_normalized":
        add("logs\\run.log", package=row.package)
    else:
        row.package.files.append({"path": "not-uploaded.log", "size": 1, "sha256": "a" * 64})
        row.package.save(update_fields=["files"])
    response = download(session_client, project, defect)
    assert response.status_code == 409, getattr(response, "data", response.status_code)
    assert response.data["detail"]
    assert not list(root.glob("attachment-bundle-*"))


def test_bundle_is_scoped_to_defect_project_and_active_reader(session_client, archive_case, create_user):
    project, defect, root, add = archive_case
    add()
    other = Project.objects.create(workspace=project.workspace, name="其他项目", identifier="OTHERARCH")
    ProjectMember.objects.create(project=other, member=create_user, role=20)
    assert download(session_client, other, defect).status_code == 404
    ProjectMember.objects.filter(project=project, member=create_user).update(is_active=False)
    assert download(session_client, project, defect).status_code == 403


def test_bundle_no_files_and_archived_defect_are_explicit(session_client, archive_case):
    project, defect, root, add = archive_case
    assert download(session_client, project, defect).status_code == 409
    add()
    defect.archived_at = timezone.now()
    defect.save(update_fields=["archived_at"])
    assert download(session_client, project, defect).status_code == 409


def test_bundle_resource_limits_and_no_diagnostic_side_effect(session_client, archive_case, mocker):
    project, defect, root, add = archive_case
    add()
    schedule = mocker.patch("plane.quality.diagnostics.schedule_automatic")
    from plane.quality import attachment_archive

    mocker.patch.object(attachment_archive, "MAX_BUNDLE_BYTES", 2)
    assert download(session_client, project, defect).status_code == 409
    mocker.patch.object(attachment_archive, "MAX_BUNDLE_BYTES", 500 * 1024 * 1024)
    mocker.patch.object(attachment_archive, "MAX_BUNDLE_FILES", 0)
    assert download(session_client, project, defect).status_code == 409
    schedule.assert_not_called()


def test_bundle_invalid_manifest_and_storage_failure_close_tempfiles(session_client, archive_case, mocker):
    project, defect, root, add = archive_case
    row = add()
    row.package.files = [{"path": "run.log", "size": "invalid", "sha256": "bad"}]
    row.package.save(update_fields=["files"])
    assert download(session_client, project, defect).status_code == 409
    row.package.files = [{"path": row.name, "size": row.size, "sha256": row.sha256}]
    row.package.save(update_fields=["files"])
    mocker.patch("plane.quality.attachment_archive.tempfile.TemporaryFile", side_effect=OSError("storage full"))
    response = download(session_client, project, defect)
    assert response.status_code == 409
    assert "storage full" not in response.data["detail"]


def test_bundle_corrupt_later_file_closes_tempfile_without_partial_success(session_client, archive_case, mocker):
    project, defect, root, add = archive_case
    add()
    row = add(content=b"second")
    (root / row.storage_key).write_bytes(b"broken")
    from plane.quality import attachment_archive

    real_tempfile = attachment_archive.tempfile.TemporaryFile
    opened = []

    def track(*args, **kwargs):
        result = real_tempfile(*args, **kwargs)
        opened.append(result)
        return result

    mocker.patch("plane.quality.attachment_archive.tempfile.TemporaryFile", side_effect=track)
    assert download(session_client, project, defect).status_code == 409
    assert opened and all(handle.closed for handle in opened)


@pytest.mark.parametrize("names", [("a", "a/b.log"), ("A/b.log", "a")])
def test_bundle_refuses_file_directory_ancestor_collisions(session_client, archive_case, names):
    project, defect, root, add = archive_case
    row = add(names[0])
    add(names[1], package=row.package)
    response = download(session_client, project, defect)
    assert response.status_code == 409
    assert "路径" in response.data["detail"]
