"""First-initialization-only knowledge import. Later upgrades never change knowledge data."""

import hashlib
import json
from pathlib import Path
import re
import uuid

SCHEMA = "engramproject-initial-knowledge-v1"
MANIFEST_SCHEMA = "engramproject-initial-knowledge-manifest-v1"
INITIALIZED_KEY = "INITIAL_KNOWLEDGE_SEED_INITIALIZED"
NAMESPACE = uuid.UUID("22cdd38a-992d-53f8-9214-a72531b9109d")
ALLOWED_RECORD = {"source_key", "source_revision", "title", "content", "tags", "provenance", "source_versions"}


_SENSITIVE = re.compile(
    r"(?i)(?:password|passwd|api[_-]?key|client[_-]?secret|access[_-]?token|refresh[_-]?token|authorization|cookie|密码|密钥|口令)[\"']?\s*[:=：]\s*[\"']?(?!\[redacted\]|\[已脱敏\]|\*\*\*)[^\s,;\"']+"
)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def record_revision(record):
    content = {k: v for k, v in record.items() if k != "source_revision"}
    content["provenance"] = {k: v for k, v in content.get("provenance", {}).items() if k != "export_sha256"}
    return hashlib.sha256(canonical(content).encode()).hexdigest()


def validate_bundle(bundle):
    if (
        not isinstance(bundle, dict)
        or set(bundle) - {"schema", "seed_version", "records", "missing_attachments"}
        or bundle.get("schema") != SCHEMA
    ):
        raise ValueError("Invalid initial knowledge schema")
    if not isinstance(bundle.get("seed_version"), str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]{1,100}", bundle["seed_version"]
    ):
        raise ValueError("Invalid seed version")
    checked_text = canonical(bundle)
    for _ in range(4):
        checked_text = checked_text.replace('\\"', '"')
    if _SENSITIVE.search(checked_text) or "-----BEGIN PRIVATE KEY-----" in canonical(bundle):
        raise ValueError("Seed contains suspected credentials")
    records = bundle.get("records")
    if not isinstance(records, list) or not records or len(records) > 1000:
        raise ValueError("Seed record budget exceeded")
    keys = set()
    versions = 0
    for row in records:
        if not isinstance(row, dict) or set(row) != ALLOWED_RECORD:
            raise ValueError("Unknown or missing seed fields")
        key = row["source_key"]
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", key) or key in keys:
            raise ValueError("Duplicate or invalid seed source")
        keys.add(key)
        if row["source_revision"] != record_revision(row):
            raise ValueError("Seed source revision mismatch")
        if (
            not isinstance(row["title"], str)
            or not 0 < len(row["title"]) <= 255
            or not isinstance(row["content"], str)
            or not 0 < len(row["content"]) <= 100000
        ):
            raise ValueError("Seed text budget exceeded")
        if (
            not isinstance(row["tags"], list)
            or len(row["tags"]) > 20
            or any(not isinstance(x, str) or len(x) > 80 for x in row["tags"])
        ):
            raise ValueError("Invalid seed tags")
        if (
            not isinstance(row["provenance"], dict)
            or any(not isinstance(v, str) or len(v) > 300 for v in row["provenance"].values())
            or set(row["provenance"])
            - {"database", "source_id", "original_status", "classification", "export_sha256", "original_title"}
        ):
            raise ValueError("Unknown seed provenance")
        history = row["source_versions"]
        seen = set()
        if not isinstance(history, list) or len(history) > 100:
            raise ValueError("Seed history budget exceeded")
        for version in history:
            if not isinstance(version, dict) or set(version) - {
                "version",
                "source_id",
                "title",
                "content",
                "original_status",
            }:
                raise ValueError("Invalid seed history schema")
            number = version.get("version")
            if type(number) is not int or number < 1 or number in seen:
                raise ValueError("Duplicate seed history version")
            seen.add(number)
            if (
                not isinstance(version.get("title"), str)
                or len(version["title"]) > 255
                or not isinstance(version.get("content"), str)
                or len(version["content"]) > 100000
            ):
                raise ValueError("Invalid seed history text")
        versions += len(history)
    missing = bundle.get("missing_attachments", [])
    if not isinstance(missing, list) or len(missing) > 100:
        raise ValueError("Invalid missing attachment metadata")
    for item in missing:
        if (
            not isinstance(item, dict)
            or set(item) != {"size", "sha256", "status"}
            or type(item["size"]) is not int
            or item["size"] < 0
            or not re.fullmatch(r"[a-f0-9]{64}", item["sha256"])
            or item["status"] != "source_missing"
        ):
            raise ValueError("Invalid missing attachment record")
    return {
        "seed_version": bundle["seed_version"],
        "records": len(records),
        "history_versions": versions,
        "missing_attachments": len(missing),
        "published": 0,
    }


def check_seed_dir(directory):
    root = Path(directory).resolve(strict=True)
    manifest_path = root / "manifest.json"
    bundle_path = root / "knowledge-bundle.json"
    if manifest_path.is_symlink() or bundle_path.is_symlink():
        raise ValueError("Seed symlinks are forbidden")
    if manifest_path.stat().st_size > 65536 or bundle_path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("Seed file budget exceeded")
    manifest = json.loads(manifest_path.read_text())
    raw = bundle_path.read_bytes()
    if manifest.get("schema") != MANIFEST_SCHEMA or set(manifest.get("files", {})) != {"knowledge-bundle.json"}:
        raise ValueError("Invalid seed manifest")
    expected = manifest["files"]["knowledge-bundle.json"]
    if expected.get("size") != len(raw) or expected.get("sha256") != hashlib.sha256(raw).hexdigest():
        raise ValueError("Seed bundle checksum mismatch")
    bundle = json.loads(raw)
    report = validate_bundle(bundle)
    if manifest.get("seed_version") != bundle["seed_version"]:
        raise ValueError("Seed manifest version mismatch")
    return bundle, {
        **report,
        "checksum_verified": True,
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    }


def import_seed(bundle, project, actor):
    """Only the first explicit successful import runs; every later seed apply is a no-op."""
    report = {"created": 0, "unchanged": 0, "skipped_edited": 0, "versions_created": 0, "mapping": [], "published": 0}
    from django.db import transaction
    from plane.license.models import InstanceConfiguration, Instance
    from .models import Article, PublishedRevision, ArticleEvent
    from .retrieval import scan_article
    from plane.quality.permissions import is_administrator, writable_member

    if not actor or not is_administrator(actor):
        raise ValueError("Seed import requires an existing administrator")
    if project.archived_at or project.network != 0 or not writable_member(project.id, actor.id, project.workspace.slug):
        raise ValueError("Explicit active private project and administrator memberships required")
    report.update(created=0, unchanged=0, skipped_edited=0, versions_created=0, mapping=[], published=0)
    with transaction.atomic():
        instance = Instance.objects.select_for_update().order_by("created_at").first()
        if instance is None:
            raise ValueError("Existing initialized platform instance required")
        marker = InstanceConfiguration.objects.select_for_update().filter(key=INITIALIZED_KEY).first()
        if marker is not None:
            report.update(
                status="already_initialized",
                created=0,
                unchanged=0,
                skipped_edited=0,
                versions_created=0,
                imported=0,
                mapping=[],
            )
            return report
        report.update(validate_bundle(bundle))
        type(project).objects.select_for_update().get(pk=project.pk)
        for row in bundle["records"]:
            if scan_article(row["title"], row["content"], row["tags"]) or any(
                scan_article(v["title"], v["content"], []) for v in row["source_versions"]
            ):
                raise ValueError("Seed content must pass sensitive-data scan")
            identity = uuid.uuid5(NAMESPACE, canonical([str(project.id), row["source_key"], row["source_revision"]]))
            article = Article.objects.select_for_update().filter(pk=identity).first()
            if article:
                same = (
                    article.project_id == project.id
                    and article.edit_version == 1
                    and article.status == "draft"
                    and not article.publication_active
                    and article.title == row["title"]
                    and article.content == row["content"]
                    and article.tags == row["tags"]
                )
                if same:
                    history = list(article.versions.order_by("version").values("version", "title", "content"))
                    expected = [
                        {k: v[k] for k in ["version", "title", "content"]}
                        for v in sorted(row["source_versions"], key=lambda x: x["version"])
                    ]
                    same = history == expected
                report["unchanged" if same else "skipped_edited"] += 1
            else:
                article = Article.objects.create(
                    id=identity,
                    project=project,
                    created_by=actor,
                    title=row["title"],
                    content=row["content"],
                    tags=row["tags"],
                    status="draft",
                    publication_active=False,
                    published_version=max((x["version"] for x in row["source_versions"]), default=0),
                )
                for version in row["source_versions"]:
                    PublishedRevision.objects.create(
                        id=uuid.uuid5(NAMESPACE, str(identity) + ":history:" + str(version["version"])),
                        article=article,
                        project=project,
                        created_by=actor,
                        version=version["version"],
                        title=version["title"],
                        content=version["content"],
                        tags=["历史追溯", "未在本平台发布"],
                    )
                    report["versions_created"] += 1
                ArticleEvent.objects.create(
                    project=project,
                    article=article,
                    created_by=actor,
                    action="seed_import",
                    version=1,
                    note=canonical(
                        {
                            "seed_version": bundle["seed_version"],
                            "source_key": row["source_key"],
                            "source_revision": row["source_revision"],
                            "provenance": row["provenance"],
                        }
                    ),
                )
                report["created"] += 1
            report["mapping"].append(
                {
                    "source_key": row["source_key"],
                    "source_revision": row["source_revision"],
                    "article_id": str(identity),
                }
            )
        InstanceConfiguration.objects.create(
            key=INITIALIZED_KEY,
            value=canonical(
                {
                    "seed_version": bundle["seed_version"],
                    "project_id": str(project.id),
                    "actor_id": str(actor.id),
                    "records": report["created"],
                    "publication_active": False,
                }
            ),
            category="KNOWLEDGE",
            is_encrypted=False,
        )
        report.update(status="initialized_drafts", imported=report["created"])
    return report
