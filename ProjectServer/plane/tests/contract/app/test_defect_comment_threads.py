from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from threading import Barrier
from uuid import uuid4

import pytest
from django.db import close_old_connections
from rest_framework.test import APIClient

from plane.db.models import Project, ProjectMember, User, WorkspaceMember
from plane.quality.models import BusinessRole, Defect, DefectComment, ProjectRolePolicy

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def thread_scope(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="线程评论验收", identifier="THREADS")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    BusinessRole.objects.create(project=project, user=create_user, role="PROJECT_MANAGER")
    defect = Defect.objects.create(project=project, title="线程讨论", created_by=create_user)
    url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/defects/{defect.id}/comments/"
    return project, defect, url, create_user


def post(client, url, text, parent=None, request_id=None):
    payload = {"request_id": str(request_id or uuid4()), "content_html": f"<p>{text}</p>"}
    if parent:
        payload["reply_to"] = str(parent)
    response = client.post(url, payload, format="json")
    assert response.status_code == 201, response.content
    return response.data


def seed(project, defect, actor, content, **extra):
    return DefectComment.objects.create(
        project=project,
        defect=defect,
        created_by=actor,
        content=content,
        content_html=f"<p>{content}</p>",
        visibility="internal",
        **extra,
    )


def test_threads_paginate_roots_before_context_search_not_flat_page_grouping(session_client, thread_scope):
    project, defect, url, actor = thread_scope
    roots = [seed(project, defect, actor, f"主评论{index}") for index in range(21)]
    first_reply = post(session_client, url, "最旧线程的独有关键词", roots[0].id)
    second_reply = post(session_client, url, "连续回应", first_reply["id"])
    page = session_client.get(url, {"view": "threads", "per_page": 10})
    assert page.status_code == 200
    assert page.data["count"] == 21 and page.data["comment_count"] == 23
    assert len(page.data["results"]) == 10
    assert page.data["results"][0]["id"] == str(roots[-1].id)
    page3 = session_client.get(url, {"view": "threads", "per_page": 10, "page": 3})
    assert page3.data["count"] == 21 and len(page3.data["results"]) == 1
    assert page3.data["results"][0]["id"] == str(roots[0].id)
    assert page3.data["results"][0]["reply_count"] == 2
    assert page3.data["results"][0]["thread_id"] == str(roots[0].id)
    search = session_client.get(url, {"view": "threads", "search": "独有关键词"})
    assert search.data["count"] == 1 and search.data["comment_count"] == 1
    assert search.data["results"][0]["id"] == str(roots[0].id)
    assert search.data["results"][0]["reply_count"] == 2
    assert session_client.get(url).data["count"] == 23  # Default contract remains flat.
    child = DefectComment.objects.get(pk=second_reply["id"])
    assert child.thread_root_id == roots[0].id and str(child.reply_to_id) == first_reply["id"]


def test_reply_endpoint_normalizes_child_and_keeps_exact_quote_and_latest_order(session_client, thread_scope):
    project, defect, url, actor = thread_scope
    root = seed(project, defect, actor, "主评论")
    responses = [post(session_client, url, f"回复{n}", root.id) for n in range(23)]
    nested = post(session_client, url, "继续回复某人", responses[0]["id"])
    response = session_client.get(url + f"{responses[0]['id']}/replies/", {"per_page": 10})
    assert response.status_code == 200
    assert response.data["count"] == response.data["reply_count"] == 24
    assert response.data["thread_id"] == str(root.id)
    assert response.data["results"][0]["id"] == nested["id"]
    assert response.data["results"][0]["reply_to"]["id"] == responses[0]["id"]
    assert response.data["results"][0]["reply_to"]["content"] == "回复0"
    assert response.data["results"][0]["thread_id"] == str(root.id)
    last = session_client.get(url + f"{root.id}/replies/", {"per_page": 10, "page": 3})
    assert last.status_code == 200 and len(last.data["results"]) == 4
    assert last.data["results"][-1]["id"] == responses[0]["id"]
    search = session_client.get(url + f"{root.id}/replies/", {"search": "继续回复"})
    assert search.data["count"] == 1 and search.data["reply_count"] == 24
    assert session_client.get(url, {"view": "unknown"}).status_code == 400


def test_author_filter_matches_reply_but_returns_root_context(session_client, thread_scope):
    project, defect, url, actor = thread_scope
    root = seed(project, defect, actor, "原始讨论")
    member = User.objects.create(username="thread-member", email="thread-member@discussion.invalid")
    WorkspaceMember.objects.create(workspace=project.workspace, member=member, role=15)
    ProjectMember.objects.create(project=project, member=member, role=15)
    BusinessRole.objects.create(project=project, user=member, role="TECHNICIAN")
    session_client.force_authenticate(member)
    reply = post(session_client, url, "成员跟进", root.id)
    page = session_client.get(url, {"view": "threads", "author": str(member.id)})
    assert page.status_code == 200 and page.data["count"] == 1 and page.data["comment_count"] == 1
    assert page.data["results"][0]["id"] == str(root.id)
    assert page.data["results"][0]["actor"] == actor.display_name or page.data["results"][0]["actor"] == actor.username
    assert len(page.data["participants"]) == 2
    replies = session_client.get(url + f"{root.id}/replies/", {"author": str(member.id)})
    assert replies.data["count"] == 1 and replies.data["results"][0]["id"] == reply["id"]


def test_thread_replies_reject_public_cross_defect_and_guest_access(session_client, thread_scope):
    project, defect, url, actor = thread_scope
    public = DefectComment.objects.create(
        project=project, defect=defect, created_by=actor, content="公开", visibility="public"
    )
    other = Defect.objects.create(project=project, title="另一条")
    foreign = seed(project, other, actor, "其他缺陷内部消息")
    assert session_client.get(url + f"{public.id}/replies/").status_code == 404
    assert session_client.get(url + f"{foreign.id}/replies/").status_code == 404
    root = seed(project, defect, actor, "本缺陷内部消息")
    ProjectMember.objects.filter(project=project, member=actor).update(role=5)
    assert session_client.get(url + f"{root.id}/replies/").status_code == 403


def test_backfill_existing_reply_chains_handles_invalid_cycles_without_rewriting_history(thread_scope):
    from django.apps import apps
    from django.db import connection

    project, defect, _, actor = thread_scope
    root = seed(project, defect, actor, "root")
    first = seed(project, defect, actor, "first", reply_to=root)
    second = seed(project, defect, actor, "second", reply_to=first)
    public = DefectComment.objects.create(
        project=project, defect=defect, created_by=actor, content="public", visibility="public"
    )
    invalid_public = seed(project, defect, actor, "bad-public", reply_to=public)
    other = Defect.objects.create(project=project, title="other")
    invalid_defect = seed(project, other, actor, "bad-defect", reply_to=root)
    cycle_a = seed(project, defect, actor, "cycle-a")
    cycle_b = seed(project, defect, actor, "cycle-b", reply_to=cycle_a)
    DefectComment.objects.filter(pk=cycle_a.pk).update(reply_to=cycle_b)
    module = import_module("plane.quality.migrations.0051_comment_threads")
    with connection.schema_editor() as editor:
        module.backfill_threads(apps, editor)
    for row in [first, second]:
        row.refresh_from_db()
        assert row.thread_root_id == root.id
    for row in [root, public, invalid_public, invalid_defect, cycle_a, cycle_b]:
        row.refresh_from_db()
        assert row.thread_root_id is None
    second.refresh_from_db()
    assert second.reply_to_id == first.id and second.content == "second"


@pytest.mark.django_db(transaction=True)
def test_five_people_reply_concurrently_to_child_share_one_thread(session_client, thread_scope):
    project, defect, url, actor = thread_scope
    ProjectRolePolicy.objects.create(project=project, enabled=True)
    root = seed(project, defect, actor, "并发线程")
    child = post(session_client, url, "已有回复", root.id)
    actors = []
    for index, duty in enumerate(
        ["PROJECT_MANAGER", "TECHNICIAN", "REGRESSION_TESTER", "TECHNICIAN", "REGRESSION_TESTER"]
    ):
        member = User.objects.create(username=f"thread-{index}", email=f"thread-{index}@discussion.invalid")
        WorkspaceMember.objects.create(workspace=project.workspace, member=member, role=15)
        ProjectMember.objects.create(project=project, member=member, role=15)
        BusinessRole.objects.create(project=project, user=member, role=duty)
        actors.append(member)
    start = Barrier(5)
    same_request_id = uuid4()

    def publish(index):
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(actors[index])
            start.wait(timeout=15)
            return post(client, url, f"成员{index}的跟帖", child["id"], request_id=same_request_id)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=5) as pool:
        replies = list(pool.map(publish, range(5)))
    assert len({reply["id"] for reply in replies}) == 5
    assert all(reply["thread_id"] == str(root.id) and reply["reply_to"]["id"] == child["id"] for reply in replies)
    page = session_client.get(url, {"view": "threads"})
    assert page.status_code == 200 and page.data["count"] == 1
    assert page.data["results"][0]["reply_count"] == 6
    assert session_client.get(url + f"{root.id}/replies/").data["count"] == 6


def test_thread_preview_never_quotes_invalid_historical_public_or_cross_defect_parent(session_client, thread_scope):
    project, defect, url, actor = thread_scope
    foreign = Defect.objects.create(project=project, title="外部上下文")
    foreign_comment = seed(project, foreign, actor, "不能泄露的其他缺陷内容")
    public = DefectComment.objects.create(project=project, defect=defect, content="公开旧回复", visibility="public")
    seed(project, defect, actor, "旧错误跨缺陷引用", reply_to=foreign_comment)
    seed(project, defect, actor, "旧错误公开引用", reply_to=public)
    response = session_client.get(url, {"view": "threads"})
    assert response.status_code == 200 and response.data["count"] == 2
    assert all(row["reply_to"] is None for row in response.data["results"])
    assert "不能泄露" not in str(response.data)


def test_threads_and_replies_query_count_stays_bounded_by_page_not_history(session_client, thread_scope):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    project, defect, url, actor = thread_scope
    roots = [seed(project, defect, actor, f"根{n}") for n in range(25)]
    for n in range(120):
        seed(project, defect, actor, f"回复{n}", reply_to=roots[0], thread_root=roots[0])
    with CaptureQueriesContext(connection) as first:
        small = session_client.get(url, {"view": "threads", "per_page": 5})
    with CaptureQueriesContext(connection) as second:
        large = session_client.get(url, {"view": "threads", "per_page": 20})
    assert small.status_code == large.status_code == 200
    assert len(large.data["results"]) == 20 and large.data["comment_count"] == 145
    assert len(second) <= len(first) + 1
    with CaptureQueriesContext(connection) as reply_small:
        a = session_client.get(url + f"{roots[0].id}/replies/", {"per_page": 5})
    with CaptureQueriesContext(connection) as reply_large:
        b = session_client.get(url + f"{roots[0].id}/replies/", {"per_page": 50})
    assert a.status_code == b.status_code == 200 and b.data["count"] == 120
    assert len(b.data["results"]) == 50 and len(reply_large) <= len(reply_small) + 1
