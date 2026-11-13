"""Resolve human-facing FILE citations within one defect without changing evidence IDs."""

import re
from .models import PackageFile

REFERENCE = re.compile(
    r"FILE-([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
    r"(?::([^\n\r,，;；。\]\)<>\"']+))?"
)


def readable_references(text, project_id, defect_id, context=None, markdown=False):
    if not isinstance(text, str) or "FILE-" not in text:
        return text
    cache = context if context is not None else {}
    key = ("evidence_reference_names", str(project_id), str(defect_id))
    if key not in cache:
        cache[key] = {
            str(file_id): name
            for file_id, name in PackageFile.objects.filter(
                project_id=project_id,
                package__project_id=project_id,
                package__defect_id=defect_id,
                package__status="files_verified",
            ).values_list("id", "name")
        }

    def replace(match):
        name = cache[key].get(match[1].lower())
        if not name:
            return "材料不可用"
        entry = (match[2] or "").strip()
        if re.fullmatch(r"feedback(?:-version)?-[0-9a-f-]{36}\.json", name, re.I):
            name = f"现场快照（{name}）"
        label = f"{name} / {entry}" if entry else name
        return re.sub(r"([\\`*_{}\[\]()<>#!|])", r"\\\1", label) if markdown else label

    return REFERENCE.sub(replace, text)
