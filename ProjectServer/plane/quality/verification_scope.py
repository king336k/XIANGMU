"""Source identity and verification requirements are separate decisions."""

from rest_framework.exceptions import PermissionDenied, ValidationError
from .models import DaqReport, DataRegression
from .data_regression import manager
from .views import Conflict


def requires_data_regression(defect):
    if defect.verification_scope != "auto":
        return defect.verification_scope == "data"
    from .daq_incidents import trusted_incident

    return DaqReport.objects.filter(defect=defect).exists() or trusted_incident(defect) is not None


def validate_scope_change(view, defect, data):
    reason = data.pop("verification_scope_reason", "")
    scope = data.get("verification_scope", defect.verification_scope)
    if scope == defect.verification_scope:
        return ""
    if not manager(view.project_id, view.request.user):
        raise PermissionDenied("验证方式由项目经理确认。")
    if not reason.strip():
        raise ValidationError({"verification_scope_reason": "请简要说明验证范围。"})
    if defect.status == "closed" or data.get("status") == "closed":
        raise ValidationError({"verification_scope": "请先单独保存验证方式，再修复验证；已关闭缺陷须先重开。"})
    if (
        DataRegression.objects.filter(defect=defect)
        .exclude(plan__status__in=["completed", "cancelled", "failed"])
        .exists()
    ):
        raise Conflict("已有数据回归进行中，请先完成或取消当前计划。")
    if defect.resolved_at:
        from django.utils import timezone

        defect.resolved_at = timezone.now()
        defect.regression_execution = None
    names = {"auto": "按来源默认", "functional": "功能验证", "data": "新数据验证"}
    return f"验证方式：{names[defect.verification_scope]} → {names[scope]}。{reason.strip()}"
