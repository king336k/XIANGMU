"""Bounded Agent tool validation, dispatch and receipt wait, independent of HTTP."""

import json
import re
import time

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError

from .errors import Conflict
from .remote_access import identity_key, online, permitted
from .remote_commands import command
from .remote_models import RemoteWorkstation
from .remote_sessions import robot_target


def execute_tool(run, data):
    if not online(run.workstation):
        raise Conflict("现场电脑离线。")
    if run.remotecommand_set.count() >= 20:
        raise Conflict("已达本轮工具次数上限。")
    op = data.get("operation")
    if op not in {"run", "read_file", "patch_file"}:
        raise ValidationError("不支持的现场工具。")
    payload = {"kind": op}
    if op == "run":
        payload["argv"] = serializers.ListField(
            child=serializers.CharField(max_length=2000), min_length=1, max_length=30
        ).run_validation(data.get("argv"))
        payload["cwd"] = str(data.get("cwd") or ".")[:500]
        payload["timeout"] = serializers.IntegerField(min_value=1, max_value=30).run_validation(data.get("timeout", 20))
    else:
        payload["path"] = serializers.CharField(max_length=500).run_validation(data.get("path"))
        if op == "patch_file":
            payload["content"] = serializers.CharField(
                max_length=100000, allow_blank=True, trim_whitespace=False
            ).run_validation(data.get("content"))
            payload["expected_sha256"] = serializers.RegexField(r"^[a-f0-9]{64}$").run_validation(
                data.get("expected_sha256")
            )
    from .remote_tools_policy import check_tool

    with transaction.atomic():
        station = (
            RemoteWorkstation.objects.select_for_update(of=("self",))
            .select_related("agent__project__workspace")
            .get(pk=run.workstation_id)
        )
        run.refresh_from_db()
        if (
            run.status != "running"
            or run.expires_at <= timezone.now()
            or run.identity_key != identity_key(station)
            or not permitted(run.owner, station)
        ):
            raise PermissionDenied("远程任务身份或权限已失效。")
        tool_context = dict(station.capabilities.get("agent_context", {}))
        tool_context["repair_allowed"] = tool_context.get("repair_allowed") is True and run.mode == "repair"
        check_tool(tool_context, op, payload)
        fixed_argv = payload.get("argv", [])
        if op == "run" and fixed_argv[:1] == ["daq-local-diagnostics-v1"]:
            target = run.result.get("configuration_target")
            if isinstance(target, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", target):
                payload["configuration_target"] = target
                if fixed_argv[1:2] == ["repair"]:
                    observed = (
                        run.remotecommand_set.filter(
                            status="done",
                            payload__argv=["daq-local-diagnostics-v1", "inspect"],
                            payload__configuration_target=target,
                        )
                        .order_by("-created_at", "-id")
                        .first()
                    )
                    try:
                        configuration = (
                            json.loads(observed.result.get("stdout", "{}")).get("configuration", {}) if observed else {}
                        )
                    except (ValueError, TypeError, AttributeError):
                        configuration = {}
                    revision = configuration.get("target_revision")
                    if (
                        not isinstance(revision, str)
                        or not re.fullmatch(r"[a-f0-9]{64}", revision)
                        or configuration.get("snapshot_sha256") != fixed_argv[-1]
                    ):
                        raise Conflict("请先读取本轮目标配置，再按当前快照执行修复。")
                    payload["expected_configuration_revision"] = revision
            elif fixed_argv[1:2] == ["repair"]:
                _, payload["expected_target_revision"] = robot_target(station)
        if run.remotecommand_set.filter(status__in=["pending", "delivered"], expires_at__gt=timezone.now()).exists():
            raise Conflict("上一个现场操作尚未完成，请等待结果。")
        if run.remotecommand_set.count() >= 20:
            raise Conflict("已达本轮工具次数上限。")
        row = command(station, payload, run=run, lifetime=40)
    deadline = time.monotonic() + 38
    while time.monotonic() < deadline:
        row.refresh_from_db()
        if row.status == "done":
            return row.result, 200
        if row.status == "expired":
            raise Conflict("现场任务已过期，未重复执行。")
        time.sleep(0.25)
    return (
        {
            "ok": False,
            "error": "现场执行结果未到达，状态未知；不要重复提交同一修复。",
            "command_id": str(row.id),
        },
        504,
    )
