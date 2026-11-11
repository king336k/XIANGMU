"""The external catalog is a bounded mirror; it never grants native access by name."""

import pytest
from plane.db.models import Issue, Project, ProjectMember
from plane.quality.models import PlatformIdentity, PlatformProject

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def catalog(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="目录同步", identifier="CAT")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    mapping = PlatformProject.objects.create(project=project, source_instance="catalog-test", external_project_id=3)
    identity = PlatformIdentity.objects.create(
        project=project, source_instance="catalog-test", external_user_id=16, user=create_user
    )
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/", project, mapping, identity


def authority(members=None, tasks=None):
    def fetch(instance, path, params=None):
        assert instance == "catalog-test"
        if path.endswith("/members"):
            return (
                members
                if members is not None
                else [{"userId": 16, "displayName": "明确映射成员", "userRole": "Collector", "active": True}]
            )
        return {
            "items": tasks
            if path.endswith("/tasks") and tasks is not None
            else (
                [{"id": 24, "projectId": 3, "name": "采集上传", "status": "ACTIVE", "description": "先检查设备"}]
                if path.endswith("/tasks")
                else [{"id": 3, "name": "来源项目", "status": "ACTIVE"}]
            ),
            "hasMore": False,
            "nextCursor": None,
            "snapshotAt": "2026-11-07T10:00:00",
        }

    return fetch


def test_catalog_sync_keeps_native_tasks_and_explicit_identity_then_imports_once(session_client, catalog, mocker):
    base, project, mapping, identity = catalog
    mocker.patch("plane.quality.platform.fetch", side_effect=authority())
    response = session_client.post(base + "integrations/catalog/", {"source_instance": "catalog-test"}, format="json")
    assert response.status_code == 200, response.content
    assert not Issue.objects.filter(project=project).exists()
    assert PlatformIdentity.objects.filter(project=project).count() == 1
    data = session_client.get(base + "integrations/catalog/").data["results"][0]
    assert data["tasks"][0]["name"] == "采集上传" and data["synced_at"]
    path = base + f"integrations/catalog/tasks/{data['tasks'][0]['id']}/import/"
    created = session_client.post(path, {}, format="json")
    assert created.status_code == 201, created.content
    issue = Issue.objects.get(pk=created.data["issue_id"])
    issue.name = "本地经理调整后的任务"
    issue.save()
    assert session_client.post(path, {}, format="json").data["issue_id"] == str(issue.id)
    session_client.post(base + "integrations/catalog/", {"source_instance": "catalog-test"}, format="json")
    issue.refresh_from_db()
    assert issue.name == "本地经理调整后的任务"
    assert Issue.objects.filter(project=project).count() == 1


def test_complete_empty_member_snapshot_revokes_only_mapped_external_access(
    session_client, catalog, mocker, create_user
):
    base, project, mapping, identity = catalog
    mocker.patch("plane.quality.platform.fetch", side_effect=authority(members=[]))
    response = session_client.post(base + "integrations/catalog/", {"source_instance": "catalog-test"}, format="json")
    assert response.status_code == 200, response.content
    identity.refresh_from_db()
    assert not identity.active
    assert ProjectMember.objects.get(project=project, member=create_user).is_active
    assert response.data["revoked_identities"] == 1


def test_malformed_or_looping_catalog_never_partially_revokes_members(session_client, catalog, mocker):
    base, project, mapping, identity = catalog
    fetch = mocker.patch("plane.quality.platform.fetch", side_effect=authority())
    fetch.side_effect = lambda *args, **kwargs: {
        "items": [{"id": 3, "name": "来源项目"}],
        "hasMore": True,
        "nextCursor": "loop",
        "snapshotAt": "2026-11-07T10:00:00",
    }
    response = session_client.post(base + "integrations/catalog/", {"source_instance": "catalog-test"}, format="json")
    assert response.status_code == 503, response.content
    identity.refresh_from_db()
    assert identity.active and fetch.call_count <= 3


def test_catalog_is_manager_only_and_rejects_tasks_from_other_project(session_client, catalog, mocker, create_user):
    base, project, mapping, identity = catalog
    mocker.patch(
        "plane.quality.platform.fetch", side_effect=authority(tasks=[{"id": 24, "projectId": 999, "name": "其他项目"}])
    )
    assert (
        session_client.post(
            base + "integrations/catalog/", {"source_instance": "catalog-test"}, format="json"
        ).status_code
        == 503
    )
    ProjectMember.objects.filter(project=project, member=create_user).update(role=15)
    assert session_client.get(base + "integrations/catalog/").status_code == 403
    assert (
        session_client.post(
            base + "integrations/catalog/", {"source_instance": "catalog-test"}, format="json"
        ).status_code
        == 403
    )


def test_incremental_sync_advances_only_complete_snapshot_and_full_sync_marks_removed_task(
    session_client, catalog, mocker
):
    from plane.quality.models import PlatformCatalogTask

    base, project, mapping, identity = catalog
    fetch = mocker.patch("plane.quality.platform.fetch", side_effect=authority())
    assert (
        session_client.post(
            base + "integrations/catalog/", {"source_instance": "catalog-test"}, format="json"
        ).status_code
        == 200
    )
    fetch.reset_mock()
    fetch.side_effect = authority(tasks=[])
    second = session_client.post(base + "integrations/catalog/", {"source_instance": "catalog-test"}, format="json")
    assert second.status_code == 200 and PlatformCatalogTask.objects.get(project=project).active
    task_call = next(call for call in fetch.call_args_list if call.args[1].endswith("/tasks"))
    assert task_call.args[2]["updatedAfter"] == "2026-11-07T10:00:00"
    assert (
        session_client.post(
            base + "integrations/catalog/", {"source_instance": "catalog-test", "full": True}, format="json"
        ).status_code
        == 200
    )
    task = PlatformCatalogTask.objects.get(project=project)
    assert not task.active
    assert (
        session_client.post(base + f"integrations/catalog/tasks/{task.id}/import/", {}, format="json").status_code
        == 409
    )


def test_missing_source_project_revokes_mapping_and_preserves_native_members(
    session_client, catalog, mocker, create_user
):
    base, project, mapping, identity = catalog
    mocker.patch(
        "plane.quality.platform.fetch",
        return_value={"items": [], "hasMore": False, "snapshotAt": "2026-11-07T10:00:00"},
    )
    response = session_client.post(base + "integrations/catalog/", {"source_instance": "catalog-test"}, format="json")
    assert response.status_code == 200, response.content
    mapping.refresh_from_db()
    identity.refresh_from_db()
    assert not mapping.active and not identity.active
    assert ProjectMember.objects.get(project=project, member=create_user).is_active


def test_invalid_catalog_date_fails_closed_without_creating_snapshot(session_client, catalog, mocker):
    base, project, mapping, identity = catalog
    mocker.patch(
        "plane.quality.platform.fetch",
        return_value={"items": [], "hasMore": False, "snapshotAt": "2026-99-99T10:00:00"},
    )
    response = session_client.post(base + "integrations/catalog/", {"source_instance": "catalog-test"}, format="json")
    assert response.status_code == 503, response.content
    identity.refresh_from_db()
    assert identity.active


def test_platform_administrator_can_import_business_task(session_client, catalog, mocker, create_user):
    from plane.quality.models import BusinessRole, ProjectRolePolicy, PlatformCatalog, PlatformCatalogTask

    base, project, mapping, identity = catalog
    ProjectRolePolicy.objects.create(project=project, enabled=True)
    BusinessRole.objects.create(project=project, user=create_user, role="PLATFORM_ADMIN")
    mirror = PlatformCatalog.objects.create(project=project, source_instance=mapping.source_instance)
    task = PlatformCatalogTask.objects.create(project=project, catalog=mirror, external_id=24, name="管理员同步业务任务")
    response = session_client.post(base + f"integrations/catalog/tasks/{task.id}/import/", {}, format="json")
    assert response.status_code == 201, response.content
    assert Issue.objects.filter(project=project, name="管理员同步业务任务").exists()


def test_catalog_tasks_are_paginated_and_searchable_after_first_500(session_client, catalog):
    from plane.quality.models import PlatformCatalog, PlatformCatalogTask

    base, project, mapping, identity = catalog
    mirror = PlatformCatalog.objects.create(project=project, source_instance=mapping.source_instance)
    PlatformCatalogTask.objects.bulk_create(
        [
            PlatformCatalogTask(project=project, catalog=mirror, external_id=i, name=f"任务 {i:04d}")
            for i in range(1, 502)
        ]
    )
    response = session_client.get(base + f"integrations/catalog/{mirror.id}/tasks/?page=6&per_page=100")
    assert response.status_code == 200, response.content
    assert response.data["count"] == 501 and len(response.data["results"]) == 1
    assert response.data["results"][0]["external_id"] == 501
    search = session_client.get(base + f"integrations/catalog/{mirror.id}/tasks/?search=0501")
    assert search.data["count"] == 1


def test_imported_task_never_inherits_completed_source_or_default_state(session_client, catalog):
    from plane.db.models import State
    from plane.quality.models import PlatformCatalog, PlatformCatalogTask

    base, project, mapping, identity = catalog
    State.objects.create(project=project, workspace=project.workspace, name="已完成", group="completed", default=True)
    mirror = PlatformCatalog.objects.create(project=project, source_instance=mapping.source_instance)
    task = PlatformCatalogTask.objects.create(
        project=project, catalog=mirror, external_id=24, name="需要重新安排", source_status="DONE"
    )
    response = session_client.post(base + f"integrations/catalog/tasks/{task.id}/import/", {}, format="json")
    assert response.status_code == 201, response.content
    assert Issue.objects.get(pk=response.data["issue_id"]).state.group in ["backlog", "unstarted"]


@pytest.mark.parametrize("invalid_state", ["deleted", "archived", "moved"])
def test_history_relation_never_returns_an_unavailable_or_other_project_issue(
    session_client, catalog, workspace, invalid_state
):
    from django.utils import timezone
    from plane.quality.models import PlatformCatalog, PlatformCatalogTask

    base, project, mapping, identity = catalog
    mirror = PlatformCatalog.objects.create(project=project, source_instance=mapping.source_instance)
    issue = Issue.objects.create(project=project, workspace=workspace, name="历史工作项")
    task = PlatformCatalogTask.objects.create(
        project=project, catalog=mirror, external_id=24, name="来源任务", issue=issue
    )
    if invalid_state == "moved":
        other = Project.objects.create(workspace=workspace, name="其他项目", identifier="OCAT")
        Issue.objects.filter(pk=issue.pk).update(project=other)
    else:
        Issue.objects.filter(pk=issue.pk).update(
            **{("deleted_at" if invalid_state == "deleted" else "archived_at"): timezone.now()}
        )
    response = session_client.post(base + f"integrations/catalog/tasks/{task.id}/import/", {}, format="json")
    assert response.status_code == 409, response.content
    listed = session_client.get(base + f"integrations/catalog/{mirror.id}/tasks/")
    assert listed.data["results"][0]["issue_state"] == invalid_state


@pytest.mark.django_db(transaction=True)
def test_sync_and_import_use_consistent_project_lock_with_separate_connections(catalog, mocker, create_user):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import close_old_connections
    from rest_framework.test import APIClient
    from plane.quality.models import PlatformCatalog, PlatformCatalogTask

    base, project, mapping, identity = catalog
    mirror = PlatformCatalog.objects.create(project=project, source_instance=mapping.source_instance)
    task = PlatformCatalogTask.objects.create(project=project, catalog=mirror, external_id=24, name="并发导入")
    mocker.patch("plane.quality.platform.fetch", side_effect=authority())
    barrier = Barrier(2)

    def worker(importing):
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(user=create_user)
            barrier.wait(timeout=5)
            response = client.post(
                base + (f"integrations/catalog/tasks/{task.id}/import/" if importing else "integrations/catalog/"),
                {} if importing else {"source_instance": mapping.source_instance, "full": True},
                format="json",
            )
            return response.status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, value) for value in [False, True]]
        assert sorted(future.result(timeout=15) for future in futures) == [200, 201]
    assert Issue.objects.filter(project=project).count() == 1
