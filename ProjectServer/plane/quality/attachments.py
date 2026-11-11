# SPDX-License-Identifier: AGPL-3.0-only
"""Private diagnostic attachments: manifest verification before durable registration."""

import hashlib
import os
import re
from pathlib import Path, PurePosixPath
import stat
import uuid
import zipfile
from django.conf import settings
from django.db import transaction
from django.http import FileResponse
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from .models import PackageFile, ProblemPackage
from .views import QualityView, Conflict
from plane.authentication.session import BaseSessionAuthentication
from .identity import PlatformBridgeAuthentication

MAX_FILE = 20 * 1024 * 1024
MAX_ARCHIVE_EXPANDED = 200 * 1024 * 1024


def directory():
    root = Path(getattr(settings, "QUALITY_ATTACHMENT_ROOT", "/code/quality-attachments"))
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root.resolve()


class FileSerializer(serializers.ModelSerializer):
    source_system = serializers.CharField(source="package.source_system", read_only=True)
    uploader = serializers.SerializerMethodField()

    def get_uploader(self, obj):
        if obj.created_by and obj.created_by.is_bot:
            from .daq_incidents import trusted_incident, signed_record
            source = trusted_incident(obj.package.defect)
            if source:
                reporter = signed_record(source).get("reporter", {})
                if reporter.get("username"):
                    return reporter["username"]
        return (obj.created_by.display_name or obj.created_by.username) if obj.created_by else "成员"


    class Meta:
        model = PackageFile
        fields = ["id", "name", "size", "sha256", "source_system", "uploader", "created_at"]


class UploadInput(serializers.Serializer):
    manifest_path = serializers.CharField(max_length=500, required=False)

    def validate_manifest_path(self, value):
        from .sources import FileManifest

        return FileManifest().validate_path(value)

    file = serializers.FileField(allow_empty_file=True)
    chunk_index = serializers.IntegerField(min_value=0, max_value=49, required=False)
    chunk_count = serializers.IntegerField(min_value=1, max_value=50, required=False)

    def validate(self, attrs):
        if ("chunk_index" in attrs) != ("chunk_count" in attrs):
            raise ValidationError({"file": "请同时提交分块编号和数量。"})
        return attrs


def validate_archive(handle, name):
    if not name.lower().endswith(".zip"):
        return
    try:
        with zipfile.ZipFile(handle) as archive:
            infos = archive.infolist()
            if len(infos) > 1000 or sum(i.file_size for i in infos) > MAX_ARCHIVE_EXPANDED:
                raise ValidationError({"file": "压缩包展开内容超出允许范围。"})
            names = set()
            for item in infos:
                normalized = item.filename.replace("\\", "/")
                if (
                    PurePosixPath(normalized).is_absolute()
                    or any(p in {".", ".."} for p in normalized.split("/"))
                    or ":" in normalized
                    or "\x00" in normalized
                    or stat.S_ISLNK(item.external_attr >> 16)
                    or item.flag_bits & 1
                ):
                    raise ValidationError({"file": "压缩包包含危险路径、链接或加密内容。"})
                if normalized in names:
                    raise ValidationError({"file": "压缩包包含重复文件路径。"})
                names.add(normalized)
            if archive.testzip():
                raise ValidationError({"file": "压缩包内容校验失败。"})
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError):
        raise ValidationError({"file": "诊断ZIP格式无效。"})
    finally:
        handle.seek(0)


class PackageFiles(QualityView):
    authentication_classes = [PlatformBridgeAuthentication, BaseSessionAuthentication]

    def get(self, request, pk, **kwargs):
        package = self.obj(ProblemPackage, pk)
        return Response(FileSerializer(package.uploaded_files.all(), many=True).data)

    def post(self, request, pk, **kwargs):
        data = self.input(UploadInput)
        upload = data["file"]
        manifest_path = data.get("manifest_path", upload.name)
        if upload.size > MAX_FILE:
            raise ValidationError({"file": "单个诊断文件不能超过20MB。"})
        if "/" in upload.name or "\\" in upload.name or upload.name.startswith("."):
            raise ValidationError({"file": "请使用普通文件名上传诊断材料。"})
        package = self.obj(ProblemPackage, pk)
        manifest = next((f for f in package.files if f["path"] == manifest_path), None)
        if not manifest:
            raise ValidationError({"file": "请先登记与文件名匹配的清单。"})
        if "chunk_index" in data:
            from .attachment_chunks import receive

            return receive(self, package, upload, manifest, data["chunk_index"], data["chunk_count"])
        digest = hashlib.sha256()
        for chunk in upload.chunks():
            digest.update(chunk)
        upload.seek(0)
        if upload.size != manifest["size"] or digest.hexdigest() != manifest["sha256"].lower():
            raise ValidationError({"file": "文件大小或SHA256与已登记清单不符。"})
        validate_archive(upload, manifest_path)
        return save_upload(self, package, upload, manifest_path, digest.hexdigest())


def save_upload(view, package, upload, manifest_path, digest):
    path = None
    try:
        with transaction.atomic():
            package = ProblemPackage.objects.select_for_update().get(pk=package.pk)
            prior = package.uploaded_files.filter(name=manifest_path).first()
            if prior:
                return Response(FileSerializer(prior).data)
            key = f"{uuid.uuid4().hex}.bin"
            path = directory() / key
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                for chunk in upload.chunks():
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            row = PackageFile.objects.create(
                project=package.project,
                created_by=view.request.user,
                package=package,
                name=manifest_path,
                size=upload.size,
                sha256=digest,
                storage_key=key,
            )
            if package.uploaded_files.count() == len(package.files):
                package.status = "files_verified"
                package.save(update_fields=["status"])
                from .diagnostics import schedule_automatic

                schedule_automatic(package.defect, view.request.user, "materials_verified")
            return Response(FileSerializer(row).data, status=201)
    except BaseException:
        if path:
            path.unlink(missing_ok=True)
        raise


class FileDownload(QualityView):
    authentication_classes = [PlatformBridgeAuthentication, BaseSessionAuthentication]

    def get(self, request, pk, **kwargs):
        row = self.obj(PackageFile, pk)
        path = directory() / row.storage_key
        if path.parent != directory() or path.is_symlink():
            raise Conflict("文件存储位置无效。")
        try:
            handle = path.open("rb")
        except FileNotFoundError:
            raise Conflict("文件暂不可用，请联系管理员核对存储。")
        if request.query_params.get("metadata") == "1":
            handle.close()
            return Response(FileSerializer(row).data)
        chunk_bytes = 4 * 1024 * 1024
        raw_range = request.headers.get("Range")
        offset, length = request.query_params.get("offset"), request.query_params.get("length")
        if raw_range is not None or offset is not None or length is not None:
            match = re.fullmatch(r"bytes=([0-9]{1,20})-([0-9]{1,20})", raw_range or "")
            valid = True
            if raw_range is not None:
                valid = bool(match) and offset is None and length is None
                start, end = (int(match[1]), int(match[2])) if match else (-1, -1)
            elif (
                offset is not None
                and length is not None
                and re.fullmatch(r"[0-9]{1,20}", offset)
                and re.fullmatch(r"[0-9]{1,20}", length)
            ):
                start = int(offset)
                end = min(row.size - 1, start + int(length) - 1)
                valid = 0 < int(length) <= chunk_bytes
            else:
                valid, start, end = False, -1, -1
            if not valid or not (0 <= start <= end < row.size) or end - start + 1 > chunk_bytes:
                handle.close()
                response = Response({"detail": "文件分段范围无效，单段最大4MiB。"}, status=416)
                response["Content-Range"] = f"bytes */{row.size}"
                return response
            handle.seek(start)
            response = FileResponse(
                bounded_read(handle, end - start + 1),
                status=206,
                as_attachment=True,
                filename=PurePosixPath(row.name).name,
                content_type="application/octet-stream",
            )
            response["Content-Range"] = f"bytes {start}-{end}/{row.size}"
            response["Content-Length"] = str(end - start + 1)
        else:
            response = FileResponse(
                handle,
                as_attachment=True,
                filename=PurePosixPath(row.name).name,
                content_type="application/octet-stream",
            )
        response["Accept-Ranges"] = "bytes"
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response


def bounded_read(handle, size):
    try:
        while size:
            block = handle.read(min(size, 64 * 1024))
            if not block:
                break
            size -= len(block)
            yield block
    finally:
        handle.close()


IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def image_type(raw, name):
    extension = Path(name).suffix.lower()
    checks = {
        ".png": raw.startswith(b"\x89PNG\r\n\x1a\n"),
        ".jpg": raw.startswith(b"\xff\xd8\xff"),
        ".jpeg": raw.startswith(b"\xff\xd8\xff"),
        ".gif": raw.startswith((b"GIF87a", b"GIF89a")),
        ".webp": raw[:4] == b"RIFF" and raw[8:12] == b"WEBP",
    }
    return IMAGE_TYPES.get(extension) if checks.get(extension) else None


class DefectAttachments(QualityView):
    def get(self, request, pk, **kwargs):
        from .models import Defect

        defect = self.obj(Defect, pk)
        return Response(
            FileSerializer(PackageFile.objects.filter(package__defect=defect).order_by("-created_at"), many=True).data
        )

    def post(self, request, pk, **kwargs):
        from .models import Defect

        defect = self.obj(Defect, pk)
        upload = self.input(UploadInput)["file"]
        extension = Path(upload.name).suffix.lower()
        allowed = set(IMAGE_TYPES) | {".log", ".txt", ".json", ".csv", ".pdf", ".zip", ".md", ".yaml", ".yml", ".bin"}
        if extension not in allowed or upload.size > MAX_FILE or upload.name.startswith("."):
            raise ValidationError({"file": "支持图片、日志、JSON、CSV、PDF和ZIP等诊断材料，单文件不超过20MB。"})
        raw = upload.read(MAX_FILE + 1)
        upload.seek(0)
        if len(raw) > MAX_FILE:
            raise ValidationError({"file": "文件超过20MB。"})
        if extension in IMAGE_TYPES and not image_type(raw, upload.name):
            raise ValidationError({"file": "图片内容与文件类型不匹配。"})
        validate_archive(upload, upload.name)
        digest = hashlib.sha256(raw).hexdigest()
        with transaction.atomic():
            type(defect).objects.select_for_update().get(pk=defect.pk)
            existing = PackageFile.objects.filter(
                package__defect=defect, package__source_system="MANUAL_ATTACHMENT", name=upload.name, sha256=digest
            ).first()
            if existing:
                return Response(FileSerializer(existing).data)
            package = ProblemPackage.objects.create(
                project=defect.project,
                created_by=request.user,
                defect=defect,
                name=upload.name,
                source_system="MANUAL_ATTACHMENT",
                external_id=str(uuid.uuid4()),
                files=[{"path": upload.name, "size": len(raw), "sha256": digest}],
                manifest_hash=digest,
            )
            return save_upload(self, package, upload, upload.name, digest)


class ImagePreview(FileDownload):
    def get(self, request, pk, **kwargs):
        row = self.obj(PackageFile, pk)
        extension = Path(row.name).suffix.lower()
        if extension in {".log", ".txt", ".json", ".csv", ".md", ".yaml", ".yml"}:
            response = super().get(request, pk, **kwargs)
            response["Content-Type"] = "text/plain; charset=utf-8"
            response["Content-Disposition"] = "inline"
            response["Content-Security-Policy"] = "default-src 'none'; sandbox"
            return response
        if extension not in IMAGE_TYPES:
            raise ValidationError({"file": "该文件不支持在线预览，请下载查看。"})
        response = super().get(request, pk, **kwargs)
        path = directory() / row.storage_key
        with path.open("rb") as handle:
            kind = image_type(handle.read(16), row.name)
        if not kind:
            response.close()
            raise ValidationError({"file": "图片内容无效，请下载核对。"})
        response["Content-Type"] = kind
        response["Content-Disposition"] = "inline"
        response["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return response
