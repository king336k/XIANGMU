# SPDX-License-Identifier: AGPL-3.0-only
"""Bound historical event reads without hiding records beyond a fixed cap."""

from types import SimpleNamespace

from .views import QualityPagination


def event_page(queryset, request=None):
    paginator = QualityPagination()
    rows = paginator.paginate_queryset(queryset, request or SimpleNamespace(query_params={}))
    page = paginator.page
    return rows, {
        "count": page.paginator.count,
        "page": page.number,
        "per_page": page.paginator.per_page,
        "next": page.next_page_number() if page.has_next() else None,
        "previous": page.previous_page_number() if page.has_previous() else None,
    }
