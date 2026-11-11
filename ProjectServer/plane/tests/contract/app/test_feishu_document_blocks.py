"""Feishu official-schema contracts; injected HTTP fixtures, no tenant credentials/network."""

import hashlib
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock
import pytest

PATH = Path(__file__).resolve().parents[3] / "quality" / "feishu_document_blocks.py"


def module():
    spec = importlib.util.spec_from_file_location("feishu_blocks_contract", PATH)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def block(bid, kind, text=None, children=None, parent="doc1", **body):
    value = {
        "block_id": bid,
        "parent_id": parent,
        "block_type": 999,
        kind: body or ({"elements": [{"text_run": {"content": text}}]} if text is not None else {}),
    }
    if children is not None:
        value["children"] = children
    return value


def test_preserves_order_and_table_cells_downloads_actual_binary_sha():
    m = module()
    rows = [
        block("doc1", "page", "Title", children=["h", "t", "c", "table", "img", "file"], parent=""),
        block("h", "heading1", "Heading"),
        block("t", "text", "Text"),
        block("c", "code", "print(1)"),
        block("table", "table", children=["cell"], cells=["cell"], property={"row_size": 1, "column_size": 1}),
        block("cell", "table_cell", children=["ct"], parent="table"),
        block("ct", "text", "Cell evidence", parent="cell"),
        block("img", "image", token="imageToken", width=10, height=10),
        block("file", "file", token="fileToken", name="notes.txt"),
    ]
    get = Mock(return_value={"items": rows, "has_more": False})
    download = Mock(
        side_effect=lambda path, max_bytes: {"raw": path.encode(), "content_type": "application/octet-stream"}
    )
    result = m.read_document("doc1", get, download)
    assert result["valid"] and not result["failures"]
    assert [r["block_id"] for r in result["blocks"]] == ["doc1", "h", "t", "c", "table", "cell", "ct", "img", "file"]
    assert next(r for r in result["blocks"] if r["block_id"] == "table")["table"]["cells"] == ["cell"]
    assert next(r for r in result["segments"] if r["block_id"] == "ct")["text"] == "Cell evidence"
    assert "第1行第1列" in next(r for r in result["segments"] if r["block_id"] == "ct")["locator"]
    assert [x["kind"] for x in result["attachments"]] == ["image", "attachment"]
    for item in result["attachments"]:
        assert item["sha256"] == hashlib.sha256(item["raw"]).hexdigest() and item["size"] == len(item["raw"])
    assert all("/open-apis/drive/v1/medias/" in call.args[0] for call in download.call_args_list)


def test_table_dimensions_cannot_claim_cells_that_were_not_read():
    m = module()
    rows = [
        block("doc1", "page", "Title", children=["table"], parent=""),
        block("table", "table", children=["c1", "c2"], cells=["c1", "c2"], property={"row_size": 2, "column_size": 2}),
        block("c1", "table_cell", children=[], parent="table"),
        block("c2", "table_cell", children=[], parent="table"),
    ]
    result = m.read_document("doc1", Mock(return_value={"items": rows, "has_more": False}), Mock())
    assert result["valid"] is False
    assert any(row.get("block_id") == "table" for row in result["failures"])


def test_cursor_paginates_beyond_first500_and_preserves_children_order():
    m = module()
    children = ["b" + str(i) for i in range(601)]
    rows = [block("doc1", "page", "Title", children=children, parent="")] + [block(b, "text", b) for b in children]
    calls = []

    def get(path, params):
        calls.append(params)
        start = int(params.get("page_token", "0"))
        end = min(len(rows), start + 200)
        return {
            "items": rows[start:end],
            "has_more": end < len(rows),
            "page_token": str(end) if end < len(rows) else "",
        }

    result = m.read_document("doc1", get, Mock())
    assert result["valid"]
    assert len(result["blocks"]) == 602
    assert result["blocks"][-1]["block_id"] == "b600"
    assert len(calls) == 4


def test_children_fallback_paginates_with_block_ids():
    m = module()
    calls = []

    def get(path, params):
        calls.append((path, params))
        if path.endswith("/blocks"):
            return {"items": [block("doc1", "page", "Root", parent="")], "has_more": False}
        return {
            "items": [block("b2" if params.get("page_token") else "b1", "text", "value")],
            "has_more": not bool(params.get("page_token")),
            "page_token": "next" if not params.get("page_token") else "",
        }

    result = m.read_document("doc1", get, Mock())
    assert result["valid"]
    assert [r["block_id"] for r in result["blocks"]] == ["doc1", "b1", "b2"]
    assert len(calls) == 3


@pytest.mark.parametrize(
    "failure", ["unsupported", "missing_child", "cycle_cursor", "media_denied", "media_budget", "orphan"]
)
def test_explicit_failures_never_silent_raw_content_fallback(failure):
    m = module()
    root = block("doc1", "page", "Root", children=["b"], parent="")
    child = block("b", "text", "body")
    down = Mock()
    if failure == "unsupported":
        child = block("b", "board")
    if failure == "missing_child":
        root["children"] = ["missing"]
    if failure == "orphan":
        child["parent_id"] = "elsewhere"
    if failure in ["media_denied", "media_budget"]:
        child = block("b", "image", token="safeToken")
        down.side_effect = RuntimeError("private error should not be echoed") if failure == "media_denied" else None
        down.return_value = {"raw": b"x" * 5}
    get = Mock(return_value={"items": [root, child], "has_more": failure == "cycle_cursor", "page_token": "loop"})
    result = m.read_document("doc1", get, down, max_media_bytes=4)
    assert result["failures"] and not result["valid"]
    assert "private error" not in json.dumps(result, default=lambda x: "binary")


@pytest.mark.parametrize("token", ["https://evil/abc", "../bad", "bad?x=1", "bad%2Fvalue", "bad\\value"])
def test_untrusted_ids_rejected_before_transport(token):
    m = module()
    get = Mock()
    result = m.read_document(token, get, Mock())
    assert not result["valid"]
    get.assert_not_called()


class Response:
    def __init__(self, status=200, payload=None, chunks=None, headers=None, url="https://open.feishu.cn"):
        self.status_code = status
        self.headers = headers or {}
        self.url = url
        self._chunks = chunks if chunks is not None else [json.dumps(payload).encode()]
        self.closed = False

    def iter_content(self, n):
        yield from self._chunks

    def close(self):
        self.closed = True


def test_transport_fixed_origin_no_redirect_stream_length_and_sha():
    m = module()
    raw = b"actual downloaded bytes"
    response = Response(chunks=[raw[:5], raw[5:]], headers={"Content-Length": str(len(raw))})
    session = Mock()
    session.get.return_value = response
    c = m.FeishuTransport("fixture-key", session=session, sleep=Mock(), interval=0)
    got = c.download("/open-apis/drive/v1/medias/fileToken/download", 100)
    assert got["raw"] == raw and got["sha256"] == hashlib.sha256(raw).hexdigest()
    assert response.closed
    assert session.get.call_args.args[0] == "https://open.feishu.cn/open-apis/drive/v1/medias/fileToken/download"
    assert session.get.call_args.kwargs["allow_redirects"] is False
    with pytest.raises(ValueError):
        c.download("https://evil/download", 100)


@pytest.mark.parametrize("status", [301, 302, 401, 403, 404])
def test_transport_denied_or_redirect_does_not_retry(status):
    m = module()
    session = Mock()
    session.get.return_value = Response(status)
    c = m.FeishuTransport("fixture-key", session=session, sleep=Mock(), interval=0)
    with pytest.raises(m.FeishuReadError):
        c.download("/open-apis/drive/v1/medias/token1/download", 100)
    assert session.get.call_count == 1


def test_transport_429_bounded_retry_and_success():
    m = module()
    session = Mock()
    session.get.side_effect = [
        Response(429, headers={"Retry-After": "999"}),
        Response(payload={"code": 0, "data": {"items": [], "has_more": False}}),
    ]
    sleep = Mock()
    c = m.FeishuTransport("fixture-key", session=session, sleep=sleep, interval=0)
    assert c.get_json("/open-apis/docx/v1/documents/doc1/blocks", {})["items"] == []
    assert session.get.call_count == 2
    assert sleep.call_args.args[0] <= 2
    session.get.side_effect = None
    session.get.return_value = Response(429)
    with pytest.raises(m.FeishuReadError):
        c.get_json("/open-apis/docx/v1/documents/doc1/blocks", {})
    assert session.get.call_count == 5


@pytest.mark.parametrize("chunks,header,budget", [([b"12345"], {}, 4), ([b"123"], {"Content-Length": "5"}, 10)])
def test_download_budget_and_truncated_content_fail(chunks, header, budget):
    m = module()
    session = Mock()
    session.get.return_value = Response(chunks=chunks, headers=header)
    c = m.FeishuTransport("fixture-key", session=session, sleep=Mock(), interval=0)
    with pytest.raises(m.FeishuReadError):
        c.download("/open-apis/drive/v1/medias/t/download", budget)


def test_shared_global_request_budget_and_metadata_only_image_explanation():
    m = module()
    calls = []

    def get(path, params):
        calls.append(path)
        if path.endswith("/blocks"):
            return {
                "items": [block("doc1", "page", "Root", children=["a"], parent=""), block("a", "table_cell")],
                "has_more": False,
            }
        return {"items": [], "has_more": False}

    result = m.read_document("doc1", get, Mock(), max_requests=1)
    assert result["failures"] and len(calls) == 1


def test_media_metadata_preserves_dimensions_and_caption_without_claiming_ocr():
    m = module()
    rows = [
        block("doc1", "page", "Root", children=["im"], parent=""),
        block("im", "image", token="tok", width=12, height=34, caption={"content": "image caption"}),
    ]
    result = m.read_document(
        "doc1", lambda p, q: {"items": rows, "has_more": False}, lambda p, n: {"raw": b"imagefixture"}
    )
    assert result["valid"]
    item = result["attachments"][0]
    assert item["metadata"] == {"width": 12, "height": 34, "caption": {"content": "image caption"}}
    assert not any("recognized" in s["text"] for s in result["segments"])


@pytest.mark.parametrize(
    "params", [{"page_token": "http://evil?next"}, {"page_size": 999}, {"document_revision_id": "bad"}]
)
def test_unsafe_or_overbudget_query_rejected_before_network(params):
    m = module()
    session = Mock()
    c = m.FeishuTransport("fixture-key", session=session, interval=0)
    with pytest.raises(ValueError):
        c.get_json("/open-apis/docx/v1/documents/doc1/blocks", params)
    session.get.assert_not_called()


def test_metadata_budget_and_total_media_budget_fail_closed():
    m = module()
    root = block("doc1", "page", "root", children=["a", "b"], parent="")
    children = [block("a", "image", token="tok1"), block("b", "image", token="tok2")]
    def get(p, q):
        return {"items": [root, *children], "has_more": False}
    result = m.read_document("doc1", get, lambda p, n: {"raw": b"123"}, max_total_media=5)
    assert len(result["attachments"]) == 1 and not result["valid"]
    result = m.read_document("doc1", get, Mock(), max_metadata_bytes=20)
    assert not result["valid"] and result["failures"][0]["error"] == "metadata_budget"


def test_unsupported_inline_mention_is_failure_not_invented_display_name():
    m = module()
    root = block("doc1", "page", "root", children=["a"], parent="")
    child = block("a", "text", elements=[{"mention_user": {"user_id": "unknown"}}])
    result = m.read_document("doc1", lambda p, q: {"items": [root, child], "has_more": False}, Mock())
    assert not result["valid"]
    assert any(x["error"] == "unsupported_text_element" for x in result["failures"])
