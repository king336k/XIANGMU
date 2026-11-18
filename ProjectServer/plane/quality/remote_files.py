"""Authenticated read-only operator/attached-robot file requests."""
from datetime import timedelta
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from plane.app.views.base import BaseAPIView
from .remote_models import RemoteFileRequest, RemoteWorkstation, RemoteUploadedFile, RemoteAgentRun, RemoteTerminal
from .remote_diagnostics import station_for, identity_key, permitted, online, browser_boundary, command, feedback_for, digest
from .views import Conflict

class RemoteFiles(BaseAPIView):
    @transaction.atomic
    def post(self, request):
        browser_boundary(request)
        station=station_for(request.user,request.data.get('device_id'))
        station=RemoteWorkstation.objects.select_for_update().select_related('agent__project__workspace').get(pk=station.pk)
        if not permitted(request.user,station):raise PermissionDenied()
        if not online(station):raise Conflict('采集电脑离线。')
        if not station.capabilities.get('file_browser',{}).get('ready'):raise Conflict('现场文件浏览尚未启用。')
        if RemoteFileRequest.objects.filter(owner=request.user,command__workstation=station,command__expires_at__gt=timezone.now(),command__status__in=['pending','delivered']).count()>=2:raise Conflict('请等待当前文件操作完成。')
        action=serializers.ChoiceField(choices=['list','prepare','chunk','upload_start','upload_chunk','upload_finish','upload_abort']).run_validation(request.data.get('action'))
        target=serializers.ChoiceField(choices=['operator','robot']).run_validation(request.data.get('target'))
        payload={'action':action,'target':target}
        if action.startswith('upload_'):
            if RemoteAgentRun.objects.filter(workstation=station,status__in=['queued','running'],expires_at__gt=timezone.now()).exists():raise Conflict('该电脑正在执行 Agent 任务，请结束后再上传。')
            if RemoteTerminal.objects.filter(workstation=station,status='open',expires_at__gt=timezone.now(),last_read_at__gt=timezone.now()-timedelta(seconds=60)).exists():raise Conflict('该电脑有人工终端正在使用，请关闭终端后上传。')
        if action in {'chunk','upload_chunk','upload_finish','upload_abort'}:
            payload['ticket']=serializers.RegexField(r'^(?:[a-f0-9]{32}|r1\.[a-f0-9]{64}\.[a-f0-9]{32})$').run_validation(request.data.get('ticket'))
            if action in {'chunk','upload_chunk'}:
                payload['offset']=serializers.IntegerField(min_value=0,max_value=256*1024*1024).run_validation(request.data.get('offset'))
            if action=='upload_chunk':
                payload['data']=serializers.CharField(max_length=131072,trim_whitespace=False).run_validation(request.data.get('data'))
        else:
            payload['offset']=serializers.IntegerField(min_value=0,max_value=5000).run_validation(request.data.get('offset',0))
            payload['path']=serializers.CharField(max_length=2000,allow_blank=True,trim_whitespace=False).run_validation(request.data.get('path',''))
            if action=='upload_start':
                payload['filename']=serializers.CharField(max_length=255,trim_whitespace=False).run_validation(request.data.get('filename'))
                payload['size']=serializers.IntegerField(min_value=0,max_value=256*1024*1024).run_validation(request.data.get('size'))
                payload['sha256']=serializers.RegexField(r'^[a-f0-9]{64}$').run_validation(request.data.get('sha256'))
        if action=='upload_start':
            defect=None
            if request.data.get('defect_id'):
                defect=get_object_or_404(feedback_for(station,request.data['defect_id']),pk=request.data['defect_id'])
            upload=RemoteUploadedFile.objects.create(workstation=station,owner=request.user,defect=defect,target=target,path=payload['path'],filename=payload['filename'],size=payload['size'],sha256=payload['sha256'],identity_key=identity_key(station),expires_at=timezone.now()+timedelta(minutes=30))
            payload['upload_record_id']=str(upload.id)
        elif action.startswith('upload_'):
            upload=get_object_or_404(RemoteUploadedFile,workstation=station,owner=request.user,target=target,ticket_hash=digest(payload['ticket']),identity_key=identity_key(station),expires_at__gt=timezone.now())
            payload['upload_record_id']=str(upload.id)
        row=command(station,{'kind':'file_browser','request':payload},lifetime=120)
        job=RemoteFileRequest.objects.create(command=row,owner=request.user,identity_key=identity_key(station))
        return Response({'id':str(job.id),'status':row.status},status=201)

    def get(self, request, pk):
        job=get_object_or_404(RemoteFileRequest.objects.select_related('command__workstation__agent__project__workspace'),pk=pk,owner=request.user)
        row=job.command;station=row.workstation
        if not permitted(request.user,station):raise PermissionDenied()
        if job.identity_key!=identity_key(station) or row.expires_at<timezone.now():raise Conflict('本次文件请求已失效，请重新读取。')
        result=row.result.get('file_result',{}) if row.result.get('ok') is True else {}
        return Response({'id':str(job.id),'status':row.status,'result':result,'error':'' if row.result.get('ok') else row.result.get('stderr','')})


def record_upload_result(row):
    import json
    from .models import DefectEvent
    payload=row.payload.get('request',{})
    if not payload.get('upload_record_id'):return
    upload=RemoteUploadedFile.objects.filter(pk=payload['upload_record_id'],workstation=row.workstation).first()
    if not upload or upload.identity_key!=identity_key(row.workstation) or upload.expires_at<=timezone.now():return
    result=row.result.get('file_result',{})
    if row.result.get('ok') is not True:
        if payload['action']=='upload_start':upload.status='failed';upload.save(update_fields=['status'])
        return
    if payload['action']=='upload_start' and isinstance(result.get('ticket'),str):
        upload.ticket_hash=digest(result['ticket']);upload.save(update_fields=['ticket_hash'])
    elif payload['action']=='upload_abort' and upload.status=='uploading':upload.status='cancelled';upload.save(update_fields=['status'])
    elif payload['action']=='upload_finish' and upload.status!='uploaded':
        if result.get('uploaded') is not True or result.get('sha256')!=upload.sha256 or result.get('size')!=upload.size:return
        upload.status='uploaded';upload.path=result.get('path','')[:2000];upload.save(update_fields=['status','path'])
        if upload.defect_id:
            defect=upload.defect
            note={'upload_id':str(upload.id),'workstation_id':str(upload.workstation_id),'target':upload.target,'path':upload.path,'filename':upload.filename,'sha256':upload.sha256,'size':upload.size,'status':'uploaded_not_deployed'}
            DefectEvent.objects.create(project_id=defect.project_id,defect=defect,created_by=upload.owner,previous_status=defect.status,status=defect.status,note='现场文件上传：'+json.dumps(note,ensure_ascii=False))
