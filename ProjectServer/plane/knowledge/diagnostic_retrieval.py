"""Server-only reuse of explicitly approved, current, sanitized diagnostic knowledge."""

import re
from .retrieval import published, scan_article

APPROVED_TAG = "daq-diagnostic-approved"


def approved(project):
    rows = (
        published(project)
        .filter(
            tags__contains=[APPROVED_TAG],
            article__tags__contains=[APPROVED_TAG],
            article__status="published",
            article__scanned_version__gt=0,
            article__scan_findings=[],
        )
        .select_related("article")
        .order_by("-created_at", "id")[:200]
    )
    return [row for row in rows if not scan_article(row.title, row.content, row.tags)]


def search(project, query, limit=5):
    """Rank within the approved set; callers gain no knowledge browsing permission."""
    terms = set(re.findall(r"[A-Za-z][A-Za-z0-9_.-]{2,}|[\u4e00-\u9fff]{2,}", str(query)[:2000].lower()))
    for term in list(terms):
        if re.fullmatch(r"[\u4e00-\u9fff]+", term):
            terms.update(term[i : i + 2] for i in range(len(term) - 1))
    terms = sorted(terms, key=len, reverse=True)[:40]
    ranked = []
    for row in approved(project):
        title, tags, text = row.title.lower(), " ".join(row.tags).lower(), row.content.lower()
        score = sum(
            (5 if term in title else 0) + (3 if term in tags else 0) + (1 if term in text else 0) for term in terms
        )
        if score:
            ranked.append((score, row))
    ranked.sort(key=lambda item: (-item[0], str(item[1].id)))
    return [row for _, row in ranked[: max(0, min(limit, 5))]]
