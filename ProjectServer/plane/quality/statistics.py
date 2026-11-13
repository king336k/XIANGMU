# SPDX-License-Identifier: AGPL-3.0-only
from datetime import timedelta
from zoneinfo import ZoneInfo
from django.db.models import Subquery, OuterRef, F, ExpressionWrapper, DurationField, Avg, Count
from rest_framework import serializers
from .defect_categories import with_category
from .models import DefectEvent
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework.response import Response
from plane.utils.date_utils import china_date_filter
from .filters import filter_records
from .models import Defect
from .views import QualityView


def statistics_queryset(project, params, user):
    filtered = filter_records(Defect.objects.filter(project=project), params, user)
    # A subquery preserves exactly the filtered identities without join duplication or pagination.
    qs = Defect.objects.filter(pk__in=filtered.values("pk"))
    first = serializers.DateField().run_validation(params["start"]) if params.get("start") else None
    last = serializers.DateField().run_validation(params["end"]) if params.get("end") else None
    if first and last and first > last:
        raise serializers.ValidationError({"end": "结束日期不能早于开始日期。"})
    qs = qs.filter(**china_date_filter(first, last))
    qs = with_category(qs)
    return qs


class DefectStatistics(QualityView):
    def get(self, request, **kwargs):
        qs = statistics_queryset(self.project(), request.query_params, request.user)
        stage_rows, response_pending = stage_statistics(qs)

        def groups(field):
            return [
                {"value": row[field], "count": row["count"]}
                for row in qs.order_by().values(field).annotate(count=Count("pk")).order_by(field)
            ]

        cutoff = timezone.localdate(timezone.now(), ZoneInfo("Asia/Shanghai")) - timedelta(days=29)
        daily = (
            qs.filter(**china_date_filter(cutoff, None))
            .annotate(day=TruncDate("created_at", tzinfo=ZoneInfo("Asia/Shanghai")))
            .order_by()
            .values("day")
            .annotate(count=Count("pk"))
            .order_by("day")
        )
        return Response(
            {
                "total": qs.count(),
                "unclosed": qs.exclude(status="closed").count(),
                "by_status": groups("status"),
                "by_severity": groups("severity"),
                "by_category": groups("defect_category"),
                "stage_durations": stage_rows,
                "response_pending": response_pending,
                "stage_scope": (
                    "按筛选范围内创建的缺陷统计首轮：创建→首次开始处理→首次修复→首次关闭；"
                    "仅计有对应事件的样本，未完成不记为0小时。"
                ),
                "opened_by_day": [{"date": row["day"], "count": row["count"]} for row in daily],
                "scope": "当前项目权限范围内、满足相同筛选条件的全部缺陷，未受分页影响；新增趋势为最近30天。",
            }
        )


def stage_statistics(qs):
    def event_time(status):
        return (
            DefectEvent.objects.filter(defect_id=OuterRef("pk"), status=status)
            .exclude(previous_status=status)
            .order_by("created_at", "id")
            .values("created_at")[:1]
        )

    rows = qs.annotate(
        response_at=Subquery(event_time("in_progress")),
        repair_at=Subquery(event_time("resolved")),
        closed_at=Subquery(event_time("closed")),
    )
    result = []
    for key, label, start, end in [
        ("response", "首次响应", "created_at", "response_at"),
        ("repair", "修复处理", "response_at", "repair_at"),
        ("verification", "回归验证", "repair_at", "closed_at"),
    ]:
        samples = rows.filter(**{start + "__isnull": False, end + "__isnull": False, end + "__gte": F(start)}).annotate(
            duration=ExpressionWrapper(F(end) - F(start), output_field=DurationField())
        )
        aggregate = samples.aggregate(count=Count("pk"), average=Avg("duration"))
        result.append(
            {
                "key": key,
                "name": label,
                "count": aggregate["count"],
                "average_hours": round(aggregate["average"].total_seconds() / 3600, 2)
                if aggregate["average"] is not None
                else None,
            }
        )
    return result, rows.filter(response_at__isnull=True, status="open").count()
