import pytest
from plane.tests.contract.app.test_module_owners import routing as routing
from plane.tests.contract.app.test_module_owners import bind, ready_job, route

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def test_admin_can_receive_a_reassignment_for_unconfirmed_module(routing):
    client, workspace, project, admin, users = routing
    assert bind(routing).status_code == 200
    d = route(ready_job(routing))
    assert d.assignee_id == users[0].id
    r = client.post(
        f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/defects/{d.id}/reassign/",
        {
            "expected_version": d.edit_version,
            "assignee_id": str(admin.id),
            "module_key": None,
            "reason": "已有双模块证据，需重新分诊",
        },
        format="json",
    )
    assert r.status_code == 200, r.data
    d.refresh_from_db()
    assert d.assignee_id == admin.id and d.module_id is None
