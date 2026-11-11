"""Explicit, offline legacy Hub import. No source connections or automatic publication."""

import hashlib
import json
import re
import uuid

NAMESPACE = uuid.UUID("d4d80f5b-a324-5b3a-9cbb-1c3426e87e91")
SENSITIVE_KEY = re.compile(
    r"(?i)^(?:password|passwd|secret|api[_-]?key|client[_-]?secret|access[_-]?token|refresh[_-]?token|authorization|cookie|密码|密钥)$"
)


def redact(value):
    """Remove credentials before export persistence, including JSON embedded in text."""
    if isinstance(value, dict):
        return {key: "[redacted]" if SENSITIVE_KEY.fullmatch(key) else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if not isinstance(value, str):
        return value
    value = re.sub(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", "[redacted]", value, flags=re.S
    )
    value = re.sub(r"(?i)(https?://)[^\s/@:]+:[^\s/@]+@", r"\1[redacted]@", value)
    value = re.sub(
        r"(?im)((?:authorization|proxy-authorization|cookie|set-cookie)[\"']?\s*[:=：]\s*)[^\r\n]+",
        r"\1[redacted]",
        value,
    )
    value = re.sub(
        r"(?i)((?<![\w])(?:password|passwd|api[_-]?key|client[_-]?secret|access[_-]?token|refresh[_-]?token|secret|token|密码|密钥|口令)[\"']?\s*[:=：]\s*[\"']?)([^\s,;，；\"'\r\n}]+)",
        r"\1[redacted]",
        value,
    )
    value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[redacted]", value)
    return re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[redacted]", value)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def identity(source, table, key):
    return uuid.uuid5(NAMESPACE, canonical([source["host"], source["database"], table, str(key)]))


def build_plan(export):
    source_evidence = export.get("source", {})
    if export.get("schema") != "hub-knowledge-export-v1" or not source_evidence.get("source_verified"):
        raise ValueError("Verified source evidence is required")
    source = export["source"]
    tables = export["tables"]
    drafts = tables["knowledge_drafts"]
    if len({str(row["id"]) for row in drafts}) != len(drafts):
        raise ValueError("Duplicate source draft identity")
    draft_ids = {str(row["id"]) for row in drafts}
    versions = tables["knowledge_versions"]
    if any(str(row["source_draft_id"]) not in draft_ids for row in versions):
        raise ValueError("Orphan source version")
    imports = tables.get("knowledge_imports", [])
    verified_files = {
        str(row["import_id"]) for row in export.get("attachments", []) if row.get("verified") and row.get("sha256")
    }
    if any(str(row["id"]) not in verified_files for row in imports):
        raise ValueError("Unverified source knowledge attachment")
    issues = {str(row["id"]): row for row in tables.get("issue_tickets", [])}
    result = []
    for raw in drafts:
        row = redact(raw)
        scope = row.get("visibility_scope", "PROJECT")
        issue = issues.get(str(row.get("source_issue_id")), {})
        project = "global" if scope == "GLOBAL" else str(issue.get("project_id") or "unmapped")
        history = []
        for original in versions:
            if str(original["source_draft_id"]) != str(row["id"]):
                continue
            version = redact(original)
            history.append(
                {
                    "id": str(identity(source, "knowledge_versions", version["id"])),
                    "version": int(version["version_no"]),
                    "title": str(version["title"])[:255],
                    "content": "原发布版本追溯（未在新平台发布）：\n"
                    + json.dumps(version, ensure_ascii=False, indent=2),
                }
            )
        tags = row.get("tags") or []
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except ValueError:
                tags = re.split(r"[,，;；]", tags)
        if not isinstance(tags, list):
            tags = []
        stable_source = {key: value for key, value in source.items() if key != "captured_at"}
        related = {}
        related_ids = {
            "issue_solutions": row.get("source_solution_id"),
            "regression_tests": row.get("source_regression_id"),
        }
        for table in ["issue_tickets", "issue_solutions", "regression_tests", "agent_reports", "problem_packages"]:
            records = tables.get(table, [])
            if table == "issue_tickets":
                selected = [record for record in records if str(record.get("id")) == str(row.get("source_issue_id"))]
            elif table in related_ids:
                selected = [
                    record
                    for record in records
                    if related_ids[table] is not None and str(record.get("id")) == str(related_ids[table])
                ]
            else:
                selected = [
                    record
                    for record in records
                    if row.get("source_issue_id") is not None
                    and str(record.get("issue_ticket_id")) == str(row["source_issue_id"])
                ]
            related[table] = redact(selected)
        package_ids = {str(record["id"]) for record in related["problem_packages"]}
        evidence_files = [
            record for record in tables.get("problem_package_files", []) if str(record.get("package_id")) in package_ids
        ]
        related["problem_package_files"] = redact(evidence_files)
        related["attachment_verification"] = [
            {key: value for key, value in record.items() if key != "base64"}
            for record in export.get("attachments", [])
            if (
                record.get("table") == "problem_package_files"
                and str(record.get("id")) in {str(file["id"]) for file in evidence_files}
            )
            or (
                record.get("table") == "knowledge_imports"
                and str(record.get("import_id"))
                in {str(file["id"]) for file in imports if str(file.get("knowledge_draft_id")) == str(row["id"])}
            )
        ]
        provenance = {"source": stable_source, "source_project": project, "original": row, "related_evidence": related}
        item = {
            "id": str(identity(source, "knowledge_drafts", row["id"])),
            "source_id": str(row["id"]),
            "source_project": project,
            "title": str(row.get("title") or f"旧知识 {row['id']}")[:255],
            "content": "157 知识迁移草稿；请复核适用范围和证据后按当前流程扫描、审核、发布。\n\n"
            + json.dumps(provenance, ensure_ascii=False, indent=2),
            "tags": list(dict.fromkeys(str(tag)[:80] for tag in tags if tag))[:18] + ["157迁移", "待复核"],
            "status": "draft",
            "publication_active": False,
            "versions": history,
        }
        item["digest"] = digest(item)
        result.append(item)
    return result


def import_plan(plan, project_map, reviewer):
    """Atomic, rerunnable imports; explicit secret projects only, never overwrite edits."""
    from django.db import transaction
    from plane.db.models import Project, ProjectMember, WorkspaceMember
    from plane.quality.permissions import knowledge_reviewer
    from .models import Article, ArticleEvent, PublishedRevision

    with transaction.atomic():
        projects = {}
        for source_project in {row["source_project"] for row in plan}:
            if source_project not in project_map:
                raise ValueError("Every source scope needs an explicit isolated project mapping")
            project = Project.objects.select_for_update().get(pk=project_map[source_project])
            if project.network != 0 or project.archived_at:
                raise ValueError("Migration target must be an active secret project")
            if not knowledge_reviewer(project.id, reviewer.id):
                raise ValueError("Migration actor must be an authorized target reviewer")
            member_ids = set(
                ProjectMember.objects.filter(project=project, is_active=True).values_list("member_id", flat=True)
            )
            workspace_ids = set(
                WorkspaceMember.objects.filter(workspace=project.workspace, is_active=True).values_list(
                    "member_id", flat=True
                )
            )
            if member_ids != {reviewer.id} or workspace_ids != {reviewer.id}:
                raise ValueError("Migration workspace and project must contain only the reviewer")
            projects[source_project] = project
        report = {"created": 0, "unchanged": 0, "versions_created": 0, "mapping": []}
        for row in plan:
            project = projects[row["source_project"]]
            article = Article.objects.select_for_update().filter(pk=row["id"]).first()
            if article:
                event = ArticleEvent.objects.filter(article=article, action="migration").first()
                if not event or event.note != row["digest"] or article.project_id != project.id:
                    raise ValueError("Source content or project mapping changed; manual reconciliation required")
                if (
                    article.content != row["content"]
                    or article.title != row["title"]
                    or article.tags != row["tags"]
                    or article.edit_version != 1
                    or article.status != "draft"
                    or article.publication_active
                ):
                    raise ValueError("Target draft has been edited; refusing to overwrite")
                for version in row["versions"]:
                    stored = PublishedRevision.objects.filter(pk=version["id"], article=article).first()
                    if not stored or stored.content != version["content"] or stored.version != version["version"]:
                        raise ValueError("Historical version differs; manual reconciliation required")
                report["unchanged"] += 1
            else:
                article = Article.objects.create(
                    id=row["id"],
                    project=project,
                    created_by=reviewer,
                    title=row["title"],
                    content=row["content"],
                    tags=row["tags"],
                    status="draft",
                    publication_active=False,
                    published_version=max((v["version"] for v in row["versions"]), default=0),
                )
                for version in row["versions"]:
                    PublishedRevision.objects.create(
                        id=version["id"],
                        project=project,
                        created_by=reviewer,
                        article=article,
                        version=version["version"],
                        title=version["title"],
                        content=version["content"],
                        tags=["157迁移历史"],
                    )
                    report["versions_created"] += 1
                ArticleEvent.objects.create(
                    project=project,
                    created_by=reviewer,
                    article=article,
                    action="migration",
                    version=1,
                    note=row["digest"],
                )
                report["created"] += 1
            report["mapping"].append(
                {
                    "source_id": row["source_id"],
                    "article_id": str(article.id),
                    "project_id": str(project.id),
                    "source_project": row["source_project"],
                    "sha256": row["digest"],
                }
            )
        return report
