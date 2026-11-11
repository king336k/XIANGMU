# SPDX-License-Identifier: AGPL-3.0-only
"""Build a complete private defect attachment bundle before sending any bytes."""

import hashlib
import os
from pathlib import PurePosixPath
import stat
import tempfile
import zipfile

from django.http import FileResponse, Http404
from rest_framework.exceptions import NotFound, ValidationError

from .attachment_chunks import MAX_DIAGNOSTIC_BYTES
from .attachments import directory
from .models import Defect, PackageFile, ProblemPackage
from .sources import FileManifest
from .views import Conflict, QualityView

# Match PackageInput's existing total and manifest-count limits.
MAX_BUNDLE_BYTES = 500 * 1024 * 1024
MAX_BUNDLE_FILES = 1000


def archive_name(value):
    try:
        name = FileManifest().validate_path(value)
    except (ValidationError, TypeError, AttributeError):
        raise Conflict("附件名称无效，请联系管理员核对。")
    if any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise Conflict("附件名称无效，请联系管理员核对。")
    return name


def bundle_entries(defect):
    packages = list(
        ProblemPackage.objects.filter(defect=defect, project=defect.project).order_by("created_at", "id")[
            : MAX_BUNDLE_FILES + 1
        ]
    )
    if len(packages) > MAX_BUNDLE_FILES:
        raise Conflict("附件过多或总大小超过500MB，请分别下载。")
    rows = list(
        PackageFile.objects.filter(
            package__in=packages, project=defect.project, package__project=defect.project
        ).order_by("created_at", "id")[: MAX_BUNDLE_FILES + 1]
    )
    if not rows:
        raise Conflict("暂无可下载的附件。")
    if len(rows) > MAX_BUNDLE_FILES or sum(row.size for row in rows) > MAX_BUNDLE_BYTES:
        raise Conflict("附件过多或总大小超过500MB，请分别下载。")
    by_package = {}
    for row in rows:
        by_package.setdefault(row.package_id, []).append(row)
    entries = []
    names = set()
    parent_names = set()
    for index, package in enumerate(packages, start=1):
        validator = FileManifest(data=package.files, many=True, max_length=MAX_BUNDLE_FILES, allow_empty=False)
        if not validator.is_valid():
            raise Conflict("附件清单无效，请联系管理员核对。")
        # Preserve exact stored manifest names for byte registration matching;
        # normalize only archive entries, where collisions are rejected below.
        manifest = {item["path"]: item for item in package.files}
        uploaded = by_package.get(package.id, [])
        if len(manifest) != len(package.files) or set(manifest) != {row.name for row in uploaded}:
            raise Conflict("附件尚未上传完整，请稍后重试。")
        for row in uploaded:
            expected = manifest[row.name]
            if row.size != expected["size"] or row.sha256.casefold() != expected["sha256"].casefold():
                raise Conflict("附件清单校验失败，请联系管理员核对。")
            name = f"附件包-{index:03d}/" + archive_name(row.name)
            folded = name.casefold()
            parents = {str(parent).casefold() for parent in PurePosixPath(name).parents if str(parent) != "."}
            if folded in names or folded in parent_names or parents & names:
                raise Conflict("附件存在重复路径，请联系管理员核对。")
            names.add(folded)
            parent_names.update(parents)
            if row.size > MAX_DIAGNOSTIC_BYTES:
                raise Conflict("单个附件超过200MB，请分别下载。")
            entries.append((row, name))
    return entries


def copy_verified(output, root, row, name):
    key = row.storage_key
    if (
        not key
        or PurePosixPath(key).name != key
        or key in {".", ".."}
        or "\\" in key
        or any(ord(char) < 32 or ord(char) == 127 for char in key)
    ):
        raise Conflict("附件存储位置无效，请联系管理员核对。")
    descriptor = os.open(root / key, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size != row.size:
            raise Conflict("附件大小校验失败，请联系管理员核对。")
        digest = hashlib.sha256()
        size = 0
        with output.open(name, "w", force_zip64=True) as target:
            while block := source.read(64 * 1024):
                size += len(block)
                if size > row.size:
                    raise Conflict("附件内容已改变，请联系管理员核对。")
                digest.update(block)
                target.write(block)
        if size != row.size or digest.hexdigest() != row.sha256.casefold():
            raise Conflict("附件内容校验失败，请联系管理员核对。")


class DefectAttachmentArchive(QualityView):
    def get(self, request, pk, **kwargs):
        try:
            defect = self.obj(Defect, pk)
        except Http404:
            raise NotFound("找不到该缺陷。")
        if defect.archived_at:
            raise Conflict("缺陷已归档，请恢复后下载附件。")
        entries = bundle_entries(defect)
        handle = None
        try:
            root = directory()
            # Disk-backed temporary file in persistent attachment storage, never
            # system /tmp. It is unlinked automatically and closed with response.
            handle = tempfile.TemporaryFile(mode="w+b", prefix="attachment-bundle-", dir=root)
            with zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
                for row, name in entries:
                    copy_verified(archive, root, row, name)
            handle.seek(0)
            response = FileResponse(
                handle,
                as_attachment=True,
                filename=f"{defect.code or defect.id}-附件.zip",
                content_type="application/zip",
            )
            response["Cache-Control"] = "private, no-store"
            response["X-Content-Type-Options"] = "nosniff"
            return response
        except BaseException as error:
            if handle is not None:
                handle.close()
            if isinstance(error, OSError):
                raise Conflict("附件暂不可用，请联系管理员核对存储。") from error
            raise
