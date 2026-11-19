# SPDX-License-Identifier: AGPL-3.0-only
import hashlib
import json
import unicodedata
from pathlib import PurePosixPath
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from .permissions import require_assignee
from .models import Defect, DefectComment, DefectEvent, ProblemPackage, SourceLink
from .serializers import DefectSerializer
from .authorship import AuthoredRecordSerializer
from .views import Conflict, QualityView, defect_queryset, notify_assignment_supervisors
from plane.authentication.session import BaseSessionAuthentication
from .identity import PlatformBridgeAuthentication


class SourceInput(serializers.Serializer):
    source_system = serializers.CharField(max_length=64)
    source_instance = serializers.CharField(max_length=120)
    record_type = serializers.CharField(max_length=64)
    record_id = serializers.CharField(max_length=255)
    title = serializers.CharField(max_length=255)
    description = serializers.CharField(max_length=20000, allow_blank=True, default="")
    task_id = serializers.CharField(max_length=255, allow_blank=True, default="")
    package_id = serializers.CharField(max_length=255, allow_blank=True, default="")
    device = serializers.CharField(max_length=255, allow_blank=True, default="")


class SourceSerializer(serializers.ModelSerializer):
    source_context = serializers.SerializerMethodField()

    def get_source_context(self, obj):
        from .daq_incidents import SYSTEM, TYPE, signed_record

        if obj.source_system != SYSTEM or obj.record_type != TYPE:
            return None
        record = signed_record(obj)
        if not record:
            return None
        payload = record["payload"]
        context = record.get("sourceContext", {})
        return {
            "platformProjectId": payload.get("platformProjectId"),
            "reporter": record.get("reporter", {}),
            "platformProjectName": context.get("projectName", ""),
            "platformTaskId": payload.get("platformTaskId"),
            "platformTaskName": context.get("taskName", ""),
            "sourceReference": payload.get("sourceReference", ""),
        }

    class Meta:
        model = SourceLink
        fields = [
            "id",
            "source_system",
            "source_instance",
            "record_type",
            "record_id",
            "task_id",
            "package_id",
            "device",
            "created_at",
            "source_context",
        ]


class SourceDefect(QualityView):
    @transaction.atomic
    def post(self, request, **kwargs):
        data = self.input(SourceInput)
        project = self.project()
        type(project).objects.select_for_update().get(pk=project.pk)
        key = {name: data[name] for name in ["source_system", "source_instance", "record_type", "record_id"]}
        existing = SourceLink.objects.filter(project=project, **key).first()
        if existing:
            if any(getattr(existing, field) != data[field] for field in ["task_id", "package_id", "device"]):
                raise Conflict("同一来源编号的设备、任务或数据包关系不同，请核对来源记录。")
            return Response(
                {
                    "source": SourceSerializer(existing).data,
                    "defect": DefectSerializer(defect_queryset().get(pk=existing.defect_id)).data,
                }
            )
        title, description = data.pop("title"), data.pop("description")
        defect = Defect.objects.create(project=project, created_by=request.user, title=title, description=description)
        link = SourceLink.objects.create(project=project, created_by=request.user, defect=defect, **data)
        DefectEvent.objects.create(
            project=project,
            created_by=request.user,
            defect=defect,
            status="open",
            note="从来源记录创建；不表示外部任务状态已改变。",
        )
        from .module_routing import initial_assign

        defect = initial_assign(defect, request.user)
        notify_assignment_supervisors(defect, request.user)
        link.defect = defect
        return Response(
            {
                "source": SourceSerializer(link).data,
                "defect": DefectSerializer(defect_queryset().get(pk=defect.pk)).data,
            },
            status=201,
        )


class CollaborationInput(serializers.Serializer):
    action = serializers.ChoiceField(choices=["claim", "comment"])
    content = serializers.CharField(max_length=10000, allow_blank=True, default="")
    visibility = serializers.ChoiceField(choices=["public", "internal"], default="public")


class CommentSerializer(serializers.ModelSerializer):
    actor = serializers.CharField(source="created_by.display_name", default="成员")
    repair_changes = serializers.SerializerMethodField()
    command_operations = serializers.SerializerMethodField()

    def agent_receipts(self, obj):
        cache=self.context.setdefault('comment_agent_receipts',{})
        if obj.id in cache:return cache[obj.id]
        changes=[];operations=[]
        from django.core.exceptions import ObjectDoesNotExist
        from .remote_event_display import safe_changes,safe_argv,safe_output,execution_steps
        try:run=obj.remoteagentrun
        except ObjectDoesNotExist:run=None
        if run is not None and run.defect_id==obj.defect_id and run.defect.project_id==obj.project_id:
            from types import SimpleNamespace
            prepared=getattr(run,'display_commands',None)
            rows=list(run.remotecommand_set.all()) if prepared is None else [SimpleNamespace(
                id=row.id,created_at=row.created_at,status=row.status,
                payload=row.display_payload,result=row.display_result) for row in prepared]
            rows.sort(key=lambda row:(row.created_at,str(row.id)))
            observed=[];receipts={}
            for row in rows:
                if row.status!='done' or row.result.get('ok') is not True or row.result.get('exit_code',0)!=0:continue
                receipt=row.result
                if row.payload.get('kind')=='run' and isinstance(receipt.get('stdout'),str) and len(receipt['stdout'])<=65536:
                    try:
                        parsed=json.loads(receipt['stdout'])
                        if isinstance(parsed,dict) and parsed.get('simulation') is True:receipt=parsed
                    except (ValueError,TypeError):pass
                if isinstance(receipt.get('changes'),list):observed.extend(receipt['changes'][:20])
                receipts[row.id]=receipt
            locations=run.result.get('repair_locations',[]) if isinstance(run.result,dict) else []
            for location in locations[:10] if isinstance(locations,list) else []:
                if not isinstance(location,dict):continue
                actual=dict(location)
                identity={'target_kind':location.get('target_kind'),'target_username':location.get('username'),'target_ip':location.get('ip_address')}
                matches=[change for change in observed if isinstance(change,dict) and all(identity.values())
                    and all(change.get(key)==value for key,value in identity.items()) and all(
                        change.get(key)==location.get(key) for key in ['path','key','before','after'])]
                for field in ['before_line','after_line','before_exists','after_exists']:
                    values=[change[field] for change in matches if field in change]
                    if values and all(value==values[0] for value in values):actual[field]=values[0]
                cleaned=safe_changes([actual])
                if cleaned and cleaned[0].get('path') and cleaned[0].get('key'):
                    changes.append({**cleaned[0],'target':safe_output(location.get('target','现场'))[:300]})
            snapshot=run.result.get('target_snapshot',{}).get('collector',{})
            frozen=bool(snapshot.get('username') and snapshot.get('host'))
            user=snapshot.get('username') or run.workstation.username
            host=snapshot.get('host') or run.workstation.capabilities.get('network',{}).get('ip_address','')
            target=('采集电脑：' if frozen else '采集电脑（当前登记信息）：')+user+('@'+host if host else '')
            policy=run.result.get('display_policy_snapshot') or run.workstation.capabilities.get('agent_context',{})
            # Public summaries retain a bounded tail; all events remain available separately.
            for row in [row for row in rows if row.payload.get('kind')=='run'][-12:]:
                result=row.result if isinstance(row.result,dict) else {}
                argv=safe_argv(row.payload.get('argv'))
                if argv==safe_argv(policy.get('inspect_argv')) or (len(argv)>=2 and argv[-2] in {'rosa','rai'} and argv[-1] in {'health','inspect'}):continue
                repair=safe_argv(policy.get('repair_argv'))
                stage='verify' if argv==safe_argv(policy.get('verify_argv')) else 'repair' if repair and argv[:len(repair)]==repair else 'command'
                command_target=target
                receipt=receipts.get(row.id,{})
                receipt_changes=receipt.get('changes',[])
                if stage=='repair' and changes and isinstance(receipt_changes,list) and any(
                    isinstance(item,dict) and any(item.get('path')==shown.get('path') and item.get('key')==shown.get('key')
                        for shown in changes) for item in receipt_changes):continue
                actual_targets={(item.get('target_kind'),item.get('target_username'),item.get('target_ip'))
                    for item in (receipt_changes if isinstance(receipt_changes,list) else []) if isinstance(item,dict)
                    and item.get('target_kind') in {'robot','collector'}
                    and isinstance(item.get('target_username'),str) and isinstance(item.get('target_ip'),str)}
                if len(actual_targets)==1:
                    kind,username,host=next(iter(actual_targets))
                    command_target=('机器人：' if kind=='robot' else '采集电脑：')+username+'@'+host
                operations.append({'target':safe_output(command_target)[:300],
                    'argv':argv,'stage':stage,'stdout':safe_output(result.get('stdout'))[-4096:],'execution_steps':execution_steps(result),
                    'stderr':safe_output(result.get('stderr'))[-4096:],'status':row.status,
                    'ok':result.get('ok') if type(result.get('ok')) is bool else None,
                    'exit_code':result.get('exit_code'),'timed_out':result.get('timed_out') is True})
        cache[obj.id]=(changes,operations)
        return cache[obj.id]

    def get_repair_changes(self,obj):return self.agent_receipts(obj)[0]

    def get_command_operations(self,obj):return self.agent_receipts(obj)[1]

    class Meta:
        model = DefectComment
        fields = ["id", "content", "visibility", "actor", "created_at", "repair_changes", "command_operations"]


def with_agent_evidence(comments):
    from django.db.models import Prefetch,F
    from django.db.models.functions import JSONObject,Substr
    from django.db.models.fields.json import KeyTextTransform
    from .remote_models import RemoteCommand
    commands=RemoteCommand.objects.only('id','run_id','created_at','status').annotate(
        display_payload=JSONObject(kind=F('payload__kind'),argv=F('payload__argv')),
        display_result=JSONObject(ok=F('result__ok'),exit_code=F('result__exit_code'),
            timed_out=F('result__timed_out'),changes=F('result__changes'),
            stdout=Substr(KeyTextTransform('stdout','result'),1,65536),stderr=Substr(KeyTextTransform('stderr','result'),1,65536))
    ).order_by('created_at','id')[:32]
    return comments.select_related("created_by", "remoteagentrun__workstation", "remoteagentrun__defect").prefetch_related(
        Prefetch("remoteagentrun__remotecommand_set",queryset=commands,to_attr="display_commands"))


class DefectCollaboration(QualityView):
    def get(self, request, pk, **kwargs):
        defect = self.obj(Defect, pk)
        from .collaboration_admin import internal_access

        # Rich discussions have their own tab; retain only legacy notes/public replies in operation history.
        comments = with_agent_evidence(defect.comments.filter(request_id__isnull=True))
        if not internal_access(self.project_id, request.user, self.workspace_slug):
            comments = comments.filter(visibility="public")
        return self.listing(comments, CommentSerializer)

    @transaction.atomic
    def post(self, request, pk, **kwargs):
        data = self.input(CollaborationInput)
        defect = get_object_or_404(Defect.objects.select_for_update(), pk=pk, project_id=self.project_id)
        if data["action"] == "claim":
            require_assignee(self, request.user.id, "TECHNICIAN")
            if defect.status not in {"open", "in_progress"}:
                raise Conflict("当前缺陷不在可认领阶段。")
            if defect.assignee_id and defect.assignee_id != request.user.id:
                raise PermissionDenied("缺陷已分派给其他处理人。")
            if defect.assignee_id == request.user.id and defect.status == "in_progress":
                return Response(DefectSerializer(defect_queryset().get(pk=defect.pk)).data)
            old_status = defect.status
            defect.assignee = request.user
            defect.status = "in_progress"
            defect.edit_version += 1
            defect.save()
            DefectEvent.objects.create(
                project=defect.project,
                defect=defect,
                created_by=request.user,
                previous_status=old_status,
                status="in_progress",
                note="处理人认领",
            )
            return Response(DefectSerializer(defect_queryset().get(pk=defect.pk)).data)
        if not data["content"].strip():
            raise ValidationError({"content": "请填写评论内容。"})
        from .collaboration_admin import internal_access

        if data["visibility"] == "internal" and not internal_access(self.project_id, request.user, self.workspace_slug):
            raise PermissionDenied("当前成员只能发表数采员可见回复。")
        comment = DefectComment.objects.create(
            project=defect.project,
            defect=defect,
            created_by=request.user,
            content=data["content"],
            visibility=data["visibility"],
        )
        from .notifications import defect_notice

        # Notification content is a fixed event label; private text is never copied to inboxes.
        if comment.visibility == "public":
            defect_notice(defect, request.user, "新增公开协作回复")
        return Response(CommentSerializer(comment).data, status=201)


class FileManifest(serializers.Serializer):
    path = serializers.CharField(max_length=500)
    size = serializers.IntegerField(min_value=0, max_value=200 * 1024 * 1024)
    sha256 = serializers.RegexField(regex=r"^[a-fA-F0-9]{64}$")

    def validate_path(self, value):
        normalized = unicodedata.normalize("NFC", value.replace("\\", "/"))
        if (
            ":" in normalized
            or "\x00" in normalized
            or normalized.startswith("/")
            or any(part in {"", ".", ".."} for part in normalized.split("/"))
        ):
            raise serializers.ValidationError("文件路径必须是包内相对路径，不能包含上级目录。")
        if PurePosixPath(normalized).is_absolute():
            raise serializers.ValidationError("不接受绝对路径。")
        return normalized


class PackageInput(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    defect_id = serializers.UUIDField()
    source_system = serializers.CharField(max_length=64)
    external_id = serializers.CharField(max_length=255)
    files = FileManifest(many=True, allow_empty=False, max_length=1000)

    def validate_files(self, files):
        if len({f["path"] for f in files}) != len(files):
            raise serializers.ValidationError("清单中存在重复文件路径。")
        if sum(f["size"] for f in files) > 500 * 1024 * 1024:
            raise serializers.ValidationError("问题包清单总大小不能超过500MB。")
        return files


class PackageSerializer(AuthoredRecordSerializer):
    class Meta:
        model = ProblemPackage
        fields = ["id", "defect_id", "name", "source_system", "external_id", "files", "status", "created_at"]


class PackagePreflight(QualityView):
    authentication_classes = [PlatformBridgeAuthentication, BaseSessionAuthentication]

    def post(self, request, **kwargs):
        data = self.input(PackageInput)
        self.obj(Defect, data["defect_id"])
        return Response(
            {
                "valid": True,
                "file_count": len(data["files"]),
                "total_bytes": sum(f["size"] for f in data["files"]),
                "scope": "仅校验元数据清单，文件内容上传与校验另行完成。",
            }
        )


class PackageList(QualityView):
    authentication_classes = [PlatformBridgeAuthentication, BaseSessionAuthentication]

    def get(self, request, **kwargs):
        qs = ProblemPackage.objects.filter(project=self.project())
        if request.query_params.get("defect_id"):
            pk = serializers.UUIDField().run_validation(request.query_params["defect_id"])
            qs = qs.filter(defect_id=pk)
        return self.listing(qs, PackageSerializer)

    @transaction.atomic
    def post(self, request, **kwargs):
        data = self.input(PackageInput)
        defect = self.obj(Defect, data.pop("defect_id"))
        type(defect.project).objects.select_for_update().get(pk=defect.project_id)
        fingerprint = hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        existing = ProblemPackage.objects.filter(
            project_id=self.project_id, source_system=data["source_system"], external_id=data["external_id"]
        ).first()
        if existing:
            if existing.manifest_hash != fingerprint or existing.defect_id != defect.id:
                raise Conflict("同一外部问题包编号的内容或关联对象不同。")
            return Response(PackageSerializer(existing).data)
        package = ProblemPackage.objects.create(
            project=defect.project, defect=defect, created_by=request.user, manifest_hash=fingerprint, **data
        )
        return Response(PackageSerializer(package).data, status=201)


class DefectSources(QualityView):
    def get(self, request, pk, **kwargs):
        from .models import DaqReport

        defect = self.obj(Defect, pk)
        sources = list(SourceSerializer(defect.sources.all(), many=True).data)
        for report in DaqReport.objects.filter(defect=defect).select_related("binding"):
            source = report.binding
            sources.append(
                {
                    "id": str(report.id),
                    "source_system": "ENGRAM_DAQ",
                    "source_instance": source.source_instance,
                    "record_type": "DAQ_SESSION",
                    "record_id": source.source_record_id,
                    "task_id": str(source.platform_task_id),
                    "package_id": source.package_id,
                    "device": source.device,
                    "created_at": report.created_at,
                }
            )
        return Response(sources)
