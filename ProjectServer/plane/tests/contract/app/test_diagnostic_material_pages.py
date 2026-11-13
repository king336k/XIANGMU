"""Full authorized sanitized evidence stays ephemeral; stored diagnostic contract stays bounded."""

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from plane.db.models import Project
from plane.quality.models import Defect, PackageFile, ProblemPackage

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def material_case(workspace, create_user, settings, tmp_path):
    from plane.quality.attachments import directory

    settings.QUALITY_ATTACHMENT_ROOT = str(tmp_path)
    project = Project.objects.create(workspace=workspace, name="Evidence paging", identifier="PAGING")
    defect = Defect.objects.create(
        project=project, title="long log", description="derived failure", created_by=create_user
    )
    package = ProblemPackage.objects.create(
        project=project, defect=defect, name="test", source_system="ENGRAM_DAQ", external_id=uuid4().hex, files=[]
    )

    def add(content, name="system.log", digest=None):
        raw = content if isinstance(content, bytes) else content.encode()
        row = PackageFile.objects.create(
            project=project,
            package=package,
            created_by=create_user,
            name=name,
            size=len(raw),
            sha256=digest or hashlib.sha256(raw).hexdigest(),
            storage_key=uuid4().hex + ".bin",
        )
        (directory() / row.storage_key).write_bytes(raw)
        return row

    def job(ids):
        return SimpleNamespace(project=project, defect=defect, result={"input": {"files": [str(i) for i in ids]}})

    return add, job


def test_full_sanitized_body_is_ephemeral_snapshot_scoped_and_legacy_compatible(material_case):
    from plane.quality.diagnostic_materials import inspect

    add, job = material_case
    content = (
        "ordinary heartbeat\n" * 3000
        + "PermissionError: [Errno 13] Permission denied: ffmpeg\npassword=not-a-real-secret\n"
    )
    selected = add(content)
    unselected = add("UNAUTHORIZED-MARKER", name="private.log")
    materials = {}
    result = inspect(job([selected.id]), materials)
    assert len(result) == 3 and len(result[1]) == 1
    retained = materials["FILE-" + str(selected.id)]["content"]
    assert "PermissionError: [Errno 13]" in retained
    assert "not-a-real-secret" not in retained
    assert "UNAUTHORIZED-MARKER" not in json.dumps(materials)
    assert str(unselected.id) not in json.dumps(materials)
    assert len(inspect(job([selected.id]))) == 3
    assert "content" not in result[1][0]


def test_real_case03_zip_exception_retained_from_verified_attachment_to_boundary(material_case, mocker):
    fixture = os.environ.get("BLIND_PUBLIC_ZIP")
    if not fixture:
        pytest.skip("optional real public artifact fixture not installed")
    from plane.quality.diagnostic_materials import inspect
    from plane.quality.diagnostic_model import analyze_diagnostic

    add, job = material_case
    row = add(Path(fixture).read_bytes(), name="incident_02-diagnostic.zip")
    maps = {}
    text, sources, _ = inspect(job([row.id]), maps)
    ref = "FILE-" + str(row.id) + ":logs/system/engram_daq_2026-11-10.log"
    assert "PermissionError: [Errno 13] Permission denied: 'ffmpeg'" in maps[ref]["content"]
    report = {
        "answer": "ffmpeg execution denied, requires configuration verification",
        "suggested_actions": [],
        "verification_steps": [],
        "citations": [ref],
    }
    mocker.patch.dict("os.environ", {"DIAGNOSTIC_AGENT_PYTHON": "/synthetic/python"})
    child = mocker.patch(
        "plane.quality.diagnostic_model.subprocess.run", return_value=SimpleNamespace(stdout=json.dumps(report))
    )
    analyze_diagnostic({"api_key": "synthetic"}, text, sources, [], maps)
    sent = json.loads(child.call_args.kwargs["input"])
    assert "PermissionError: [Errno 13] Permission denied: 'ffmpeg'" in sent["materials"][ref]["content"]
    assert len(sent["materials"][ref]["content"]) > 6000


def test_corrupt_and_out_of_scope_materials_never_enter_agent_map(material_case):
    from plane.quality.diagnostic_materials import inspect

    add, job = material_case
    corrupt = add("corrupt-private", digest="0" * 64)
    maps = {}
    _, sources, _ = inspect(job([corrupt.id]), maps)
    assert not maps and sources[0]["scan_incomplete"] and sources[0]["read_bytes"] == 0


def test_hard_utf8_per_file_and_total_budget_with_tail_fault_context(material_case):
    from plane.quality.diagnostic_materials import inspect, FILE_BYTES, TOTAL_BYTES

    add, job = material_case
    rows = [add("普通日志\n" * 25000, name=f"normal{n}.log") for n in range(6)]
    maps = {}
    inspect(job([r.id for r in rows]), maps)
    sizes = [len(x["content"].encode()) for x in maps.values()]
    assert max(sizes) <= FILE_BYTES and sum(sizes) <= TOTAL_BYTES
    big = add("heartbeat\n" * 40000 + "\nERROR OSError fault-at-very-end\n", name="big.log")
    maps = {}
    _, sources, _ = inspect(job([big.id]), maps)
    assert "fault-at-very-end" in maps["FILE-" + str(big.id)]["content"]
    assert maps["FILE-" + str(big.id)]["truncated"]
    assert sources[0]["scanned_bytes"] == sources[0]["file_bytes"]


def test_agent_payload_filters_forged_materials_redacts_and_never_persists_fulltext(mocker):
    from plane.quality.diagnostic_model import analyze_diagnostic

    ref = "FILE-local"
    report = {"answer": "待验证", "suggested_actions": [], "verification_steps": [], "citations": [ref]}
    mocker.patch.dict("os.environ", {"DIAGNOSTIC_AGENT_PYTHON": "/synthetic/python"})
    child = mocker.patch(
        "plane.quality.diagnostic_model.subprocess.run", return_value=SimpleNamespace(stdout=json.dumps(report))
    )
    source = {"file_id": "local", "name": "test.log", "read_bytes": 200, "excerpt": "safe summary"}
    result = analyze_diagnostic(
        {"api_key": "synthetic"},
        "description",
        [source],
        [],
        {
            ref: {"content": "x" * 15000 + "PermissionError tail\npassword=secret-body"},
            "FILE-foreign": {"content": "foreign marker"},
        },
    )
    sent = json.loads(child.call_args.kwargs["input"])
    assert "PermissionError tail" in sent["materials"][ref]["content"]
    assert "secret-body" not in sent["materials"][ref]["content"]
    assert "FILE-foreign" not in sent["materials"]
    assert result["citations"][0]["content"] == "safe summary"
    assert "PermissionError tail" not in json.dumps(result)
    assert child.call_args.kwargs["timeout"] == 310


def test_trace_validation_rejects_unknown_refs_and_strips_text(mocker):
    from plane.quality.diagnostic_model import validated_evidence_trace

    fingerprint = {"bytes": 12, "sha256": "a" * 64}
    trace = {
        "version": 1,
        "initial_prompt": {**fingerprint, "content": "secret-prompt"},
        "reads": [
            {
                "reference": "FILE-local",
                "offset": 0,
                "length": 12,
                "bytes": 12,
                "sha256": "b" * 64,
                "total_chars": 12,
                "truncated": False,
                "content": "secret-page",
            }
        ],
        "finalizer": {
            "used": True,
            "prompt_bytes": 24,
            "prompt_sha256": "c" * 64,
            "read_indices": [0],
            "content": "secret-final",
        },
    }
    safe = validated_evidence_trace(trace, {"FILE-local": {}})
    assert safe and "secret" not in json.dumps(safe)
    trace["reads"][0]["reference"] = "FILE-foreign"
    assert validated_evidence_trace(trace, {"FILE-local": {}}) is None


def test_trace_never_persists_revocable_knowledge_identifiers_and_remaps_pages():
    from plane.quality.diagnostic_model import validated_evidence_trace

    reads = [
        {
            "reference": ref,
            "offset": 0,
            "length": 3,
            "bytes": 3,
            "sha256": "a" * 64,
            "total_chars": 3,
            "truncated": False,
        }
        for ref in ["KN-private-revision", "FILE-local"]
    ]
    trace = {
        "version": 1,
        "initial_prompt": {"bytes": 10, "sha256": "b" * 64},
        "reads": reads,
        "finalizer": {"used": True, "prompt_bytes": 16, "prompt_sha256": "c" * 64, "read_indices": [0, 1]},
        "model_requests": [{"ordinal": 0, "finalizer": True, "status": "completed", "read_indices": [0, 1]}],
    }
    result = validated_evidence_trace(trace, {"KN-private-revision": {}, "FILE-local": {}})
    assert len(result["reads"]) == 1 and result["reads"][0]["reference"] == "FILE-local"
    assert result["finalizer"]["read_indices"] == [0]
    assert result["model_requests"][0]["read_indices"] == [0]
    assert "KN-private-revision" not in json.dumps(result)


def test_invalid_utf8_preview_budget_keeps_terminal_fault_for_plain_and_zip(material_case):
    from plane.quality.diagnostic_materials import inspect
    import io
    import zipfile

    add, job = material_case
    raw = b"\xff" * 240000 + b"\nERROR E-UTF8-TAIL retained\n"
    plain = add(raw, "invalid.log")
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("logs/invalid.log", raw)
    zipped = add(stream.getvalue(), "invalid.zip")
    _, sources, _ = inspect(job([plain.id, zipped.id]))
    assert len(sources) == 2
    for source in sources:
        assert source["scanned_bytes"] == len(raw)
        assert "E-UTF8-TAIL" in source["excerpt"]
        assert source["read_bytes"] <= 256 * 1024


def test_unicode_byte_budget_preserves_error_tail_and_handles_tiny_budget():
    from plane.quality.diagnostic_materials import bounded_preview

    text = "\ufffd" * 240000 + "\nERROR E-UTF8-BUDGET-TAIL\n"
    preview = bounded_preview(text, 256 * 1024)
    assert len(preview) <= 256 * 1024
    assert b"E-UTF8-BUDGET-TAIL" in preview
    assert len(bounded_preview("中文", 1)) <= 1
    assert bounded_preview(text, 0) == b""
