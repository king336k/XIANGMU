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


def test_material_coverage_distinguishes_verified_image_from_read_text(material_case):
    from plane.quality.diagnostic_materials import inspect

    add, job = material_case
    text = add("ERROR local service failed", name="中文日志.log")
    image = add(b"\x89PNG\r\n\x1a\nneutral", name="合成图片.jpg")
    coverage = []
    _, sources, _ = inspect(job([text.id, image.id]), {}, coverage=coverage)
    assert [row["file_id"] for row in sources] == [str(text.id)]
    assert {row["file_id"] for row in coverage} == {str(text.id), str(image.id)}
    picture = next(row for row in coverage if row["file_id"] == str(image.id))
    assert picture == {
        "file_id": str(image.id),
        "name": "合成图片.jpg",
        "kind": "image",
        "status": "unsupported",
        "reason": "当前诊断未读取图片内容",
        "verified": True,
    }
    log = next(row for row in coverage if row["file_id"] == str(text.id))
    assert log["status"] == "analyzed" and log["verified"] is True


def test_material_coverage_never_marks_corrupt_or_unselected_attachment_verified(material_case):
    from plane.quality.diagnostic_materials import inspect

    add, job = material_case
    image = add(b"not-real-image", name="corrupt.png", digest="0" * 64)
    unselected = add("private", name="other.log")
    coverage = []
    inspect(job([image.id]), {}, coverage=coverage)
    assert len(coverage) == 1 and coverage[0]["file_id"] == str(image.id)
    assert coverage[0]["verified"] is False and coverage[0]["status"] == "not_read"
    assert str(unselected.id) not in json.dumps(coverage)


def test_zero_read_budget_is_not_reported_as_read(material_case, mocker):
    from plane.quality.diagnostic_materials import inspect

    add, job = material_case
    row = add("ERROR retained original log", name="budget.log")
    mocker.patch("plane.quality.diagnostic_materials.TOTAL_BYTES", 0)
    coverage = []
    _, sources, _ = inspect(job([row.id]), {}, coverage=coverage)
    assert sources[0]["read_bytes"] == 0
    assert coverage[0]["status"] == "not_read" and coverage[0]["verified"] is True


def test_verified_png_ocr_text_is_derived_and_binary_bytes_stay_separate(material_case, mocker):
    from plane.quality.diagnostic_materials import inspect

    add, job = material_case
    image = add(b"\x89PNG\r\n\x1a\nneutral", name="截图.png")
    mocker.patch(
        "plane.quality.diagnostic_image_text.extract_png",
        return_value={"text": "ERROR module=daq timeout", "status": "read", "reason": "ocr_unreviewed"},
    )
    coverage = []
    materials = {}
    text, sources, _ = inspect(job([image.id]), materials, coverage=coverage)
    assert len(sources) == 1 and sources[0]["origin"] == "image_ocr"
    assert sources[0]["requires_review"] is True
    assert sources[0]["file_bytes"] == image.size
    assert sources[0]["text_bytes"] == len("ERROR module=daq timeout".encode())
    assert coverage[0]["status"] == "analyzed"
    assert coverage[0]["reason"] == "已提取图片文字，需核对原图"
    assert "未经人工核对" in text
    assert materials["FILE-" + str(image.id)]["origin"] == "image_ocr"


def test_ocr_failure_does_not_prevent_other_log_diagnosis(material_case, mocker):
    from plane.quality.diagnostic_materials import inspect

    add, job = material_case
    image = add(b"\x89PNG\r\n\x1a\nneutral", name="截图.png")
    log = add("ERROR independent current log", name="event.log")
    mocker.patch(
        "plane.quality.diagnostic_image_text.extract_png",
        return_value={"text": "", "status": "unavailable", "reason": "ocr_timeout"},
    )
    coverage = []
    _, sources, _ = inspect(job([image.id, log.id]), {}, coverage=coverage)
    assert len(sources) == 1 and sources[0]["file_id"] == str(log.id)
    picture = next(row for row in coverage if row["file_id"] == str(image.id))
    assert picture["verified"] is True and picture["status"] == "not_read"
    assert picture["reason"] == "图片文字识别超时"


def test_optional_image_deadline_does_not_mark_completed_log_incomplete(material_case, mocker):
    from plane.quality.diagnostic_materials import inspect

    add, job = material_case
    log = add("ERROR current text log", name="event.log")
    first = add(b"\x89PNG\r\n\x1a\nneutral1", name="first.png")
    second = add(b"\x89PNG\r\n\x1a\nneutral2", name="second.png")
    clock = [0.0]
    mocker.patch("plane.quality.diagnostic_materials.time.monotonic", side_effect=lambda: clock[0])

    def exhausted(*args):
        clock[0] = 30.0
        return {"status": "unavailable", "reason": "ocr_timeout", "text": ""}

    mocker.patch("plane.quality.diagnostic_image_text.extract_png", side_effect=exhausted)
    coverage = []
    _, sources, _ = inspect(job([log.id, first.id, second.id]), {}, coverage=coverage)
    assert [row["file_id"] for row in sources] == [str(log.id)]
    assert sources[0]["scan_incomplete"] is False
    assert next(row for row in coverage if row["file_id"] == str(second.id))["status"] == "not_read"


def test_trace_preserves_duplicate_read_attempts_without_private_page_content():
    from plane.quality.diagnostic_model import validated_evidence_trace

    read = {
        "reference": "FILE-local",
        "offset": 0,
        "length": 5,
        "bytes": 5,
        "sha256": "b" * 64,
        "total_chars": 5,
        "truncated": False,
    }
    trace = {
        "version": 1,
        "initial_prompt": {"bytes": 10, "sha256": "a" * 64},
        "reads": [read],
        "read_attempts": [
            {**read, "status": "read", "first_read_index": 0},
            {**read, "status": "already_read", "first_read_index": 0, "content": "PRIVATE-PAGE"},
        ],
        "finalizer": {"used": False},
    }
    safe = validated_evidence_trace(trace, {"FILE-local": {}})
    assert len(safe["read_attempts"]) == 2
    assert safe["read_attempts"][1]["status"] == "already_read"
    assert "PRIVATE" not in json.dumps(safe)
    trace["read_attempts"][1]["sha256"] = "c" * 64
    assert validated_evidence_trace(trace, {"FILE-local": {}}) is None


def test_successful_finalizer_keeps_only_fixed_reason_metadata():
    from plane.quality.diagnostic_model import validated_evidence_trace

    trace = {
        "version": 1,
        "initial_prompt": {"bytes": 10, "sha256": "a" * 64},
        "reads": [],
        "finalizer": {
            "used": True,
            "reason": "output_reference_invalid",
            "validation_categories": ["severity_reference_not_file", "PRIVATE_ERROR_BODY"],
            "prompt_bytes": 10,
            "prompt_sha256": "b" * 64,
            "read_indices": [],
        },
    }
    safe = validated_evidence_trace(trace, {})
    assert safe["finalizer"]["reason"] == "output_reference_invalid"
    assert safe["finalizer"]["validation_categories"] == ["severity_reference_not_file"]
    trace["finalizer"]["reason"] = "PRIVATE_ERROR_BODY"
    assert "PRIVATE" not in json.dumps(validated_evidence_trace(trace, {}))


def test_zip_small_entries_and_each_attachment_get_evidence_before_large_warning_flood(material_case, mocker):
    import io
    import zipfile
    from plane.quality.diagnostic_materials import inspect

    add, job = material_case
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as output:
        output.writestr('large.log', b'WARNING periodic heartbeat\n' * 30000)
        for index in range(6):
            output.writestr(f'node-{index}.log', b'INFO service healthy\n' * 10000 + f'ERROR E-NODE-{index} fault\n'.encode())
    row = add(archive.getvalue(), 'diagnostics.zip')
    materials, coverage = {}, []
    _, sources, _ = inspect(job([row.id]), materials, coverage=coverage)
    for index in range(6):
        assert f'E-NODE-{index}' in materials[f'FILE-{row.id}:node-{index}.log']['content']
    assert all(source['scanned_bytes'] == source['file_bytes'] and not source['scan_incomplete'] for source in sources)
    assert coverage[0]['status'] == 'analyzed'


def test_zip_crc_failure_never_exposes_preceding_valid_entry(material_case):
    import io
    import struct
    import zipfile
    from plane.quality.diagnostic_materials import inspect

    add, job = material_case
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as output:
        output.writestr('valid.log', b'ERROR preceding valid log\n')
        output.writestr('bad.log', b'ERROR corrupt me\n')
    raw = bytearray(buffer.getvalue())
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        info = archive.getinfo('bad.log')
        name_length, extra_length = struct.unpack_from('<HH', raw, info.header_offset + 26)
        offset = info.header_offset + 30 + name_length + extra_length
        raw[offset] ^= 1
    row = add(bytes(raw), 'corrupt.zip')
    materials, coverage = {}, []
    _, sources, _ = inspect(job([row.id]), materials, coverage=coverage)
    assert not materials
    assert sources[0]['scan_incomplete'] is True
    assert coverage[0]['status'] == 'not_read'


def test_real_large_capture_zip_scans_completely_with_digest_and_crc(material_case):
    import time
    from plane.quality.diagnostic_materials import inspect

    fixture = os.environ.get('TD498_REPLAY_ZIP')
    if not fixture:
        pytest.skip('optional incident ZIP replay fixture not installed')
    add, job = material_case
    raw = Path(fixture).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == 'cfcb6b5ce0c660cebdbddaa0b59365a56e13ce8dd80cc12452f41cf4e109a29d'
    row = add(raw, 'incident.zip')
    materials, coverage = {}, []
    started = time.monotonic()
    _, sources, _ = inspect(job([row.id]), materials, coverage=coverage)
    elapsed = time.monotonic() - started
    print(json.dumps({'elapsed': round(elapsed, 3), 'sources': [{key: source.get(key) for key in ('archive_entry', 'file_bytes', 'scanned_bytes', 'scan_incomplete')} for source in sources]}))
    assert len(sources) == 7
    assert all(source['scanned_bytes'] == source['file_bytes'] and not source['scan_incomplete'] for source in sources)
    assert coverage[0]['status'] == 'analyzed' and coverage[0]['verified']
    capture = next(source for source in sources if 'capture_service' in source['archive_entry'])
    assert capture['scanned_bytes'] == 194189145
    print(json.dumps({'real_zip_inspect_seconds': round(elapsed, 3), 'entries': len(sources),
                      'scanned_bytes': sum(source['scanned_bytes'] for source in sources)}))
    assert elapsed < 18


def test_real_uploaded_observations_preserve_planning_failure_through_material_preview(material_case):
    from plane.quality.diagnostic_materials import inspect
    from plane.quality.log_evidence import summarize

    fixture = os.environ.get('TD498_REPLAY_OBSERVATIONS')
    if not fixture:
        pytest.skip('optional incident observations replay fixture not installed')
    data = json.loads(Path(fixture).read_text().split('MATERIALS_JSON=', 1)[1])[1]
    document = {'sourceSystem': 'ENGRAM_TELEOP_DAQ', 'evidence': {'observations': data['observations']}}
    add, job = material_case
    row = add(json.dumps(document, ensure_ascii=False), 'feedback.json')
    materials, coverage = {}, []
    text, sources, _ = inspect(job([row.id]), materials, coverage=coverage)
    content = materials[f'FILE-{row.id}']['content']
    summary = summarize(text, 12000)
    for value in (content, summary, sources[0]['excerpt']):
        assert 'joint limit violation' in value and 'planning_failed' in value
        assert '/api/launcher/feedback-context' in value
        assert '2026-11-19T12:45:29.777Z' in value
    assert sources[0]['scanned_bytes'] == row.size and not sources[0]['scan_incomplete']
