# SPDX-License-Identifier: AGPL-3.0-only
"""Permission scoped published text retrieval; never fetch arbitrary URLs."""

import re
from django.db.models import F, Q, OuterRef, Subquery, Value, CharField
from django.db.models.functions import Coalesce
from .models import PublishedRevision


def scan_content(content):
    # Findings describe locations and categories, never reproduce the matched value.
    placeholders = {
        "[已移除]",
        "[已脱敏]",
        "<已移除>",
        "<已脱敏>",
        "[redacted]",
        "<redacted>",
        "***redacted***",
        "***",
        "******",
    }

    def redacted(value):
        return value.strip().strip("\"'").casefold() in placeholders

    # Encoded JSON strings retain credential semantics when embedded in another record.
    for _ in range(32):
        decoded = content.replace('\\"', '"').replace("\\\\", "\\")
        if decoded == content:
            break
        content = decoded
    else:
        return [{"kind": "credential", "line": 1, "message": "嵌套编码过深，请展开后检查。"}]
    # Decode printable JSON unicode escapes before matching credential keys.
    # Newline escapes stay escaped so reported source line numbers remain stable.
    content = re.sub(
        r"\\u([0-9a-fA-F]{4})",
        lambda m: (
            chr(int(m.group(1), 16))
            if chr(int(m.group(1), 16)).isalnum() or chr(int(m.group(1), 16)) in "_-"
            else m.group(0)
        ),
        content,
    )
    findings = []
    patterns = [
        (
            "credential",
            r"(?i)(?<![\w])(?:password|passwd|pwd|api[_-]?key|client[_-]?secret|access[_-]?token|refresh[_-]?token"
            r"|secret|token|密码|密钥|口令|访问令牌)[\"']?\s*[:=：]\s*[\"']?"
            r"(?P<value>[^\s,;，；\"'\r\n}]+)",
        ),
        (
            "credential",
            r"(?im)(?<![\w])(?:authorization|proxy-authorization|cookie|set-cookie)[\"']?"
            r"\s*[:=：]\s*[\"']?(?P<value>[^\"'\r\n}]+)",
        ),
        ("private_key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        ("email", r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
        ("phone", r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    ]
    for kind, pattern in patterns:
        for match in re.finditer(pattern, content):
            value = match.groupdict().get("value")
            if value is not None:
                if redacted(value) or redacted(re.sub(r"(?i)^(?:Bearer|Basic)\s+", "", value)):
                    continue
            findings.append(
                {
                    "kind": kind,
                    "line": content[: match.start()].count("\n") + 1,
                    "message": {
                        "credential": "发现疑似账号凭据，请移除或脱敏后重新扫描。",
                        "private_key": "发现私钥标记，请移除完整私钥。",
                        "email": "发现邮箱，请移除或匿名化。",
                        "phone": "发现手机号，请移除或匿名化。",
                    }[kind],
                }
            )
            if sum(row["kind"] == kind for row in findings) >= 30:
                break
    return findings


def scan_article(title, content, tags):
    return [
        {**finding, "field": field}
        for field, value in [("title", title), ("content", content), ("tags", "\n".join(tags))]
        for finding in scan_content(value)
    ]


def published(project):
    from .sharing_models import KnowledgeShare

    shared = KnowledgeShare.objects.filter(
        target_project=project,
        active=True,
        project__archived_at__isnull=True,
        target_project__archived_at__isnull=True,
        project__workspace_id=F("target_project__workspace_id"),
        revision__article_id=F("article_id"),
        revision__project_id=F("project_id"),
        article__project_id=F("project_id"),
        revision__version=F("article__published_version"),
        article__publication_active=True,
    ).values("revision_id")
    grants = KnowledgeShare.objects.filter(target_project=project, active=True, revision_id=OuterRef("pk"))
    return (
        PublishedRevision.objects.filter(
            Q(project=project) | Q(pk__in=shared),
            project__archived_at__isnull=True,
            article__publication_active=True,
            version=F("article__published_version"),
        )
        .select_related("project")
        .annotate(
            share_device_scope=Coalesce(
                Subquery(grants.values("device_scope")[:1]), Value(""), output_field=CharField()
            ),
            share_version_scope=Coalesce(
                Subquery(grants.values("version_scope")[:1]), Value(""), output_field=CharField()
            ),
        )
    )


def keyword_search(project, query):
    terms = set(re.findall(r"[A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,}", query.strip()))
    for token in list(terms):
        if re.fullmatch(r"[\u4e00-\u9fff]+", token) and len(token) > 2:
            terms.update(token[i : i + 2] for i in range(len(token) - 1))
    terms = sorted(terms, key=len, reverse=True)[:24]
    qs = published(project)
    if not terms:
        return qs.none() if query.strip() else qs
    condition = Q()
    for term in terms:
        condition |= Q(title__icontains=term) | Q(content__icontains=term)
    return qs.filter(condition)


def search(project, query):
    # Preserve every literal match; optional semantic recall can only add current publications.
    keyword = keyword_search(project, query)
    if not query.strip():
        return keyword
    try:
        from .semantic import ranked_ids

        ids = ranked_ids(project, query)
    except Exception:
        ids = None
    if not ids:
        return keyword
    from django.db.models import Case, When, IntegerField

    return (
        published(project)
        .filter(Q(pk__in=keyword.values("pk")) | Q(pk__in=ids))
        .annotate(
            semantic_order=Case(When(pk__in=keyword.values("pk"), then=0), default=1, output_field=IntegerField()),
            semantic_rank=Case(
                *[When(pk=pk, then=index) for index, pk in enumerate(ids)], default=0, output_field=IntegerField()
            ),
        )
        .order_by("semantic_order", "semantic_rank", "id")
    )
