"""Install one editable base edition per workspace; never replay it on upgrades."""

import json
from pathlib import Path

from django.db import transaction
from plane.db.models import Project, ProjectMember, WorkspaceMember
from plane.license.models import InstanceConfiguration, Instance
from .models import Article, PublishedRevision, ArticleEvent
from .sharing_models import KnowledgeShare
from .retrieval import scan_article

PREFIX = "BASE_KNOWLEDGE_INITIALIZED:"


def share_base_knowledge(project):
    marker = InstanceConfiguration.objects.filter(key=PREFIX + str(project.workspace_id)).first()
    if not marker:
        return
    state = json.loads(marker.value)
    if state["project_id"] == str(project.id):
        return
    source = Project.objects.filter(
        pk=state["project_id"], workspace_id=project.workspace_id, archived_at__isnull=True
    ).first()
    if not source:
        return
    for article in Article.objects.filter(project=source, publication_active=True):
        revision = PublishedRevision.objects.filter(article=article, version=article.published_version).first()
        if revision:
            KnowledgeShare.objects.get_or_create(
                article=article,
                target_project=project,
                defaults={
                    "project": source,
                    "revision": revision,
                    "created_by_id": source.created_by_id,
                    "reason": "首次部署基础知识，工作区项目默认可检索",
                },
            )


@transaction.atomic
def initialize_base_knowledge(workspace, actor):
    Instance.objects.select_for_update().get()
    key = PREFIX + str(workspace.id)
    marker = InstanceConfiguration.objects.filter(key=key).first()
    if marker:
        return {"created": 0, "status": "preserved", "project_id": json.loads(marker.value)["project_id"]}
    from plane.quality.permissions import is_administrator

    if (
        not is_administrator(actor)
        or not WorkspaceMember.objects.filter(workspace=workspace, member=actor, is_active=True, role__gte=15).exists()
    ):
        raise ValueError("Existing workspace administrator required")
    data = json.loads(Path(__file__).with_name("base_knowledge.json").read_text())
    rows = data["records"]
    for row in rows:
        if scan_article(row["title"], row["content"], row["tags"]):
            raise ValueError("Base knowledge content scan failed")
    identifier = "BASEKNOW"
    suffix = 1
    while Project.objects.filter(workspace=workspace, identifier=identifier).exists():
        suffix += 1
        identifier = "BASEKNOW" + str(suffix)
    project = Project.objects.create(
        workspace=workspace,
        name="平台基础知识",
        identifier=identifier,
        network=0,
        created_by=actor,
        hidden_menu_items=["requirements", "work_items", "defects", "quality", "versions"],
    )
    ProjectMember.objects.update_or_create(
        project=project, member=actor, defaults={"role": 20, "is_active": True, "created_by": actor}
    )
    from plane.quality.models import ProjectRolePolicy

    ProjectRolePolicy.objects.create(project=project, enabled=True)
    articles = []
    for row in rows:
        version = max([0, *[v["version"] for v in row["history"]]]) + 1
        article = Article.objects.create(
            project=project,
            created_by=actor,
            title=row["title"],
            content=row["content"],
            tags=[x for x in row["tags"] if x != "待复核"],
            status="published",
            publication_active=True,
            published_version=version,
            scanned_version=1,
        )
        for old in row["history"]:
            PublishedRevision.objects.create(
                project=project,
                article=article,
                created_by=actor,
                version=old["version"],
                title=old["title"],
                content=old["content"],
                tags=["历史追溯"],
            )
        PublishedRevision.objects.create(
            project=project,
            article=article,
            created_by=actor,
            version=version,
            title=article.title,
            content=article.content,
            tags=article.tags,
        )
        ArticleEvent.objects.create(
            project=project,
            article=article,
            created_by=actor,
            action="base_seed",
            version=1,
            note=json.dumps({"edition": data["version"], "source": row["source"]}, ensure_ascii=False),
        )
        articles.append(str(article.id))
    InstanceConfiguration.objects.create(
        key=key,
        value=json.dumps(
            {"version": data["version"], "project_id": str(project.id), "articles": articles}, ensure_ascii=False
        ),
        category="KNOWLEDGE",
    )
    for target in Project.objects.filter(workspace=workspace, archived_at__isnull=True).exclude(pk=project.pk):
        share_base_knowledge(target)
    return {"created": len(articles), "status": "initialized", "project_id": str(project.id)}


def sync_base_publication(article):
    marker = InstanceConfiguration.objects.filter(key=PREFIX + str(article.project.workspace_id)).first()
    if not marker or json.loads(marker.value)["project_id"] != str(article.project_id):
        return
    revision = PublishedRevision.objects.get(article=article, version=article.published_version)
    for target in Project.objects.filter(workspace_id=article.project.workspace_id, archived_at__isnull=True).exclude(
        pk=article.project_id
    ):
        row, created = KnowledgeShare.objects.get_or_create(
            article=article,
            target_project=target,
            defaults={
                "project_id": article.project_id,
                "revision": revision,
                "created_by_id": article.created_by_id,
                "reason": "平台基础知识统一发布",
            },
        )
        if not created and row.active:
            row.revision = revision
            row.version += 1
            row.save(update_fields=["revision", "version"])
