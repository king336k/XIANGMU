"""Local document originals and strict extraction stay private to their source project."""

import base64
import hashlib
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from plane.db.models import Project, ProjectMember, WorkspaceMember
from plane.knowledge.models import Article
from plane.quality.models import BusinessRole, ProjectRolePolicy

pytestmark = [pytest.mark.contract, pytest.mark.django_db]
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
)


def docx(text="导入正文", external=False, extra=None):
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as z:
        z.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="png" ContentType="image/png"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        )
        z.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        )
        z.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'
            + text
            + "</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>表格内容</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>",
        )
        z.writestr("word/media/image1.png", PNG)
        z.writestr(
            "word/_rels/document.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="'
            + (
                'https://example.org/image.png" TargetMode="External'
                if external
                else "media/image1.png"
            )
            + '"/></Relationships>',
        )
        for name, raw in (extra or {}).items():
            z.writestr(name, raw)
    return output.getvalue()


def pdf(text=True, encrypted=False):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=200)
    if text:
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {NameObject("/F1"): writer._add_object(font)}
                )
            }
        )
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 20 100 Td (Actual PDF text) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("test-password")
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


@pytest.fixture
def imports152(workspace, create_user, settings, tmp_path):
    settings.QUALITY_ATTACHMENT_ROOT = tmp_path / "private"
    settings.DATA_UPLOAD_MAX_MEMORY_SIZE = 22 * 1024 * 1024
    WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(
        role=15
    )
    p = Project.objects.create(workspace=workspace, name="文档原件", identifier="D152")
    ProjectMember.objects.create(project=p, member=create_user, role=15)
    ProjectRolePolicy.objects.create(project=p, enabled=True)
    BusinessRole.objects.create(project=p, user=create_user, role="TECHNICIAN")
    return f"/api/workspaces/{workspace.slug}/projects/{p.id}/quality/", p


def upload(client, base, raw, name="source.docx", resource="knowledge"):
    return client.post(
        base + "document-imports/",
        {"resource": resource, "file": SimpleUploadedFile(name, raw)},
        format="multipart",
    )


def test_docx_preserves_original_tables_images_and_creates_one_draft(
    session_client, imports152
):
    base, project = imports152
    raw = docx()
    response = upload(session_client, base, raw)
    assert response.status_code == 201 and response.data["valid"], response.content
    data = response.data
    assert (
        "导入正文" in data["rows"][0]["content"]
        and "表格内容" in data["rows"][0]["content"]
    )
    assert data["extraction"]["image_count"] == 1 and data["extraction"]["segments"]
    original = next(f for f in data["files"] if f["kind"] == "original")
    assert original["sha256"] == hashlib.sha256(
        raw
    ).hexdigest() and "storage_key" not in str(data)
    downloaded = session_client.get(original["download_url"])
    assert downloaded.status_code == 200
    assert (
        hashlib.sha256(b"".join(downloaded.streaming_content)).hexdigest()
        == original["sha256"]
    )
    assert downloaded["X-Content-Type-Options"] == "nosniff"
    image = next(f for f in data["files"] if f["kind"] == "image")
    assert session_client.get(image["preview_url"]).status_code == 200
    assert upload(session_client, base, raw).data["id"] == data["id"]
    assert not Article.objects.filter(project=project).exists()
    for expected in (201, 200):
        assert (
            session_client.post(
                base + f"document-imports/{data['id']}/confirm/", {}, format="json"
            ).status_code
            == expected
        )
    article = Article.objects.get(project=project)
    assert article.status == "draft" and not article.publication_active
    detail = session_client.get(
        base.replace("/quality/", "/knowledge/") + f"articles/{article.id}/"
    )
    assert detail.status_code == 200 and len(detail.data["source_files"]) == 2
    from plane.knowledge.serializers import PublicationSerializer

    assert "source_files" not in PublicationSerializer().fields


def test_pdf_actual_text_is_extracted_by_page(session_client, imports152):
    base, _ = imports152
    response = upload(session_client, base, pdf(), "real.pdf")
    assert response.status_code == 201 and response.data["valid"], response.content
    assert "Actual PDF text" in response.data["rows"][0]["content"]
    assert response.data["extraction"]["page_count"] == 1
    assert "【来源：PDF 第1页】" in response.data["rows"][0]["content"]


@pytest.mark.parametrize(
    "raw,name,expected",
    [
        (lambda: pdf(False), "scan.pdf", "检索"),
        (lambda: pdf(encrypted=True), "encrypted.pdf", "加密"),
        (lambda: b"%PDF-broken", "broken.pdf", "格式"),
        (lambda: docx(external=True), "external.docx", "外部"),
        (lambda: docx(extra={"../evil.xml": b"<root/>"}), "path.docx", "路径"),
        (
            lambda: docx(
                extra={
                    "word/evil.xml": b'<!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><a>&x;</a>'
                }
            ),
            "entity.docx",
            "实体",
        ),
        (
            lambda: docx(extra={"word/huge.xml": b"x" * (25 * 1024 * 1024)}),
            "bomb.docx",
            "预算",
        ),
    ],
)
def test_incomplete_extraction_cannot_be_confirmed(
    session_client, imports152, raw, name, expected
):
    base, _ = imports152
    response = upload(session_client, base, raw(), name)
    assert response.status_code == 201 and not response.data["valid"], response.content
    assert expected in str(response.data["errors"])
    assert response.data["extraction"]["failures"]
    assert (
        session_client.post(
            base + f"document-imports/{response.data['id']}/confirm/", {}, format="json"
        ).status_code
        == 400
    )
    assert any(f["kind"] == "original" for f in response.data["files"])


def test_originals_require_editor_permission_and_project_membership(
    session_client, imports152, create_user, workspace
):
    base, p = imports152
    data = upload(session_client, base, docx()).data
    url = data["files"][0]["download_url"]
    other = Project.objects.create(workspace=workspace, name="Other", identifier="D153")
    ProjectMember.objects.create(project=other, member=create_user, role=20)
    assert session_client.get(url.replace(str(p.id), str(other.id))).status_code == 404
    BusinessRole.objects.filter(project=p, user=create_user).update(role="REPORTER")
    assert session_client.get(url).status_code == 403
    assert session_client.get(base + "document-imports/").data == []
    assert (
        session_client.post(
            base + f"document-imports/{data['id']}/confirm/", {}, format="json"
        ).status_code
        == 403
    )
    ProjectMember.objects.filter(project=p, member=create_user).update(is_active=False)
    assert session_client.get(url).status_code == 403


def test_sensitive_original_blocked_and_nonknowledge_permission_unchanged(
    session_client, imports152
):
    base, _ = imports152
    response = upload(session_client, base, docx("password=SuperSecret123456"))
    assert response.status_code == 201 and not response.data["valid"], response.content
    assert (
        session_client.post(
            base + f"document-imports/{response.data['id']}/confirm/", {}, format="json"
        ).status_code
        == 400
    )
    assert (
        upload(
            session_client, base, b"[]", "requirements.json", "requirements"
        ).status_code
        == 403
    )


@pytest.mark.parametrize("field", ["content", "tags"])
def test_multiline_import_fields_cannot_hide_sensitive_content(field):
    from plane.quality.document_imports import validate

    value = "普通说明。\npassword=SYNTHETIC_VALUE_160"
    row = {"title": "扫描边界", "content": "普通正文。"}
    row[field] = [value] if field == "tags" else value
    errors, normalized = validate("knowledge", [row])
    assert errors and normalized == []


def test_upload_size_and_legacy_doc_are_rejected(session_client, imports152):
    base, _ = imports152
    assert (
        upload(session_client, base, b"x" * (20 * 1024 * 1024 + 1)).status_code == 400
    )
    assert upload(session_client, base, b"legacy binary", "old.doc").status_code == 400


@pytest.mark.django_db(transaction=True)
def test_concurrent_confirmation_produces_exactly_one_article(imports152, create_user):
    from concurrent.futures import ThreadPoolExecutor
    from django.db import close_old_connections
    from rest_framework.test import APIClient

    base, project = imports152
    client = APIClient()
    client.force_authenticate(create_user)
    preview = upload(client, base, docx()).data

    def confirm():
        close_old_connections()
        try:
            other = APIClient()
            other.force_authenticate(create_user)
            response = other.post(
                base + f"document-imports/{preview['id']}/confirm/", {}, format="json"
            )
            return response.status_code, response.data.get("object_ids")
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: confirm(), range(2)))
    assert sorted(status for status, _ in results) == [200, 201], results
    assert results[0][1] == results[1][1]
    assert Article.objects.filter(project=project).count() == 1


def test_mixed_text_and_scanned_page_blocks_whole_pdf(session_client, imports152):
    from pypdf import PdfReader, PdfWriter

    source = PdfReader(BytesIO(pdf()))
    writer = PdfWriter()
    writer.add_page(source.pages[0])
    writer.add_blank_page(width=300, height=200)
    out = BytesIO()
    writer.write(out)
    base, _ = imports152
    response = upload(session_client, base, out.getvalue(), "mixed.pdf")
    assert response.status_code == 201 and not response.data["valid"]
    assert response.data["extraction"]["failures"][0]["page"] == 2
    assert "Actual PDF text" in response.data["rows"][0]["content"]
    assert (
        session_client.post(
            base + f"document-imports/{response.data['id']}/confirm/", {}, format="json"
        ).status_code
        == 400
    )


def test_docx_dangling_image_is_not_success(session_client, imports152):
    base, _ = imports152
    raw = docx(
        extra={
            "word/_rels/header1.xml.rels": b'<Relationships><Relationship Id="missing" Target="media/missing.png"/></Relationships>'
        }
    )
    response = upload(session_client, base, raw)
    assert response.status_code == 201 and not response.data["valid"], response.content


def test_pdf_image_and_attachment_manifest_are_downloadable(session_client, imports152):
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import (
        NameObject,
        DictionaryObject,
        DecodedStreamObject,
        NumberObject,
    )

    writer = PdfWriter()
    writer.add_page(PdfReader(BytesIO(pdf())).pages[0])
    image = DecodedStreamObject()
    image.set_data(b"\xff\x00\x00")
    image.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(1),
            NameObject("/Height"): NumberObject(1),
            NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
            NameObject("/BitsPerComponent"): NumberObject(8),
        }
    )
    writer.pages[0]["/Resources"][NameObject("/XObject")] = DictionaryObject(
        {NameObject("/Im1"): writer._add_object(image)}
    )
    writer.add_attachment("notes.txt", b"complete embedded attachment")
    out = BytesIO()
    writer.write(out)
    base, _ = imports152
    response = upload(session_client, base, out.getvalue(), "image.pdf")
    assert response.status_code == 201 and response.data["valid"], response.content
    assert response.data["extraction"]["image_count"] == 1
    assert response.data["extraction"]["attachment_count"] == 1
    image_file = next(f for f in response.data["files"] if f["kind"] == "image")
    preview = session_client.get(image_file["preview_url"])
    assert preview.status_code == 200
    assert b"".join(preview.streaming_content).startswith(b"\x89PNG")
    attachment = next(f for f in response.data["files"] if f["kind"] == "attachment")
    assert (
        b"".join(session_client.get(attachment["download_url"]).streaming_content)
        == b"complete embedded attachment"
    )


@pytest.mark.parametrize(
    "relations",
    [
        None,
        '<Relationships><Relationship Id="different" Target="media/image1.png"/></Relationships>',
        '<Relationships><Relationship Id="missing-image" Target="media/missing.png"/></Relationships>',
    ],
)
def test_docx_drawing_relationship_integrity_is_required(
    session_client, imports152, relations
):
    base, _ = imports152
    original = docx()
    output = BytesIO()
    with ZipFile(BytesIO(original)) as source, ZipFile(
        output, "w", ZIP_DEFLATED
    ) as dest:
        for name in source.namelist():
            if name == "word/_rels/document.xml.rels":
                continue
            raw = source.read(name)
            if name == "word/document.xml":
                raw = raw.replace(
                    b"<w:body>",
                    b'<w:body xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><w:p><w:r><w:drawing><a:blip r:embed="missing-image"/></w:drawing></w:r></w:p>',
                )
            dest.writestr(name, raw)
        if relations is not None:
            dest.writestr("word/_rels/document.xml.rels", relations)
    response = upload(session_client, base, output.getvalue())
    assert response.status_code == 201 and not response.data["valid"], response.content
    assert (
        session_client.post(
            base + f"document-imports/{response.data['id']}/confirm/", {}, format="json"
        ).status_code
        == 400
    )


def test_changed_original_cannot_download_or_confirm(
    session_client, imports152, settings
):
    from pathlib import Path
    from plane.quality.models import DocumentFile

    base, _ = imports152
    data = upload(session_client, base, docx()).data
    original = DocumentFile.objects.get(document_import_id=data["id"], kind="original")
    (
        Path(settings.QUALITY_ATTACHMENT_ROOT)
        / "document-imports"
        / original.storage_key
    ).write_bytes(b"changed original")
    assert (
        session_client.get(
            next(f["download_url"] for f in data["files"] if f["kind"] == "original")
        ).status_code
        == 409
    )
    assert (
        session_client.post(
            base + f"document-imports/{data['id']}/confirm/", {}, format="json"
        ).status_code
        == 409
    )


def test_pdf_inline_image_is_explicitly_blocked_instead_of_omitted(
    session_client, imports152
):
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import NameObject, DecodedStreamObject

    reader = PdfReader(BytesIO(pdf()))
    writer = PdfWriter()
    writer.add_page(reader.pages[0])
    stream = DecodedStreamObject()
    stream.set_data(
        writer.pages[0].get_contents().get_data()
        + b"\nq BI /W 1 /H 1 /CS /RGB /BPC 8 ID \xff\x00\x00 EI Q"
    )
    writer.pages[0][NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    base, _ = imports152
    response = upload(session_client, base, output.getvalue(), "inline.pdf")
    assert response.status_code == 201 and not response.data["valid"], response.content
    assert response.data["extraction"]["failures"]
