import re
import pytest
from django.conf import settings
from django.utils import translation
from rest_framework import serializers
from plane.app.serializers import WorkSpaceSerializer

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def test_default_validation_errors_are_chinese_for_native_clients():
    with translation.override(settings.LANGUAGE_CODE):
        with pytest.raises(serializers.ValidationError) as result:
            serializers.DateField().run_validation("invalid-date")
        assert re.search(r"[\u4e00-\u9fff]", str(result.value.detail))


def test_workspace_name_error_describes_the_actual_field():
    form = WorkSpaceSerializer(data={"name": "https://example.test"}, partial=True)
    assert not form.is_valid()
    assert str(form.errors["name"][0]) == "工作空间名称不能包含网址。"
