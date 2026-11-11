"""Execute with Django shell on the new platform; explicit reviewed historical exports only.

Input comes from stdin. Output contains mappings/counts, never knowledge bodies.
"""

import importlib.util
import json
import sys
import uuid

from django.db import transaction
from plane.db.models import Project, ProjectMember, User, Workspace, WorkspaceMember
from plane.knowledge.models import Article, PublishedRevision
from plane.knowledge.retrieval import search
from plane.quality.models import BusinessRole, ProjectRolePolicy

spec = importlib.util.spec_from_file_location(
    "plane.knowledge.legacy_migration", "/migration-legacy.py"
)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)

payload = json.loads(sys.stdin.read())
reviewer = User.objects.get(id=payload["reviewer_id"], is_active=True)
reports = []
with transaction.atomic():
    for export in payload["exports"]:
        source = export["source"]
        plan = migration.build_plan(export)
        db = source["database"]
        scope_key = "acceptance" if "acceptance" in db else "local"
        workspace_id = uuid.uuid5(
            migration.NAMESPACE, "workspace:" + source["host"] + ":" + db
        )
        workspace, created = Workspace.objects.get_or_create(
            id=workspace_id,
            defaults={
                "name": "157历史知识复核·" + scope_key,
                "slug": "knowledge-157-" + scope_key,
                "owner": reviewer,
            },
        )
        if created:
            WorkspaceMember.objects.create(
                workspace=workspace, member=reviewer, role=20
            )
        mapping = {}
        for index, scope in enumerate(
            sorted({item["source_project"] for item in plan}), 1
        ):
            project_id = uuid.uuid5(
                migration.NAMESPACE,
                "project:" + source["host"] + ":" + db + ":" + scope,
            )
            project, created = Project.objects.get_or_create(
                id=project_id,
                defaults={
                    "workspace": workspace,
                    "name": f"157 {scope_key} 原项目{scope}知识复核",
                    "identifier": f"K157{scope_key[0].upper()}{index}",
                    "network": 0,
                    "description": f"只读迁移自 {db}；源Hub未运行。仅保全草稿，待适用范围、来源证据和脱敏复核，不自动参与诊断检索。",
                },
            )
            if created:
                ProjectMember.objects.create(project=project, member=reviewer, role=20)
                ProjectRolePolicy.objects.create(project=project, enabled=True)
                BusinessRole.objects.create(
                    project=project, user=reviewer, role="PROJECT_MANAGER"
                )
            mapping[scope] = str(project.id)
        first = migration.import_plan(plan, mapping, reviewer)
        second = migration.import_plan(plan, mapping, reviewer)
        verification = []
        for scope, project_id in mapping.items():
            articles = Article.objects.filter(project_id=project_id)
            verification.append(
                {
                    "source_scope": scope,
                    "project_id": project_id,
                    "workspace_slug": workspace.slug,
                    "draft_count": articles.filter(
                        status="draft", publication_active=False
                    ).count(),
                    "historical_versions": PublishedRevision.objects.filter(
                        project_id=project_id
                    ).count(),
                    "search_count": search(project_id, "").count(),
                    "source_fks_null": not articles.exclude(
                        source_defect=None, source_issue=None, source_regression=None
                    ).exists(),
                    "project_members": ProjectMember.objects.filter(
                        project_id=project_id, is_active=True
                    ).count(),
                    "workspace_members": WorkspaceMember.objects.filter(
                        workspace=workspace, is_active=True
                    ).count(),
                }
            )
        reports.append(
            {
                "source_database": db,
                "first_import": first,
                "retry": second,
                "verification": verification,
            }
        )
print(json.dumps({"reports": reports}, ensure_ascii=False))
