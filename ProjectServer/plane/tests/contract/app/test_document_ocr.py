"""OCR is a cited candidate until an authorized human reviews every extracted range."""

import hashlib
import pytest
from plane.db.models import Project, ProjectMember
from plane.quality.models import DocumentImport, DocumentFile
from plane.knowledge.models import Article

pytestmark = [pytest.mark.contract, pytest.mark.django_db]
PNG = bytes.fromhex("89504e470d0a1a0a") + b"isolated test image placeholder"


@pytest.fixture
def ocr_case(session_client, workspace, create_user, settings, tmp_path, mocker):
    settings.QUALITY_ATTACHMENT_ROOT = str(tmp_path / "files")
    project = Project.objects.create(workspace=workspace, name="图片文字核对", identifier="OCR163")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    mocker.patch.dict(
        "os.environ",
        {
            "DOCUMENT_OCR_BASE_URL": "http://document-ocr:18886",
            "DOCUMENT_OCR_API_KEY": "test-only-ocr-key",
            "DOCUMENT_OCR_ALLOWED_HTTP_ORIGINS": "http://document-ocr:18886",
        },
    )
    return base, project, create_user


def preview_fixture(project, user, raw=PNG, extension="png"):
    from plane.quality.document_imports import private_directory
    import uuid

    row = DocumentImport.objects.create(
        project=project,
        created_by=user,
        resource="knowledge",
        name="排查." + extension,
        rows=[],
        errors=[{"row": 1, "error": "请先识别图片文字并核对"}],
        sha256=uuid.uuid4().hex * 2,
        extraction={
            "format": extension,
            "segments": [],
            "failures": [{"range": "document", "error": "需OCR"}],
            "safe_for_ocr": True,
        },
    )
    key = uuid.uuid4().hex
    (private_directory() / key).write_bytes(raw)
    DocumentFile.objects.create(
        project=project,
        created_by=user,
        document_import=row,
        name=row.name,
        kind="original",
        size=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        storage_key=key,
    )
    return row


def candidate(row, token="token-current"):
    return {
        "token": token,
        "status": "completed",
        "segments": [
            {
                "key": "ocr-1",
                "text": "设备无法连按，检查端口。",
                "method": "ocr",
                "source_image": row.name,
                "width": 300,
                "height": 200,
            }
        ],
        "failures": [],
        "requires_review": True,
        "reviewed": False,
        "source_sha256": row.files.get(kind="original").sha256,
    }


def test_ocr_review_corrects_text_only_after_explicit_confirmation(session_client, ocr_case):
    base, p, u = ocr_case
    row = preview_fixture(p, u)
    state = candidate(row)
    row.extraction["ocr"] = state
    row.save()
    url = base + f"document-imports/{row.id}/ocr/review/"
    denied = session_client.post(
        url,
        {
            "expected_token": state["token"],
            "confirmed": False,
            "segments": [{"key": "ocr-1", "text": "设备无法连接，检查端口。"}],
        },
        format="json",
    )
    assert denied.status_code == 400
    assert session_client.post(base + f"document-imports/{row.id}/confirm/", {}, format="json").status_code == 400
    reviewed = session_client.post(
        url,
        {
            "expected_token": state["token"],
            "confirmed": True,
            "segments": [{"key": "ocr-1", "text": "设备无法连接，检查端口。"}],
        },
        format="json",
    )
    assert reviewed.status_code == 200 and reviewed.data["valid"], reviewed.content
    assert reviewed.data["extraction"]["ocr"]["requires_review"] is False
    assert reviewed.data["extraction"]["ocr"]["reviewed"] is True
    assert "设备无法连接" in reviewed.data["rows"][0]["content"]
    assert "OCR" in reviewed.data["rows"][0]["content"]
    assert not Article.objects.filter(project=p).exists()
    result = session_client.post(base + f"document-imports/{row.id}/confirm/", {}, format="json")
    assert result.status_code == 201, result.content
    article = Article.objects.get(pk=result.data["object_ids"][0])
    assert article.status == "draft" and not article.publication_active
    row.refresh_from_db()
    assert row.extraction["ocr"]["segments"][0]["text"] == "设备无法连按，检查端口。"
    assert row.files.get(kind="original").sha256 == hashlib.sha256(PNG).hexdigest()


@pytest.mark.parametrize("mutation", ["wrong_token", "partial", "extra", "page_forged", "unreviewed_failure"])
def test_ocr_review_rejects_stale_incomplete_or_forged_ranges(session_client, ocr_case, mutation):
    base, p, u = ocr_case
    row = preview_fixture(p, u)
    state = candidate(row)
    if mutation == "unreviewed_failure":
        state["failures"] = [{"page": 2, "error": "此页识别失败"}]
    row.extraction["ocr"] = state
    row.save()
    before = row.sha256
    data = {"expected_token": state["token"], "confirmed": True, "segments": [{"key": "ocr-1", "text": "核对后的文字"}]}
    if mutation == "wrong_token":
        data["expected_token"] = "old-token"
    if mutation == "partial":
        data["segments"] = []
    if mutation == "extra":
        data["segments"].append({"key": "fake", "text": "伪造图源"})
    if mutation == "page_forged":
        data["segments"][0]["page"] = 99
    result = session_client.post(base + f"document-imports/{row.id}/ocr/review/", data, format="json")
    assert result.status_code in {400, 409}, result.content
    row.refresh_from_db()
    assert row.sha256 == before and not row.extraction["ocr"].get("reviewed")
    assert not Article.objects.filter(project=p).exists()


def test_ocr_job_is_idempotent_and_cannot_change_confirmed_import(
    session_client, ocr_case, mocker, django_capture_on_commit_callbacks
):
    base, p, u = ocr_case
    row = preview_fixture(p, u)
    enqueue = mocker.patch("plane.quality.document_ocr.enqueue_ocr")
    with django_capture_on_commit_callbacks(execute=True):
        started = session_client.post(base + f"document-imports/{row.id}/ocr/", {}, format="json")
    assert started.status_code == 202, started.content
    token = started.data["token"]
    again = session_client.post(base + f"document-imports/{row.id}/ocr/", {}, format="json")
    assert again.status_code == 202 and again.data["token"] == token
    assert enqueue.call_count == 1
    row.refresh_from_db()
    row.status = "confirmed"
    row.save()
    assert session_client.post(base + f"document-imports/{row.id}/ocr/", {}, format="json").status_code == 409


def test_ocr_worker_keeps_candidate_separate_and_drops_outdated_reply(ocr_case, mocker):
    from plane.quality.document_ocr import process_ocr

    base, p, u = ocr_case
    row = preview_fixture(p, u)
    before = list(row.errors)
    row.extraction["ocr"] = {"token": "work-token", "status": "queued", "requires_review": True, "actor_id": str(u.id)}
    row.save()
    response = mocker.Mock()
    response.status_code = 200
    response.content = b"bounded"
    body = {
        "status": "completed",
        "source_sha256": row.files.get().sha256,
        "engine": "tesseract",
        "requires_review": True,
        "segments": [{"key": "ocr-1", "text": "候选文字", "width": 300, "height": 200, "source_image": "原始PNG"}],
        "failures": [],
    }
    response.iter_content.return_value = [__import__("json").dumps(body).encode()]
    provider = mocker.patch("plane.quality.document_ocr.requests.post", return_value=response)
    process_ocr(str(row.id), "obsolete-token")
    provider.assert_not_called()
    process_ocr(str(row.id), "work-token")
    row.refresh_from_db()
    assert row.extraction["ocr"]["status"] == "completed" and row.errors == before and row.rows == []
    assert not Article.objects.filter(project=p).exists()


def test_ocr_permission_revocation_prevents_worker_outbound(ocr_case, mocker):
    from plane.quality.document_ocr import process_ocr

    base, p, u = ocr_case
    row = preview_fixture(p, u)
    row.extraction["ocr"] = {"token": "revoked", "status": "queued", "requires_review": True, "actor_id": str(u.id)}
    row.save()
    ProjectMember.objects.filter(project=p, member=u).update(is_active=False)
    provider = mocker.patch("plane.quality.document_ocr.requests.post")
    process_ocr(str(row.id), "revoked")
    provider.assert_not_called()
    row.refresh_from_db()
    assert row.extraction["ocr"]["status"] == "failed"


@pytest.mark.parametrize(
    "patch",
    [
        {"status": "failed"},
        {"engine": "unknown"},
        {"requires_review": False},
        {
            "segments": [
                {"key": "repeat", "text": "候选", "page": 1, "width": 300, "height": 200},
                {"key": "repeat", "text": "重复来源", "page": 1, "width": 300, "height": 200},
            ]
        },
        {"failures": [{"page": True, "error": "bad page"}]},
    ],
)
def test_service_response_cannot_forge_success_or_ranges(ocr_case, patch):
    from plane.quality.document_ocr import checked_result

    _, p, u = ocr_case
    row = preview_fixture(p, u, extension="pdf")
    file = row.files.get()
    result = {
        "status": "completed",
        "engine": "tesseract",
        "requires_review": True,
        "source_sha256": file.sha256,
        "segments": [{"key": "ocr-1", "text": "候选", "page": 1, "width": 300, "height": 200}],
        "failures": [],
    }
    result.update(patch)
    with pytest.raises(ValueError):
        checked_result(result, file, ".pdf")


def test_review_rejects_extra_outer_keys_and_expired_queue_can_retry(session_client, ocr_case, mocker):
    from django.utils import timezone

    base, p, u = ocr_case
    row = preview_fixture(p, u)
    state = candidate(row)
    row.extraction["ocr"] = state
    row.save()
    data = {
        "expected_token": state["token"],
        "confirmed": True,
        "segments": [{"key": "ocr-1", "text": "完整核对结果"}],
        "source_sha256": "forged",
    }
    assert session_client.post(base + f"document-imports/{row.id}/ocr/review/", data, format="json").status_code == 400
    row.extraction["ocr"] = {
        "token": "expired",
        "status": "queued",
        "requires_review": True,
        "requested_at": timezone.now().timestamp() - 1000,
    }
    row.save()
    mocker.patch("plane.quality.document_ocr.enqueue_ocr")
    result = session_client.post(base + f"document-imports/{row.id}/ocr/", {}, format="json")
    assert result.status_code == 202 and result.data["token"] != "expired"


def test_late_worker_result_cannot_overwrite_reviewed_candidate(ocr_case):
    from plane.quality.document_ocr import finish

    _, p, u = ocr_case
    row = preview_fixture(p, u)
    state = candidate(row)
    state["reviewed"] = True
    state["requires_review"] = False
    row.extraction["ocr"] = state
    row.save()
    finish(str(row.id), state["token"], {"status": "failed", "requires_review": True, "error": "late result"})
    row.refresh_from_db()
    assert row.extraction["ocr"]["reviewed"] is True
    assert row.extraction["ocr"]["requires_review"] is False


@pytest.mark.parametrize(
    "part,image",
    [("word/../outside.xml", None), (None, "https://unapproved.invalid/image"), ("Bearer secret-canary", None)],
)
def test_failed_range_metadata_is_never_trusted_as_public_text(ocr_case, part, image):
    from plane.quality.document_ocr import checked_result

    _, p, u = ocr_case
    row = preview_fixture(p, u)
    file = row.files.get()
    failure = {"error": "service error"}
    if part:
        failure["part"] = part
    if image:
        failure["source_image"] = image
    with pytest.raises(ValueError):
        checked_result(
            {
                "status": "completed",
                "engine": "tesseract",
                "requires_review": True,
                "source_sha256": file.sha256,
                "segments": [],
                "failures": [failure],
            },
            file,
            ".png",
        )


def test_total_pixels_and_outbound_revocation_after_safety_parse(ocr_case, mocker):
    from plane.quality.document_ocr import checked_result, process_ocr

    _, p, u = ocr_case
    row = preview_fixture(p, u, raw=b"pdf bytes explicitly mocked parser", extension="pdf")
    file = row.files.get()
    with pytest.raises(ValueError):
        checked_result(
            {
                "status": "completed",
                "engine": "tesseract",
                "requires_review": True,
                "source_sha256": file.sha256,
                "segments": [
                    {"key": f"ocr-{n}", "text": "文字", "page": n, "width": 3000, "height": 3000} for n in range(1, 8)
                ],
                "failures": [],
            },
            file,
            ".pdf",
        )
    row.extraction["ocr"] = {
        "token": "parse-revoked",
        "status": "queued",
        "actor_id": str(u.id),
        "requires_review": True,
    }
    row.save()

    def revoked(*args):
        ProjectMember.objects.filter(project=p, member=u).update(is_active=False)
        return {"safe_for_ocr": True}

    mocker.patch("plane.quality.document_ocr.extract_local", side_effect=revoked)
    provider = mocker.patch("plane.quality.document_ocr.requests.post")
    process_ocr(str(row.id), "parse-revoked")
    provider.assert_not_called()
    row.refresh_from_db()
    assert row.extraction["ocr"]["status"] == "failed"


def test_get_converges_expired_queue_so_browser_polling_stops(session_client, ocr_case):
    from django.utils import timezone

    base, p, u = ocr_case
    row = preview_fixture(p, u)
    row.extraction["ocr"] = {
        "token": "gone",
        "status": "running",
        "requires_review": True,
        "requested_at": timezone.now().timestamp() - 601,
    }
    row.save()
    response = session_client.get(base + f"document-imports/{row.id}/ocr/")
    assert response.status_code == 200 and response.data["status"] == "failed"
    assert response.data["requires_review"] is True
    row.refresh_from_db()
    assert row.extraction["ocr"]["status"] == "failed"


def test_service_cannot_omit_pdf_page_or_invent_docx_image_location(ocr_case):
    from plane.quality.document_ocr import checked_result

    _, p, u = ocr_case
    row = preview_fixture(p, u)
    file = row.files.get()
    result = {
        "status": "completed",
        "engine": "tesseract",
        "requires_review": True,
        "source_sha256": file.sha256,
        "segments": [{"key": "ocr-1", "text": "第一页", "page": 1, "width": 300, "height": 200}],
        "failures": [],
    }
    with pytest.raises(ValueError):
        checked_result(result, file, ".pdf", {"page_count": 2})
    result["segments"] = [
        {
            "key": "ocr-1",
            "text": "图片字",
            "part": "word/document.xml",
            "paragraph": 99,
            "source_image": "word/media/image1.png",
            "width": 300,
            "height": 200,
        }
    ]
    with pytest.raises(ValueError):
        checked_result(
            result,
            file,
            ".docx",
            {
                "image_locations": [
                    {"part": "word/document.xml", "paragraph": 2, "source_image": "word/media/image1.png"}
                ]
            },
        )


def test_busy_local_service_requeues_bounded_instead_of_losing_import(
    ocr_case, mocker, django_capture_on_commit_callbacks
):
    from plane.quality.document_ocr import process_ocr

    _, p, u = ocr_case
    row = preview_fixture(p, u)
    row.extraction["ocr"] = {"token": "busy", "status": "queued", "requires_review": True, "actor_id": str(u.id)}
    row.save()
    response = mocker.Mock()
    response.status_code = 429
    mocker.patch("plane.quality.document_ocr.requests.post", return_value=response)
    enqueue = mocker.patch("plane.quality.document_ocr.enqueue_ocr")
    with django_capture_on_commit_callbacks(execute=True):
        process_ocr(str(row.id), "busy")
    row.refresh_from_db()
    assert row.extraction["ocr"]["status"] == "queued"
    assert row.extraction["ocr"]["busy_retries"] == 1
    enqueue.assert_called_once_with(str(row.id), "busy", 5)
    assert row.rows == [] and not Article.objects.filter(project=p).exists()
