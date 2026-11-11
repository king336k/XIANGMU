import pytest
from rest_framework.exceptions import AuthenticationFailed
from plane.db.models import Project,ProjectMember
from plane.quality.models import PlatformProject,PlatformIdentity
from plane.quality import platform

pytestmark=[pytest.mark.contract,pytest.mark.django_db]
def test_legacy_authority_checks_selected_mapping_not_first(workspace,create_user,mocker):
    project=Project.objects.create(workspace=workspace,name="双来源映射",identifier="AUTH152")
    ProjectMember.objects.create(project=project,member=create_user,role=20)
    PlatformProject.objects.create(project=project,source_instance="old",external_project_id=9)
    PlatformProject.objects.create(project=project,source_instance="old",external_project_id=10)
    identity=PlatformIdentity.objects.create(project=project,source_instance="old",external_user_id=4,user=create_user)
    mocker.patch("plane.quality.platform.configuration",return_value={"kind":"legacy_hub","login_enabled":True})
    mocker.patch("plane.quality.platform.fetch",return_value={"total":1,"page":1,"size":100,"items":[{"id":4,"active":True,"projectMemberships":[{"projectId":9,"active":True,"roles":["PROJECT_ADMIN"]}]}]})
    assert platform.verify_identity(identity,9).external_project_id==9
    with pytest.raises(AuthenticationFailed): platform.verify_identity(identity,10)
