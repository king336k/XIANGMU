# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.db.models import Case, CharField, F, IntegerField, Min, OuterRef, Subquery, Value, When
from rest_framework.exceptions import ParseError

# Custom ordering for priority and state
PRIORITY_ORDER = ["urgent", "high", "medium", "low", "none"]
STATE_ORDER = ["backlog", "unstarted", "started", "completed", "cancelled"]

# ---------------------------------------------------------------------------
# order_by allowlists — one per model/endpoint family
# All contain bare field names (no leading '-'); the sanitizer strips the
# prefix before looking up, so descending variants are implicitly covered.
# Prevents ORM order_by injection via user-supplied query params.
# ---------------------------------------------------------------------------

ISSUE_ORDER_BY_ALLOWLIST = frozenset(
    {
        "created_at",
        "updated_at",
        "sequence_id",
        "sort_order",
        "target_date",
        "start_date",
        "completed_at",
        "archived_at",
        "priority",
        "state__name",
        "state__group",
        "assignees__first_name",
        "labels__name",
        "issue_module__module__name",
    }
)

# IntakeIssue queryset — fields are prefixed with `issue__` for the join.
INTAKE_ISSUE_ORDER_BY_ALLOWLIST = frozenset(
    {
        "issue__created_at",
        "issue__updated_at",
        "issue__sequence_id",
        "issue__sort_order",
        "issue__target_date",
        "issue__start_date",
        "issue__priority",
        "issue__state__name",
        "created_at",
        "updated_at",
        "status",
    }
)

# IssueActivity queryset (user activity, workspace member activity).
ACTIVITY_ORDER_BY_ALLOWLIST = frozenset(
    {
        "created_at",
        "updated_at",
    }
)

# Project list queryset.
PROJECT_ORDER_BY_ALLOWLIST = frozenset(
    {
        "created_at",
        "updated_at",
        "name",
        "network",
        "sort_order",
    }
)

# Saved view (IssueView) list queryset.
VIEW_ORDER_BY_ALLOWLIST = frozenset(
    {
        "created_at",
        "updated_at",
        "name",
    }
)

# Notification queryset.
NOTIFICATION_ORDER_BY_ALLOWLIST = frozenset(
    {
        "created_at",
        "updated_at",
    }
)

# Page list queryset.
PAGE_ORDER_BY_ALLOWLIST = frozenset(
    {
        "created_at",
        "updated_at",
        "name",
        "sort_order",
    }
)

# ---------------------------------------------------------------------------
# group_by / sub_group_by allowlist for Issue querysets — used by
# GroupedOffsetPaginator / SubGroupedOffsetPaginator (plane/utils/paginator.py),
# which pass the field name straight into F(), .values(), .order_by(), and
# Window partition_by. Prevents unauthenticated ORM field-name injection via
# user-supplied query params.
# ---------------------------------------------------------------------------
ISSUE_GROUP_BY_ALLOWLIST = frozenset(
    {
        "state_id",
        "state__group",
        "priority",
        "labels__id",
        "assignees__id",
        "issue_module__module_id",
        "cycle_id",
        "project_id",
        "created_by",
        "target_date",
        "start_date",
    }
)

# Cycle list queryset.
CYCLE_ORDER_BY_ALLOWLIST = frozenset(
    {
        "created_at",
        "updated_at",
        "name",
        "start_date",
        "end_date",
        "sort_order",
    }
)

# Module list queryset.
MODULE_ORDER_BY_ALLOWLIST = frozenset(
    {
        "created_at",
        "updated_at",
        "name",
        "start_date",
        "target_date",
        "status",
        "sort_order",
    }
)


def sanitize_order_by(value, allowed_fields, default="-created_at"):
    """Return a safe ordering string derived from *value*.

    Strips at most one leading '-' (descending indicator), checks the bare
    field name against *allowed_fields*, and reconstructs the value.  Inputs
    with multiple leading dashes (e.g. ``--created_at``) are rejected and
    *default* is returned instead, preventing both allowlist bypass and
    malformed tokens from reaching ``.order_by()``.

    Call this before passing any user-supplied ordering string to .order_by() or
    a paginator to prevent ORM order_by injection.
    """
    if not value:
        return default
    is_desc = value.startswith("-")
    bare = value[1:] if is_desc else value
    # Reject malformed prefixes like "--created_at".
    if bare.startswith("-"):
        return default
    if bare not in allowed_fields:
        return default
    return f"-{bare}" if is_desc else bare


# Native issue columns only; external endpoint allowlists remain unchanged.
ISSUE_SORT_ALLOWLIST = ISSUE_ORDER_BY_ALLOWLIST | {
    "name",
    "issue_cycle__cycle__name",
    "estimate_point__key",
}


def sanitize_issue_order_by(value):
    """Accept up to five ordered native issue columns, rejecting the entire
    multi-column expression if any token is invalid. Single-column callers
    retain their historical safe fallback.
    """
    if not isinstance(value, str):
        return ["-created_at"]
    if "," not in value:
        return [sanitize_order_by(value, ISSUE_SORT_ALLOWLIST)]
    tokens = value.split(",")
    fields = [token.removeprefix("-") for token in tokens]
    if len(tokens) > 5 or len(set(fields)) != len(fields) or any(field not in ISSUE_SORT_ALLOWLIST for field in fields):
        raise ParseError("Invalid issue order_by: use up to five distinct supported fields.")
    return tokens


def ordering_expressions(tokens):
    """Use the same complete ordering for querysets and pagination windows."""
    expressions = []
    fields = set()
    for token in tokens:
        descending = token.startswith("-")
        field = token[1:] if descending else token
        fields.add(field)
        expression = F(field)
        expressions.append(expression.desc(nulls_last=True) if descending else expression.asc(nulls_last=True))
    if "created_at" not in fields:
        expressions.append(F("created_at").desc(nulls_last=True))
    if "id" not in fields:
        expressions.append(F("id").asc())
    return expressions


def _order_multiple_issue_columns(queryset, tokens):
    annotations = {}
    ordering = []
    for index, token in enumerate(tokens):
        descending = token.startswith("-")
        field = token.removeprefix("-")
        alias = f"issue_sort_{index}"
        if field == "priority":
            annotations[alias] = Case(
                *[When(priority=value, then=Value(rank)) for rank, value in enumerate(PRIORITY_ORDER)],
                default=Value(len(PRIORITY_ORDER)),
                output_field=IntegerField(),
            )
            # Existing native priority direction: -priority means urgent first.
            descending = not descending
        elif field == "state__group":
            annotations[alias] = Case(
                *[When(state__group=value, then=Value(rank)) for rank, value in enumerate(STATE_ORDER)],
                default=Value(len(STATE_ORDER)),
                output_field=IntegerField(),
            )
            # Preserve the existing single-column state-group ordering.
            descending = False
        elif field in {
            "labels__name",
            "assignees__first_name",
            "issue_module__module__name",
            "issue_cycle__cycle__name",
        }:
            # Aggregate each relation independently. Joining several m2m columns
            # into the outer query would multiply rows and corrupt page windows.
            minimum = (
                queryset.model.objects.filter(pk=OuterRef("pk"))
                .order_by()
                .values("pk")
                .annotate(value=Min(field))
                .values("value")[:1]
            )
            annotations[alias] = Subquery(minimum)
        else:
            alias = field
        ordering.append(f"-{alias}" if descending else alias)
    queryset = queryset.annotate(**annotations)
    return queryset.order_by(*ordering_expressions(ordering)), ordering


def order_issue_queryset(issue_queryset, order_by_param="-created_at"):
    # Reject any field that is not in the allowlist before building the queryset.
    # An unrecognised value is silently replaced with the safe default so callers
    # receive consistent output rather than an ORM error or data leak.
    tokens = sanitize_issue_order_by(order_by_param)
    if len(tokens) > 1:
        return _order_multiple_issue_columns(issue_queryset, tokens)
    order_by_param = tokens[0]
    # Priority Ordering
    if order_by_param == "priority" or order_by_param == "-priority":
        issue_queryset = issue_queryset.annotate(
            priority_order=Case(
                *[When(priority=p, then=Value(i)) for i, p in enumerate(PRIORITY_ORDER)],
                output_field=CharField(),
            )
        ).order_by("priority_order", "-created_at")
        order_by_param = "priority_order" if order_by_param.startswith("-") else "-priority_order"
    # State Ordering
    elif order_by_param in ["state__group", "-state__group"]:
        state_order = STATE_ORDER if order_by_param in ["state__name", "state__group"] else STATE_ORDER[::-1]
        issue_queryset = issue_queryset.annotate(
            state_order=Case(
                *[When(state__group=state_group, then=Value(i)) for i, state_group in enumerate(state_order)],
                default=Value(len(state_order)),
                output_field=CharField(),
            )
        ).order_by("state_order", "-created_at")
        order_by_param = "-state_order" if order_by_param.startswith("-") else "state_order"
    # assignee and label ordering
    elif order_by_param in [
        "labels__name",
        "assignees__first_name",
        "issue_module__module__name",
        "issue_cycle__cycle__name",
        "-issue_cycle__cycle__name",
        "-labels__name",
        "-assignees__first_name",
        "-issue_module__module__name",
    ]:
        issue_queryset = issue_queryset.annotate(
            min_values=Min(order_by_param[1::] if order_by_param.startswith("-") else order_by_param)
        ).order_by(
            "-min_values" if order_by_param.startswith("-") else "min_values",
            "-created_at",
        )
        order_by_param = "-min_values" if order_by_param.startswith("-") else "min_values"
    else:
        # If the order_by_param is created_at, then don't add the -created_at
        if "created_at" in order_by_param:
            issue_queryset = issue_queryset.order_by(order_by_param)
        else:
            issue_queryset = issue_queryset.order_by(order_by_param, "-created_at")
        order_by_param = order_by_param
    return issue_queryset, order_by_param
