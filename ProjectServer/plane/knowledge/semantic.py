"""Bounded semantic ranking over current published revisions; keywords remain available."""

import hashlib
import time
from uuid import uuid4
from django.db import transaction
from django.utils import timezone
from . import semantic_provider
from .semantic_models import SemanticProjectIndex, SemanticRevisionIndex
from .semantic_vectors import normalized_vector, cosine  # noqa: F401

MAX_REVISIONS = 128
MAX_CHUNKS = 256


def document(revision):
    return revision.title + "\n" + revision.content + "\n" + "\n".join(revision.tags)


def content_hash(revision):
    return hashlib.sha256(document(revision).encode()).hexdigest()


def request_build(project, actor=None):
    config = semantic_provider.configuration(project.workspace_id)
    if not config["configured"]:
        raise ValueError("EMBEDDING_UNCONFIGURED")
    from .retrieval import published

    snapshot_hash = hashlib.sha256(
        "\n".join(
            f"{row.id}:{content_hash(row)}" for row in published(project).order_by("id")[: MAX_REVISIONS + 1]
        ).encode()
    ).hexdigest()
    with transaction.atomic():
        job, _ = SemanticProjectIndex.objects.select_for_update().get_or_create(
            project=project, defaults={"token": uuid4(), "fingerprint": config["fingerprint"], "created_by": actor}
        )
        if (
            job.fingerprint == config["fingerprint"]
            and job.snapshot_hash == snapshot_hash
            and job.status in {"queued", "running"}
            and job.started_at
            and (timezone.now() - job.started_at).total_seconds() < 180
        ):
            return job
        job.snapshot_hash = snapshot_hash
        job.token = uuid4()
        job.fingerprint = config["fingerprint"]
        job.status = "queued"
        job.error_code = ""
        job.started_at = timezone.now()
        if actor is not None:
            job.created_by = actor
        job.save()
        return job


def enqueue(project_id, token):
    from .semantic_tasks import build_semantic_index

    try:
        build_semantic_index.delay(str(project_id), str(token))
    except Exception:
        SemanticProjectIndex.objects.filter(project_id=project_id, token=token).update(
            status="failed", error_code="INDEX_QUEUE_UNAVAILABLE"
        )


def schedule_if_opted_in(project):
    config = semantic_provider.configuration(project.workspace_id)
    if config["configured"] and (
        config.get("source") == "builtin"
        or SemanticProjectIndex.objects.filter(project=project, fingerprint=config["fingerprint"]).exists()
    ):
        job = request_build(project)
        transaction.on_commit(lambda: enqueue(project.id, job.token))


def run_build(project_id, token):
    from .retrieval import published, scan_content

    from plane.db.models import Project

    workspace_id = Project.objects.get(pk=project_id).workspace_id
    config = semantic_provider.configuration(workspace_id)
    job = SemanticProjectIndex.objects.filter(project_id=project_id, token=token).first()
    if not job:
        return {"status": "stale"}
    if not config["configured"] or job.fingerprint != config["fingerprint"]:
        SemanticProjectIndex.objects.filter(pk=job.pk, token=token).update(
            status="failed", error_code="CONFIGURATION_CHANGED"
        )
        return {"status": "unconfigured"}
    if not SemanticProjectIndex.objects.filter(pk=job.pk, token=token, status="queued").update(status="running"):
        return {"status": job.status}
    error = ""
    try:
        if job.created_by_id:
            from plane.quality.permissions import knowledge_reviewer

            if not knowledge_reviewer(project_id, job.created_by_id):
                raise ValueError("INDEX_PERMISSION_REVOKED")
        revisions = list(published(job.project).order_by("id")[: MAX_REVISIONS + 1])
        if len(revisions) > MAX_REVISIONS:
            raise ValueError("INDEX_REVISION_BUDGET")
        prepared = []
        total_chunks = 0
        for revision in revisions:
            text = document(revision)
            if scan_content(text):
                raise ValueError("SENSITIVE_CONTENT")
            digest = content_hash(revision)
            existing = SemanticRevisionIndex.objects.filter(
                revision=revision, fingerprint=config["fingerprint"], content_hash=digest
            ).exists()
            if existing:
                continue
            chunks = [text[offset : offset + 350] for offset in range(0, len(text), 350)]
            total_chunks += len(chunks)
            if total_chunks > MAX_CHUNKS:
                raise ValueError("INDEX_CHUNK_BUDGET")
            prepared.append((revision, digest, chunks))
        started = time.monotonic()
        for revision, digest, chunks in prepared:
            vectors = []
            for offset in range(0, len(chunks), 16):
                if not published(job.project).filter(pk=revision.pk).exists():
                    break
                if job.created_by_id and not knowledge_reviewer(project_id, job.created_by_id):
                    raise ValueError("INDEX_PERMISSION_REVOKED")
                if time.monotonic() - started > 90:
                    raise ValueError("INDEX_TIME_BUDGET")
                if not SemanticProjectIndex.objects.filter(pk=job.pk, token=token, status="running").exists():
                    return {"status": "stale"}
                if (
                    semantic_provider.configuration(workspace_id)["fingerprint"] != config["fingerprint"]
                    or not semantic_provider.configuration(workspace_id)["configured"]
                ):
                    raise ValueError("CONFIGURATION_CHANGED")
                vectors.extend(semantic_provider.embed(chunks[offset : offset + 16], config))
            with transaction.atomic():
                # Publication can be revoked while the external request is in flight.
                if not published(job.project).filter(pk=revision.pk).exists() or len(vectors) != len(chunks):
                    continue
                SemanticRevisionIndex.objects.update_or_create(
                    revision=revision,
                    fingerprint=config["fingerprint"],
                    defaults={"project": revision.project, "content_hash": digest, "vectors": vectors},
                )
    except Exception as exc:
        error = (
            str(exc)
            if isinstance(exc, ValueError)
            and str(exc)
            in {
                "INDEX_PERMISSION_REVOKED",
                "SENSITIVE_CONTENT",
                "INDEX_REVISION_BUDGET",
                "INDEX_CHUNK_BUDGET",
                "INDEX_TIME_BUDGET",
                "CONFIGURATION_CHANGED",
            }
            else "EMBEDDING_PROVIDER_FAILED"
        )
    state = "failed" if error else "completed"
    SemanticProjectIndex.objects.filter(pk=job.pk, token=token).update(status=state, error_code=error)
    return {"status": state, "error_code": error}


def ranked_ids(project, query):
    from .retrieval import published, scan_content

    config = semantic_provider.configuration(project.workspace_id)
    if not config["configured"] or not query.strip() or scan_content(query):
        return None
    if not SemanticProjectIndex.objects.filter(
        project=project, fingerprint=config["fingerprint"], status="completed"
    ).exists():
        if config.get("source") == "builtin" and published(project).exists():
            recent = SemanticProjectIndex.objects.filter(project=project, fingerprint=config["fingerprint"]).first()
            if not recent or not recent.started_at or (timezone.now() - recent.started_at).total_seconds() >= 180:
                job = request_build(project)
                transaction.on_commit(lambda: enqueue(project.id, job.token))
        return None
    candidates = list(
        SemanticRevisionIndex.objects.filter(revision__in=published(project), fingerprint=config["fingerprint"])
        .select_related("revision")
        .order_by("id")[:MAX_REVISIONS]
    )
    candidates = [row for row in candidates if row.content_hash == content_hash(row.revision)]
    if not candidates:
        return None
    try:
        vector = semantic_provider.embed([query[:350]], config)[0]
        scores = [
            (max(cosine(vector, part) for part in row.vectors), row.revision_id) for row in candidates if row.vectors
        ]
        return [pk for score, pk in sorted(scores, key=lambda item: (-item[0], str(item[1]))) if score >= 0.25][:20]
    except Exception:
        return None
