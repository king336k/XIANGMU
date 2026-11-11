# SPDX-License-Identifier: AGPL-3.0-only
"""Bounded local extraction. A failed range always blocks draft confirmation."""

import base64
import io
import json
import posixpath
import re
import stat
import subprocess
import sys
import zipfile

MAX_UPLOAD = 20 * 1024 * 1024
MAX_EXPANDED = 24 * 1024 * 1024
MAX_TEXT = 100000
MAX_PARTS = 1000
MAX_PAGES = 300


class ExtractionError(ValueError):
    pass


def budget(condition):
    if condition:
        raise ExtractionError("文档超过解析预算，请拆分后重试。")


def xml(raw):
    from lxml import etree

    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)
    root = etree.fromstring(raw, parser)
    if root.getroottree().docinfo.doctype or any(isinstance(node, etree._Entity) for node in root.iter()):
        raise ExtractionError("文档包含危险实体或DTD。")
    budget(sum(1 for _ in root.iter()) > 100000)
    return root


def parse_docx(raw):
    output = {
        "format": "docx",
        "page_count": None,
        "segments": [],
        "failures": [],
        "attachments": [],
        "safe_for_ocr": True,
        "image_locations": [],
    }
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        names = set()
        budget(len(infos) > MAX_PARTS or sum(item.file_size for item in infos) > MAX_EXPANDED)
        for item in infos:
            name = item.filename
            if (
                "\\" in name
                or name.startswith("/")
                or ":" in name
                or any(p in {".", ".."} for p in name.split("/"))
                or "\x00" in name
                or stat.S_ISLNK(item.external_attr >> 16)
                or item.flag_bits & 1
                or name in names
            ):
                raise ExtractionError("文档包含危险路径、重复条目或加密内容。")
            budget(item.file_size > MAX_EXPANDED or item.file_size > max(1, item.compress_size) * 200)
            names.add(name)
        if "word/document.xml" not in names or "[Content_Types].xml" not in names:
            raise ExtractionError("DOCX格式无效。")
        expanded = 0
        relationships = {}
        relationship_targets = {}
        image_references = []
        references = []
        rel_namespace = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
        for item in infos:
            if item.is_dir():
                continue
            data = archive.read(item)
            expanded += len(data)
            budget(expanded > MAX_EXPANDED)
            root = xml(data) if item.filename.endswith((".xml", ".rels")) else None
            if root is not None and not item.filename.endswith(".rels"):
                references.extend(
                    (item.filename, attr)
                    for node in root.iter()
                    for key, attr in node.attrib.items()
                    if key
                    in {
                        rel_namespace + "embed",
                        rel_namespace + "link",
                        rel_namespace + "id",
                    }
                )
            if item.filename.endswith(".rels"):
                relation_ids = set()
                targets = {}
                for rel in root:
                    relation_id = rel.get("Id", "")
                    if not relation_id or relation_id in relation_ids:
                        raise ExtractionError("文档关系ID缺失或重复。")
                    relation_ids.add(relation_id)
                    if rel.get("TargetMode", "").lower() == "external":
                        raise ExtractionError("文档包含外部图片或链接资源，请移除后重试。")
                    target = rel.get("Target", "")
                    if "\\" in target or target.startswith("/") or ":" in target:
                        raise ExtractionError("文档关系包含非法路径。")
                    # OPC relative parent paths are legal only while they remain inside the archive.
                    parent = posixpath.dirname(posixpath.dirname(item.filename))
                    resolved = posixpath.normpath(posixpath.join(parent, target))
                    if resolved.startswith("../"):
                        raise ExtractionError("文档关系包含非法路径。")
                    if resolved not in names:
                        raise ExtractionError("文档关系目标缺失，无法完整提取。")
                    targets[relation_id] = resolved
                relationships[item.filename] = relation_ids
                relationship_targets[item.filename] = targets
            if re.fullmatch(
                r"word/(document|header\d*|footer\d*|footnotes|endnotes|comments)\.xml",
                item.filename,
            ):
                if any(node.tag in {w + "altChunk", w + "subDoc"} for node in root.iter()):
                    raise ExtractionError("文档含无法完整提取的外部正文片段。")
                for index, paragraph in enumerate(root.iter(w + "p"), 1):
                    for node in paragraph.iter():
                        image_id = node.get(rel_namespace + "embed") or (
                            node.get(rel_namespace + "id") if node.tag.endswith("}imagedata") else None
                        )
                        if image_id:
                            image_references.append((item.filename,index,image_id))
                    pieces = []
                    for node in paragraph.iter():
                        if node.tag == w + "t":
                            pieces.append(node.text or "")
                        elif node.tag == w + "tab":
                            pieces.append("\t")
                        elif node.tag in {w + "br", w + "cr"}:
                            pieces.append("\n")
                    text = "".join(pieces)
                    if text.strip():
                        output["segments"].append({"part": item.filename, "paragraph": index, "text": text})
            if item.filename.startswith(("word/media/", "word/embeddings/")):
                output["attachments"].append(
                    {
                        "name": item.filename,
                        "kind": ("image" if item.filename.startswith("word/media/") else "attachment"),
                        "data": base64.b64encode(data).decode(),
                    }
                )
        for part, relation_id in references:
            rel_path = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
            if relation_id not in relationships.get(rel_path, set()):
                raise ExtractionError("文档引用的图片或附件关系缺失，无法完整提取。")
        for part, paragraph, relation_id in image_references:
            rel_path = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
            target = relationship_targets.get(rel_path,{}).get(relation_id)
            if not target or not target.startswith('word/media/'):
                raise ExtractionError("文档图片来源关系无效。")
            output['image_locations'].append({'part':part,'paragraph':paragraph,'source_image':target})
    return output


def parse_pdf(raw):
    from pypdf import PdfReader
    from pypdf.generic import (
        IndirectObject,
        DictionaryObject,
        ArrayObject,
        StreamObject,
        ContentStream,
    )

    reader = PdfReader(io.BytesIO(raw), strict=True)
    if reader.is_encrypted:
        raise ExtractionError("加密PDF不能导入，请使用未加密原件。")
    budget(len(reader.pages) > MAX_PAGES or sum(len(group) for group in reader.xref.values()) > 20000)
    output = {
        "format": "pdf",
        "page_count": len(reader.pages),
        "segments": [],
        "failures": [],
        "attachments": [],
        "safe_for_ocr": True,
    }
    seen = set()
    total = 0
    decoded = 0

    def walk(value, depth=0):
        nonlocal total, decoded
        budget(depth > 40)
        if isinstance(value, IndirectObject):
            key = (value.idnum, value.generation)
            if key in seen:
                return
            seen.add(key)
            value = value.get_object()
        total += 1
        budget(total > 100000)
        if isinstance(value, DictionaryObject):
            if any(
                key in value
                for key in (
                    "/JS",
                    "/JavaScript",
                    "/Launch",
                    "/RichMediaContent",
                    "/XFA",
                )
            ):
                raise ExtractionError("PDF含不支持的活动内容，无法完整提取。")
            if isinstance(value, StreamObject):
                if "/F" in value:
                    raise ExtractionError("PDF包含外部文件资源。")
                data = value.get_data()
                decoded += len(data)
                budget(decoded > MAX_EXPANDED)
                if value.get("/Subtype") == "/Image":
                    import struct
                    import zlib

                    filters = str(value.get("/Filter", ""))
                    extension = ".bin"
                    if "/DCTDecode" in filters:
                        extension = ".jpg"
                    elif "/JPXDecode" in filters:
                        extension = ".jp2"
                    elif value.get("/BitsPerComponent") == 8 and value.get("/ColorSpace") in (
                        "/DeviceRGB",
                        "/DeviceGray",
                    ):
                        width, height = int(value["/Width"]), int(value["/Height"])
                        channels = 3 if value["/ColorSpace"] == "/DeviceRGB" else 1
                        budget(width <= 0 or height <= 0 or width * height * channels > MAX_EXPANDED)
                        if len(data) == width * height * channels:

                            def chunk(kind, payload):
                                return (
                                    struct.pack(">I", len(payload))
                                    + kind
                                    + payload
                                    + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
                                )

                            stride = width * channels
                            pixels = b"".join(b"\x00" + data[y * stride : (y + 1) * stride] for y in range(height))
                            data = (
                                b"\x89PNG\r\n\x1a\n"
                                + chunk(
                                    b"IHDR",
                                    struct.pack(
                                        ">IIBBBBB",
                                        width,
                                        height,
                                        8,
                                        2 if channels == 3 else 0,
                                        0,
                                        0,
                                        0,
                                    ),
                                )
                                + chunk(b"IDAT", zlib.compress(pixels))
                                + chunk(b"IEND", b"")
                            )
                            extension = ".png"
                    output["attachments"].append(
                        {
                            "name": f"pdf-image-{len(output['attachments']) + 1}{extension}",
                            "kind": "image",
                            "data": base64.b64encode(data).decode(),
                        }
                    )
            for key, child in value.items():
                if key != "/Parent":
                    walk(child, depth + 1)
        elif isinstance(value, ArrayObject):
            for child in value:
                walk(child, depth + 1)

    walk(reader.trailer)
    # Iterate xref objects too: embedded files and otherwise unreferenced streams count toward budgets.
    for generation, offsets in reader.xref.items():
        if generation != 65535:
            for number in offsets:
                if number:
                    walk(IndirectObject(number, generation, reader))
    for index, page in enumerate(reader.pages, 1):
        contents = page.get_contents()
        if contents is not None and any(
            operator == b"INLINE IMAGE" for _, operator in ContentStream(contents, reader).operations
        ):
            output["safe_for_ocr"] = False
            output["failures"].append(
                {
                    "page": index,
                    "error": "此页包含暂不支持提取的内联图片，请转换为标准图片PDF后重试。",
                }
            )
        try:
            text = page.extract_text(extraction_mode="plain") or ""
        except Exception:
            output["safe_for_ocr"] = False
            output["failures"].append({"page": index, "error": "此页正文提取失败。"})
            text = ""
        if not text.strip():
            output["failures"].append({"page": index, "error": "此页没有可检索正文，可识别图片文字后核对。"})
        output["segments"].append({"page": index, "text": text})
    for name, values in reader.attachments.items():
        for index, data in enumerate(values, 1):
            output["attachments"].append(
                {
                    "name": f"attachments/{index}-{name}",
                    "kind": "attachment",
                    "data": base64.b64encode(data).decode(),
                }
            )
    return output


def extract_local(raw, extension):
    """Separate process gives PDF/XML parsers a hard memory/CPU/wall-clock boundary."""
    try:
        result = subprocess.run(
            [sys.executable, "-I", __file__, extension],
            input=raw,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            check=False,
        )
        if result.returncode:
            raise ExtractionError("文档解析超过资源预算或格式无效。")
        output = json.loads(result.stdout)
    except (subprocess.TimeoutExpired, ValueError):
        output = {
            "format": extension[1:],
            "segments": [],
            "attachments": [],
            "failures": [{"range": "document", "error": "文档解析失败或超过资源预算。"}],
            "safe_for_ocr": False,
        }
    return output


def main():
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    raw = sys.stdin.buffer.read(MAX_UPLOAD + 1)
    extension = sys.argv[1]
    try:
        budget(len(raw) > MAX_UPLOAD)
        result = parse_docx(raw) if extension == ".docx" else parse_pdf(raw)
        text = "\n\n".join(s["text"] for s in result["segments"])
        budget(len(text) > MAX_TEXT or len(result["segments"]) > 10000 or len(result["attachments"]) > MAX_PARTS)
        budget(sum(len(a["data"]) for a in result["attachments"]) > MAX_EXPANDED * 4 // 3 + MAX_PARTS * 4)
        if not text.strip() and not result["failures"]:
            result["failures"].append({"range": "document", "error": "文档没有可检索正文。"})
    except Exception as error:
        message = str(error) if isinstance(error, ExtractionError) else "文档格式无效或提取失败。"
        result = {
            "format": extension[1:],
            "segments": [],
            "attachments": [],
            "failures": [{"range": "document", "error": message}],
            "safe_for_ocr": False,
        }
    sys.stdout.write(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
