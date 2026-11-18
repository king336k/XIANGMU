"""Classify tools from enrolled device policy, never from the model's purpose label."""
import re

from rest_framework.exceptions import PermissionDenied


def check_tool(context, operation, payload):
    if not isinstance(context,dict):raise PermissionDenied("本设备未配置远程工具。")
    mutation=operation=="patch_file"
    if operation=="run":
        argv=payload.get("argv")
        reads=[context.get("inspect_argv"),context.get("verify_argv")]
        for role,settings in context.get("specialists",{}).items():
            prefix=settings.get("argv_prefix") if isinstance(settings,dict) else None
            if role in {"rosa","rai"} and isinstance(prefix,list):reads.extend([prefix+[role,"health"],prefix+[role,"inspect"]])
        if argv in [r for r in reads if isinstance(r,list) and r]:return
        repair=context.get("repair_argv")
        if not (isinstance(repair,list) and repair and argv[:len(repair)]==repair and len(argv)==len(repair)+1 and re.fullmatch(r"[a-f0-9]{64}",argv[-1])):
            raise PermissionDenied("该命令不在本设备授权工具范围内。")
        mutation=True
    if operation in {"read_file","patch_file"}:
        key="editable_files" if operation=="patch_file" else "readable_files"
        if payload.get("path") not in context.get(key,[]):raise PermissionDenied("该文件不在本设备授权范围内。")
    if mutation and context.get("repair_allowed") is not True:raise PermissionDenied("本设备本轮仅允许检查。")
