"""Local screenshot OCR is bounded unreviewed derived text, never raw operational evidence."""

import hashlib
import importlib.util
import io
import json
import struct
from types import SimpleNamespace
import zlib

import pytest
import requests

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def png(width=64, height=32):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\0" + b"\0" * (width * 3)))
        + chunk(b"IEND", b"")
    )


def file(raw=None):
    raw = png() if raw is None else raw
    return SimpleNamespace(name="截图.png", size=len(raw), sha256=hashlib.sha256(raw).hexdigest()), io.BytesIO(raw)


def helper():
    assert importlib.util.find_spec("plane.quality.diagnostic_image_text"), "Bounded image OCR helper is missing"
    from plane.quality.diagnostic_image_text import extract_png

    return extract_png


def result(row, text="本地截图候选文字"):
    return {
        "status": "completed",
        "source_sha256": row.sha256,
        "engine": "tesseract",
        "requires_review": True,
        "segments": [{"key": "ocr-1", "text": text, "width": 64, "height": 32}],
        "failures": [],
    }


@pytest.fixture
def provider(mocker):
    mocker.patch(
        "plane.quality.document_ocr.configuration", return_value=("http://document-ocr:18886", "synthetic-local-key")
    )
    session = mocker.patch("requests.Session").return_value
    session.__enter__.return_value = session
    response = session.post.return_value
    response.status_code = 200
    response.headers = {"Content-Type": "application/json"}
    response.iter_content.side_effect = lambda chunk_size: [json.dumps(response.fixture, ensure_ascii=False).encode()]
    return session, response


def test_local_success_uses_no_proxy_no_redirect_and_checked_unreviewed_text(provider):
    row, handle = file()
    session, response = provider
    response.fixture = result(row)
    got = helper()(row, handle, 10)
    assert got == {"text": "本地截图候选文字", "status": "read", "reason": "ocr_unreviewed"}
    assert session.trust_env is False
    kwargs = session.post.call_args.kwargs
    assert session.post.call_args.args[0] == "http://document-ocr:18886/v1/extract"
    assert kwargs["allow_redirects"] is False and kwargs["stream"] is True
    assert kwargs["headers"]["X-Content-SHA256"] == row.sha256
    assert kwargs["headers"]["X-Document-Type"] == "png"
    assert kwargs["timeout"][0] <= 2 and kwargs["timeout"][1] <= 6
    response.close.assert_called_once()


@pytest.mark.parametrize("kind", ["bad_hash", "size", "signature", "dimensions", "pixels", "crc", "oversize"])
def test_invalid_input_never_leaves_process(provider, kind):
    raw = png()
    row, handle = file(raw)
    if kind == "bad_hash":
        row.sha256 = "0" * 64
    elif kind == "size":
        row.size += 1
    elif kind == "signature":
        row, handle = file(b"invalid")
    elif kind == "dimensions":
        row, handle = file(png(3509, 1))
    elif kind == "pixels":
        row, handle = file(png(3100, 3100))
    elif kind == "crc":
        row, handle = file(raw[:-1] + b"x")
    elif kind == "oversize":
        row, handle = file(b"x" * (4 * 1024 * 1024 + 1))
    got = helper()(row, handle, 10)
    assert got["status"] == "invalid" and got["text"] == ""
    provider[0].post.assert_not_called()


@pytest.mark.parametrize(
    "url",
    [
        "https://document-ocr:18886",
        "http://external.invalid:18886",
        "http://document-ocr:18886/path",
        "http://document-ocr:18886?x=1",
        "http://user:secret@document-ocr:18886",
    ],
)
def test_only_builtin_root_origin_is_allowed(provider, mocker, url):
    mocker.patch("plane.quality.document_ocr.configuration", return_value=(url, "synthetic-local-key"))
    got = helper()(*file(), 10)
    assert got["status"] == "unavailable" and got["reason"] == "ocr_configuration"
    provider[0].post.assert_not_called()


@pytest.mark.parametrize(
    "change", ["sha", "engine", "review", "malformed", "sensitive", "dimensions", "oversized_response", "deep_json"]
)
def test_untrusted_provider_result_fails_closed_without_echo(provider, change):
    row, handle = file()
    session, response = provider
    response.fixture = result(row)
    if change == "sha":
        response.fixture["source_sha256"] = "0" * 64
    elif change == "engine":
        response.fixture["engine"] = "unverified"
    elif change == "review":
        response.fixture["requires_review"] = False
    elif change == "malformed":
        response.iter_content.side_effect = lambda chunk_size: [b"{not-json"]
    elif change == "sensitive":
        response.fixture = result(row, '{"password":"synthetic-hidden-value"}')
    elif change == "dimensions":
        response.fixture["segments"][0]["width"] = 9999
    elif change == "oversized_response":
        response.iter_content.side_effect = lambda chunk_size: [b"x" * (256 * 1024 + 1)]
    elif change == "deep_json":
        response.iter_content.side_effect = lambda chunk_size: [b"[" * 2000 + b"]" * 2000]
    got = helper()(row, handle, 10)
    assert got["status"] == "invalid" and got["text"] == ""
    assert "synthetic-hidden-value" not in json.dumps(got)
    response.close.assert_called_once()


@pytest.mark.parametrize("status,reason", [(429, "ocr_busy"), (302, "ocr_redirect_rejected"), (503, "ocr_unavailable")])
def test_service_status_is_explicit_without_retry(provider, status, reason):
    provider[1].status_code = status
    got = helper()(*file(), 10)
    assert got["status"] == "unavailable" and got["reason"] == reason
    assert provider[0].post.call_count == 1


def test_timeout_is_not_read_and_does_not_retry(provider):
    provider[0].post.side_effect = requests.Timeout("sensitive arbitrary error")
    got = helper()(*file(), 10)
    assert got == {"text": "", "status": "unavailable", "reason": "ocr_timeout"}
    assert provider[0].post.call_count == 1


def test_empty_ocr_is_explicit_no_text(provider):
    row, handle = file()
    provider[1].fixture = {**result(row), "segments": [], "failures": [{"error": "no_recognized_text"}]}
    assert helper()(row, handle, 10) == {"text": "", "status": "no_text", "reason": "ocr_no_text"}


def test_remaining_budget_is_shared_and_empty_budget_does_not_call(provider):
    got = helper()(*file(), 0)
    assert got == {"text": "", "status": "unavailable", "reason": "ocr_time_budget"}
    provider[0].post.assert_not_called()


def test_less_than_two_seconds_never_starts_ocr(provider):
    got = helper()(*file(), 1.9)
    assert got == {"text": "", "status": "unavailable", "reason": "ocr_time_budget"}
    provider[0].post.assert_not_called()


def test_late_stream_result_never_returns_candidate_text(provider, mocker):
    row, handle = file()
    provider[1].fixture = result(row)
    mocker.patch("plane.quality.diagnostic_image_text.time.monotonic", side_effect=[0.0, 0.1, 20.0])
    assert helper()(row, handle, 10) == {"text": "", "status": "unavailable", "reason": "ocr_time_budget"}
    provider[1].close.assert_called_once()


def test_service_failure_or_no_text_are_distinct(provider):
    row, handle = file()
    provider[1].fixture = {**result(row), "segments": [], "failures": [{"error": "document_timeout"}]}
    assert helper()(row, handle, 10) == {"text": "", "status": "unavailable", "reason": "ocr_incomplete"}
