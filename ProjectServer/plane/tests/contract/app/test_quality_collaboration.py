"""Business collaboration reuses project membership and native notification inbox."""

import pytest
from plane.db.models import Project, ProjectMember, WorkspaceMember, User, Notification

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def collaboration(session_client, workspace, create_user):
    p = Project.objects.create(workspace=workspace, name="协作交接", identifier="COLLAB")
    ProjectMember.objects.create(project=p, member=create_user, role=20)
    people = []
    for index in range(2):
        user = User.objects.create(
            email=f"collab{index}@local.test", username=f"collab{index}", display_name=f"技术员{index}"
        )
        WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
        ProjectMember.objects.create(project=p, member=user, role=15)
        people.append(user)
    base = f"/api/workspaces/{workspace.slug}/projects/{p.id}/quality/"
    d = session_client.post(
        base + "defects/", {"title": "待交接缺陷", "assignee_id": str(people[0].id)}, format="json"
    ).data
    return base, p, d, people, create_user


def test_defect_handoff_requires_acceptance_and_revokes_old_owner(session_client, collaboration):
    base, p, d, people, manager = collaboration
    url = base + f"defects/{d['id']}/team/"
    proposed = session_client.post(
        url,
        {
            "action": "transfer",
            "user_id": str(people[1].id),
            "reason": "轮班交接",
            "expected_version": d["edit_version"],
        },
        format="json",
    )
    assert proposed.status_code == 200, proposed.content
    assert str(proposed.data["assignee_id"]) == str(people[0].id)
    session_client.force_authenticate(user=people[0])
    assert (
        session_client.post(
            url, {"action": "accept", "expected_version": proposed.data["edit_version"]}, format="json"
        ).status_code
        == 403
    )
    session_client.force_authenticate(user=people[1])
    accepted = session_client.post(
        url, {"action": "accept", "expected_version": proposed.data["edit_version"]}, format="json"
    )
    assert accepted.status_code == 200 and str(accepted.data["assignee_id"]) == str(people[1].id), accepted.content
    assert any("轮班交接" in event["note"] for event in accepted.data["events"])
    assert Notification.objects.filter(project=p, receiver=people[1], entity_name="quality").exists()
    session_client.force_authenticate(user=people[0])
    assert (
        session_client.patch(
            base + f"defects/{d['id']}/", {"description": "原负责人不能继续改写"}, format="json"
        ).status_code
        == 403
    )


def test_collaborators_are_valid_members_and_cannot_self_elevate(session_client, collaboration):
    base, p, d, people, manager = collaboration
    url = base + f"defects/{d['id']}/team/"
    stranger = User.objects.create(email="outsider@local.test", username="outsider")
    assert (
        session_client.post(
            url, {"action": "add", "user_id": str(stranger.id), "expected_version": d["edit_version"]}, format="json"
        ).status_code
        == 400
    )
    added = session_client.post(
        url, {"action": "add", "user_id": str(people[1].id), "expected_version": d["edit_version"]}, format="json"
    )
    assert added.status_code == 200, added.content
    assert added.data["collaborators"][0]["user_id"] == str(people[1].id)
    session_client.force_authenticate(user=people[1])
    assert (
        session_client.post(
            url,
            {
                "action": "transfer",
                "user_id": str(people[1].id),
                "expected_version": added.data["edit_version"],
                "reason": "协作者不可改负责人",
            },
            format="json",
        ).status_code
        == 403
    )


def test_plan_assignment_sends_native_notification_and_cross_receiver_read_is_denied(session_client, collaboration):
    base, p, d, people, manager = collaboration
    case = session_client.post(
        base + "cases/", {"title": "通知验证", "steps": [{"action": "测试", "expected": "通知"}]}, format="json"
    ).data
    plan = session_client.post(
        base + "plans/",
        {"name": "需通知的测试计划", "build": "v1", "environment": "本地", "managed": True, "case_ids": [case["id"]]},
        format="json",
    ).data
    assigned = session_client.post(
        base + f"plans/{plan['id']}/workflow/",
        {"action": "assign", "expected_version": plan["workflow_version"], "assignee_id": str(people[0].id)},
        format="json",
    )
    assert assigned.status_code == 200
    n = Notification.objects.filter(receiver=people[0], entity_name="quality", entity_identifier=plan["id"]).first()
    assert n and n.data["quality"]["url"].endswith(f"plan={plan['id']}")
    session_client.force_authenticate(user=people[0])
    inbox = session_client.get(f"/api/workspaces/{p.workspace.slug}/users/notifications/")
    assert inbox.status_code == 200 and str(n.id) in str(inbox.data), inbox.content
    session_client.force_authenticate(user=people[1])
    assert (
        session_client.post(f"/api/workspaces/{p.workspace.slug}/users/notifications/{n.id}/read/").status_code == 404
    )


def test_revoked_members_do_not_receive_or_read_business_notifications(session_client, collaboration):
    base, p, d, people, manager = collaboration
    from plane.quality.notifications import notify

    notify(p, manager, [people[0].id], d["id"], "待处理通知", f"defects?defect={d['id']}")
    notification = Notification.objects.get(project=p, receiver=people[0], entity_name="quality", title="待处理通知")
    count_before = Notification.objects.filter(project=p, receiver=people[0], entity_name="quality").count()
    ProjectMember.objects.filter(project=p, member=people[0]).update(is_active=False)
    session_client.force_authenticate(user=people[0])
    response = session_client.get(f"/api/workspaces/{p.workspace.slug}/users/notifications/")
    assert response.status_code == 200 and str(notification.id) not in str(response.data)
    detail = session_client.get(f"/api/workspaces/{p.workspace.slug}/users/notifications/{notification.id}/")
    assert detail.status_code == 404
    notify(p, manager, [people[0].id], d["id"], "撤权后不投递", f"defects?defect={d['id']}")
    assert Notification.objects.filter(project=p, receiver=people[0], entity_name="quality").count() == count_before


def test_handoff_old_page_conflict_and_direct_reassign_cannot_skip_acceptance(session_client, collaboration):
    base, p, d, people, manager = collaboration
    url = base + f"defects/{d['id']}/"
    assert (
        session_client.patch(
            url, {"assignee_id": str(people[1].id), "expected_version": d["edit_version"]}, format="json"
        ).status_code
        == 409
    )
    changed = session_client.post(
        url + "team/",
        {"action": "add", "user_id": str(people[1].id), "expected_version": d["edit_version"]},
        format="json",
    ).data
    assert changed["edit_version"] > d["edit_version"]
    assert (
        session_client.patch(
            url, {"description": "旧页面覆盖", "expected_version": d["edit_version"]}, format="json"
        ).status_code
        == 409
    )
