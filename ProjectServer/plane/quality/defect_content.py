"""Keep a concise DAQ title and retain structured context in the description."""

import re

FIELDS = ("问题范围", "发生阶段", "受影响模块", "异常类型", "现场描述", "时间说明")
PATTERN = re.compile(r"(" + "|".join(FIELDS) + r")[：:]\s*([\s\S]*?)(?=(?:" + "|".join(FIELDS) + r")[：:]|$)")


def defect_content(title, description):
    title_fields = {key: value.strip() for key, value in PATTERN.findall(title)}
    if not title_fields:
        return title, description
    description_fields = {key: value.strip() for key, value in PATTERN.findall(description)}
    fields = {**title_fields, **description_fields}
    scene = (
        description_fields.get("现场描述")
        or (description.strip() if not description_fields else "")
        or title_fields.get("现场描述")
        or "DAQ异常反馈"
    )
    concise = scene.splitlines()[0].strip()[:200]
    if any(key in title_fields and key not in description_fields for key in FIELDS[:4]):
        lines = [f"{key}：{fields.get(key) or '未记录'}" for key in FIELDS[:4]]
        lines.append("现场描述：" + scene)
        if fields.get("时间说明"):
            lines.append("时间说明：" + fields["时间说明"])
        description = "\n\n".join(lines)
    return concise, description
