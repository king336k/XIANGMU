"""New public replies preserve generated brief text and a separate evidence disclosure."""
from datetime import timedelta
import re

import pytest
from django.utils import timezone
from plane.quality.models import Defect
from plane.quality.remote_models import RemoteAgentRun,RemoteWorkstation
from plane.quality.remote_diagnostics import identity_key
from plane.quality.remote_tasks import finish
from plane.tests.contract.app.test_remote_diagnostics import remote,heartbeat

pytestmark=[pytest.mark.contract,pytest.mark.django_db]


def test_public_brief_keeps_model_three_lines_and_evidence_header_on_its_own_line(remote):
    _,edge,device,project=remote;heartbeat(edge)
    station=RemoteWorkstation.objects.get(pk=device)
    defect=Defect.objects.create(project=project,title='brief evidence separator',description='synthetic')
    run=RemoteAgentRun.objects.create(workstation=station,defect=defect,owner=station.agent.owner,
        identity_key=identity_key(station),status='running',expires_at=timezone.now()+timedelta(minutes=1))
    brief='**故障**：目标超限。\n**已处理**：配置已复查。\n**待验证**：现场安全复位。'
    details='原始节点日志记录目标无效；配置复查未覆盖实际复位。'
    finish(run.id,{'summary':'legacy summary','brief_report':brief,'evidence_details':details,'repaired':False})
    run.refresh_from_db();content=run.comment.content
    assert brief in content
    assert '\n问题：legacy summary' not in content
    assert '\n详细依据：\n'+details in content
    # Match the existing React/Vue disclosure separator without changing any report facts.
    blocks=re.split(r'\r?\n\s*(?:\*\*)?(?:详细证据与处理过程|详细依据)(?:\*\*)?[:：]\s*\r?\n',content)
    assert len(blocks)==2 and blocks[1]==details
    assert run.result['brief_report']==brief
