from datetime import timedelta
from zoneinfo import ZoneInfo
import pytest
from django.utils import timezone
from plane.db.models import Project,ProjectMember
from plane.quality.models import Defect,DefectEvent

pytestmark=[pytest.mark.contract,pytest.mark.django_db]

def test_response_stages_use_events_and_creation_cohort_before_paging(session_client,workspace,create_user):
    project=Project.objects.create(workspace=workspace,name="阶段统计",identifier="SLA152")
    ProjectMember.objects.create(project=project,member=create_user,role=20)
    now=timezone.now();start=now-timedelta(hours=10)
    defect=Defect.objects.create(project=project,title="闭环缺陷",status="closed")
    Defect.objects.filter(pk=defect.pk).update(created_at=start)
    for previous,status,hours in [("open","in_progress",2),("in_progress","resolved",5),("resolved","closed",8)]:
        event=DefectEvent.objects.create(project=project,defect=defect,previous_status=previous,status=status)
        DefectEvent.objects.filter(pk=event.pk).update(created_at=start+timedelta(hours=hours))
    Defect.objects.create(project=project,title="未响应",status="open")
    base=f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/defect-statistics/"
    response=session_client.get(base,{"per_page":1,"start":timezone.localtime(start,ZoneInfo("Asia/Shanghai")).date().isoformat(),"end":timezone.localtime(now,ZoneInfo("Asia/Shanghai")).date().isoformat()})
    assert response.status_code==200,response.content
    stages={r["key"]:r for r in response.data["stage_durations"]}
    assert stages["response"]["count"]==1 and stages["response"]["average_hours"]==2
    assert stages["repair"]["average_hours"]==3 and stages["verification"]["average_hours"]==3
    assert response.data["response_pending"]==1
    assert response.data["by_category"]==[{"value":"manual","count":2}]
    assert session_client.get(base,{"start":"2026-11-09","end":"2026-01-01"}).status_code==400


def test_resolved_defect_without_started_event_is_not_unresponsive(session_client,workspace,create_user):
    project=Project.objects.create(workspace=workspace,name="直接修复",identifier="SLA153")
    ProjectMember.objects.create(project=project,member=create_user,role=20)
    Defect.objects.create(project=project,title="已修复",status="resolved")
    response=session_client.get(f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/defect-statistics/")
    assert response.status_code==200,response.content
    assert response.data["response_pending"]==0
