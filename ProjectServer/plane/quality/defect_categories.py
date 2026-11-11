"""One source-category projection for both lists and aggregate charts."""

from django.db.models import Case, When, Value, CharField, OuterRef, Subquery
from django.db.models.functions import Coalesce
from .models import DaqReport, SourceLink

CATEGORIES = {
    "UploadError": "上传异常",
    "DataAnomaly": "数据异常",
    "ValidationFailed": "质检未通过",
    "TimestampAnomaly": "时间异常",
    "Other": "其他上报",
    "daq_incident": "启动或录制异常",
    "test": "测试发现",
    "manual": "平台新建",
}


def with_category(queryset):
    report = DaqReport.objects.filter(defect_id=OuterRef("pk")).values("category")[:1]
    incident = SourceLink.objects.filter(
        defect_id=OuterRef("pk"), source_system="ENGRAM_DAQ", record_type="daq_incident"
    ).values("record_type")[:1]
    return queryset.annotate(
        defect_category=Coalesce(
            Subquery(report),
            Subquery(incident),
            Case(When(source_execution__isnull=False, then=Value("test")), default=Value("manual")),
            output_field=CharField(),
        )
    )
