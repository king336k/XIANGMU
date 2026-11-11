"""Disk-backed, idempotent transport for a single manifest-verified diagnostic file."""

import hashlib
import os
from pathlib import Path
import shutil
import uuid
from django.core.files import File
from django.db import transaction
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from .models import ProblemPackage
from .views import Conflict

CHUNK_BYTES = 4 * 1024 * 1024
MAX_DIAGNOSTIC_BYTES = 200 * 1024 * 1024


def digest_stream(handle):
    digest = hashlib.sha256()
    for block in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(block)
    handle.seek(0)
    return digest.hexdigest()


def receive(view, package, upload, manifest, index, count):
    from .attachments import directory, FileSerializer, save_upload, validate_archive

    expected_count = max(1, (manifest["size"] + CHUNK_BYTES - 1) // CHUNK_BYTES)
    expected_size = min(CHUNK_BYTES, manifest["size"] - index * CHUNK_BYTES)
    if count != expected_count or index >= count or upload.size != expected_size:
        raise ValidationError({"file": "分块编号、数量或大小与原始清单不符。"})
    digest = digest_stream(upload)
    key = hashlib.sha256((manifest["path"] + ":" + manifest["sha256"]).encode()).hexdigest()
    # All names are server generated. The package row serializes concurrent retries/finalization.
    with transaction.atomic():
        package = ProblemPackage.objects.select_for_update().get(pk=package.pk)
        prior = package.uploaded_files.filter(name=manifest["path"]).first()
        if prior:
            return Response(FileSerializer(prior).data)
        root = directory() / ".chunks" / str(package.pk) / key
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        part = root / str(index)
        if part.exists():
            with part.open("rb") as saved:
                if part.stat().st_size != upload.size or digest_stream(saved) != digest:
                    raise Conflict("同一分块内容不同，请核对原始诊断文件后重试。")
        else:
            write_file(part, upload.chunks())
        if not all((root / str(number)).is_file() for number in range(count)):
            return Response({"uploading": True, "chunk_index": index, "chunk_count": count}, status=202)
        assembled = root / "assembled"
        try:

            def pieces():
                for number in range(count):
                    with (root / str(number)).open("rb") as source:
                        yield from iter(lambda: source.read(1024 * 1024), b"")

            write_file(assembled, pieces())
            with assembled.open("rb") as handle:
                if assembled.stat().st_size != manifest["size"] or digest_stream(handle) != manifest["sha256"].lower():
                    # Discard bad chunks so a corrected transfer can restart with the same manifest.
                    shutil.rmtree(root)
                    raise ValidationError({"file": "完整文件大小或SHA256与已登记清单不符。"})
                validate_archive(handle, manifest["path"])
                response = save_upload(
                    view,
                    package,
                    File(handle, name=Path(manifest["path"]).name),
                    manifest["path"],
                    manifest["sha256"].lower(),
                )
            shutil.rmtree(root)
            return response
        finally:
            assembled.unlink(missing_ok=True)


def write_file(path, pieces):
    temporary = path.with_name("pending-" + uuid.uuid4().hex)
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            for block in pieces:
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
