"""Triage resolutions are explicit manager decisions and never masquerade as repaired regressions."""

import pytest
from plane.db.models import Project, ProjectMember

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def triage(session_client, workspace, create_user):
    p = Project.objects.create(workspace=workspace, name="缺陷分类", identifier="TRIAGE")
    ProjectMember.objects.create(project=p, member=create_user, role=20)
    base = f"/api/workspaces/{workspace.slug}/projects/{p.id}/quality/"
    d = session_client.post(base + "defects/", {"title": "重复故障"}, format="json").data
    return base, p, d


def test_duplicate_has_canonical_target_reason_and_no_fake_regression(session_client, triage):
    base, p, d = triage
    target = session_client.post(base + "defects/", {"title": "主故障"}, format="json").data
    result = session_client.post(
        base + f"defects/{d['id']}/disposition/",
        {
            "kind": "duplicate",
            "duplicate_of_id": target["id"],
            "reason": "同一设备同一根因，归到主故障追踪",
            "expected_version": d["edit_version"],
        },
        format="json",
    )
    assert result.status_code == 200, result.content
    assert (
        result.data["status"] == "closed"
        and result.data["resolution_kind"] == "duplicate"
        and result.data["duplicate_of_id"] == target["id"]
    )
    assert result.data["regression_execution"] is None and not result.data["fixed_build"]
    assert session_client.get(base + f"defects/{target['id']}/").data["status"] == "open"


def test_triage_requires_reason_manager_and_no_self_duplicate(session_client, triage, create_user):
    base, p, d = triage
    url = base + f"defects/{d['id']}/disposition/"
    assert session_client.post(url, {"kind": "wont_fix", "expected_version": 1}, format="json").status_code == 400
    assert (
        session_client.post(
            url,
            {"kind": "duplicate", "duplicate_of_id": d["id"], "reason": "不能指向自己", "expected_version": 1},
            format="json",
        ).status_code
        == 400
    )
    ProjectMember.objects.filter(project=p, member=create_user).update(role=15)
    assert (
        session_client.post(
            url, {"kind": "not_a_bug", "reason": "成员不能自行关闭", "expected_version": 1}, format="json"
        ).status_code
        == 403
    )


def test_defer_keeps_unclosed_and_reopen_preserves_decision_history(session_client, triage):
    from django.utils import timezone
    from datetime import timedelta

    base, p, d = triage
    result = session_client.post(
        base + f"defects/{d['id']}/disposition/",
        {
            "kind": "deferred",
            "reason": "等待硬件到货后排查",
            "defer_until": (timezone.localdate() + timedelta(days=3)).isoformat(),
            "expected_version": 1,
        },
        format="json",
    )
    assert result.status_code == 200 and result.data["status"] == "open" and result.data["defer_until"], result.content
    reopened = session_client.patch(
        base + f"defects/{d['id']}/",
        {"status": "in_progress", "resolution": "硬件提前到位", "expected_version": result.data["edit_version"]},
        format="json",
    )
    assert reopened.status_code == 200
