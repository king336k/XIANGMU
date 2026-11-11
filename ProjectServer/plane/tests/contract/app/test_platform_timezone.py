import pytest
from plane.db.models import Project, User, Workspace
from plane.app.serializers import UserSerializer, ProjectSerializer, WorkSpaceSerializer
from plane.quality.project_report import PeriodInput

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.mark.parametrize(
    "serializer,field",
    [(UserSerializer, "user_timezone"), (ProjectSerializer, "timezone"), (WorkSpaceSerializer, "timezone")],
)
def test_timezone_is_fixed_even_for_old_api_clients(serializer, field):
    form = serializer(data={field: "UTC"}, partial=True)
    assert form.is_valid(), form.errors
    assert form.validated_data[field] == "Asia/Shanghai"


def test_new_records_and_report_use_china_standard_time(workspace):
    assert User._meta.get_field("user_timezone").default == "Asia/Shanghai"
    assert Workspace._meta.get_field("timezone").default == "Asia/Shanghai"
    assert Project._meta.get_field("timezone").default == "Asia/Shanghai"
    form = PeriodInput(data={"start": "2026-11-01", "end": "2026-11-08", "timezone": "UTC"})
    assert form.is_valid(), form.errors
    assert form.validated_data["timezone"] == "Asia/Shanghai"
