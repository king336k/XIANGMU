"""Bounded official Docx blocks/media reader. No configuration lookup, models or arbitrary URLs.

Verified official generated schemas (read 2026-11-10):
https://github.com/larksuite/oapi-sdk-python/tree/0d9749a4728446a0ffa2e8374b37b5e1ce1cfd9c/lark_oapi/api/docx/v1/model
Image/file tokens in Docx are downloaded as cloud-document media. Independent Drive
files use a different API and are not a fallback when a document media is denied.
"""

import hashlib
import json
import math
import re
import time

import requests

ORIGIN = "https://open.feishu.cn"
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
TEXT_KINDS = {
    "page",
    "text",
    "bullet",
    "ordered",
    "code",
    "quote",
    "equation",
    "todo",
    *("heading" + str(i) for i in range(1, 10)),
}
CONTAINERS = {"table", "table_cell"}
SUPPORTED = TEXT_KINDS | CONTAINERS | {"image", "file", "divider"}
PATH = re.compile(
    r"^/open-apis/(?:docx/v1/documents/[A-Za-z0-9_-]{1,200}/blocks(?:/[A-Za-z0-9_-]{1,200}/children)?|drive/v1/medias/[A-Za-z0-9_-]{1,200}/download)$"
)


class FeishuReadError(ValueError):
    """Safe error labels only; never include upstream response, credentials or content."""


def safe_id(value):
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise FeishuReadError("invalid_identifier")
    return value


class FeishuTransport:
    """Fixed-origin GET only; bounded stream, request count, timeout and429 retry.

    Callbacks can instead be injected into read_document. Authorization exists only
    in this object/request memory. The caller owns and closes an injected session.
    """

    def __init__(
        self, service_token, *, session=None, sleep=time.sleep, interval=0.2, max_requests=500, max_seconds=90
    ):
        if not isinstance(service_token, str) or not service_token:
            raise ValueError("authorized service token required")
        self._token = service_token
        self.session = session or requests.Session()
        self.sleep = sleep
        self.interval = interval
        self.requests = 0
        self.maximum = max_requests
        self.deadline = time.monotonic() + max_seconds
        self.last_request = None

    def _request(self, path, params=None):
        if not isinstance(path, str) or not PATH.fullmatch(path):
            raise ValueError("only fixed official API paths allowed")
        if params and any(k not in {"page_size", "page_token", "document_revision_id", "user_id_type"} for k in params):
            raise ValueError("unsupported API query")
        for name, value in (params or {}).items():
            if name == "page_size" and (type(value) is not int or not 1 <= value <= 500):
                raise ValueError("invalid page size")
            if name == "page_token" and (
                not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_+./=-]{1,2048}", value)
            ):
                raise ValueError("invalid cursor")
            if name == "document_revision_id" and (type(value) is not int or value < -1):
                raise ValueError("invalid revision")
            if name == "user_id_type" and value not in {"open_id", "union_id", "user_id"}:
                raise ValueError("invalid user id type")
        for attempt in range(3):
            remaining = self.deadline - time.monotonic()
            if remaining <= 0 or self.requests >= self.maximum:
                raise FeishuReadError("request_budget")
            if self.last_request is not None and self.interval:
                delay = max(0, self.interval - (time.monotonic() - self.last_request))
                if delay:
                    self.sleep(delay)
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise FeishuReadError("request_budget")
            self.requests += 1
            self.last_request = time.monotonic()
            try:
                response = self.session.get(
                    ORIGIN + path,
                    params=params or {},
                    headers={"Authorization": "Bearer " + self._token, "Accept-Encoding": "identity"},
                    timeout=(min(3, remaining), min(8, remaining)),
                    allow_redirects=False,
                    stream=True,
                )
            except requests.RequestException:
                raise FeishuReadError("upstream_unavailable") from None
            if response.status_code == 429:
                raw = response.headers.get("Retry-After", "1")
                response.close()
                if attempt == 2:
                    raise FeishuReadError("rate_limit")
                try:
                    delay = float(raw)
                except (TypeError, ValueError):
                    delay = 1
                self.sleep(min(2, max(0, delay)) if math.isfinite(delay) else 1)
                continue
            if response.status_code != 200:
                response.close()
                raise FeishuReadError("upstream_denied_or_failed")
            return response
        raise FeishuReadError("rate_limit")

    def _bytes(self, path, limit, params=None):
        response = self._request(path, params)
        try:
            if response.headers.get("Content-Encoding", "identity").lower() not in {"", "identity"}:
                raise FeishuReadError("unsupported_content_encoding")
            expected = response.headers.get("Content-Length")
            if expected is not None and (not re.fullmatch(r"[0-9]{1,12}", expected) or int(expected) > limit):
                raise FeishuReadError("download_budget")
            content = bytearray()
            for block in response.iter_content(64 * 1024):
                if time.monotonic() > self.deadline:
                    raise FeishuReadError("request_budget")
                content.extend(block)
                if len(content) > limit:
                    raise FeishuReadError("download_budget")
            if expected is not None and len(content) != int(expected):
                raise FeishuReadError("incomplete_download")
            return bytes(content), response.headers.get("Content-Type", "application/octet-stream")
        except requests.RequestException:
            raise FeishuReadError("incomplete_download") from None
        finally:
            response.close()

    def get_json(self, path, params):
        raw, _ = self._bytes(path, 2 * 1024 * 1024, params)
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise FeishuReadError("invalid_json") from None
        if not isinstance(payload, dict) or payload.get("code") != 0 or not isinstance(payload.get("data"), dict):
            raise FeishuReadError("upstream_error_payload")
        return payload["data"]

    def download(self, path, max_bytes):
        raw, content_type = self._bytes(path, max_bytes)
        if not raw:
            raise FeishuReadError("empty_download")
        kind = content_type.split(";", 1)[0].strip().lower()
        if kind in {"text/html", "application/xhtml+xml"}:
            raise FeishuReadError("upstream_error_content")
        if raw.lstrip().startswith(b"{"):
            try:
                payload = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                payload = None
            if (
                isinstance(payload, dict)
                and type(payload.get("code")) is int
                and payload["code"] != 0
                and isinstance(payload.get("msg"), str)
                and set(payload) <= {"code", "msg", "error", "error_data", "data"}
            ):
                raise FeishuReadError("upstream_error_content")
        return {"raw": raw, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "content_type": content_type}

    def close(self):
        self.session.close()


def read_document(
    document_id,
    get_json,
    download,
    *,
    max_blocks=5000,
    max_depth=40,
    max_text=100000,
    max_media_bytes=20 * 1024 * 1024,
    max_total_media=40 * 1024 * 1024,
    max_attachments=100,
    max_pages=100,
    max_seconds=90,
    max_requests=500,
    max_metadata_bytes=8 * 1024 * 1024,
):
    """Return partial evidence plus explicit failures; valid=False must block confirmation.

    get_json(path, params)->official data; download(path, max_bytes)->{raw:bytes,...}.
    Attachment raw bytes are private in-memory descriptors, never a JSON API payload.
    read_document does not fetch secret configuration or fall back to raw_content.
    """
    result = {
        "format": "feishu_docx",
        "document_id": document_id,
        "blocks": [],
        "segments": [],
        "attachments": [],
        "failures": [],
        "valid": False,
    }
    deadline = time.monotonic() + max_seconds
    blocks = {}
    walked = set()
    active = set()
    total_text = 0
    total_media = 0
    requests_count = 0
    metadata_bytes = 0

    def fail(stage, error, bid=None):
        item = {"stage": stage, "error": error}
        if bid:
            item["block_id"] = bid
        result["failures"].append(item)

    def paged(path):
        nonlocal requests_count, metadata_bytes
        cursor = None
        seen = set()
        rows = []
        for _ in range(max_pages):
            if time.monotonic() > deadline:
                raise FeishuReadError("document_time_budget")
            params = {"page_size": 200}
            if cursor is not None:
                params["page_token"] = cursor
            requests_count += 1
            if requests_count > max_requests:
                raise FeishuReadError("request_budget")
            data = get_json(path, params)
            if (
                not isinstance(data, dict)
                or not isinstance(data.get("items"), list)
                or type(data.get("has_more")) is not bool
            ):
                raise FeishuReadError("invalid_page")
            metadata_bytes += len(json.dumps(data, ensure_ascii=False).encode())
            if metadata_bytes > max_metadata_bytes:
                raise FeishuReadError("metadata_budget")
            rows.extend(data["items"])
            if len(rows) > max_blocks:
                raise FeishuReadError("block_budget")
            if not data["has_more"]:
                return rows
            next_cursor = data.get("page_token")
            if not isinstance(next_cursor, str) or not next_cursor or len(next_cursor) > 2048 or next_cursor in seen:
                raise FeishuReadError("pagination_cycle_or_missing_cursor")
            seen.add(next_cursor)
            cursor = next_cursor
        raise FeishuReadError("pagination_budget")

    def register(row, allow_same=False):
        if not isinstance(row, dict):
            raise FeishuReadError("invalid_block")
        bid = safe_id(row.get("block_id"))
        if bid in blocks:
            if allow_same and blocks[bid] == row:
                return
            raise FeishuReadError("duplicate_block")
        if len(blocks) >= max_blocks:
            raise FeishuReadError("block_budget")
        blocks[bid] = row

    def kind_of(row):
        keys = [
            key
            for key in row
            if key not in {"block_id", "parent_id", "block_type", "children", "comment_ids"} and row[key] is not None
        ]
        if len(keys) != 1 or keys[0] not in SUPPORTED:
            raise FeishuReadError("unsupported_block")
        key = keys[0]
        if not isinstance(row[key], dict):
            raise FeishuReadError("invalid_block_payload")
        return key

    def children_of(row, kind):
        bid = row["block_id"]
        ids = row.get("children")
        if kind == "table":
            cells = row[kind].get("cells")
            if not isinstance(cells, list):
                raise FeishuReadError("missing_table_cells")
            if ids is not None and ids != cells:
                raise FeishuReadError("inconsistent_table_cells")
            ids = cells
        needs_fetch = (
            ids is None
            and kind in {"page", "table_cell"}
            or isinstance(ids, list)
            and any(x not in blocks for x in ids if isinstance(x, str))
        )
        if needs_fetch:
            found = paged("/open-apis/docx/v1/documents/" + document_id + "/blocks/" + bid + "/children")
            fetched = []
            for child in found:
                register(child, allow_same=True)
                fetched.append(child["block_id"])
            if ids is None:
                ids = fetched
            elif ids != fetched:
                raise FeishuReadError("incomplete_children")
        if ids is None:
            ids = []
        if (
            not isinstance(ids, list)
            or len(ids) > max_blocks
            or any(not isinstance(x, str) for x in ids)
            or len(set(ids)) != len(ids)
        ):
            raise FeishuReadError("invalid_children")
        return [safe_id(x) for x in ids]

    def text_of(value, bid):
        elements = value.get("elements")
        if not isinstance(elements, list):
            raise FeishuReadError("missing_text_elements")
        chunks = []
        for element in elements:
            if not isinstance(element, dict):
                raise FeishuReadError("invalid_text_element")
            keys = [k for k, v in element.items() if v is not None]
            if len(keys) != 1 or keys[0] not in {"text_run", "equation"}:
                raise FeishuReadError("unsupported_text_element")
            part = element[keys[0]]
            if not isinstance(part, dict) or not isinstance(part.get("content"), str):
                raise FeishuReadError("invalid_text_content")
            chunks.append(part["content"])
        return "".join(chunks)

    def media(row, kind):
        nonlocal total_media
        bid = row["block_id"]
        info = row[kind]
        token = safe_id(info.get("token"))
        if len(result["attachments"]) >= max_attachments:
            raise FeishuReadError("attachment_budget")
        remaining = min(max_media_bytes, max_total_media - total_media)
        if remaining <= 0:
            raise FeishuReadError("media_total_budget")
        nonlocal requests_count
        requests_count += 1
        if requests_count > max_requests or time.monotonic() > deadline:
            raise FeishuReadError("request_budget")
        payload = download("/open-apis/drive/v1/medias/" + token + "/download", remaining)
        raw = payload.get("raw") if isinstance(payload, dict) else None
        if not isinstance(raw, bytes) or not raw or len(raw) > remaining:
            raise FeishuReadError("media_download_or_budget")
        total_media += len(raw)
        name = info.get("name") if kind == "file" else "image-" + bid
        if not isinstance(name, str) or not name or len(name) > 255:
            raise FeishuReadError("invalid_media_name")
        return {
            "block_id": bid,
            "kind": "image" if kind == "image" else "attachment",
            "name": name,
            "token": token,
            "size": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "raw": raw,
            "content_type": payload.get("content_type", "application/octet-stream"),
            "metadata": {
                key: info[key]
                for key in (["width", "height", "caption"] if kind == "image" else ["view_type"])
                if key in info
            },
        }

    def walk(bid, parent=None, depth=0, table_location=None):
        nonlocal total_text
        if time.monotonic() > deadline:
            raise FeishuReadError("document_time_budget")
        if depth > max_depth:
            raise FeishuReadError("depth_budget")
        if bid in active or bid in walked:
            raise FeishuReadError("block_cycle_or_reused_child")
        row = blocks.get(bid)
        if row is None:
            raise FeishuReadError("missing_child_block")
        if parent is not None and row.get("parent_id") != parent:
            raise FeishuReadError("parent_mismatch")
        active.add(bid)
        walked.add(bid)
        try:
            kind = kind_of(row)
            ids = children_of(row, kind)
            record = {
                "block_id": bid,
                "parent_id": row.get("parent_id", ""),
                "kind": kind,
                "block_type": row.get("block_type"),
                "order": len(result["blocks"]),
                "children": ids,
            }
            result["blocks"].append(record)
            if kind in TEXT_KINDS:
                text = text_of(row[kind], bid)
                total_text += len(text)
                if total_text > max_text:
                    raise FeishuReadError("text_budget")
                record["text"] = text
                if row[kind].get("style") is not None:
                    record["style"] = row[kind]["style"]
                if text:
                    result["segments"].append(
                        {
                            "block_id": bid,
                            "kind": kind,
                            "locator": ("飞书表格 " + table_location + " · 内容块 " + bid)
                            if table_location
                            else "飞书块 " + bid,
                            "text": text,
                        }
                    )
            elif kind == "table":
                table = row[kind]
                prop = table.get("property")
                if not isinstance(prop, dict):
                    raise FeishuReadError("missing_table_dimensions")
                rows, columns = prop.get("row_size"), prop.get("column_size")
                if (
                    type(rows) is not int
                    or type(columns) is not int
                    or min(rows, columns) < 1
                    or rows * columns != len(ids)
                ):
                    raise FeishuReadError("incomplete_table_cells")
                if prop.get("merge_info"):
                    # Exact merge spans require additional layout validation;
                    # never flatten unsupported merged cells into a complete document.
                    raise FeishuReadError("merged_table_requires_review")
                record["table"] = table
            elif kind in {"image", "file"}:
                result["attachments"].append(media(row, kind))
            for index, child in enumerate(ids):
                location = (
                    (f"{bid} 第{index // columns + 1}行第{index % columns + 1}列")
                    if kind == "table"
                    else table_location
                )
                try:
                    walk(child, bid, depth + 1, location)
                except FeishuReadError as e:
                    fail("block", str(e), child)
        except FeishuReadError as e:
            fail("block", str(e), bid)
        except Exception:
            fail("block", "read_failed", bid)
        finally:
            active.discard(bid)

    try:
        safe_id(document_id)
        for row in paged("/open-apis/docx/v1/documents/" + document_id + "/blocks"):
            register(row)
        root = blocks.get(document_id)
        if root is None:
            roots = [r for r in blocks.values() if not r.get("parent_id") and "page" in r]
            if len(roots) != 1:
                raise FeishuReadError("missing_document_root")
            root = roots[0]
        walk(root["block_id"])
        for bid in blocks.keys() - walked:
            fail("structure", "unreachable_block", bid)
    except FeishuReadError as e:
        fail("document", str(e))
    except Exception:
        fail("document", "read_failed")
    result["valid"] = not result["failures"]
    return result
