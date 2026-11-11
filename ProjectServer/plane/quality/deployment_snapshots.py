# SPDX-License-Identifier: AGPL-3.0-only
"""Read only the bounded version projection from verified feedback uploads."""

import hashlib
import json
import os
import re
import stat
from uuid import UUID

from django.utils.dateparse import parse_datetime
from rest_framework.response import Response

from .attachments import directory
from .models import Defect, PackageFile
from .views import Conflict, QualityView

MAX_FEEDBACK_BYTES = 1024 * 1024
MAX_FEEDBACK_FILES = 100
MAX_COMPONENTS = 64
MAX_SUBMODULES = 50
MAX_COMPARISON_ITEMS = 50
LOCATIONS = {"host", "robot", "remote", "web"}
STATUSES = {"available", "unavailable", "excluded"}
TEXT_FIELDS = (
    "version",
    "branch",
    "commit",
    "commitMessage",
    "commitDate",
    "builtAt",
    "generatedAt",
    "image",
    "source",
    "reason",
)
MODULE_FIELDS = (
    "version",
    "branch",
    "commit",
    "commitMessage",
    "commitDate",
    "builtAt",
    "generatedAt",
    "image",
)


def source_identity(value):
    dirty = value.get("dirty", False)
    if type(dirty) is not bool:
        raise ValueError("Invalid dirty state")
    snapshot = text(value.get("sourceSnapshotSha256", ""), 64)
    if snapshot and not re.fullmatch(r"[0-9a-f]{64}", snapshot):
        raise ValueError("Invalid source snapshot")
    file_count = value.get("sourceFileCount")
    if file_count is not None and (
        type(file_count) is not int or not 0 <= file_count <= 10_000_000
    ):
        raise ValueError("Invalid source file count")
    return {
        "dirty": dirty,
        "sourceSnapshotSha256": snapshot,
        "sourceFileCount": file_count,
    }


def text(value, maximum=2048):
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError("Invalid version text")
    return value


def module(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid module")
    return {
        **{field: text(value.get(field, "")) for field in MODULE_FIELDS},
        **source_identity(value),
    }


def submodule_key(value):
    key = text(value, 256)
    if (
        "\\" in key
        or ":" in key
        or "\x7f" in key
        or any(part in {"", ".", ".."} for part in key.split("/"))
    ):
        raise ValueError("Invalid submodule path")
    return key


def component(value):
    if (
        not isinstance(value, dict)
        or value.get("status") not in STATUSES
        or value.get("location") not in LOCATIONS
    ):
        raise ValueError("Invalid component")
    children = value.get("submodules", [])
    if not isinstance(children, list) or len(children) > MAX_SUBMODULES:
        raise ValueError("Invalid submodules")
    key = text(value.get("key"), 80)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", key):
        raise ValueError("Invalid component key")
    output = {
        "key": key,
        "label": text(value.get("label"), 120),
        "location": value["location"],
        "status": value["status"],
        **{field: text(value.get(field, "")) for field in TEXT_FIELDS},
        **source_identity(value),
        "submodules": [
            {"key": submodule_key(child.get("key")), **module(child)}
            for child in children
            if isinstance(child, dict)
        ],
    }
    if len(output["submodules"]) != len(children) or not output["key"]:
        raise ValueError("Invalid submodule or key")
    if len({child["key"] for child in output["submodules"]}) != len(children):
        raise ValueError("Duplicate submodule key")
    omitted = value.get("omittedSubmodules", 0)
    if type(omitted) is not int or not 0 <= omitted <= 10000:
        raise ValueError("Invalid omitted submodule count")
    output["omittedSubmodules"] = omitted
    return output


def project_snapshot(document, filename):
    if not isinstance(document, dict):
        raise ValueError("Invalid feedback")
    snapshot = document.get("deploymentSnapshot")
    if snapshot is None:
        return None
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("schemaVersion") != 1
        or snapshot.get("source") != "combined_client_info"
    ):
        raise ValueError("Invalid snapshot")
    event = text(snapshot.get("eventId"), 64)
    try:
        UUID(event)
    except (ValueError, AttributeError) as error:
        raise ValueError("Invalid event ID") from error
    if document.get("eventId") != event or filename not in {
        f"feedback-{event}.json", f"feedback-version-{event}.json"
    }:
        raise ValueError("Feedback event mismatch")
    captured_at = text(snapshot.get("capturedAt", ""), 80)
    if captured_at and parse_datetime(captured_at) is None:
        raise ValueError("Invalid capture time")
    components = snapshot.get("components")
    if not isinstance(components, list) or len(components) > MAX_COMPONENTS:
        raise ValueError("Invalid component list")
    comparison = snapshot.get("comparison", {})
    if not isinstance(comparison, dict) or comparison.get("status", "unknown") not in {
        "match",
        "mismatch",
        "unknown",
    }:
        raise ValueError("Invalid comparison")
    items = comparison.get("items", [])
    if not isinstance(items, list) or len(items) > MAX_COMPARISON_ITEMS:
        raise ValueError("Invalid comparison items")
    clean_items = []
    for item in items:
        if not isinstance(item, dict) or type(item.get("match")) is not bool:
            raise ValueError("Invalid comparison item")
        clean_items.append(
            {
                "label": text(item.get("label", "")),
                "local": text(item.get("local", "")),
                "remote": text(item.get("remote", "")),
                "match": item["match"],
            }
        )
    clean_components = [component(item) for item in components]
    if len({item["key"] for item in clean_components}) != len(clean_components):
        raise ValueError("Duplicate component key")
    return {
        "schemaVersion": 1,
        "eventId": event,
        "capturedAt": captured_at,
        "source": "combined_client_info",
        "components": clean_components,
        "comparison": {
            "status": comparison.get("status", "unknown"),
            "items": clean_items,
        },
    }


def read_feedback(row):
    manifest = row.package.files
    expected = (
        next(
            (
                entry
                for entry in manifest
                if isinstance(entry, dict) and entry.get("path") == row.name
            ),
            None,
        )
        if isinstance(manifest, list)
        else None
    )
    if (
        not expected
        or expected.get("size") != row.size
        or not isinstance(expected.get("sha256"), str)
        or expected["sha256"].lower() != row.sha256.lower()
        or not 0 <= row.size <= MAX_FEEDBACK_BYTES
        or not re.fullmatch(r"[0-9a-f]{32}\.bin", row.storage_key)
    ):
        raise Conflict("反馈版本附件校验失败，请联系管理员核对。")
    try:
        descriptor = os.open(
            directory() / row.storage_key, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        )
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size != row.size:
                raise Conflict("反馈版本附件校验失败，请联系管理员核对。")
            raw = handle.read(MAX_FEEDBACK_BYTES + 1)
    except OSError as error:
        raise Conflict("反馈版本附件暂不可用，请联系管理员核对存储。") from error
    if len(raw) != row.size or hashlib.sha256(raw).hexdigest() != row.sha256.lower():
        raise Conflict("反馈版本附件校验失败，请联系管理员核对。")
    try:
        return project_snapshot(json.loads(raw), row.name)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        TypeError,
        RecursionError,
    ) as error:
        raise Conflict("反馈版本快照格式无效，请联系管理员核对。") from error


class DefectDeploymentSnapshots(QualityView):
    def get(self, request, pk, **kwargs):
        defect = self.obj(Defect, pk)
        rows = list(
            PackageFile.objects.filter(
                project=defect.project,
                package__project=defect.project,
                package__defect=defect,
                package__status="files_verified",
                name__startswith="feedback-",
                name__endswith=".json",
            )
            .select_related("package")
            .order_by("-created_at", "-id")[: MAX_FEEDBACK_FILES + 1]
        )
        if len(rows) > MAX_FEEDBACK_FILES:
            raise Conflict("反馈版本附件过多，请联系管理员核对。")
        results = []
        seen = set()
        for row in rows:
            snapshot = read_feedback(row)
            if snapshot is None:
                continue
            identity = (snapshot["eventId"], snapshot["capturedAt"])
            if identity in seen:
                continue
            seen.add(identity)
            results.append(
                {
                    "file": {"id": str(row.id), "name": row.name, "sha256": row.sha256},
                    "snapshot": snapshot,
                }
            )
        response = Response({"count": len(results), "results": results})
        response["Cache-Control"] = "private, no-store"
        return response
