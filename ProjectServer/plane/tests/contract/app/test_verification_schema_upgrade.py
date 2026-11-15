"""Upgrading an already-applied early 0055 must repair physical legacy-link columns."""

from importlib import import_module
from uuid import uuid4

import pytest
from django.apps import apps
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from plane.db.models import Project
from plane.quality.models import (
    CaseRevision,
    Defect,
    DefectVerification,
    DefectVerificationCase,
    DefectVerificationCaseExecution,
    PlanItem,
    TestCase,
    TestExecution,
    TestPlan,
)

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]

LINKS = (
    (DefectVerificationCase, "source_plan_item", "quality_verification_legacy_plan_item_unique"),
    (DefectVerificationCaseExecution, "source_execution", "quality_verification_legacy_execution_unique"),
)


def table_columns(model):
    with connection.cursor() as cursor:
        return {column.name for column in connection.introspection.get_table_description(cursor, model._meta.db_table)}


def table_constraints(model):
    with connection.cursor() as cursor:
        return connection.introspection.get_constraints(cursor, model._meta.db_table)


def restore_test_schema():
    """Keep this isolated test database usable even when a deliberately broken repair fails."""
    with connection.schema_editor() as editor:
        for model, name, constraint_name in LINKS:
            field = model._meta.get_field(name)
            if field.column not in table_columns(model):
                editor.add_field(model, field)
            if constraint_name not in table_constraints(model):
                constraint = next(value for value in model._meta.constraints if value.name == constraint_name)
                editor.add_constraint(model, constraint)


@pytest.fixture
def upgrade_records(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="验证升级兼容", identifier="VUPGRADE")
    case = TestCase.objects.create(project=project, created_by=create_user, title="保留公共定义", steps=[])
    revision = CaseRevision.objects.create(
        project=project,
        created_by=create_user,
        case=case,
        version=1,
        title=case.title,
        snapshot={"title": case.title, "steps": []},
    )
    plan = TestPlan.objects.create(
        project=project, created_by=create_user, name="保留旧计划", build="v2", environment="隔离升级测试"
    )
    legacy_item = PlanItem.objects.create(
        project=project, created_by=create_user, plan=plan, case=case, revision=revision
    )
    legacy_execution = TestExecution.objects.create(
        project=project,
        created_by=create_user,
        item=legacy_item,
        request_id=uuid4(),
        result="passed",
        actual_result="原有执行结果",
    )
    defect = Defect.objects.create(
        project=project,
        created_by=create_user,
        title="旧部署已有缺陷",
        status="resolved",
        fixed_build="v2",
        resolved_at=timezone.now(),
    )
    verification = DefectVerification.objects.create(
        project=project,
        created_by=create_user,
        defect=defect,
        plan=plan,
        round_no=1,
        version=1,
        mode="cases",
        status="testing",
        fixed_build="v2",
        environment="隔离升级测试",
        resolved_at=defect.resolved_at,
        request_id=uuid4(),
        request_hash="old-round",
    )
    frozen = DefectVerificationCase.objects.create(
        project=project,
        created_by=create_user,
        verification=verification,
        source_case=case,
        source_revision=revision,
        source="library",
        title=revision.title,
        snapshot=revision.snapshot,
    )
    execution = DefectVerificationCaseExecution.objects.create(
        project=project,
        created_by=create_user,
        item=frozen,
        request_id=uuid4(),
        request_hash="old-execution",
        result="passed",
        actual_result="原有轮次结果不可丢失",
    )
    return project, verification, frozen, execution, legacy_item, legacy_execution, create_user


@pytest.mark.parametrize(
    "missing_fields,missing_constraints",
    [((), ()), ((0,), ()), ((1,), ()), ((0, 1), ()), ((), (0, 1))],
    ids=["fresh", "missing-item", "missing-execution", "early-0055", "missing-uniqueness"],
)
def test_forward_repair_preserves_rows_and_restores_legacy_fk_uniqueness(
    upgrade_records, missing_fields, missing_constraints
):
    migration = import_module("plane.quality.migrations.0056_verification_legacy_link_schema")
    project, verification, frozen, execution, legacy_item, legacy_execution, actor = upgrade_records
    previous_ids = (frozen.pk, execution.pk)

    try:
        # Simulate a deployment where the early 0055 was recorded as applied,
        # before its file gained source links. Merely running normal migrate on
        # the subsequently revised 0055 cannot add these absent columns.
        with connection.schema_editor() as editor:
            for index in missing_constraints:
                model, _, constraint_name = LINKS[index]
                constraint = next(value for value in model._meta.constraints if value.name == constraint_name)
                editor.remove_constraint(model, constraint)
            for index in missing_fields:
                model, name, _ = LINKS[index]
                editor.remove_field(model, model._meta.get_field(name))
        for index in missing_fields:
            model, name, _ = LINKS[index]
            assert model._meta.get_field(name).column not in table_columns(model)
        for index in missing_constraints:
            model, _, constraint_name = LINKS[index]
            assert constraint_name not in table_constraints(model)

        with connection.schema_editor() as editor:
            migration.ensure_legacy_links(apps, editor)

        frozen.refresh_from_db()
        execution.refresh_from_db()
        assert (frozen.pk, execution.pk) == previous_ids
        assert frozen.title == "保留公共定义"
        assert execution.actual_result == "原有轮次结果不可丢失"
        assert execution.created_by_id == actor.pk
        assert execution.item_id == frozen.pk
        assert frozen.source_plan_item_id is None and execution.source_execution_id is None

        for model, name, constraint_name in LINKS:
            field = model._meta.get_field(name)
            constraints = table_constraints(model)
            assert field.column in table_columns(model)
            assert constraints[constraint_name]["unique"]
            assert constraints[constraint_name]["columns"] == [field.column]
            assert any(
                value.get("foreign_key") == (field.target_field.model._meta.db_table, field.target_field.column)
                and value["columns"] == [field.column]
                for value in constraints.values()
            )

        frozen.source_plan_item = legacy_item
        frozen.save(update_fields=["source_plan_item"])
        execution.source_execution = legacy_execution
        execution.save(update_fields=["source_execution"])
        # A new private case and execution are exactly the write path that
        # previously failed with UndefinedColumn in the deployed platform.
        private = DefectVerificationCase.objects.create(
            project=project,
            created_by=actor,
            verification=verification,
            source="round",
            title="升级后补充的临时用例",
            snapshot={"title": "升级后补充的临时用例", "steps": [{"action": "检查", "expected": "正常"}]},
        )
        recorded = DefectVerificationCaseExecution.objects.create(
            project=project,
            created_by=actor,
            item=private,
            request_id=uuid4(),
            request_hash="after-upgrade",
            result="passed",
            actual_result="升级后可执行",
        )
        assert recorded.item_id == private.pk

        with pytest.raises(IntegrityError), transaction.atomic():
            DefectVerificationCase.objects.create(
                project=project,
                verification=verification,
                source="round",
                source_plan_item=legacy_item,
                title="重复旧来源必须被拒绝",
                snapshot={},
            )
        with pytest.raises(IntegrityError), transaction.atomic():
            DefectVerificationCaseExecution.objects.create(
                project=project,
                item=private,
                source_execution=legacy_execution,
                request_id=uuid4(),
                request_hash="duplicate-legacy-execution",
                result="passed",
            )

        # A completed or partially upgraded installation can safely see the
        # repair again: no duplicate columns, constraints or result copies.
        before = [(table_columns(model), set(table_constraints(model))) for model, _, _ in LINKS]
        with connection.schema_editor() as editor:
            migration.ensure_legacy_links(apps, editor)
        after = [(table_columns(model), set(table_constraints(model))) for model, _, _ in LINKS]
        assert after == before
        assert DefectVerificationCase.objects.filter(verification=verification).count() == 2
        assert DefectVerificationCaseExecution.objects.filter(item__verification=verification).count() == 2
        assert TestExecution.objects.filter(pk=legacy_execution.pk).exists()
    finally:
        restore_test_schema()
