# SPDX-License-Identifier: AGPL-3.0-only
"""Read-only migration preview. Identity names never grant native access."""

from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from . import platform
from .models import PlatformIdentity
from .permissions import ROLE_NAMES
from .views import QualityView


def read_directory(instance):
    if platform.configuration(instance).get("kind") != "legacy_hub":
        raise platform.PlatformUnavailable("请选择原45100账号服务连接。")
    rows, seen, expected = [], set(), None
    for page in range(1, 41):
        data = platform.fetch(instance, "/api/admin/users", {"page": page, "size": 100})
        if (
            not isinstance(data, dict)
            or type(data.get("total")) is not int
            or not 0 <= data["total"] <= 4000
            or data.get("page") != page
            or data.get("size") != 100
            or not isinstance(data.get("items"), list)
            or len(data["items"]) != min(100, data["total"] - (page - 1) * 100)
            or expected is not None
            and expected != data["total"]
        ):
            raise platform.PlatformUnavailable("账号目录分页不完整或正在变化，请重试；未修改任何账号。")
        expected = data["total"]
        for item in data["items"]:
            if (
                not isinstance(item, dict)
                or type(item.get("id")) is not int
                or item["id"] <= 0
                or item["id"] in seen
                or not isinstance(item.get("username"), str)
                or not 0 < len(item["username"]) <= 64
                or type(item.get("active")) is not bool
                or not isinstance(item.get("primaryRole"), str)
                or item["primaryRole"] not in ROLE_NAMES
                or type(item.get("platformAdmin")) is not bool
                or not isinstance(item.get("projectMemberships"), list)
                or len(item["projectMemberships"]) > 1000
            ):
                raise platform.PlatformUnavailable("账号目录包含重复或无效身份；未修改任何账号。")
            seen.add(item["id"])
            memberships = []
            projects = set()
            for member in item["projectMemberships"]:
                if (
                    not isinstance(member, dict)
                    or type(member.get("projectId")) is not int
                    or member["projectId"] <= 0
                    or member["projectId"] in projects
                    or type(member.get("active")) is not bool
                    or not isinstance(member.get("roles"), list)
                    or len(member["roles"]) > 5
                    or any(
                        not isinstance(role, str) or role not in {*ROLE_NAMES, "PROJECT_ADMIN"}
                        for role in member["roles"]
                    )
                ):
                    raise platform.PlatformUnavailable("账号项目角色快照无效；未修改任何账号。")
                projects.add(member["projectId"])
                memberships.append({key: member[key] for key in ["projectId", "active", "roles"]})
            rows.append(
                {
                    "external_user_id": item["id"],
                    "username": item["username"],
                    "active": item["active"],
                    "role": item["primaryRole"],
                    "role_name": ROLE_NAMES[item["primaryRole"]],
                    "platform_admin": item["platformAdmin"],
                    "projects": memberships,
                }
            )
        if len(rows) == expected:
            return rows
    raise platform.PlatformUnavailable("账号目录超过允许数量，未修改任何账号。")


class LegacyDirectoryPreview(QualityView):
    def get(self, request, **kwargs):
        from .permissions import is_administrator

        if not is_administrator(request.user):
            raise PermissionDenied("原账号目录预检仅供管理员查看。")
        schema = serializers.RegexField(r"^[a-zA-Z0-9_-]{1,80}$")
        instance = schema.run_validation(request.query_params.get("source_instance"))
        project = self.project()
        rows = read_directory(instance)
        identities = {
            row.external_user_id: row
            for row in PlatformIdentity.objects.filter(project=project, source_instance=instance)
        }
        for row in rows:
            identity = identities.get(row["external_user_id"])
            row["mapping_status"] = (
                "disabled" if not row["active"] else "mapped" if identity and identity.active else "unmapped"
            )
            row["native_user_id"] = str(identity.user_id) if identity else None
        response = Response(
            {
                "source_instance": instance,
                "total": len(rows),
                "active": sum(row["active"] for row in rows),
                "results": rows,
                "notice": "只读预检：不创建账号、不导入密码、不自动按同名关联，也不授予项目或角色权限。",
            }
        )
        response["Cache-Control"] = "no-store"
        return response
