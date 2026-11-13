"""Readable evidence references keep canonical provenance and defect boundaries intact."""

from uuid import uuid4
import pytest
from plane.db.models import Project
from plane.quality.models import Defect, DefectEvent, DiagnosticJob, PackageFile, ProblemPackage

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def references(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="引用展示", identifier="REFNAMES")
    defect = Defect.objects.create(project=project, title="已有诊断", created_by=create_user)
    package = ProblemPackage.objects.create(
        project=project, defect=defect, created_by=create_user, name="材料", status="files_verified"
    )
    file = PackageFile.objects.create(
        project=project, package=package, name="原始采集.log", storage_key=uuid4().hex, size=10, sha256="a" * 64
    )
    archive = PackageFile.objects.create(
        project=project, package=package, name="现场日志.zip", storage_key=uuid4().hex, size=10, sha256="b" * 64
    )
    return project, defect, file, archive, create_user


def test_existing_defect_reason_and_events_show_uploaded_name_without_rewriting_history(references):
    from plane.quality.serializers import DefectSerializer

    project, defect, file, archive, actor = references
    original = f"依据；引用：FILE-{file.id}, FILE-{archive.id}:logs/recording.log。"
    defect.assignment_reason = original
    defect.save()
    event = DefectEvent.objects.create(project=project, defect=defect, created_by=actor, status="open", note=original)
    data = DefectSerializer(defect).data
    assert data["assignment_reason"] == "依据；引用：原始采集.log, 现场日志.zip / logs/recording.log。"
    assert data["events"][0]["note"] == data["assignment_reason"]
    defect.refresh_from_db()
    event.refresh_from_db()
    assert defect.assignment_reason == event.note == original


def test_diagnostic_assignment_answer_and_citation_title_resolve_but_reference_id_stays(references):
    from plane.quality.diagnostics import DiagnosticSerializer

    project, defect, file, archive, actor = references
    reference = f"FILE-{archive.id}:logs/节点 日志.log"
    job = DiagnosticJob.objects.create(
        project=project,
        defect=defect,
        created_by=actor,
        request_id=uuid4(),
        mode="rules",
        status="completed",
        result={
            "assignment": {"reason": f"引用：FILE-{file.id}。"},
            "answer": f"检查 [{reference}]。",
            "citations": [{"reference": reference, "title": reference}],
            "sources": [
                {
                    "file_id": str(archive.id),
                    "name": archive.name,
                    "archive_entry": "logs/节点 日志.log",
                    "excerpt": f"raw FILE-{file.id}",
                }
            ],
        },
    )
    data = DiagnosticSerializer(job).data["result"]
    assert data["assignment"]["reason"] == "引用：原始采集.log。"
    assert data["answer"] == "检查 [现场日志.zip / logs/节点 日志.log]。"
    assert data["citations"][0] == {"reference": reference, "title": "现场日志.zip / logs/节点 日志.log"}
    assert data["sources"][0]["excerpt"] == f"raw FILE-{file.id}"
    job.refresh_from_db()
    assert job.result["citations"][0]["reference"] == reference


def test_foreign_defect_reference_does_not_reveal_another_upload_name(references):
    from plane.quality.serializers import DefectSerializer

    project, defect, file, _, actor = references
    other = Defect.objects.create(
        project=project, created_by=actor, title="另一个缺陷", assignment_reason=f"引用：FILE-{file.id}。"
    )
    value = DefectSerializer(other).data["assignment_reason"]
    assert file.name not in value
    assert "材料不可用" in value


def test_multiple_events_reuse_one_scoped_reference_lookup(references, django_assert_num_queries):
    from plane.quality.reference_names import readable_references

    project, defect, file, archive, _ = references
    cache = {}
    with django_assert_num_queries(1):
        for _ in range(20):
            assert readable_references(f"FILE-{file.id}", project.id, defect.id, cache) == file.name
            assert (
                readable_references(f"FILE-{archive.id}:a.log", project.id, defect.id, cache) == "现场日志.zip / a.log"
            )


def test_markdown_filename_remains_text_and_does_not_create_a_link(references):
    from plane.quality.reference_names import readable_references

    project, defect, file, _, _ = references
    file.name = "[报告](example.invalid).log"
    file.save(update_fields=["name"])
    assert (
        readable_references(f"FILE-{file.id}", project.id, defect.id, markdown=True)
        == r"\[报告\]\(example.invalid\).log"
    )
    assert readable_references(f"FILE-{file.id}", project.id, defect.id) == file.name


def test_automatic_snapshot_is_not_presented_as_a_runtime_log(references):
    from plane.quality.reference_names import readable_references

    project, defect, file, _, _ = references
    file.name = f"feedback-version-{uuid4()}.json"
    file.save(update_fields=["name"])
    assert readable_references(f"FILE-{file.id}", project.id, defect.id) == f"现场快照（{file.name}）"
