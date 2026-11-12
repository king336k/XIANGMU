# SPDX-License-Identifier: AGPL-3.0-only
"""Validated project-list filters run on the authorized queryset before pagination."""

from functools import reduce
from operator import or_
from django.db.models import F, Q
from rest_framework import serializers
from rest_framework.exceptions import ValidationError


def choice(values):
    return serializers.ChoiceField(choices=values.split())


TEXT = serializers.CharField(max_length=255)
UUID = serializers.UUIDField()
PRIORITY = choice("urgent high medium low none")
SPECS = {
    "projectversion": {
        "search": ["name", "version", "description"],
        "status": ("status", choice("planning development testing ready released cancelled")),
        "version": ("version", TEXT),
        "owner_id": ("owner_id", UUID),
    },
    "testcase": {
        "search": ["title", "module", "preconditions"],
        "priority": ("priority", PRIORITY),
        "module": ("module", TEXT),
        "version": ("version", serializers.IntegerField(min_value=1)),
        "requirement_id": ("requirement_id", UUID),
    },
    "testplan": {
        "search": ["name", "description", "build", "environment"],
        "status": ("status", choice("pending ready running paused review completed returned cancelled failed")),
        "build": ("build", TEXT),
        "environment": ("environment", TEXT),
        "assignee_id": ("assignee_id", UUID),
    },
    "testexecution": {
        "search": ["item__revision__title", "actual_result", "item__plan__name"],
        "result": ("result", choice("passed failed blocked inconclusive skipped")),
        "build": ("item__plan__build", TEXT),
        "environment": ("item__plan__environment", TEXT),
        "plan_id": ("item__plan_id", UUID),
    },
    "defect": {
        "search": ["title", "description", "resolution"],
        "status": ("status", choice("open in_progress resolved closed")),
        "severity": ("severity", choice("critical major minor trivial")),
        "responsible_department": ("responsible_department", TEXT),
        "component": ("component", TEXT),
        "resolution_kind": ("resolution_kind", choice("fixed duplicate deferred not_reproducible not_a_bug wont_fix")),
        "assignee_id": ("assignee_id", UUID),
        "build": ("affected_build", TEXT),
        "fixed_build": ("fixed_build", TEXT),
        "source_system": ("sources__source_system__iexact", TEXT),
        "device": ("sources__device__icontains", TEXT),
        "task_id": ("sources__task_id", TEXT),
    },
    "requirement": {
        "search": ["issue__name", "issue__description_stripped", "acceptance"],
        "status": ("status", choice("draft review approved completed cancelled archived")),
        "priority": ("issue__priority", PRIORITY),
        "build": ("target_build", TEXT),
    },
    "testsuite": {"search": ["name", "description"], "published": ("published", serializers.BooleanField())},
    "release": {
        "search": ["name", "description", "version"],
        "status": ("status", choice("draft admitted")),
        "build": ("version", TEXT),
    },
    "savedreport": {"search": ["name", "plan__name"], "plan_id": ("plan_id", UUID)},
    "solution": {
        "search": ["title", "root_cause", "steps"],
        "status": ("status", choice("draft review approved rejected")),
    },
    "problempackage": {"search": ["name", "external_id"], "source_system": ("source_system__iexact", TEXT)},
    "article": {"search": ["title", "content"], "status": ("status", choice("draft review published offline"))},
    "conversation": {"search": ["title"]},
}


def filter_records(queryset, params, user):
    from .models import BusinessNumber
    from .numbering import PREFIXES

    resource = queryset.model._meta.label_lower
    numbered = resource in PREFIXES
    if queryset.model._meta.model_name == "defect" and params.get("category"):
        from .defect_categories import with_category, CATEGORIES

        category = serializers.ChoiceField(choices=list(CATEGORIES)).run_validation(params["category"])
        queryset = with_category(queryset).filter(defect_category=category)
    spec = SPECS.get(queryset.model._meta.model_name)
    if spec is None:
        return queryset
    if queryset.model._meta.model_name in {"testcase", "testsuite"}:
        deleted = serializers.BooleanField().run_validation(params.get("deleted", False))
        queryset = queryset.filter(trashed_at__isnull=not deleted)
    if (
        queryset.model._meta.model_name in {"testcase", "testplan", "testsuite", "defect"}
        and not params.get("deleted") == "true"
    ):
        archived = serializers.BooleanField().run_validation(params.get("archived", False))
        queryset = queryset.filter(archived_at__isnull=not archived)
    if params.get("search", "").strip():
        term = TEXT.run_validation(params["search"].strip())
        condition = reduce(or_, [Q(**{field + "__icontains": term}) for field in spec["search"]])
        if numbered:
            condition |= Q(
                pk__in=BusinessNumber.objects.filter(resource=resource, code__iexact=term).values("object_id")
            )
        elif queryset.model._meta.model_name == "requirement":
            from django.db.models.functions import Cast, Concat
            from django.db.models import CharField, Value

            queryset = queryset.annotate(
                public_code=Concat("project__identifier", Value("-R-"), Cast("number", CharField()))
            )
            condition |= Q(public_code__iexact=term)
        queryset = queryset.filter(condition)
    if numbered and (params.get("code") or params.get("number")):
        matches = BusinessNumber.objects.filter(resource=resource)
        if params.get("code"):
            matches = matches.filter(code__iexact=TEXT.run_validation(params["code"]))
        if params.get("number"):
            matches = matches.filter(number=serializers.IntegerField(min_value=1).run_validation(params["number"]))
        queryset = queryset.filter(pk__in=matches.values("object_id"))
    filters = {}
    source_filters = {}
    for key, (lookup, validator) in {k: v for k, v in spec.items() if k != "search"}.items():
        raw = params.get(key)
        if raw:
            try:
                if key == "assignee_id" and raw == "unassigned":
                    filters[lookup + "__isnull"] = True
                else:
                    destination = (
                        source_filters
                        if queryset.model._meta.model_name == "defect" and key in {"source_system", "device", "task_id"}
                        else filters
                    )
                    destination[lookup] = validator.run_validation(
                        str(user.id) if key == "assignee_id" and raw == "me" else raw
                    )
            except ValidationError as exc:
                raise ValidationError({key: exc.detail})
    if params.get("created_by_id"):
        try:
            filters["created_by_id"] = UUID.run_validation(
                str(user.id) if params["created_by_id"] == "me" else params["created_by_id"]
            )
        except ValidationError as exc:
            raise ValidationError({"created_by_id": exc.detail})
    dates = {}
    for key in ("created_after", "created_before"):
        if params.get(key):
            try:
                dates[key] = serializers.DateField().run_validation(params[key])
            except ValidationError as exc:
                raise ValidationError({key: exc.detail})
    if len(dates) == 2 and dates["created_after"] > dates["created_before"]:
        raise ValidationError({"created_before": "结束日期不能早于开始日期。"})
    from plane.utils.date_utils import china_date_filter

    filters.update(china_date_filter(dates.get("created_after"), dates.get("created_before")))
    if queryset.model._meta.model_name == "defect" and params.get("exclude_status"):
        raw_excluded = params.getlist("exclude_status") if hasattr(params, "getlist") else [params["exclude_status"]]
        excluded = [choice("open in_progress resolved closed").run_validation(value) for value in raw_excluded]
        queryset = queryset.exclude(status__in=excluded)
    if source_filters:
        generic = Q(**source_filters)
        daq = Q(daq_report__isnull=False)
        system = source_filters.get("sources__source_system__iexact")
        if system and system.casefold() != "daq":
            daq = Q(pk__isnull=True)
        if source_filters.get("sources__device__icontains"):
            daq &= Q(daq_report__binding__device__icontains=source_filters["sources__device__icontains"])
        task = source_filters.get("sources__task_id")
        if task:
            daq &= Q(daq_report__binding__platform_task_id=int(task)) if task.isdigit() else Q(pk__isnull=True)
        queryset = queryset.filter(generic | daq)
    queryset = queryset.filter(**filters)
    view = params.get("view")
    if view:
        allowed = ["all", "created_by_me"]
        if "assignee_id" in spec:
            allowed += ["assigned_to_me", "unassigned"]
        if queryset.model._meta.model_name == "defect":
            allowed += ["unclosed", "awaiting_regression"]
        choice(" ".join(allowed)).run_validation(view)
        if view == "created_by_me":
            queryset = queryset.filter(created_by=user)
        elif view == "assigned_to_me":
            queryset = queryset.filter(assignee=user)
        elif view == "unassigned":
            queryset = queryset.filter(assignee__isnull=True)
        elif view == "unclosed":
            queryset = queryset.exclude(status="closed")
        elif view == "awaiting_regression":
            queryset = queryset.filter(status="resolved")
    ordering = params.get("ordering", "-created_at")
    if queryset.model._meta.model_name == "projectversion":
        fields = ["created_at", "updated_at", "name", "version", "start_date", "target_date", "status"]
        choice(" ".join([*fields, *("-" + field for field in fields)])).run_validation(ordering)
        expression = F(ordering.removeprefix("-"))
        expression = expression.desc(nulls_last=True) if ordering.startswith("-") else expression.asc(nulls_last=True)
        return queryset.order_by(expression, "id").distinct()
    choice("created_at -created_at").run_validation(ordering)
    return queryset.order_by(ordering, "id").distinct()
