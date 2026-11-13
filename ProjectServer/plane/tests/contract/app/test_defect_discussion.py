from uuid import uuid4
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from plane.db.models import Project, ProjectMember, WorkspaceMember, User
from plane.quality.models import Defect, BusinessRole, ProjectRolePolicy

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def discussion(workspace, create_user):
    p = Project.objects.create(workspace=workspace, name="评论验收", identifier="DISCUSS")
    ProjectMember.objects.create(project=p, member=create_user, role=20)
    BusinessRole.objects.create(project=p, user=create_user, role="PROJECT_MANAGER")
    d = Defect.objects.create(project=p, title="讨论缺陷", created_by=create_user)
    return p, d, f"/api/workspaces/{workspace.slug}/projects/{p.id}/quality/defects/{d.id}/comments/", create_user


def test_internal_rich_comment_replay_quote_search_and_latest_first(session_client, discussion):
    p, d, url, u = discussion
    data = {
        "request_id": str(uuid4()),
        "content_html": "<h2>验证结论</h2><p><strong>通过</strong> 👍<script>bad()</script></p>",
    }
    a = session_client.post(url, data, format="json")
    assert a.status_code == 201, a.content
    assert "<script" not in a.data["content_html"] and "<strong>通过</strong>" in a.data["content_html"]
    assert a.data["visibility"] == "internal"
    assert session_client.post(url, data, format="json").data["id"] == a.data["id"]
    changed = session_client.post(url, {**data, "content_html": "<p>不同</p>"}, format="json")
    assert changed.status_code == 409
    reply = session_client.post(
        url, {"request_id": str(uuid4()), "content_html": "<p>补充复测</p>", "reply_to": a.data["id"]}, format="json"
    )
    assert reply.status_code == 201
    result = session_client.get(url)
    assert result.status_code == 200 and result.data["count"] == 2
    assert result.data["results"][0]["id"] == reply.data["id"]
    assert result.data["results"][0]["reply_to"]["id"] == a.data["id"]
    assert session_client.get(url, {"search": "补充"}).data["count"] == 1
    assert session_client.get(url, {"author": str(u.id)}).data["count"] == 2
    assert session_client.get(url, {"author": str(uuid4())}).data["count"] == 0
    assert len(result.data["participants"]) == 1
    other = Defect.objects.create(project=p, title="其他")
    wrong = f"/api/workspaces/{p.workspace.slug}/projects/{p.id}/quality/defects/{other.id}/comments/"
    assert (
        session_client.post(
            wrong,
            {"request_id": str(uuid4()), "content_html": "<p>错引用</p>", "reply_to": a.data["id"]},
            format="json",
        ).status_code
        == 400
    )


def test_private_upload_scoped_to_comment_no_diagnostic_side_effect(session_client, discussion):
    from unittest.mock import patch

    p, d, url, u = discussion
    with patch("plane.quality.diagnostics.schedule_automatic") as auto:
        uploaded = session_client.post(
            url + "files/", {"file": SimpleUploadedFile("说明.txt", "说明".encode())}, format="multipart"
        )
        assert uploaded.status_code == 201, uploaded.content
        auto.assert_not_called()
    f = uploaded.data
    comment = session_client.post(
        url, {"request_id": str(uuid4()), "content_html": "<p>附件</p>", "attachment_ids": [f["id"]]}, format="json"
    )
    assert comment.status_code == 201 and comment.data["attachments"][0]["name"] == "说明.txt"
    assert session_client.get(url + f"files/{f['id']}/download/").status_code == 200
    other = Defect.objects.create(project=p, title="其他")
    wrong = url.replace(str(d.id), str(other.id))
    assert session_client.get(wrong + f"files/{f['id']}/download/").status_code == 404
    assert (
        session_client.post(
            wrong,
            {"request_id": str(uuid4()), "content_html": "<p>不能盗用</p>", "attachment_ids": [f["id"]]},
            format="json",
        ).status_code
        == 400
    )
    assert (
        session_client.post(
            url + "files/", {"file": SimpleUploadedFile("unsafe.svg", b"<svg/>")}, format="multipart"
        ).status_code
        == 400
    )
    assert (
        session_client.post(url, {"request_id": str(uuid4()), "content_html": "<p></p>"}, format="json").status_code
        == 400
    )


def test_guest_cannot_read_or_download_internal_discussion(session_client, discussion):
    p, d, url, u = discussion
    up = session_client.post(url + "files/", {"file": SimpleUploadedFile("a.txt", b"test")}, format="multipart")
    assert up.status_code == 201
    c = session_client.post(
        url,
        {"request_id": str(uuid4()), "content_html": "<p>内部沟通</p>", "attachment_ids": [up.data["id"]]},
        format="json",
    )
    assert c.status_code == 201
    guest = User.objects.create(username="discussion-guest", email="discussion-guest@local.test")
    WorkspaceMember.objects.create(workspace=p.workspace, member=guest, role=5)
    ProjectMember.objects.create(project=p, member=guest, role=5)
    session_client.force_authenticate(guest)
    assert session_client.get(url).status_code == 403
    assert session_client.get(url + f"files/{up.data['id']}/download/").status_code == 403
    assert (
        session_client.post(url, {"request_id": str(uuid4()), "content_html": "<p>越权</p>"}, format="json").status_code
        == 403
    )


@pytest.mark.parametrize("duty", ["PROJECT_MANAGER", "TECHNICIAN", "REGRESSION_TESTER"])
def test_project_roles_can_discuss_but_downgrade_revokes_every_file_operation(session_client, discussion, duty):
    p, d, url, u = discussion
    ProjectRolePolicy.objects.create(project=p, enabled=True)
    member = User.objects.create(username=f"discussion-{duty}", email=f"{duty}@discussion.invalid")
    WorkspaceMember.objects.create(workspace=p.workspace, member=member, role=15)
    membership = ProjectMember.objects.create(project=p, member=member, role=15)
    BusinessRole.objects.create(project=p, user=member, role=duty)
    session_client.force_authenticate(member)
    upload = session_client.post(url + "files/", {"file": SimpleUploadedFile("a.txt", b"private")}, format="multipart")
    assert upload.status_code == 201
    posted = session_client.post(
        url,
        {"request_id": str(uuid4()), "content_html": "<p>参与讨论</p>", "attachment_ids": [upload.data["id"]]},
        format="json",
    )
    assert posted.status_code == 201
    assert session_client.get(url).status_code == 200
    assert session_client.get(url + f"files/{upload.data['id']}/download/").status_code == 200
    membership.role = 5
    membership.save()
    assert session_client.get(url).status_code == 403
    assert session_client.get(url + f"files/{upload.data['id']}/download/").status_code == 403
    assert (
        session_client.post(url + "files/", {"file": SimpleUploadedFile("b.txt", b"x")}, format="multipart").status_code
        == 403
    )


def test_fifteen_people_and_old_internal_comments_paginate_newest_first(session_client, discussion):
    from plane.quality.models import DefectComment

    p, d, url, u = discussion
    old = DefectComment.objects.create(project=p, defect=d, created_by=u, content="历史普通文本", visibility="internal")
    # A public DAQ reply belongs to the independent public channel, not the internal discussion.
    public = DefectComment.objects.create(project=p, defect=d, created_by=u, content="采集员可见", visibility="public")
    for n in range(15):
        user = User.objects.create(username=f"person-{n}", email=f"person-{n}@discussion.invalid")
        DefectComment.objects.create(project=p, defect=d, created_by=user, content=f"讨论{n}", visibility="internal")
    page = session_client.get(url, {"per_page": 10})
    assert page.status_code == 200 and page.data["count"] == 16
    assert len(page.data["results"]) == 10 and len(page.data["participants"]) == 16
    page2 = session_client.get(url, {"per_page": 10, "page": 2})
    assert len(page2.data["results"]) == 6
    assert page2.data["results"][-1]["id"] == str(old.id)
    assert page2.data["results"][-1]["content_html"] == ""
    assert str(public.id) not in {row["id"] for row in [*page.data["results"], *page2.data["results"]]}
    assert set(row["id"] for row in page.data["results"]).isdisjoint(row["id"] for row in page2.data["results"])


def test_attachment_draft_private_and_other_author_cannot_claim_it(session_client, discussion):
    p, d, url, u = discussion
    uploaded = session_client.post(url + "files/", {"file": SimpleUploadedFile("a.txt", b"secret")}, format="multipart")
    assert uploaded.status_code == 201
    other = User.objects.create(username="draft-peer", email="draft-peer@discussion.invalid")
    WorkspaceMember.objects.create(workspace=p.workspace, member=other, role=15)
    ProjectMember.objects.create(project=p, member=other, role=15)
    BusinessRole.objects.create(project=p, user=other, role="TECHNICIAN")
    session_client.force_authenticate(other)
    file_url = url + f"files/{uploaded.data['id']}/download/"
    assert session_client.get(file_url).status_code == 403
    posted = session_client.post(
        url,
        {"request_id": str(uuid4()), "content_html": "<p>盗用</p>", "attachment_ids": [uploaded.data["id"]]},
        format="json",
    )
    assert posted.status_code == 400
    session_client.force_authenticate(u)
    data = {"request_id": str(uuid4()), "content_html": "", "attachment_ids": [uploaded.data["id"]]}
    published = session_client.post(url, data, format="json")
    assert published.status_code == 201
    assert session_client.post(url, data, format="json").data["id"] == published.data["id"]
    session_client.force_authenticate(other)
    assert session_client.get(file_url).status_code == 200


def test_rich_text_safe_links_no_remote_images_and_inline_preview_private(session_client, discussion):
    p, d, url, u = discussion
    html = (
        '<h3 onclick="bad()">标题</h3><p><a href="javascript:alert(1)">不安全</a>'
        '<img src="https://outside.invalid/x" onerror="bad()"><strong>正常</strong></p>'
    )
    response = session_client.post(url, {"request_id": str(uuid4()), "content_html": html}, format="json")
    assert response.status_code == 201
    assert "onclick" not in response.data["content_html"] and "javascript:" not in response.data["content_html"]
    assert "<img" not in response.data["content_html"]
    assert "<strong>正常</strong>" in response.data["content_html"]
    raw = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    image = session_client.post(url + "files/", {"file": SimpleUploadedFile("test.png", raw)}, format="multipart")
    assert image.status_code == 201 and image.data["content_type"] == "image/png"
    preview = session_client.get(url + f"files/{image.data['id']}/preview/")
    assert preview.status_code == 200 and preview["Content-Type"] == "image/png"
    assert preview["X-Content-Type-Options"] == "nosniff" and preview["Cache-Control"] == "private, no-store"
    text = session_client.post(url + "files/", {"file": SimpleUploadedFile("text.txt", b"text")}, format="multipart")
    assert session_client.get(url + f"files/{text.data['id']}/preview/").status_code == 400
    assert (
        session_client.post(
            url + "files/", {"file": SimpleUploadedFile("fake.png", b"not a png")}, format="multipart"
        ).status_code
        == 400
    )


def test_cross_project_record_and_revoked_workspace_never_read_discussion(session_client, discussion):
    p, d, url, u = discussion
    other = Project.objects.create(workspace=p.workspace, name="其他项目", identifier="OTHERDIS")
    defect = Defect.objects.create(project=other, title="别的缺陷")
    wrong = url.replace(str(d.id), str(defect.id))
    assert session_client.get(wrong).status_code == 404
    assert (
        session_client.post(wrong, {"request_id": str(uuid4()), "content_html": "<p>x</p>"}, format="json").status_code
        == 404
    )
    WorkspaceMember.objects.filter(workspace=p.workspace, member=u).update(is_active=False)
    assert session_client.get(url).status_code == 403


def test_new_discussion_does_not_duplicate_operation_history_or_public_channel(session_client, discussion):
    from plane.quality.models import DefectComment

    p, d, url, u = discussion
    legacy = DefectComment.objects.create(
        project=p, defect=d, created_by=u, content="原内部备注", visibility="internal"
    )
    public = DefectComment.objects.create(project=p, defect=d, created_by=u, content="原公开回复", visibility="public")
    posted = session_client.post(url, {"request_id": str(uuid4()), "content_html": "<p>新内部讨论</p>"}, format="json")
    assert posted.status_code == 201
    operation = session_client.get(url.replace("comments/", "collaboration/"))
    assert operation.status_code == 200
    assert {row["id"] for row in operation.data["results"]} == {str(legacy.id), str(public.id)}
    assert all("content_html" not in row for row in operation.data["results"])
    assert session_client.get(url).data["count"] == 2


def test_published_attachment_count_and_aggregate_size_are_bounded(session_client, discussion):
    from plane.quality.models import CommentAttachment

    p, d, url, u = discussion
    files = [
        CommentAttachment.objects.create(
            project=p,
            defect=d,
            created_by=u,
            name=f"large-{n}.txt",
            size=20 * 1024 * 1024,
            sha256="0" * 64,
            storage_key=f"test-large-{n}.bin",
            content_type="text/plain",
        )
        for n in range(3)
    ]
    payload = {
        "request_id": str(uuid4()),
        "content_html": "<p>超过50MB</p>",
        "attachment_ids": [str(f.id) for f in files],
    }
    assert session_client.post(url, payload, format="json").status_code == 400
    assert (
        session_client.post(
            url, {**payload, "attachment_ids": [str(uuid4()) for _ in range(11)]}, format="json"
        ).status_code
        == 400
    )


@pytest.mark.django_db(transaction=True)
def test_concurrent_same_request_publishes_one_attachment_only_comment_once(session_client, discussion):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import close_old_connections
    from rest_framework.test import APIClient
    from plane.quality.models import CommentAttachment, DefectComment

    p, d, url, actor = discussion
    uploaded = session_client.post(
        url + "files/", {"file": SimpleUploadedFile("并发附件.txt", b"concurrent attachment")}, format="multipart"
    )
    assert uploaded.status_code == 201, uploaded.content
    request_id = str(uuid4())
    payload = {"request_id": request_id, "content_html": "", "attachment_ids": [uploaded.data["id"]]}
    start = Barrier(2)

    def publish():
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(actor)
            start.wait(timeout=10)
            response = client.post(url, payload, format="json")
            return response.status_code, response.data
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: publish(), range(2)))
    assert sorted(code for code, _ in results) == [200, 201], results
    identifiers = {body["id"] for _, body in results}
    assert len(identifiers) == 1
    comment = DefectComment.objects.get(defect=d, created_by=actor, request_id=request_id)
    assert str(comment.pk) in identifiers and comment.content == "" and comment.content_html == ""
    assert DefectComment.objects.filter(defect=d, request_id=request_id).count() == 1
    attachment = CommentAttachment.objects.get(pk=uploaded.data["id"])
    assert attachment.comment_id == comment.id
    assert CommentAttachment.objects.filter(comment=comment).count() == 1
    assert all(len(body["attachments"]) == 1 for _, body in results)
    print("Concurrent attachment-only publish: HTTP200/201, one comment, one attachment association")


@pytest.mark.django_db(transaction=True)
def test_five_distinct_actors_publish_same_request_id_without_cross_actor_dedup(session_client, discussion):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import close_old_connections
    from rest_framework.test import APIClient
    from plane.quality.models import CommentAttachment, DefectComment

    project, defect, url, _ = discussion
    ProjectRolePolicy.objects.create(project=project, enabled=True)
    request_id = str(uuid4())
    start = Barrier(5)
    actors = []
    for index, duty in enumerate(
        ["PROJECT_MANAGER", "TECHNICIAN", "REGRESSION_TESTER", "TECHNICIAN", "REGRESSION_TESTER"]
    ):
        actor = User.objects.create(
            username=f"concurrent-actor-{index}",
            email=f"concurrent-actor-{index}@discussion.invalid",
            display_name=f"并发成员{index}",
        )
        WorkspaceMember.objects.create(workspace=project.workspace, member=actor, role=15)
        ProjectMember.objects.create(project=project, member=actor, role=15)
        BusinessRole.objects.create(project=project, user=actor, role=duty)
        actors.append(actor)

    def publish(index):
        close_old_connections()
        try:
            actor = actors[index]
            client = APIClient()
            client.force_authenticate(actor)
            upload = client.post(
                url + "files/",
                {"file": SimpleUploadedFile(f"成员{index}材料.txt", f"private-file-{index}".encode())},
                format="multipart",
            )
            assert upload.status_code == 201, upload.content
            start.wait(timeout=15)
            response = client.post(
                url,
                {
                    "request_id": request_id,
                    "content_html": f"<p>成员{index}独立评论</p>",
                    "attachment_ids": [upload.data["id"]],
                },
                format="json",
            )
            return index, response.status_code, response.data, upload.data
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=5) as pool:
        responses = list(pool.map(publish, range(5)))
    assert [status for _, status, _, _ in responses] == [201] * 5, responses
    assert len({body["id"] for _, _, body, _ in responses}) == 5
    assert DefectComment.objects.filter(defect=defect, request_id=request_id).count() == 5
    assert CommentAttachment.objects.filter(defect=defect, comment__request_id=request_id).count() == 5
    for index, _, body, upload in responses:
        assert body["created_by_id"] == str(actors[index].id)
        assert body["content"] == f"成员{index}独立评论"
        assert body["actor"] == f"并发成员{index}"
        assert [file["id"] for file in body["attachments"]] == [upload["id"]]
        attachment = CommentAttachment.objects.get(pk=upload["id"])
        assert str(attachment.comment_id) == body["id"] and attachment.created_by_id == actors[index].id
        assert attachment.name == f"成员{index}材料.txt"
    print("Five-actor concurrent publish: 5xHTTP201, five distinct comments with exact author/content/attachment")


@pytest.mark.django_db(transaction=True)
def test_two_people_publish_on_separate_defects_with_scoped_results_and_files(session_client, discussion):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import close_old_connections
    from rest_framework.test import APIClient
    from plane.quality.models import DefectComment

    project, first, first_url, first_actor = discussion
    second = Defect.objects.create(project=project, title="第二条独立缺陷", created_by=first_actor)
    second_url = first_url.replace(str(first.id), str(second.id))
    other = User.objects.create(username="separate-actor", email="separate-actor@discussion.invalid")
    WorkspaceMember.objects.create(workspace=project.workspace, member=other, role=15)
    ProjectMember.objects.create(project=project, member=other, role=15)
    BusinessRole.objects.create(project=project, user=other, role="TECHNICIAN")
    people = [(first_actor, first, first_url), (other, second, second_url)]
    request_id = str(uuid4())
    start = Barrier(2)

    def publish(index):
        close_old_connections()
        try:
            actor, defect, url = people[index]
            client = APIClient()
            client.force_authenticate(actor)
            upload = client.post(
                url + "files/",
                {"file": SimpleUploadedFile(f"缺陷{index}.txt", f"defect-{index}".encode())},
                format="multipart",
            )
            assert upload.status_code == 201
            start.wait(timeout=15)
            response = client.post(
                url,
                {
                    "request_id": request_id,
                    "content_html": f"<p>缺陷{index}的独立讨论</p>",
                    "attachment_ids": [upload.data["id"]],
                },
                format="json",
            )
            return index, response.status_code, response.data, upload.data
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(publish, range(2)))
    assert [status for _, status, _, _ in responses] == [201, 201], responses
    assert len({body["id"] for _, _, body, _ in responses}) == 2
    assert DefectComment.objects.filter(project=project, request_id=request_id).count() == 2
    for index, _, body, upload in responses:
        actor, defect, url = people[index]
        session_client.force_authenticate(actor)
        result = session_client.get(url)
        assert result.status_code == 200 and result.data["count"] == 1
        assert result.data["results"][0]["id"] == body["id"]
        assert result.data["results"][0]["created_by_id"] == str(actor.id)
        assert result.data["results"][0]["content"] == f"缺陷{index}的独立讨论"
        assert result.data["results"][0]["attachments"][0]["id"] == upload["id"]
        wrong_url = people[1 - index][2]
        assert session_client.get(wrong_url + f"files/{upload['id']}/download/").status_code == 404
    print("Two-defect concurrent publish: 2xHTTP201, correctly scoped comment lists and cross-defect file404")
