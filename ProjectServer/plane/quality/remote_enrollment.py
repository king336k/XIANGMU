"""Automatic enrollment has its own claim proof and administrator-owned policy."""
from datetime import timedelta
import hashlib
import hmac
import json

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from plane.app.views.base import BaseAPIView
from plane.authentication.rate_limit import AuthenticationThrottle
from plane.db.models import Project, User
from plane.license.models import InstanceConfiguration
from .models import FieldAgent
from .remote_models import RemoteWorkstation
from .remote_diagnostics import digest, permitted
from .views import Conflict


class EnrollmentInput(serializers.Serializer):
    protocol=serializers.ChoiceField(choices=['daq-remote-enrollment-v1'])
    installation_id=serializers.UUIDField()
    claim_secret=serializers.CharField(min_length=32,max_length=128,write_only=True,trim_whitespace=False)
    machine_fingerprint=serializers.RegexField(r'^[a-f0-9]{64}$')
    identity=serializers.DictField()


class RemoteEnrollmentThrottle(AuthenticationThrottle):
    # Multiple collectors can share one NAT address during a batch rollout.
    scope='remote_enrollment'
    rate='120/minute'


class RemoteEnrollment(BaseAPIView):
    authentication_classes=[]
    permission_classes=[AllowAny]
    throttle_classes=[RemoteEnrollmentThrottle]

    @transaction.atomic
    def post(self,request):
        parser=EnrollmentInput(data=request.data);parser.is_valid(raise_exception=True);data=parser.validated_data
        # A report-only key never enters this authentication path. This policy is
        # set centrally by the project administrator, not by the enrolling host.
        row=InstanceConfiguration.objects.select_for_update().filter(key='QUALITY_REMOTE_AUTO_ENROLLMENT').first()
        policy=json.loads(row.value) if row else {}
        if policy.get('enabled') is not True:
            raise Conflict('平台尚未启用采集电脑自动接入。')
        project=get_object_or_404(Project,pk=policy.get('project_id'),archived_at__isnull=True,workspace__deleted_at__isnull=True)
        owner=get_object_or_404(User,pk=policy.get('owner_user_id'),is_active=True,is_bot=False)
        station=RemoteWorkstation.objects.select_for_update(of=('self',)).select_related('agent__project__workspace').filter(pk=data['installation_id']).first()
        if station:
            if not station.enrollment_claim_hash or not hmac.compare_digest(station.enrollment_claim_hash,digest(data['claim_secret'])):
                raise Conflict('设备已登记，无法以新凭据重新接管。')
            if not station.enabled or not station.agent.enabled:
                raise Conflict('设备接入已撤销，请联系平台管理员。')
            if station.machine_fingerprint != data['machine_fingerprint']:
                raise Conflict('设备环境已变化，请恢复原设备关联。')
            if station.agent.project_id!=project.id or station.agent.owner_id!=owner.id:
                raise Conflict('设备项目或负责人已变化，请联系平台管理员。')
            created=False
        else:
            agent=FieldAgent(project=project,owner=owner,created_by=owner,name='采集电脑',source_instance='daq-auto:'+str(data['installation_id']))
            station=RemoteWorkstation(id=data['installation_id'],agent=agent,enabled=True,credential_expires_at=timezone.now())
            if not permitted(owner,station):
                raise Conflict('平台自动接入负责人权限未配置。')
            agent.save()
            station.enrollment_claim_hash=digest(data['claim_secret']);station.machine_fingerprint=data['machine_fingerprint'];created=True
        if not permitted(owner,station):raise Conflict('平台自动接入负责人权限已失效。')
        # Stable idempotent issuance requires the unguessable, persisted local
        # claim. A guessed UUID/IP/username cannot recover the credential.
        raw='rw_'+hmac.new(settings.SECRET_KEY.encode(),('daq-remote-v1:'+str(station.pk)+':'+data['claim_secret']).encode(),hashlib.sha256).hexdigest()
        station.credential_hash=digest(raw);station.credential_expires_at=timezone.now()+timedelta(days=30)
        if created:
            station.username=str(data['identity'].get('username',''))[:120]
            station.hostname=str(data['identity'].get('hostname',''))[:200]
        station.save()
        result=Response({'protocol':'daq-remote-enrollment-v1','status':'active','workstation_id':str(station.pk),'token':raw,
            'server_instance_id':digest('remote-server:'+settings.SECRET_KEY)[:32],
            'expires_at':station.credential_expires_at.isoformat(),'policy':{'allowed_commands':[],'editable_files':[]}},status=201 if created else 200)
        result['Cache-Control']='no-store'
        return result
