"""Server-only reuse of explicitly approved, current, sanitized diagnostic knowledge."""

from heapq import nsmallest
import re
from .retrieval import published, scan_article, scan_content

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


def semantic_ids(project, query):
    """Optional local recall only after an existing completed index; no lazy build or external embed."""
    from . import semantic_provider
    from .semantic import MAX_REVISIONS, content_hash, cosine
    from .semantic_models import SemanticProjectIndex, SemanticRevisionIndex

    config = semantic_provider.configuration(project.workspace_id)
    if config.get("source") != "builtin" or not config.get("configured") or scan_content(query):
        return []
    if not SemanticProjectIndex.objects.filter(
        project=project, fingerprint=config["fingerprint"], status="completed"
    ).exists():
        return []
    candidates = list(
        SemanticRevisionIndex.objects.filter(
            revision__in=[row.id for row in approved(project)], fingerprint=config["fingerprint"]
        )
        .select_related("revision")
        .order_by("id")[:MAX_REVISIONS]
    )
    candidates = [row for row in candidates if row.content_hash == content_hash(row.revision) and row.vectors]
    if not candidates:
        return []
    # Pin the already validated local configuration across the optional request.
    vector = semantic_provider.embed([query[:350]], config)[0]
    scores = [(max(cosine(vector, part) for part in row.vectors), row.revision_id) for row in candidates]
    return [pk for score, pk in sorted(scores, key=lambda item: (-item[0], str(item[1]))) if score >= 0.25][:20]


def rank_diagnostic_rows(rows, query, limit=5):
    """Pure relevance ranking within the caller's already authorized publications."""
    limit = max(0, min(limit, 5))
    if not limit:
        return []
    query = str(query)[:2000]
    terms = set(re.findall(r"[A-Za-z][A-Za-z0-9_.-]{2,}|[\u4e00-\u9fff]{2,}", query.lower()))
    for term in list(terms):
        if re.fullmatch(r"[\u4e00-\u9fff]+", term):
            terms.update(term[i : i + 2] for i in range(len(term) - 1))
    terms = sorted(terms, key=len, reverse=True)[:40]
    literals = [term for term in terms if re.fullmatch(r"[a-z][a-z0-9_.-]*_[a-z0-9_.-]+", term)]

    def scored():
        for row in rows:
            title, tags, text = row.title.lower(), " ".join(row.tags).lower(), row.content.lower()
            score = sum(
                (5 if term in title else 0) + (3 if term in tags else 0) + (1 if term in text else 0) for term in terms
            )
            if score:
                exact = any(
                    re.search(
                        r"(?<![a-z0-9_.-])" + re.escape(term) + r"(?![a-z0-9_.-])", title + "\n" + tags + "\n" + text
                    )
                    for term in literals
                )
                yield (-exact, -score, str(row.id)), row

    return [row for _, row in nsmallest(limit, scored(), key=lambda item: item[0])]


def search(project, query, limit=5):
    """Rank within the approved set; callers gain no knowledge browsing permission."""
    limit = max(0, min(limit, 5))
    if not limit:
        return []
    query = str(query)[:2000]
    ids = [str(row.id) for row in rank_diagnostic_rows(approved(project), query, limit)]
    if len(ids) < limit and query.strip():
        try:
            for identity in semantic_ids(project, query):
                key = str(identity)
                if key not in ids:
                    ids.append(key)
        except Exception:
            # The existing local embedding client has a12s timeout and zero SDK retries.
            # Optional ranking failure never hides a literal result.
            pass
    # Re-evaluate all candidates after optional I/O, including keyword hits.
    current = {str(row.id): row for row in approved(project)}
    return [current[key] for key in ids if key in current][:limit]
