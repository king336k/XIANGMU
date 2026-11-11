"""Reviewed offline Hub migration. No source login, password import, or background work."""

import base64
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import uuid

from plane.knowledge.legacy_migration import canonical, digest, redact, identity

NAMESPACE = uuid.UUID("91cba413-a978-5fd7-8057-6cc65aad5cc4")
SCHEMA = json.loads(Path(__file__).with_name("legacy_schema.json").read_text())
RUNTIME_TABLES = {
    "project_hub_sessions",
    "issue_idempotency_records",
    "seq_problem_package",
    "seq_agent_task",
    "seq_agent_report",
    "issue_ticket_number_sequences",
}
SECRET = re.compile(r"password|passwd|token|secret|credential|authorization|cookie", re.I)
KEYS = {
    "platform_project_mirrors": ["source_project_id"],
    "platform_task_mirrors": ["source_task_id"],
    "platform_catalog_sync_states": ["sync_key"],
    "embedded_test_task_runtime": ["task_id"],
    "embedded_release_settings": ["project_id", "section"],
    "regression_test_attachments": ["regression_id", "attachment_id"],
}
NATIVE = {
    "platform_task_mirrors",
    "issue_tickets",
    "issue_solutions",
    "issue_comments",
    "issue_timeline_events",
    "issue_assignments",
    "embedded_test_cases",
    "embedded_test_suites",
    "embedded_test_tasks",
    "embedded_test_executions",
    "embedded_requirements",
    "embedded_versions",
    "embedded_release_plans",
    "embedded_test_reports",
    "embedded_release_issues",
    "embedded_release_issue_records",
    "feature_test_items",
    "feature_test_rounds",
    "knowledge_drafts",
    "knowledge_versions",
    "embedded_test_resources",
    "problem_packages",
    "problem_package_files",
    "issue_attachments",
    "embedded_test_artifacts",
}
FILE_TABLES = {
    "issue_attachments",
    "problem_package_files",
    "embedded_test_artifacts",
    "embedded_task_package_imports",
    "knowledge_imports",
}
# Provenance follows actual V14/V15/V16/V17/V28/V40/V43/V47/V51 foreign-key columns.
REFERENCES = {
    "issue_attachments": {"ticket_id": "issue_tickets"},
    "issue_members": {"ticket_id": "issue_tickets"},
    "issue_assignments": {"ticket_id": "issue_tickets"},
    "issue_comments": {"ticket_id": "issue_tickets"},
    "issue_timeline_events": {"ticket_id": "issue_tickets"},
    "issue_notifications": {"ticket_id": "issue_tickets"},
    "problem_packages": {"issue_ticket_id": "issue_tickets"},
    "problem_package_files": {"package_id": "problem_packages"},
    "agent_analysis_tasks": {"package_id": "problem_packages", "issue_ticket_id": "issue_tickets"},
    "agent_reports": {
        "package_id": "problem_packages",
        "issue_ticket_id": "issue_tickets",
        "task_id": "agent_analysis_tasks",
    },
    "agent_feedback": {
        "report_id": "agent_reports",
        "package_id": "problem_packages",
        "issue_ticket_id": "issue_tickets",
    },
    "agent_task_events": {"task_id": "agent_analysis_tasks"},
    "issue_solutions": {"issue_ticket_id": "issue_tickets"},
    "regression_tests": {"issue_ticket_id": "issue_tickets", "solution_id": "issue_solutions"},
    "regression_test_data": {"regression_id": "regression_tests"},
    "regression_test_attachments": {"regression_id": "regression_tests", "attachment_id": "issue_attachments"},
    "feature_test_items": {"ticket_id": "issue_tickets"},
    "feature_test_rounds": {"ticket_id": "issue_tickets"},
    "project_member_roles": {"project_member_id": "project_members"},
    "issue_review_tasks": {
        "ticket_id": "issue_tickets",
        "solution_id": "issue_solutions",
        "policy_id": "project_review_policies",
    },
    "issue_review_assignments": {"review_task_id": "issue_review_tasks"},
    "embedded_test_executions": {"task_id": "embedded_test_tasks"},
    "embedded_test_reports": {"task_id": "embedded_test_tasks"},
    "issue_operation_audits": {"ticket_id": "issue_tickets"},
    "issue_rtp_test_task_links": {
        "issue_ticket_id": "issue_tickets",
        "issue_solution_id": "issue_solutions",
        "review_task_id": "issue_review_tasks",
        "regression_test_id": "regression_tests",
    },
    "embedded_test_task_runtime": {"task_id": "embedded_test_tasks"},
    "embedded_release_issue_records": {"issue_id": "embedded_release_issues"},
    "embedded_knowledge_documents": {"knowledge_base_id": "embedded_knowledge_bases"},
    "knowledge_drafts": {
        "source_issue_id": "issue_tickets",
        "source_solution_id": "issue_solutions",
        "source_regression_id": "regression_tests",
    },
    "knowledge_sanitization_findings": {"record_id": "knowledge_sanitization_records"},
    "knowledge_versions": {"source_draft_id": "knowledge_drafts"},
    "knowledge_review_records": {"knowledge_draft_id": "knowledge_drafts"},
}


def sanitize(value):
    if isinstance(value, dict):
        return {key: sanitize(item) for key, item in value.items() if not SECRET.search(key)}
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, (dict, list)):
                cleaned = sanitize(parsed)
                if cleaned != parsed:
                    return canonical(cleaned)
        except ValueError:
            pass
    return redact(value)


def source_key(source):
    return canonical([source["host"], source["database"]])


def source_id(table, row):
    return canonical([str(row[key]) for key in KEYS.get(table, SCHEMA[table].get("primary_key") or ["id"])])


def stable_id(source, table, key, suffix=""):
    if table in {"knowledge_drafts", "knowledge_versions"} and not suffix:
        return str(identity(source, table, json.loads(key)[0]))
    return str(uuid.uuid5(NAMESPACE, canonical([source_key(source), table, key, suffix])))


def payload(row, key, default=None):
    value = row.get(key, default)
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return default
    return value


def build_plan(export, mapping):
    errors = []
    if export.get("schema") != "hub-full-export-v1" or export.get("source", {}).get("source_verified") is not True:
        raise ValueError("A verified full source export is required")
    source = export["source"]
    tables = export.get("tables", {})
    if not source.get("host") or not source.get("database"):
        raise ValueError("Source identity is required")
    if len(source_key(source)) > 255:
        raise ValueError("Source identity is too long")
    if sanitize(source) != source:
        raise ValueError("Source evidence contains sensitive values")
    rows = []
    indexes = {}
    file_index = {}
    for item in export.get("attachments", []):
        key = (item.get("table"), str(item.get("id")))
        if key in file_index:
            errors.append({"code": "duplicate_attachment", "table": key[0], "id": key[1]})
        file_index[key] = item
    for table, values in tables.items():
        if table not in SCHEMA:
            errors.append({"code": "unknown_table", "table": table})
            continue
        if table in RUNTIME_TABLES:
            if values:
                errors.append({"code": "runtime_rows_must_be_excluded", "table": table})
            continue
        indexes[table] = {}
        for original in values:
            unknown = set(original) - set(SCHEMA[table]["columns"])
            if unknown:
                errors.append({"code": "unknown_or_sensitive_columns", "table": table, "fields": sorted(unknown)})
                continue
            clean = sanitize(original)
            if clean != original:
                errors.append({"code": "unsanitized_source", "table": table})
                continue
            try:
                key = source_id(table, clean)
            except KeyError:
                errors.append({"code": "missing_primary_key", "table": table})
                continue
            if key in indexes[table]:
                errors.append({"code": "duplicate_source_identity", "table": table, "id": key})
                continue
            indexes[table][key] = clean
            rows.append(
                {
                    "table": table,
                    "key": key,
                    "snapshot": clean,
                    "source_hash": digest(clean),
                    "id": stable_id(source, table, key),
                    "disposition": "native" if table in NATIVE else "archive_only",
                }
            )
        if export.get("counts", {}).get(table) != len(values) or export.get("table_sha256", {}).get(table) != digest(
            values
        ):
            errors.append({"code": "count_or_hash_mismatch", "table": table})

    def scope(table, row, seen=None):
        seen = set() if seen is None else seen
        key = (table, source_id(table, row))
        if key in seen:
            return None
        seen.add(key)
        direct = row.get("project_id", row.get("source_project_id"))
        if direct is not None:
            return str(direct)
        for field, parent in REFERENCES.get(table, {}).items():
            if row.get(field) is not None:
                value = indexes.get(parent, {}).get(canonical([str(row[field])]))
                if value is not None:
                    result = scope(parent, value, seen)
                    if result is not None:
                        return result
        return None

    for item in rows:
        table, row = item["table"], item["snapshot"]
        for field, target in REFERENCES.get(table, {}).items():
            if row.get(field) is not None and canonical([str(row[field])]) not in indexes.get(target, {}):
                errors.append(
                    {"code": "orphan_reference", "table": table, "id": item["key"], "field": field, "target": target}
                )
            elif row.get(field) is not None:
                parent = indexes[target][canonical([str(row[field])])]
                own_scope, parent_scope = scope(table, row), scope(target, parent)
                if own_scope is not None and parent_scope is not None and own_scope != parent_scope:
                    errors.append(
                        {"code": "cross_project_reference", "table": table, "id": item["key"], "field": field}
                    )
        if table in NATIVE:
            for field in [
                "author_id",
                "operator_id",
                "reporter_id",
                "created_by_id",
                "created_by",
                "submitter_id",
                "uploader_id",
                "uploaded_by_id",
                "returned_by",
                "assignee_id",
            ]:
                if row.get(field) is not None and str(row[field]) not in mapping.get("users", {}):
                    errors.append({"code": "unmapped_actor", "table": table, "id": item["key"], "field": field})
        if table in FILE_TABLES:
            entry = file_index.get((table, str(row.get("id"))))
            verified = False
            if entry and entry.get("verified") is True:
                try:
                    raw = base64.b64decode(entry["base64"], validate=True)
                    verified = len(raw) == entry["bytes"] and hashlib.sha256(raw).hexdigest() == entry["sha256"]
                    if entry.get("media") == "text":
                        text = raw.decode("utf-8")
                        verified = verified and sanitize(text) == text
                    else:
                        verified = verified and entry.get("privacy_reviewed") is True
                except (ValueError, KeyError, TypeError, UnicodeDecodeError):
                    pass
            if not verified:
                item["missing_attachment"] = True
                if not mapping.get("allow_missing_attachment_metadata"):
                    errors.append({"code": "unverified_attachment", "table": table, "id": item["key"]})
                else:
                    item["disposition"] = "archive_missing_file"
    project_ids = {
        str(
            row["snapshot"].get("source_project_id")
            if row["table"] == "platform_project_mirrors"
            else row["snapshot"].get("project_id")
        )
        for row in rows
        if row["table"] == "platform_project_mirrors" or row["snapshot"].get("project_id") is not None
    }
    missing = project_ids - set(mapping.get("projects", {}))
    errors += [{"code": "unmapped_project", "id": key} for key in sorted(missing)]
    stable_source = {key: value for key, value in source.items() if key != "captured_at"}
    manifest = {
        "source": stable_source,
        "tables": tables,
        "attachments": export.get("attachments", []),
        "excluded": export.get("excluded", {}),
    }
    result = {
        "schema": "hub-full-plan-v1",
        "source": stable_source,
        "source_key": source_key(source),
        "manifest_hash": digest(manifest),
        "mapping_hash": digest(mapping),
        "mapping": mapping,
        "rows": rows,
        "conflicts": errors,
        "counts": dict(Counter(item["table"] for item in rows)),
        "dispositions": dict(Counter(item["disposition"] for item in rows)),
        "absent_tables": sorted(set(SCHEMA) - set(tables) - RUNTIME_TABLES),
        "excluded": export.get("excluded", {}),
        "attachments": export.get("attachments", []),
    }
    result["plan_hash"] = digest(result)
    return result


def model_snapshot(obj):
    from django.core.serializers.json import DjangoJSONEncoder

    snapshot = json.loads(
        json.dumps(
            {field.attname: getattr(obj, field.attname) for field in obj._meta.concrete_fields}, cls=DjangoJSONEncoder
        )
    )
    if obj._meta.label_lower == "quality.packagefile":
        from .attachments import directory

        path = directory() / obj.storage_key
        snapshot["_file_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return snapshot


def validate_targets(plan, actor):
    from plane.db.models import Project, User
    from .models import PlatformIdentity
    from .project_versions import is_manager

    projects = {}
    for key, pk in sorted(plan["mapping"].get("projects", {}).items()):
        project = Project.objects.select_for_update().get(pk=pk)
        if project.network != 0 or project.archived_at or not is_manager(project.id, actor):
            raise ValueError("Target must be an authorized active secret project")
        projects[str(key)] = project
    users = {}
    source = plan["mapping"].get("source_instance")
    if not source:
        raise ValueError("Explicit source-managed identity is required")
    for key, pk in plan["mapping"].get("users", {}).items():
        user = User.objects.get(pk=pk)
        if (
            not user.is_active
            or not PlatformIdentity.objects.filter(
                project__in=projects.values(), source_instance=source, external_user_id=int(key), user=user, active=True
            ).exists()
        ):
            raise ValueError("Source-managed user mapping is not verified")
        users[str(key)] = user
    return projects, users


def apply_plan(plan, actor):
    created_files = []
    try:
        return _apply_plan(plan, actor, created_files)
    except Exception:
        for path in created_files:
            path.unlink(missing_ok=True)
        raise


def preview_plan(plan, actor):
    from django.db import transaction

    created_files = []
    try:
        with transaction.atomic():
            result = _apply_plan(plan, actor, created_files, preview=True)
            transaction.set_rollback(True)
        return result
    finally:
        for path in created_files:
            path.unlink(missing_ok=True)


def _apply_plan(plan, actor, created_files, preview=False):
    from django.apps import apps
    from django.db import transaction, connection
    from .models import LegacyMigrationRun, LegacyMigrationRecord

    if plan.get("conflicts"):
        raise ValueError("Resolve all source conflicts before apply")
    if plan.get("plan_hash") != digest({key: value for key, value in plan.items() if key != "plan_hash"}):
        raise ValueError("Plan changed after review")
    if digest(plan["mapping"]) != plan["mapping_hash"]:
        raise ValueError("Plan mapping changed after review")
    for item in plan["rows"]:
        if item["source_hash"] != digest(item["snapshot"]):
            raise ValueError("Plan row changed after review")
    with transaction.atomic():
        with connection.cursor() as cursor:
            lock = int.from_bytes(hashlib.sha256(plan["source_key"].encode()).digest()[:8], "big", signed=True)
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock])
        projects, users = validate_targets(plan, actor)
        old = LegacyMigrationRun.objects.select_for_update().filter(source_key=plan["source_key"]).first()
        if old:
            if old.manifest_hash != plan["manifest_hash"] or old.mapping_hash != plan["mapping_hash"]:
                raise ValueError("Source or mapping changed; manual reconciliation required")
            if old.status != "applied":
                raise ValueError("This source run was rolled back; explicit new source revision is required")
            for record in old.records.all():
                for target in record.targets:
                    obj = apps.get_model(target["model"])._base_manager.filter(pk=target["id"]).first()
                    if obj is None or digest(model_snapshot(obj)) != target["sha256"]:
                        raise ValueError("Target changed after migration: " + target["model"])
            return {"run_id": str(old.id), "created_records": 0, "unchanged_records": old.records.count()}
        run = LegacyMigrationRun.objects.create(
            source_key=plan["source_key"],
            manifest_hash=plan["manifest_hash"],
            mapping_hash=plan["mapping_hash"],
            created_by=actor,
            summary={
                "counts": plan["counts"],
                "dispositions": plan["dispositions"],
                "excluded": plan["excluded"],
                "absent_tables": plan["absent_tables"],
                "mapping": plan["mapping"],
            },
        )
        importer = Importer(plan, projects, users, created_files, preview)
        importer.execute()
        for item in plan["rows"]:
            refs = importer.targets.get((item["table"], item["key"]), [])
            LegacyMigrationRecord.objects.create(
                id=stable_id(plan["source"], item["table"], item["key"], "audit"),
                run=run,
                source_table=item["table"],
                source_id=item["key"],
                source_hash=item["source_hash"],
                source_snapshot=importer.archived_snapshot(item),
                disposition=importer.dispositions.get((item["table"], item["key"]), item["disposition"]),
                targets=[
                    {
                        "model": obj._meta.label_lower,
                        "id": str(obj.pk),
                        "sha256": digest(model_snapshot(obj)),
                        "order": order,
                    }
                    for order, obj in refs
                ],
            )
        return {
            "run_id": str(run.id),
            "created_records": len(plan["rows"]),
            "unchanged_records": 0,
            "native_targets": importer.counter,
        }


class Importer:
    def __init__(self, plan, projects, users, created_files, preview=False):
        self.plan, self.projects, self.users = plan, projects, users
        self.created_files = created_files
        self.preview = preview
        self.index = {(item["table"], item["key"]): item for item in plan["rows"]}
        self.targets = {}
        self.objects = {}
        self.dispositions = {}
        self.counter = 0

    def row(self, table, key):
        return self.index.get((table, canonical([str(key)])), {}).get("snapshot", {})

    def related(self, table, key):
        return self.objects.get((table, canonical([str(key)])))

    def project(self, item):
        row = item["snapshot"]
        table = item["table"]
        key = row.get("project_id", row.get("source_project_id"))
        if key is None:
            ticket = row.get("ticket_id", row.get("issue_ticket_id", row.get("source_issue_id")))
            if ticket is not None:
                key = self.row("issue_tickets", ticket).get("project_id")
        if key is None and table == "problem_package_files":
            parent = self.row("problem_packages", row["package_id"])
            key = self.row("issue_tickets", parent["issue_ticket_id"]).get("project_id")
        if key is None and table == "knowledge_versions":
            draft = self.row("knowledge_drafts", row["source_draft_id"])
            key = self.row("issue_tickets", draft.get("source_issue_id")).get("project_id")
        if str(key) not in self.projects:
            raise ValueError("Native source scope has no explicit project mapping: " + table)
        return self.projects[str(key)]

    def author(self, row):
        for key in [
            "author_id",
            "operator_id",
            "reporter_id",
            "created_by_id",
            "created_by",
            "submitter_id",
            "uploader_id",
            "uploaded_by_id",
            "returned_by",
        ]:
            if row.get(key) is not None:
                if str(row[key]) not in self.users:
                    raise ValueError("Historical actor has no verified source mapping")
                return self.users[str(row[key])]
        return None

    def add(self, source_item, model, suffix="", **fields):
        from django.apps import apps
        from django.utils.dateparse import parse_datetime
        from django.utils import timezone
        from zoneinfo import ZoneInfo

        cls = apps.get_model(model)
        pk = stable_id(self.plan["source"], source_item["table"], source_item["key"], suffix)
        if cls._base_manager.filter(pk=pk).exists():
            raise ValueError("Target identity collision; refusing to adopt existing records")
        if any(f.name == "project" for f in cls._meta.fields):
            fields.setdefault("project", self.project(source_item))
        if any(f.name == "created_by" for f in cls._meta.fields):
            fields.setdefault("created_by", self.author(source_item["snapshot"]))
        obj = cls(id=pk, **fields)
        from plane.db.models.base import BaseModel

        obj.save(disable_auto_set_user=True) if isinstance(obj, BaseModel) else obj.save()
        stamp = source_item["snapshot"].get("created_at", source_item["snapshot"].get("source_created_at"))
        if stamp:
            parsed = parse_datetime(stamp)
            if parsed is None:
                raise ValueError("Invalid source timestamp")
            if timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed, ZoneInfo("Asia/Shanghai"))
            cls._base_manager.filter(pk=obj.pk).update(created_at=parsed)
            obj.refresh_from_db()
        obj.refresh_from_db()
        self.counter += 1
        self.targets.setdefault((source_item["table"], source_item["key"]), []).append((self.counter, obj))
        from .models import BusinessNumber

        for number in BusinessNumber.objects.filter(resource=obj._meta.label_lower, object_id=obj.pk):
            self.counter += 1
            self.targets[(source_item["table"], source_item["key"])].append((self.counter, number))
        if model == "db.Issue":
            from plane.db.models import IssueSequence

            for sequence in IssueSequence.objects.filter(issue=obj):
                self.counter += 1
                self.targets[(source_item["table"], source_item["key"])].append((self.counter, sequence))
        return obj

    def revision(self, item, case):
        return self.add(
            item,
            "quality.CaseRevision",
            "revision",
            case=case,
            version=1,
            title=case.title,
            snapshot={
                "title": case.title,
                "steps": case.steps,
                "preconditions": case.preconditions,
                "legacy_source": item["snapshot"],
            },
        )

    def execute(self):
        order = [
            "platform_task_mirrors",
            "embedded_test_cases",
            "issue_tickets",
            "feature_test_items",
            "embedded_test_tasks",
            "issue_solutions",
            "issue_comments",
            "issue_timeline_events",
            "issue_assignments",
            "feature_test_rounds",
            "embedded_test_executions",
            "embedded_test_suites",
            "embedded_requirements",
            "embedded_versions",
            "embedded_release_plans",
            "embedded_test_reports",
            "embedded_release_issues",
            "embedded_release_issue_records",
            "knowledge_drafts",
            "knowledge_versions",
            "embedded_test_resources",
            "problem_packages",
            "issue_attachments",
            "problem_package_files",
            "embedded_test_artifacts",
        ]
        for table in order:
            for item in self.plan["rows"]:
                if item["table"] == table and item["disposition"] == "native":
                    obj = self.convert(item)
                    if obj:
                        self.objects[(table, item["key"])] = obj
                    else:
                        self.dispositions[(table, item["key"])] = "archive_only"

    def convert(self, item):
        from django.utils import timezone

        row, table = item["snapshot"], item["table"]
        if table == "platform_task_mirrors":
            return self.add(
                item,
                "db.Issue",
                workspace=self.project(item).workspace,
                name=row["name"],
                description_html="<pre>" + __import__("html").escape(str(row.get("description") or "")) + "</pre>",
            )
        if table == "embedded_test_cases":
            steps = payload(row, "steps", [])
            if not isinstance(steps, list):
                raise ValueError("Case steps must be a list")
            obj = self.add(
                item,
                "quality.TestCase",
                title=row.get("scenario") or row["case_id"],
                module=row.get("module") or "",
                preconditions=row.get("prerequisites") or "",
                steps=steps,
                priority={"P0": "critical", "P1": "high", "P2": "medium", "P3": "low"}.get(
                    row.get("priority"), "medium"
                ),
                archived_at=None if row.get("enabled", True) else timezone.now(),
            )
            self.revision(item, obj)
            return obj
        if table == "issue_tickets":
            if row.get("ticket_type") == "FEATURE_TEST":
                return self.add(
                    item,
                    "quality.TestPlan",
                    name=row.get("title") or row["ticket_no"],
                    build="",
                    environment="历史迁移，待核对",
                    description=row.get("description") or "",
                    managed=False,
                    status="pending",
                )
            statuses = {
                "Open": "open",
                "PENDING_ACCEPTANCE": "open",
                "AGENT_ANALYZING": "open",
                "REOPENED": "open",
                "InProgress": "in_progress",
                "PROCESSING": "in_progress",
                "PENDING_REVIEW": "in_progress",
                "SOLUTION_APPROVED": "in_progress",
                "SOLUTION_REJECTED": "in_progress",
                "PENDING_MANAGER_ACCEPTANCE": "resolved",
                "REGRESSION_BLOCKED": "resolved",
                "PENDING_REGRESSION": "resolved",
                "REGRESSION_TESTING": "resolved",
                "Resolved": "resolved",
                "RESOLVED": "resolved",
                "Closed": "closed",
                "ARCHIVED": "closed",
                "CANCELLED": "open",
            }
            if row.get("status") not in statuses:
                raise ValueError("Unknown defect status requires explicit mapping")
            obj = self.add(
                item,
                "quality.Defect",
                title=row.get("title") or row["ticket_no"],
                description=row.get("description") or "",
                status=statuses[row["status"]],
                repair_issue=self.related("platform_task_mirrors", row.get("task_id")),
                assignee=self.users.get(str(row.get("assignee_id"))),
                archived_at=timezone.now() if row.get("status") in {"ARCHIVED", "CANCELLED"} else None,
            )
            self.add(
                item,
                "quality.SourceLink",
                "source",
                defect=obj,
                source_system="LEGACY_HUB",
                source_instance=self.plan["mapping"]["source_instance"],
                record_type="historical_issue",
                record_id=str(row["id"]),
                task_id=str(row.get("task_id") or ""),
                package_id=str(row.get("data_package_id") or ""),
            )
            self.add(
                item,
                "quality.DefectEvent",
                "migration",
                defect=obj,
                status=obj.status,
                note="历史迁移："
                + str(row.get("ticket_no"))
                + "；原状态 "
                + row["status"]
                + "，不代表本平台新数据验收。",
            )
            return obj
        if table == "feature_test_items":
            plan = self.related("issue_tickets", row["ticket_id"])
            if plan is None or plan._meta.model_name != "testplan":
                raise ValueError("Feature item must reference FEATURE_TEST ticket")
            case = self.add(
                item,
                "quality.TestCase",
                title=row["content"][:255],
                steps=[{"action": row["content"], "expected": "按原需求点验证"}],
            )
            revision = self.revision(item, case)
            self.add(item, "quality.PlanItem", "item", plan=plan, case=case, revision=revision)
            return case
        if table == "embedded_test_tasks":
            return self.add(
                item,
                "quality.TestPlan",
                name=row["name"],
                build="",
                environment="历史迁移，待核对",
                description=canonical(row.get("request_payload") or {}),
                managed=False,
                status="pending",
            )
        if table == "issue_solutions":
            defect = self.related("issue_tickets", row["issue_ticket_id"])
            if defect is None or defect._meta.model_name != "defect":
                return None
            solution = self.add(
                item,
                "quality.Solution",
                defect=defect,
                title="历史方案 " + str(row.get("solution_id") or row["id"]),
                root_cause=row.get("root_cause") or "",
                steps=row.get("solution_steps") or "",
                verification=row.get("verification_method") or "",
                risk=row.get("risk_description") or "",
                rollback=row.get("rollback_method") or "",
                repository=row.get("repository") or "",
                commit_sha=row.get("commit_sha") or "",
                status="draft",
            )
            self.add(
                item,
                "quality.SolutionRevision",
                "revision",
                solution=solution,
                version=1,
                snapshot={**row, "legacy_status": row.get("status")},
                reviewer_ids=[],
                required_count=1,
            )
            return solution
        if table in {"issue_comments", "issue_timeline_events", "issue_assignments", "feature_test_rounds"}:
            parent = self.related("issue_tickets", row["ticket_id"])
            if row.get("deleted_at") or row.get("comment_type") == "INTERNAL_NOTE":
                return None
            if parent._meta.model_name == "defect":
                if table == "issue_comments":
                    return self.add(item, "quality.DefectComment", defect=parent, content=row["content"])
                return self.add(
                    item,
                    "quality.DefectEvent",
                    defect=parent,
                    status=parent.status,
                    note=str(row.get("summary") or row.get("note") or row.get("reason") or canonical(row)),
                )
            return self.add(
                item,
                "quality.PlanEvent",
                plan=parent,
                action="migration",
                previous_status="",
                status=parent.status,
                round_no=int(row.get("round_no") or 1),
                note=str(row.get("summary") or row.get("content") or row.get("reason") or canonical(row)),
            )
        if table == "embedded_test_executions":
            plan = self.related("embedded_test_tasks", row["task_id"])
            case = self.find_case(row.get("case_id"), row["project_id"])
            if not case:
                raise ValueError("Execution case is missing or ambiguous")
            from .models import PlanItem

            link = PlanItem.objects.filter(plan=plan, case=case).first()
            if not link:
                link = self.add(
                    item, "quality.PlanItem", "item", plan=plan, case=case, revision=case.revisions.get(version=1)
                )
            result = {"PASSED": "passed", "FAILED": "failed", "BLOCKED": "blocked", "SKIPPED": "skipped"}.get(
                row.get("result", "").upper()
            )
            if not result:
                return None
            data = payload(row, "payload", {}) or {}
            return self.add(
                item,
                "quality.TestExecution",
                item=link,
                request_id=item["id"],
                result=result,
                actual_result=str(data.get("actual_result") or ""),
                evidence="历史执行快照；不作为新数据回归证据。",
                resource_snapshot={"legacy": row},
            )
        if table == "embedded_test_suites":
            suite = self.add(
                item, "quality.TestSuite", name=row["name"], description=row.get("description") or "", published=False
            )
            for index, key in enumerate(payload(row, "case_ids", []) or []):
                case = self.find_case(key, row["project_id"])
                if not case:
                    raise ValueError("Suite case is missing or ambiguous")
                self.add(
                    item,
                    "quality.SuiteItem",
                    str(index),
                    suite=suite,
                    case=case,
                    revision=case.revisions.get(version=1),
                )
            return suite
        if table == "embedded_requirements":
            issue = self.add(
                item,
                "db.Issue",
                "issue",
                workspace=self.project(item).workspace,
                name=row["title"],
                description_html="<pre>" + __import__("html").escape(row.get("description") or "") + "</pre>",
            )
            requirement = self.add(
                item,
                "quality.Requirement",
                issue=issue,
                acceptance=canonical(row.get("source_payload") or {}),
                status="draft",
            )
            self.add(
                item,
                "quality.RequirementRevision",
                "revision",
                requirement=requirement,
                version=1,
                snapshot={"status": "draft", "title": row["title"], "legacy": row},
            )
            return requirement
        if table == "embedded_versions":
            return self.add(
                item,
                "quality.ProjectVersion",
                name=row["name"],
                version=row["version_key"],
                description=row.get("description") or "",
                status="planning",
                target_date=row.get("release_date"),
                automation_enabled=False,
            )
        if table == "embedded_release_plans":
            return self.add(
                item,
                "quality.Release",
                name=row["name"],
                version=row["plan_key"],
                description=row.get("description") or "",
                status="draft",
            )
        if table == "embedded_test_reports":
            return self.add(
                item,
                "quality.SavedReport",
                name=row["name"],
                plan=self.related("embedded_test_tasks", row.get("task_id")),
                request_id=item["id"],
                request_hash=item["source_hash"],
                snapshot={"legacy_import": True, "source": row},
            )
        if table == "embedded_release_issues":
            if row.get("issue_ticket_id") is not None:
                return None
            return self.add(
                item,
                "quality.Defect",
                title=row["title"],
                status="open",
                description=canonical(row.get("payload_json") or {}),
            )
        if table == "embedded_release_issue_records":
            parentrow = self.row("embedded_release_issues", row["issue_id"])
            defect = self.related("embedded_release_issues", row["issue_id"]) or self.related(
                "issue_tickets", parentrow.get("issue_ticket_id")
            )
            if defect is None:
                return None
            return self.add(item, "quality.DefectComment", defect=defect, content=row["content"])
        if table == "knowledge_drafts":
            content = row.get("content") or canonical(row)
            return self.add(
                item,
                "knowledge.Article",
                title=row.get("title") or "历史知识",
                content="历史知识迁移，待扫描审核：\n" + content,
                tags=["旧库迁移", "待复核"],
                status="draft",
                publication_active=False,
                source_defect=self.related("issue_tickets", row.get("source_issue_id")),
            )
        if table == "knowledge_versions":
            article = self.related("knowledge_drafts", row["source_draft_id"])
            return self.add(
                item,
                "knowledge.PublishedRevision",
                article=article,
                version=int(row["version_no"]),
                title=row["title"],
                content="历史发布版本，未在新平台发布：\n" + str(row.get("content_snapshot") or canonical(row)),
                tags=["旧库历史"],
            )
        if table == "embedded_test_resources":
            return self.add(
                item,
                "quality.TestResource",
                name=row["name"],
                kind=str(row.get("resource_type") or "other")[:32],
                description=canonical(row.get("payload_json") or {}),
                status="available",
                source_instance=self.plan["mapping"]["source_instance"],
                external_id=str(row["id"]),
            )
        if table == "problem_packages":
            defect = self.related("issue_tickets", row["issue_ticket_id"])
            if defect is None or defect._meta.model_name != "defect":
                return None
            return self.add(
                item,
                "quality.ProblemPackage",
                defect=defect,
                name=row["title"],
                source_system="LEGACY_HUB",
                external_id=str(row["id"]),
                manifest_hash=item["source_hash"],
                files=[],
                status="historical",
            )
        if table in {"issue_attachments", "problem_package_files", "embedded_test_artifacts"}:
            return self.file(item)
        return None

    def find_case(self, key, project):
        values = [
            self.related("embedded_test_cases", row["snapshot"]["id"])
            for row in self.plan["rows"]
            if row["table"] == "embedded_test_cases"
            and str(row["snapshot"]["project_id"]) == str(project)
            and str(row["snapshot"]["case_id"]) == str(key)
        ]
        return values[0] if len(values) == 1 else None

    def archived_snapshot(self, item):
        if item["table"] not in FILE_TABLES:
            return item["snapshot"]
        attachment = next(
            (
                row
                for row in self.plan["attachments"]
                if row.get("table") == item["table"] and str(row.get("id")) == str(item["snapshot"].get("id"))
            ),
            None,
        )
        return {
            "row": item["snapshot"],
            "attachment": attachment,
            "restored": (item["table"], item["key"]) in self.targets,
        }

    def file(self, item):
        from pathlib import PurePosixPath
        from .attachments import directory

        row = item["snapshot"]
        table = item["table"]
        if table == "problem_package_files":
            package = self.related("problem_packages", row["package_id"])
        else:
            defect = self.related("issue_tickets", row.get("ticket_id", row.get("issue_id")))
            if defect is None or defect._meta.model_name != "defect":
                self.dispositions[(table, item["key"])] = "archive_verified_file"
                return None
            package = self.add(
                item,
                "quality.ProblemPackage",
                "package",
                defect=defect,
                name="历史附件",
                source_system="LEGACY_HUB",
                external_id=table + ":" + str(row["id"]),
                manifest_hash=item["source_hash"],
                files=[],
                status="historical",
            )
        if package is None:
            self.dispositions[(table, item["key"])] = "archive_verified_file"
            return None
        entry = next(
            row
            for row in self.plan["attachments"]
            if row.get("table") == table and str(row.get("id")) == str(item["snapshot"]["id"])
        )
        raw = base64.b64decode(entry["base64"], validate=True)
        name = str(row.get("file_name", row.get("filename", "attachment")))
        if PurePosixPath(name).name != name or "\\" in name or name in {".", ".."}:
            raise ValueError("Unsafe attachment name")
        storage = "legacy-import/" + item["id"] + "/" + name
        path = directory() / storage
        if path.exists():
            raise ValueError("Target private attachment path already exists")
        if not self.preview:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with path.open("xb") as handle:
                handle.write(raw)
            self.created_files.append(path)
        return self.add(
            item,
            "quality.PackageFile",
            package=package,
            name=name,
            size=len(raw),
            sha256=entry["sha256"],
            storage_key=storage,
        )


def rollback(run_id, actor):
    from django.apps import apps
    from django.db import transaction
    from django.db.models.deletion import get_candidate_relations_to_delete
    from django.utils import timezone
    from .models import LegacyMigrationRun

    with transaction.atomic():
        run = LegacyMigrationRun.objects.select_for_update().get(pk=run_id)
        if run.created_by_id != actor.id:
            raise ValueError("Only the migration owner can rollback")
        if run.status == "rolled_back":
            return {"run_id": str(run.id), "status": "rolled_back", "removed": 0}
        validate_targets({"mapping": run.summary["mapping"]}, actor)
        targets = [target for record in run.records.all() for target in record.targets]
        allowed = {}
        objects = []
        for target in targets:
            cls = apps.get_model(target["model"])
            obj = cls._base_manager.select_for_update().filter(pk=target["id"]).first()
            if obj is None or digest(model_snapshot(obj)) != target["sha256"]:
                raise ValueError("Target changed after migration; rollback refused: " + target["model"])
            allowed.setdefault(cls._meta.label_lower, set()).add(obj.pk)
            objects.append((target["order"], obj))
        for _, obj in objects:
            for relation in get_candidate_relations_to_delete(obj._meta):
                cls = relation.related_model
                external = cls._base_manager.filter(**{relation.field.attname: obj.pk}).exclude(
                    pk__in=allowed.get(cls._meta.label_lower, set())
                )
                if external.exists():
                    raise ValueError("New dependent records exist; rollback refused")
        from django.db import models

        for _, obj in sorted(objects, key=lambda pair: pair[0], reverse=True):
            if obj._meta.label_lower == "quality.packagefile":
                from .attachments import directory

                path = directory() / obj.storage_key
                transaction.on_commit(lambda path=path: path.unlink(missing_ok=True))
            models.Model.delete(obj)
        run.status = "rolled_back"
        run.rolled_back_at = timezone.now()
        run.save(update_fields=["status", "rolled_back_at"])
        return {"run_id": str(run.id), "status": run.status, "removed": len(objects)}
