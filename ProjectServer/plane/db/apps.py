# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.apps import AppConfig


class DbConfig(AppConfig):
    name = "plane.db"

    def ready(self):
        from django.db.models.signals import post_save
        from plane.quality.workspace_roles import inherit_project_access
        from plane.db.models import Project

        post_save.connect(inherit_project_access, sender=Project, dispatch_uid="workspace_business_role_inheritance")
