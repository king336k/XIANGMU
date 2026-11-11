"""Project-scoped public references; internal UUID relations remain unchanged."""

from django.db.models import Max

PREFIXES = {
    "quality.defect": "D",
    "quality.testcase": "C",
    "quality.testplan": "P",
    "quality.testsuite": "S",
    "quality.testexecution": "E",
    "quality.solution": "SOL",
    "quality.release": "REL",
    "quality.projectversion": "V",
    "quality.problempackage": "PKG",
    "quality.savedreport": "REP",
    "quality.testresource": "RES",
    "quality.fieldagent": "AG",
    "knowledge.article": "K",
}


def allocate(record, project, using):
    from .models import BusinessNumber

    resource = record._meta.label_lower
    rows = BusinessNumber.objects.using(using)
    last = rows.filter(project_id=record.project_id, resource=resource).aggregate(last=Max("number"))["last"] or 0
    prefix = f"{project.identifier}-{PREFIXES[resource]}-"
    previous = (
        rows.filter(workspace_id=project.workspace_id, code__startswith=prefix).aggregate(last=Max("number"))["last"]
        or 0
    )
    number = max(last, previous) + 1
    record._business_number = rows.create(
        project_id=record.project_id,
        workspace_id=project.workspace_id,
        resource=resource,
        object_id=record.pk,
        number=number,
        code=f"{prefix}{number}",
    )


def metadata(record):
    from .models import BusinessNumber

    if record._meta.label_lower not in PREFIXES:
        return {}
    if not hasattr(record, "_business_number"):
        record._business_number = BusinessNumber.objects.filter(
            resource=record._meta.label_lower,
            object_id=record.pk,
            project_id=record.project_id,
        ).first()
    row = record._business_number
    return {"number": row.number, "code": row.code} if row else {}


def preload(records):
    from .models import BusinessNumber

    if not records or records[0]._meta.label_lower not in PREFIXES:
        return
    by_id = {
        row.object_id: row
        for row in BusinessNumber.objects.filter(
            resource=records[0]._meta.label_lower,
            object_id__in=[record.pk for record in records],
        )
    }
    for record in records:
        record._business_number = by_id.get(record.pk)
