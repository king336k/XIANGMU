from datetime import timedelta
import pytest
from django.utils import timezone
from plane.quality.models import DefectEvent
from plane.quality.remote_models import RemoteAgentRun
from plane.tests.contract.app.test_agent_lifecycle import job

pytest_plugins=['plane.tests.contract.app.test_remote_diagnostics']
pytestmark=[pytest.mark.contract,pytest.mark.django_db]


def test_backfill_dryrun_is_readonly_and_apply_is_idempotent(job):
    _,_,defect,run=job
    run.status='completed';run.completed_at=timezone.now()
    run.result={'repaired':True,'verification_passed':True};run.save()
    from plane.quality.agent_lifecycle import reconcile
    before=defect.events.count()
    assert reconcile(run,apply=False)['eligible'] is True
    defect.refresh_from_db();run.refresh_from_db()
    assert defect.status=='open' and 'defect_state_version' not in run.result and defect.events.count()==before
    result=reconcile(run,apply=True)
    defect.refresh_from_db();run.refresh_from_db()
    assert result['applied'] and defect.status=='pending_tech'
    assert reconcile(run,apply=True)['eligible'] is False


@pytest.mark.parametrize('blocker',['human_event','human_update','newer_run','closed','archive','in_progress_without_agent'])
def test_backfill_skips_any_human_followup_or_newer_work(job,blocker):
    _,station,defect,run=job
    run.status='completed';run.completed_at=timezone.now();run.result={'repaired':True,'verification_passed':True};run.save()
    if blocker=='human_event':DefectEvent.objects.create(project=defect.project,defect=defect,status='open',previous_status='open',note='人工接手',created_by=run.owner)
    elif blocker=='human_update':defect.title='human edit';defect.save()
    elif blocker=='newer_run':RemoteAgentRun.objects.create(workstation=station,defect=defect,owner=run.owner,expires_at=timezone.now()+timedelta(minutes=5))
    elif blocker=='closed':defect.status='closed';defect.save()
    elif blocker=='archive':defect.archived_at=timezone.now();defect.save()
    else:defect.status='in_progress';defect.save()
    from plane.quality.agent_lifecycle import reconcile
    assert reconcile(run,apply=False)['eligible'] is False
