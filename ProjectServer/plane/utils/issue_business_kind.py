"""Optional project-list presentation scope; never a global issue or detail restriction."""

from rest_framework.exceptions import ParseError


def filter_issue_business_kind(queryset, query_params, project_id):
    values = (
        query_params.getlist("business_kind")
        if hasattr(query_params, "getlist")
        else [query_params.get("business_kind", "all")]
    )
    if not values:
        return queryset
    if len(values) != 1 or values[0] not in {"task", "requirement", "all"}:
        raise ParseError("business_kind must be task, requirement or all.")
    if values[0] == "all":
        return queryset
    from plane.quality.models import Requirement

    requirements = Requirement.objects.filter(project_id=project_id).values("issue_id")
    return queryset.exclude(pk__in=requirements) if values[0] == "task" else queryset.filter(pk__in=requirements)
