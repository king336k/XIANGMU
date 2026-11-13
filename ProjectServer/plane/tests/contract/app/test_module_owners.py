"""Workspace module owners never grant access; diagnostic assignment is evidence bound and once only."""

import hashlib
from uuid import uuid4
import pytest
from django.utils import timezone
from plane.db.models import User, Project, ProjectMember, WorkspaceMember, Notification
from plane.license.models import Instance, InstanceAdmin
from plane.quality.models import BusinessRole, Defect, DiagnosticJob, ProblemPackage, PackageFile

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def routing(session_client, workspace, create_user):
    instance = Instance.objects.create(
        instance_name="routing", instance_id=str(uuid4()), current_version="test", last_checked_at=timezone.now()
    )
    InstanceAdmin.objects.create(instance=instance, user=create_user)
    project = Project.objects.create(workspace=workspace, name="模块路由", identifier="MODROUTE")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    users = []
    for index in range(3):
        user = User.objects.create(
            username=f"module-tech-{index}", email=f"module-tech-{index}@test.invalid", display_name=f"技术员{index}"
        )
        WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
        ProjectMember.objects.create(workspace=workspace, project=project, member=user, role=15)
        BusinessRole.objects.create(project=project, user=user, role="TECHNICIAN" if index < 2 else "REGRESSION_TESTER")
        users.append(user)
    return session_client, workspace, project, create_user, users


def bind(routing, user=None, key="daq"):
    client, workspace, _, _, users = routing
    return client.patch(
        "/api/quality-auth/accounts/",
        {
            "action": "module_owners",
            "user_id": str((user or users[0]).id),
            "bindings": [{"workspace_id": str(workspace.id), "module_key": key}],
        },
        format="json",
    )


def test_catalog_defaults_and_binding_do_not_grant_access(routing):
    client, workspace, project, _, users = routing
    response = client.get("/api/quality-auth/accounts/")
    assert {row["key"]: row["name"] for row in response.data["module_options"]} == {"daq": "DAQ", "teleop": "遥操"}
    before = (WorkspaceMember.objects.count(), ProjectMember.objects.count(), BusinessRole.objects.count())
    assert bind(routing).status_code == 200
    assert before == (WorkspaceMember.objects.count(), ProjectMember.objects.count(), BusinessRole.objects.count())
    response = client.get("/api/quality-auth/accounts/")
    row = next(row for row in response.data["results"] if row["id"] == str(users[0].id))
    assert row["module_owners"][0]["module_key"] == "daq"
    assert row["module_owners"][0]["workspace_id"] == str(workspace.id)
    assert bind(routing, users[2]).status_code == 400


def test_replacing_owner_and_clearing_bindings(routing):
    from plane.quality.models import ModuleOwner

    client, workspace, _, _, users = routing
    assert bind(routing).status_code == 200
    assert bind(routing, users[1]).status_code == 200
    assert ModuleOwner.objects.get(workspace=workspace, module_id="daq").user == users[1]
    response = client.patch(
        "/api/quality-auth/accounts/",
        {"action": "module_owners", "user_id": str(users[1].id), "bindings": []},
        format="json",
    )
    assert response.status_code == 200 and not ModuleOwner.objects.exists()


def test_create_account_with_project_grant_and_module_is_atomic(routing):
    client, workspace, project, _, _ = routing
    data = {
        "username": "created-module-tech",
        "password": "disposable-test-pass",
        "grant_mode": "project",
        "grants": [{"id": str(project.id), "roles": ["TECHNICIAN"]}],
        "module_owners": [{"workspace_id": str(workspace.id), "module_key": "teleop"}],
    }
    response = client.post("/api/quality-auth/accounts/", data, format="json")
    assert response.status_code == 201, response.content
    from plane.quality.models import ModuleOwner

    assert ModuleOwner.objects.get(module_id="teleop").user_id == User.objects.get(username=data["username"]).id
    data.update(username="invalid-module-tech", grant_mode="none", grants=[])
    denied = client.post("/api/quality-auth/accounts/", data, format="json")
    assert denied.status_code == 400 and not User.objects.filter(username="invalid-module-tech").exists()


def test_admin_can_set_six_character_initial_password_without_granting_extra_access(routing):
    client, _, _, _, _ = routing
    response = client.post("/api/quality-auth/accounts/", {"username": "six-char-initial", "password": "a3B!9x"}, format="json")
    assert response.status_code == 201, response.content
    user = User.objects.get(username="six-char-initial")
    assert user.check_password("a3B!9x")
    assert not ProjectMember.objects.filter(member=user).exists()
    denied = client.post("/api/quality-auth/accounts/", {"username": "short-initial", "password": "a3B!9"}, format="json")
    assert denied.status_code == 400 and not User.objects.filter(username="short-initial").exists()


def test_custom_module_and_nonadmin_binding_rejected(routing):
    client, _, _, _, users = routing
    response = client.post(
        "/api/quality-auth/accounts/", {"action": "create_module", "key": "vision", "name": "视觉"}, format="json"
    )
    assert response.status_code == 201, response.content
    assert bind(routing, key="vision").status_code == 200
    client.force_authenticate(user=users[0])
    assert bind(routing).status_code == 403
    assert (
        client.post(
            "/api/quality-auth/accounts/", {"action": "create_module", "key": "evil", "name": "evil"}, format="json"
        ).status_code
        == 403
    )


def ready_job(routing, excerpt="ERROR module=daq connection refused", description=""):
    _, _, project, actor, _ = routing
    defect = Defect.objects.create(project=project, created_by=actor, title="现场故障", description=description)
    package = ProblemPackage.objects.create(
        project=project, created_by=actor, defect=defect, name="现场材料", status="files_verified"
    )
    digest = hashlib.sha256(excerpt.encode()).hexdigest()
    file = PackageFile.objects.create(
        project=project,
        created_by=actor,
        package=package,
        name="现场.log",
        storage_key=uuid4().hex,
        size=len(excerpt.encode()),
        sha256=digest,
    )
    result = {
        "sources": [
            {
                "file_id": str(file.id),
                "sha256": digest,
                "excerpt": excerpt,
                "read_bytes": len(excerpt.encode()),
                "scan_incomplete": False,
            }
        ],
        "findings": [{"kind": "error", "samples": [excerpt]}],
        "materials_status": "read",
        "model_status": "not_requested",
    }
    return DiagnosticJob.objects.create(
        project=project, defect=defect, created_by=actor, request_id=uuid4(), status="completed", result=result
    )


def route(job):
    from django.db import transaction
    from plane.quality.module_routing import route_completed

    with transaction.atomic():
        route_completed(job)
    job.defect.refresh_from_db()
    return job.defect


def test_evidence_routes_exactly_once_and_notifies(routing):
    assert bind(routing).status_code == 200
    job = ready_job(routing)
    defect = route(job)
    assert defect.assignee_id == routing[4][0].id and defect.module_id == "daq"
    assert defect.assignment_origin == "diagnostic" and "现场材料" in defect.assignment_reason
    events, notices, version = defect.events.count(), Notification.objects.count(), defect.edit_version
    route(job)
    assert defect.events.count() == events and Notification.objects.count() == notices
    defect.refresh_from_db()
    assert defect.edit_version == version


@pytest.mark.parametrize(
    "excerpt,description",
    [
        ("ERROR generic timeout; DAQ may be related", ""),
        ("INFO module=daq healthy", ""),
        ("ERROR module=daq timeout\nERROR module=teleop failed", ""),
        ("ERROR generic timeout", "这是一个DAQ问题"),
    ],
)
def test_ambiguous_or_unproven_claims_stay_unassigned(routing, excerpt, description):
    assert bind(routing).status_code == 200
    defect = route(ready_job(routing, excerpt, description))
    assert defect.assignee_id is None and defect.assignment_reason


def test_structured_description_requires_real_failure_material_and_custom_key_works(routing):
    client = routing[0]
    client.post(
        "/api/quality-auth/accounts/", {"action": "create_module", "key": "vision", "name": "视觉"}, format="json"
    )
    assert bind(routing, key="vision").status_code == 200
    defect = route(ready_job(routing, "ERROR image pipeline crashed", "受影响模块：视觉\n现场描述：无法采集"))
    assert defect.module_id == "vision" and defect.assignee_id == routing[4][0].id


@pytest.mark.parametrize("invalid", ["revoked", "incomplete", "scan", "foreign", "failed"])
def test_revocation_invalid_materials_and_failed_jobs_never_assign(routing, invalid):
    assert bind(routing).status_code == 200
    job = ready_job(routing)
    if invalid == "revoked":
        BusinessRole.objects.filter(project=routing[2], user=routing[4][0]).update(role="REGRESSION_TESTER")
    elif invalid == "incomplete":
        ProblemPackage.objects.filter(defect=job.defect).update(status="uploading")
    elif invalid == "scan":
        job.result["sources"][0]["scan_incomplete"] = True
    elif invalid == "foreign":
        job.result["sources"][0]["file_id"] = str(uuid4())
    else:
        job.status = "failed"
    assert route(job).assignee_id is None


def test_reassign_is_explicit_project_scoped_and_locks_out_diagnostic(routing):
    client, workspace, project, _, users = routing
    assert bind(routing).status_code == 200
    job = ready_job(routing)
    defect = route(job)
    client.force_authenticate(user=users[0])
    url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/defects/{defect.id}/reassign/"
    payload = {
        "assignee_id": str(users[1].id),
        "expected_version": defect.edit_version,
        "reason": "转交现场负责人",
        "module_key": "teleop",
    }
    response = client.post(url, payload, format="json")
    assert response.status_code == 200, response.content
    assert response.data["module"] == {"key": "teleop", "name": "遥操"}
    notices, events = Notification.objects.count(), defect.events.count()
    client.force_authenticate(user=users[1])
    assert client.post(url, payload, format="json").status_code == 409
    assert Notification.objects.count() == notices and defect.events.count() == events
    defect = route(job)
    assert defect.assignee_id == users[1].id and defect.assignment_origin == "manual"
    payload.update(assignee_id=str(users[2].id), expected_version=defect.edit_version)
    client.force_authenticate(user=users[1])
    assert client.post(url, payload, format="json").status_code == 400


def test_workspace_grants_bind_without_adding_project_duties(routing):
    client, workspace, project, actor, _ = routing
    payload = {
        "username": "workspace-module-owner",
        "password": "disposable-test-pass",
        "grant_mode": "workspace",
        "grants": [{"id": str(workspace.id), "roles": ["TECHNICIAN"]}],
        "module_owners": [{"workspace_id": str(workspace.id), "module_key": "daq"}],
    }
    response = client.post("/api/quality-auth/accounts/", payload, format="json")
    assert response.status_code == 201, response.content
    user = User.objects.get(pk=response.data["id"])
    from plane.quality.module_owners import eligible_technician

    assert eligible_technician(project, user.id)
    assert not BusinessRole.objects.filter(user=user).exists()
    # New projects materialize inherited workspace membership through the existing project API.
    created = client.post(
        f"/api/workspaces/{workspace.slug}/projects/", {"name": "未来项目", "identifier": "FUTUREMOD"}, format="json"
    )
    assert created.status_code == 201, created.content
    future = Project.objects.get(pk=created.data["id"])
    assert eligible_technician(future, user.id)
    assert not BusinessRole.objects.filter(project=future, user=user).exists()


def test_owner_directory_contains_unowned_modules_and_module_read_is_project_scoped(routing):
    client, workspace, project, _, users = routing
    response = client.get("/api/quality-auth/accounts/")
    options = next(row for row in response.data["module_owner_options"] if row["workspace_id"] == str(workspace.id))
    assert {row["key"] for row in options["modules"]} == {"daq", "teleop"}
    assert all(row["user_id"] is None for row in options["modules"])
    client.force_authenticate(user=users[0])
    response = client.get(
        "/api/quality-auth/accounts/",
        {"module_options": "1", "workspace_slug": workspace.slug, "project_id": str(project.id)},
    )
    assert response.status_code == 200 and "results" not in response.data
    ProjectMember.objects.filter(project=project, member=users[0]).update(is_active=False)
    assert (
        client.get(
            "/api/quality-auth/accounts/",
            {"module_options": "1", "workspace_slug": workspace.slug, "project_id": str(project.id)},
        ).status_code
        == 403
    )


def test_healthy_unstarted_component_is_not_failure(routing):
    assert bind(routing).status_code == 200
    defect = route(ready_job(routing, '{"components":[{"module":"daq","running":false,"status":"stopped"}]}'))
    assert defect.assignee_id is None


@pytest.mark.parametrize(
    "module,data",
    [
        ("daq", {"record": {"phase": "ERROR", "error": "MCAP writer failed"}}),
        ("daq", {"ros": {"running": False, "error": "ros service crashed"}}),
        (
            "teleop",
            {
                "observations": {
                    "launcher": {
                        "status": "available",
                        "data": {
                            "running": False,
                            "startup": {"remote_control_robot": {"state": "failed", "exit_code": 1}},
                        },
                    }
                }
            },
        ),
    ],
)
def test_real_collect_evidence_structure_routes_only_failed_domain(routing, module, data):
    import json

    assert bind(routing, key=module).status_code == 200
    document = {
        "sourceSystem": "ENGRAM_TELEOP_DAQ",
        "feedback": {"scope": "combined", "stage": "recording", "modules": ["recording", "vr", "ik"]},
        "evidence": {"observations": {module: {"status": "available", "data": data}}},
    }
    defect = route(ready_job(routing, json.dumps(document)))
    assert defect.module_id == module and defect.assignee_id == routing[4][0].id


def test_collect_evidence_idle_not_started_does_not_route(routing):
    import json

    assert bind(routing).status_code == 200
    document = {
        "feedback": {"scope": "daq", "modules": ["recording"]},
        "evidence": {
            "observations": {
                "daq": {
                    "status": "available",
                    "data": {"record": {"phase": "IDLE", "error": None}, "ros": {"running": False, "error": None}},
                },
                "teleop": {
                    "status": "available",
                    "data": {"running": False, "failure_kind": "not_started", "startup": {"state": "failed"}},
                },
            }
        },
    }
    assert route(ready_job(routing, json.dumps(document))).assignee_id is None


@pytest.mark.parametrize(
    "line,module",
    [("[ERROR] MCAP writer write failed", "daq"), ("[ERROR] remote_control_robot failed: process exited", "teleop")],
)
def test_real_component_failure_log_routes(routing, line, module):
    assert bind(routing, key=module).status_code == 200
    defect = route(ready_job(routing, line))
    assert defect.module_id == module and defect.assignee_id == routing[4][0].id


def test_task_finalization_routes_real_materials_once(routing, settings, tmp_path, mocker):
    from plane.quality.tasks import run_diagnostic

    assert bind(routing).status_code == 200
    job = ready_job(routing, "[ERROR] MCAP writer write failed")
    settings.QUALITY_ATTACHMENT_ROOT = str(tmp_path)
    file = PackageFile.objects.get(package__defect=job.defect)
    (tmp_path / file.storage_key).write_bytes(job.result["sources"][0]["excerpt"].encode())
    job.status = "queued"
    job.mode = "rules"
    job.save()
    run_diagnostic(job.id)
    job.refresh_from_db()
    job.defect.refresh_from_db()
    assert job.status == "completed" and job.defect.assignee_id == routing[4][0].id
    assert str(file.id) in job.defect.assignment_reason
    count = job.defect.events.count()
    run_diagnostic(job.id)
    assert job.defect.events.count() == count


def test_admin_can_override_without_membership_but_target_must_have_project_role(routing):
    client, workspace, project, actor, users = routing
    job = ready_job(routing)
    ProjectMember.objects.filter(project=project, member=actor).delete()
    response = client.post(
        f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/defects/{job.defect_id}/reassign/",
        {"assignee_id": str(users[0].id), "expected_version": 1, "reason": "管理员覆盖"},
        format="json",
    )
    assert response.status_code == 200, response.content
    assert response.data["assignment_origin"] == "manual"


def test_current_assignee_can_reassign_after_technician_duty_removed(routing):
    client, workspace, project, _, users = routing
    job = ready_job(routing)
    job.defect.assignee = users[2]
    job.defect.save()
    client.force_authenticate(user=users[2])
    response = client.post(
        f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/defects/{job.defect_id}/reassign/",
        {"assignee_id": str(users[0].id), "expected_version": 1, "reason": "技术职责交接"},
        format="json",
    )
    assert response.status_code == 200, response.content


def test_foreign_project_owner_does_not_receive_assignment(routing):
    _, workspace, project, actor, users = routing
    assert bind(routing).status_code == 200
    other = Project.objects.create(workspace=workspace, name="另一个项目", identifier="MODULEOTHER")
    ProjectMember.objects.create(project=other, member=users[0], role=15)
    BusinessRole.objects.create(project=other, user=users[0], role="TECHNICIAN")
    ProjectMember.objects.filter(project=project, member=users[0]).update(is_active=False)
    assert route(ready_job(routing)).assignee_id is None


@pytest.mark.django_db(transaction=True)
def test_parallel_diagnostic_jobs_create_one_assignment_event(routing):
    from concurrent.futures import ThreadPoolExecutor
    from django.db import close_old_connections, transaction
    from plane.quality.module_routing import route_completed

    assert bind(routing).status_code == 200
    job = ready_job(routing)
    another = DiagnosticJob.objects.create(
        project=job.project,
        defect=job.defect,
        created_by=job.created_by,
        request_id=uuid4(),
        status="completed",
        result=job.result,
    )

    def execute(pk):
        close_old_connections()
        try:
            with transaction.atomic():
                route_completed(DiagnosticJob.objects.get(pk=pk))
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(execute, [job.pk, another.pk]))
    job.defect.refresh_from_db()
    assert job.defect.assignee_id == routing[4][0].id
    assert job.defect.events.count() == 1
    assert Notification.objects.filter(entity_identifier=job.defect_id).count() == 1


def test_manual_unassignment_and_existing_human_assignment_survive_rediagnosis(routing):
    client, workspace, project, _, users = routing
    assert bind(routing).status_code == 200
    job = ready_job(routing)
    job.defect.assignee = users[1]
    job.defect.save()
    assert route(job).assignee_id == users[1].id
    response = client.post(
        f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/defects/{job.defect_id}/reassign/",
        {"assignee_id": None, "expected_version": 1, "reason": "模块归属待人工确认"},
        format="json",
    )
    assert response.status_code == 200, response.content
    assert route(job).assignee_id is None
    job.defect.refresh_from_db()
    assert job.defect.assignment_origin == "manual"


def test_unrelated_project_technician_cannot_reassign_and_model_prose_never_routes(routing):
    client, workspace, project, _, users = routing
    assert bind(routing).status_code == 200
    job = ready_job(routing, "ERROR generic timeout")
    job.result.update(answer="DAQ module is definitely faulty", model_confidence=1, evidence_assessment="supported")
    assert route(job).assignee_id is None
    client.force_authenticate(user=users[1])
    job.defect.refresh_from_db()
    response = client.post(
        f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/defects/{job.defect_id}/reassign/",
        {"assignee_id": str(users[0].id), "expected_version": job.defect.edit_version, "reason": "无权替别人改派"},
        format="json",
    )
    assert response.status_code == 403
    assert not job.defect.events.exists()


@pytest.mark.parametrize(
    "line", ["INFO MCAP writer error=none", "INFO MCAP writer no errors", "INFO module=daq error:0"]
)
def test_healthy_error_counters_are_not_failures(routing, line):
    assert bind(routing).status_code == 200
    assert route(ready_job(routing, line)).assignee_id is None


def test_legacy_project_manager_can_reassign_without_becoming_admin(routing):
    client, workspace, project, _, users = routing
    manager = User.objects.create(username="legacy-module-manager", email="legacy-module-manager@test.invalid")
    WorkspaceMember.objects.create(workspace=workspace, member=manager, role=15)
    ProjectMember.objects.create(workspace=workspace, project=project, member=manager, role=20)
    job = ready_job(routing)
    client.force_authenticate(user=manager)
    response = client.post(
        f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/defects/{job.defect_id}/reassign/",
        {"assignee_id": str(users[0].id), "expected_version": 1, "reason": "项目经理安排"},
        format="json",
    )
    assert response.status_code == 200, response.content


@pytest.mark.parametrize("key,name", [("vision", "teleop"), ("vision", "DAQ"), ("vision", "daq"), ("vision", "TELEOP")])
def test_catalog_rejects_cross_key_name_alias_collision(routing, key, name):
    response = routing[0].post(
        "/api/quality-auth/accounts/", {"action": "create_module", "key": key, "name": name}, format="json"
    )
    assert response.status_code == 400, response.content


def test_routing_alias_collision_stays_ambiguous_for_existing_bad_catalog_data():
    from plane.quality.module_routing import identified

    options = [{"key": "teleop", "name": "遥操"}, {"key": "vision", "name": "teleop"}]
    assert identified("module=teleop", options) == {"teleop", "vision"}


def test_initial_report_assigns_unambiguous_owner_before_materials(routing):
    from plane.quality.module_routing import initial_assign

    _, _, project, actor, users = routing
    assert bind(routing, key="teleop").status_code == 200
    defect = Defect.objects.create(
        project=project,
        created_by=actor,
        title="遥操故障",
        description="问题范围：teleop\n发生阶段：control\n受影响模块：遥操",
    )
    initial_assign(defect, actor)
    defect.refresh_from_db()
    assert defect.assignee_id == users[0].id and defect.assignment_origin == "initial"
    assert defect.module_id == "teleop" and "初步" in defect.assignment_reason
    events = defect.events.count()
    initial_assign(defect, actor)
    assert defect.events.count() == events


def test_initial_ambiguous_report_triages_to_admin_without_granting_membership(routing):
    from plane.quality.module_routing import initial_assign

    _, _, project, actor, _ = routing
    ProjectMember.objects.filter(project=project, member=actor).delete()
    defect = Defect.objects.create(project=project, title="未知现场故障", description="问题范围：combined")
    initial_assign(defect, None)
    defect.refresh_from_db()
    assert defect.assignee_id == actor.id and defect.assignment_origin == "triage"
    assert not ProjectMember.objects.filter(project=project, member=actor).exists()
    assert Notification.objects.filter(receiver=actor, entity_identifier=defect.id).count() == 1


def test_inherited_project_manager_triages_before_global_admin(routing):
    from plane.quality.module_routing import initial_assign
    from plane.quality.models import ProjectRolePolicy

    _, workspace, project, actor, users = routing
    ProjectRolePolicy.objects.create(project=project, enabled=True)
    WorkspaceMember.objects.filter(workspace=workspace, member=users[2]).update(business_roles=["PROJECT_MANAGER"])
    ProjectMember.objects.filter(project=project, member=actor).delete()
    defect = Defect.objects.create(project=project, title="范围不明确")
    initial_assign(defect, actor)
    defect.refresh_from_db()
    assert defect.assignee_id == users[2].id and defect.assignment_origin == "triage"


def test_diagnostic_refines_initial_triage_but_manual_selection_is_final(routing):
    from plane.quality.module_routing import initial_assign

    assert bind(routing).status_code == 200
    job = ready_job(routing)
    initial_assign(job.defect, routing[3])
    job.defect.refresh_from_db()
    initial_owner = job.defect.assignee_id
    assert initial_owner is not None and job.defect.assignment_origin == "triage"
    defect = route(job)
    assert defect.assignee_id == routing[4][0].id and defect.assignment_origin == "diagnostic"
    assert defect.events.count() == 2
    assert any(str(initial_owner) in event.note for event in defect.events.all())
    defect.assignment_origin = "manual"
    defect.assignee = routing[4][1]
    defect.save()
    assert route(job).assignee_id == routing[4][1].id


def test_admin_notification_exposes_only_current_record_metadata(routing):
    from types import SimpleNamespace
    from plane.quality.notifications import defect_notice, serialize_with_current_status

    _, _, project, actor, users = routing
    ProjectMember.objects.filter(project=project, member=actor).delete()
    defect = Defect.objects.create(project=project, assignee=actor, title="分诊通知")
    defect_notice(defect, users[0], "初步分派")
    notice = Notification.objects.get(receiver=actor, entity_identifier=defect.id)
    data = serialize_with_current_status([notice], SimpleNamespace(user=actor))
    record = data[0]["data"]["current_record"]
    context = data[0]["data"]["defect_context"]
    assert record["available"] and context["assignee_name"] == (actor.display_name or actor.username)
    assert context["url"].endswith(f"defects?defect={defect.id}")


def test_admin_without_workspace_membership_can_list_count_and_read_own_quality_notice(routing):
    from plane.quality.notifications import defect_notice

    client, workspace, project, actor, users = routing
    ProjectMember.objects.filter(member=actor).delete()
    WorkspaceMember.objects.filter(member=actor).delete()
    defect = Defect.objects.create(project=project, assignee=actor, title="管理员接单")
    defect_notice(defect, users[0], "初步分诊")
    notice = Notification.objects.get(receiver=actor, entity_identifier=defect.id)
    base = f"/api/workspaces/{workspace.slug}/users/notifications/"
    response = client.get(base)
    assert response.status_code == 200, response.content
    assert [str(row["id"]) for row in response.data] == [str(notice.id)]
    count = client.get(f"/api/workspaces/{workspace.slug}/users/notifications/unread/")
    assert count.status_code == 200, count.content
    assert count.data["total_unread_notifications_count"] == 1
    response = client.post(base + f"{notice.id}/read/")
    assert response.status_code == 200, response.content
    assert response.data["data"]["defect_context"]["assignee_name"]
    notice.refresh_from_db()
    assert notice.read_at is not None


def test_admin_without_any_membership_can_read_handle_reassign_and_diagnose(routing, mocker):
    from plane.quality.models import ProjectRolePolicy
    from plane.quality.tasks import run_diagnostic

    client, workspace, project, actor, users = routing
    ProjectRolePolicy.objects.create(project=project, enabled=True)
    ProjectMember.objects.filter(member=actor).delete()
    WorkspaceMember.objects.filter(member=actor).delete()
    defect = Defect.objects.create(project=project, title="管理员兜底处理")
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    context = client.get(base + "context/")
    assert context.status_code == 200, context.content
    assert context.data["is_manager"] and context.data["can_write"]
    assert client.get(base + f"defects/{defect.id}/").status_code == 200
    response = client.patch(
        base + f"defects/{defect.id}/", {"title": "已排查标题", "expected_version": 1}, format="json"
    )
    assert response.status_code == 200, response.content
    mocker.patch("plane.quality.diagnostics.enqueue")
    response = client.post(
        base + f"defects/{defect.id}/diagnostics/", {"mode": "rules", "request_id": str(uuid4())}, format="json"
    )
    assert response.status_code == 201, response.content
    run_diagnostic(response.data["id"])
    job = DiagnosticJob.objects.get(pk=response.data["id"])
    assert job.status == "completed", job.error_code
    # Existing administrator access projection may materialize memberships at authentication.
    assert not ProjectMember.objects.filter(project=project, member__is_bot=True).exists()


@pytest.mark.parametrize(
    "description,expected",
    [
        ("问题范围：DAQ 采集\n发生阶段：数据录制\n受影响模块：DAQ 录制", {"daq"}),
        ("问题范围：遥操\n发生阶段：遥操控制\n受影响模块：VR / 输入设备、IK / 重定向", {"teleop"}),
        ("问题范围：遥操与 DAQ\n发生阶段：数据录制\n受影响模块：尚不确定", {"daq", "teleop"}),
    ],
)
def test_producer_chinese_scope_and_stage_initial_candidates(description, expected):
    from plane.quality.module_routing import initial_candidates

    assert initial_candidates(description) == expected


def test_project_manager_has_triage_priority_over_projected_global_admin(routing):
    from plane.quality.module_routing import initial_assign

    _, _, project, actor, users = routing
    ProjectMember.objects.filter(project=project, member=users[2]).update(role=20)
    defect = Defect.objects.create(project=project, title="需要项目经理分诊")
    initial_assign(defect, actor)
    defect.refresh_from_db()
    assert defect.assignee_id == users[2].id
