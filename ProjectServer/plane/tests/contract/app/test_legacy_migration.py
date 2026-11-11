"""Offline migration plans fail closed and rollback only unmodified imported graphs."""

import pytest
from plane.db.models import Project, ProjectMember
from plane.quality.models import PlatformIdentity, Defect, TestCase, TestPlan, TestExecution
from plane.quality.legacy_migration import build_plan, digest

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def snapshot():
    tables = {
        "platform_project_mirrors": [{"source_project_id": 9, "name": "旧项目", "status": "ACTIVE"}],
        "project_hub_users": [
            {
                "id": 1,
                "username": "old-user",
                "display_name": "历史人员",
                "active": 1,
                "primary_role": "PROJECT_MANAGER",
            }
        ],
        "platform_task_mirrors": [
            {
                "source_task_id": 24,
                "source_project_id": 9,
                "name": "旧任务",
                "description": "任务说明",
                "status": "InProgress",
            }
        ],
        "issue_tickets": [
            {
                "id": 4,
                "ticket_no": "TK-OLD-1",
                "project_id": 9,
                "task_id": 24,
                "ticket_type": "EXCEPTION",
                "reporter_id": 1,
                "assignee_id": 1,
                "title": "历史连接故障",
                "description": "旧问题说明",
                "status": "PROCESSING",
            }
        ],
        "issue_solutions": [
            {
                "id": 6,
                "issue_ticket_id": 4,
                "solution_id": "SOL-OLD",
                "version_no": 1,
                "status": "APPROVED",
                "root_cause": "监听未启动",
                "solution_steps": "启动监听",
                "verification_method": "新Session",
                "author_id": 1,
            }
        ],
        "issue_comments": [
            {"id": 7, "ticket_id": 4, "author_id": 1, "content": "真实历史评论", "comment_type": "COMMENT"}
        ],
        "issue_timeline_events": [
            {"id": 8, "ticket_id": 4, "operator_id": 1, "summary": "已分派处理", "event_type": "ASSIGNEE_SET"}
        ],
        "embedded_test_cases": [
            {
                "id": 10,
                "project_id": 9,
                "case_id": "C-OLD",
                "scenario": "连接验证",
                "prerequisites": "服务运行",
                "steps": [{"action": "连接", "expected": "正常"}],
                "expected_result": "正常",
                "priority": "P1",
                "enabled": 1,
                "created_by": 1,
            }
        ],
        "embedded_test_tasks": [
            {"id": 11, "project_id": 9, "name": "旧测试计划", "status": "COMPLETED", "created_by_id": 1}
        ],
        "embedded_test_executions": [
            {
                "id": 12,
                "project_id": 9,
                "task_id": 11,
                "case_id": "C-OLD",
                "result": "PASSED",
                "payload": {"actual_result": "连接正常"},
                "created_by": 1,
            }
        ],
        "embedded_test_suites": [
            {
                "id": 13,
                "project_id": 9,
                "suite_key": "suite-old",
                "version": 1,
                "name": "旧套件",
                "description": "套件说明",
                "case_ids": ["C-OLD"],
                "status": "published",
                "created_by": 1,
            }
        ],
        "embedded_requirements": [
            {
                "id": 14,
                "project_id": 9,
                "requirement_key": "REQ-OLD",
                "title": "旧需求",
                "description": "需求说明",
                "status": "APPROVED",
                "created_by": 1,
            }
        ],
        "embedded_versions": [
            {"id": 15, "project_id": 9, "version_key": "v-old", "name": "旧版本", "status": "RELEASED", "created_by": 1}
        ],
        "embedded_release_plans": [
            {"id": 16, "project_id": 9, "plan_key": "rel-old", "name": "旧发布", "status": "RELEASED", "created_by": 1}
        ],
        "embedded_test_reports": [
            {
                "id": 17,
                "project_id": 9,
                "task_id": 11,
                "name": "旧报告",
                "report_payload": {"conclusion": "passed"},
                "created_by": 1,
            }
        ],
        "regression_tests": [
            {
                "id": 18,
                "issue_ticket_id": 4,
                "solution_id": 6,
                "regression_id": "REG-OLD",
                "round_no": 1,
                "status": "PASSED",
                "created_by_id": 1,
            }
        ],
    }
    return {
        "schema": "hub-full-export-v1",
        "source": {"host": "isolated-fixture", "database": "project_hub_fixture", "source_verified": True},
        "tables": tables,
        "counts": {k: len(v) for k, v in tables.items()},
        "table_sha256": {k: digest(v) for k, v in tables.items()},
        "attachments": [],
    }


@pytest.fixture
def target(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="隔离迁移", identifier="MIG", network=0)
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    PlatformIdentity.objects.create(
        project=project, created_by=create_user, source_instance="legacy-fixture", external_user_id=1, user=create_user
    )
    mapping = {
        "projects": {"9": str(project.id)},
        "users": {"1": str(create_user.id)},
        "source_instance": "legacy-fixture",
    }
    return project, create_user, mapping


def test_apply_atomic_idempotent_source_change_and_user_edit_rollback_guards(target):
    from plane.quality.legacy_migration import apply_plan, rollback
    from plane.quality.models import LegacyMigrationRun

    project, user, mapping = target
    plan = build_plan(snapshot(), mapping)
    assert not plan["conflicts"]
    first = apply_plan(plan, user)
    assert first["created_records"] == 16
    assert Defect.objects.get().title == "历史连接故障"
    assert TestCase.objects.count() == 1 and TestPlan.objects.count() == 1 and TestExecution.objects.count() == 1
    assert Defect.objects.get().sources.count() == 1
    second = apply_plan(plan, user)
    assert second["unchanged_records"] == 16
    changed = snapshot()
    changed["tables"]["issue_tickets"][0]["description"] = "源已更改"
    changed["table_sha256"]["issue_tickets"] = digest(changed["tables"]["issue_tickets"])
    with pytest.raises(ValueError, match="changed"):
        apply_plan(build_plan(changed, mapping), user)
    defect = Defect.objects.get()
    defect.title = "用户后续编辑"
    defect.save()
    with pytest.raises(ValueError, match="changed"):
        rollback(first["run_id"], user)
    assert LegacyMigrationRun.objects.get().status == "applied" and Defect.objects.exists()


def test_clean_rollback_removes_only_this_run_and_preserves_existing_project_account(target):
    from plane.quality.legacy_migration import apply_plan, rollback
    from plane.quality.models import LegacyMigrationRun

    project, user, mapping = target
    result = apply_plan(build_plan(snapshot(), mapping), user)
    rolled = rollback(result["run_id"], user)
    assert rolled["status"] == "rolled_back"
    assert not Defect.objects.exists() and not TestCase.objects.exists()
    assert Project.objects.filter(pk=project.id).exists() and PlatformIdentity.objects.filter(user=user).exists()
    assert LegacyMigrationRun.objects.get().records.count() == 16


def test_plan_rejects_unknown_sensitive_orphan_hash_and_missing_file(target):
    project, user, mapping = target
    for table, field, value in [
        ("issue_tickets", "unexpected", "x"),
        ("project_hub_users", "password_hash", "synthetic"),
        ("issue_comments", "ticket_id", 999),
    ]:
        source = snapshot()
        source["tables"][table][0][field] = value
        source["table_sha256"][table] = digest(source["tables"][table])
        assert build_plan(source, mapping)["conflicts"]
    source = snapshot()
    source["tables"]["issue_attachments"] = [
        {
            "id": 30,
            "ticket_id": 4,
            "file_name": "missing.log",
            "file_path": "/missing",
            "file_size": 5,
            "uploader_id": 1,
        }
    ]
    source["counts"]["issue_attachments"] = 1
    source["table_sha256"]["issue_attachments"] = digest(source["tables"]["issue_attachments"])
    assert build_plan(source, mapping)["conflicts"]
    plan = build_plan(source, {**mapping, "allow_missing_attachment_metadata": True})
    assert not plan["conflicts"] and plan["dispositions"]["archive_missing_file"] == 1


def with_attachment(source, raw=b"isolated legacy diagnostic log\n"):
    import base64
    import hashlib

    values = [
        {
            "id": 30,
            "ticket_id": 4,
            "file_name": "history.log",
            "file_path": "/old/private/history.log",
            "file_size": len(raw),
            "uploader_id": 1,
        }
    ]
    source["tables"]["issue_attachments"] = values
    source["counts"]["issue_attachments"] = 1
    source["table_sha256"]["issue_attachments"] = digest(values)
    source["attachments"] = [
        {
            "table": "issue_attachments",
            "id": "30",
            "verified": True,
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "base64": base64.b64encode(raw).decode(),
            "media": "text",
        }
    ]
    return source


def test_verified_attachment_bytes_import_and_file_change_blocks_rollback(target, settings, tmp_path):
    from plane.quality.legacy_migration import apply_plan, rollback
    from plane.quality.models import PackageFile

    settings.QUALITY_ATTACHMENT_ROOT = str(tmp_path)
    project, user, mapping = target
    source = with_attachment(snapshot())
    plan = build_plan(source, mapping)
    assert not plan["conflicts"]
    run = apply_plan(plan, user)
    file = PackageFile.objects.get()
    stored = tmp_path / file.storage_key
    assert stored.read_bytes() == b"isolated legacy diagnostic log\n"
    stored.write_text("user changed file")
    with pytest.raises(ValueError, match="changed"):
        rollback(run["run_id"], user)
    assert PackageFile.objects.exists()


def test_partial_apply_failure_is_atomic_and_cleans_new_files(target, settings, tmp_path):
    from plane.quality.legacy_migration import apply_plan
    from plane.quality.models import LegacyMigrationRun

    project, user, mapping = target
    settings.QUALITY_ATTACHMENT_ROOT = str(tmp_path)
    source = with_attachment(snapshot())
    bad = {
        "id": 31,
        "package_id": 999,
        "file_name": "bad.log",
        "file_path": "/old/bad",
        "file_size_bytes": 4,
        "uploaded_by_id": 1,
    }
    source["tables"]["problem_package_files"] = [bad]
    source["counts"]["problem_package_files"] = 1
    source["table_sha256"]["problem_package_files"] = digest([bad])
    plan = build_plan(source, mapping)
    assert plan["conflicts"]
    with pytest.raises(ValueError):
        apply_plan(plan, user)
    assert not LegacyMigrationRun.objects.exists() and not Defect.objects.exists()


def test_new_dependency_blocks_entire_rollback(target):
    from plane.quality.legacy_migration import apply_plan, rollback
    from plane.quality.models import DefectComment

    project, user, mapping = target
    run = apply_plan(build_plan(snapshot(), mapping), user)
    comment = DefectComment.objects.create(
        project=project, created_by=user, defect=Defect.objects.get(), content="迁移后用户新增"
    )
    with pytest.raises(ValueError, match="dependent"):
        rollback(run["run_id"], user)
    assert Defect.objects.exists() and DefectComment.objects.filter(pk=comment.id).exists()


def complete_snapshot():
    source = with_attachment(snapshot())
    extra = {
        "issue_tickets": [
            {
                "id": 41,
                "ticket_no": "FT-OLD",
                "project_id": 9,
                "ticket_type": "FEATURE_TEST",
                "reporter_id": 1,
                "title": "功能测试单",
                "description": "旧功能测试",
                "status": "TEST_PASSED",
            }
        ],
        "feature_test_items": [
            {
                "id": 42,
                "ticket_id": 41,
                "project_id": 9,
                "item_no": 1,
                "content": "功能需求点",
                "status": "PASSED",
                "created_by_id": 1,
            }
        ],
        "feature_test_rounds": [{"id": 43, "ticket_id": 41, "round_no": 1, "reason": "历史退回", "returned_by": 1}],
        "embedded_release_issues": [
            {"id": 44, "project_id": 9, "title": "发布问题", "status": "CLOSED", "created_by": 1}
        ],
        "embedded_release_issue_records": [
            {"id": 45, "project_id": 9, "issue_id": 44, "content": "发布问题历史", "created_by": 1}
        ],
        "knowledge_drafts": [
            {
                "id": 46,
                "draft_id": "DRAFT-OLD",
                "source_issue_id": 4,
                "source_solution_id": 6,
                "source_regression_id": 18,
                "title": "历史知识",
                "content": "历史故障解决过程",
                "status": "PUBLISHED",
                "created_by": 1,
            }
        ],
        "knowledge_versions": [
            {
                "id": 47,
                "source_draft_id": 46,
                "version_no": 1,
                "title": "历史知识v1",
                "content_snapshot": "历史发布内容",
            }
        ],
        "embedded_test_resources": [
            {
                "id": 48,
                "project_id": 9,
                "name": "历史资源",
                "resource_type": "device",
                "status": "BUSY",
                "created_by": 1,
            }
        ],
        "problem_packages": [
            {"id": 49, "issue_ticket_id": 4, "title": "历史问题包", "status": "ANALYZED", "submitter_id": 1}
        ],
        "issue_assignments": [{"id": 50, "ticket_id": 4, "action": "REASSIGN", "note": "历史转派", "operator_id": 1}],
        "project_review_policies": [
            {
                "id": 51,
                "project_id": 9,
                "policy_name": "历史审核策略",
                "subject_type": "SOLUTION",
                "decision_mode": "ALL",
                "required_count": 1,
                "reviewer_user_ids": [1],
                "active": 1,
            }
        ],
        "issue_review_tasks": [
            {
                "id": 52,
                "ticket_id": 4,
                "solution_id": 6,
                "policy_id": 51,
                "decision_mode": "ALL",
                "required_count": 1,
                "status": "APPROVED",
            }
        ],
        "issue_review_assignments": [
            {"id": 53, "review_task_id": 52, "reviewer_id": 1, "reviewer_name": "历史人员", "decision": "APPROVE"}
        ],
        "issue_members": [{"id": 54, "ticket_id": 4, "user_id": 1, "user_name": "历史人员", "role": "COLLABORATOR"}],
        "agent_analysis_tasks": [
            {"id": 55, "package_id": 49, "issue_ticket_id": 4, "status": "COMPLETED", "task_no": "AT-OLD"}
        ],
        "agent_reports": [
            {
                "id": 56,
                "package_id": 49,
                "issue_ticket_id": 4,
                "task_id": 55,
                "report_no": "AR-OLD",
                "report_json": {"answer": "历史报告"},
            }
        ],
    }
    for table, rows in extra.items():
        source["tables"].setdefault(table, []).extend(rows)
    from plane.quality.legacy_migration import SCHEMA, RUNTIME_TABLES

    for table in set(SCHEMA) - RUNTIME_TABLES:
        source["tables"].setdefault(table, [])
    source["counts"] = {k: len(v) for k, v in source["tables"].items()}
    source["table_sha256"] = {k: digest(v) for k, v in source["tables"].items()}
    return source


def test_complete_source_fixture_native_and_archive_coverage_is_explicit(target, settings, tmp_path):
    from plane.quality.legacy_migration import apply_plan, rollback
    from plane.quality.models import LegacyMigrationRun, LegacyMigrationRecord, DaqReport, DataRegression, SourceLink
    from plane.knowledge.models import Article

    project, user, mapping = target
    settings.QUALITY_ATTACHMENT_ROOT = str(tmp_path)
    source = complete_snapshot()
    plan = build_plan(source, mapping)
    assert not plan["conflicts"], plan["conflicts"]
    assert not plan["absent_tables"]
    result = apply_plan(plan, user)
    assert result["created_records"] == sum(source["counts"].values())
    assert not DaqReport.objects.exists() and not DataRegression.objects.exists()
    article = Article.objects.get()
    assert article.status == "draft" and article.publication_active is False
    assert LegacyMigrationRecord.objects.get(source_table="regression_tests").disposition == "archive_only"
    assert LegacyMigrationRecord.objects.get(source_table="issue_review_tasks").source_snapshot["status"] == "APPROVED"
    assert LegacyMigrationRecord.objects.get(source_table="agent_reports").disposition == "archive_only"
    assert all(link.source_system == "LEGACY_HUB" for link in SourceLink.objects.all())
    assert apply_plan(plan, user)["unchanged_records"] == result["created_records"]
    assert rollback(result["run_id"], user)["status"] == "rolled_back"
    assert (
        not Article.objects.exists() and LegacyMigrationRun.objects.get().records.count() == result["created_records"]
    )


def test_dry_run_validates_native_graph_without_persisting_or_restoring_bytes(target, settings, tmp_path):
    from plane.quality.legacy_migration import preview_plan
    from plane.quality.models import LegacyMigrationRun, PackageFile, BusinessNumber

    project, user, mapping = target
    settings.QUALITY_ATTACHMENT_ROOT = str(tmp_path)
    result = preview_plan(build_plan(complete_snapshot(), mapping), user)
    assert result["created_records"] > 20 and not LegacyMigrationRun.objects.exists()
    assert not Defect.objects.exists() and not PackageFile.objects.exists() and not BusinessNumber.objects.exists()
    assert not list(tmp_path.rglob("*.log"))


def test_composite_source_identity_runtime_exclusion_and_cross_project_reference(target):

    project, user, mapping = target
    source = snapshot()
    source["tables"]["platform_user_id_mappings"] = [
        {"source_system": "data_platform", "source_user_id": 99, "project_hub_user_id": 1, "status": "VERIFIED"}
    ]
    source["counts"]["platform_user_id_mappings"] = 1
    source["table_sha256"]["platform_user_id_mappings"] = digest(source["tables"]["platform_user_id_mappings"])
    plan = build_plan(source, mapping)
    assert (
        not plan["conflicts"]
        and len(next(row for row in plan["rows"] if row["table"] == "platform_user_id_mappings")["key"]) > 1
    )
    source["tables"]["issue_tickets"][0]["project_id"] = 10
    source["table_sha256"]["issue_tickets"] = digest(source["tables"]["issue_tickets"])
    source["tables"]["embedded_test_executions"][0]["project_id"] = 10
    source["table_sha256"]["embedded_test_executions"] = digest(source["tables"]["embedded_test_executions"])
    assert any(
        row["code"] == "cross_project_reference"
        for row in build_plan(source, {**mapping, "projects": {**mapping["projects"], "10": str(project.id)}})[
            "conflicts"
        ]
    )


def test_in_transaction_failure_removes_prior_objects_and_restored_file(target, settings, tmp_path, mocker):
    from plane.quality.legacy_migration import apply_plan
    from plane.quality.models import LegacyMigrationRecord, LegacyMigrationRun, PackageFile

    project, user, mapping = target
    settings.QUALITY_ATTACHMENT_ROOT = str(tmp_path)
    mocker.patch.object(LegacyMigrationRecord.objects, "create", side_effect=ValueError("synthetic audit failure"))
    with pytest.raises(ValueError, match="synthetic"):
        apply_plan(build_plan(with_attachment(snapshot()), mapping), user)
    assert not LegacyMigrationRun.objects.exists() and not PackageFile.objects.exists() and not Defect.objects.exists()
    assert not list(tmp_path.rglob("*.log"))
