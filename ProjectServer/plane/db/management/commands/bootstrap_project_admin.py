"""Initialize an empty independent deployment once; never reset an existing owner."""

import os
from uuid import uuid4
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from plane.db.models import User, Profile, Workspace, WorkspaceMember
from plane.license.models import Instance, InstanceAdmin, InstanceConfiguration
from plane.quality.models import LocalManagedAccount


class Command(BaseCommand):
    help = "Initialize the project platform administrator on the first deployment"

    @transaction.atomic
    def handle(self, *args, **options):
        instance = Instance.objects.select_for_update().first()
        if InstanceAdmin.objects.filter(user__is_active=True, user__is_bot=False).exists():
            self.stdout.write("Existing administrator preserved")
            return
        if instance and instance.is_setup_done:
            raise CommandError("Configured instance has no administrator; recover it explicitly")
        if User.objects.filter(is_bot=False).exists():
            raise CommandError("Existing users found; automatic administrator initialization refused")
        if not instance:
            instance = Instance.objects.create(
                instance_name="项目管理平台",
                instance_id=str(uuid4()),
                current_version="1.0",
                last_checked_at=timezone.now(),
                is_telemetry_enabled=False,
                is_support_required=False,
            )
        user = User(
            username=os.environ.get("PROJECT_INITIAL_ADMIN_USERNAME", "admin"),
            email="administrator@accounts.invalid",
            display_name="管理员",
            first_name="管理员",
            is_password_autoset=False,
        )
        user.set_password(os.environ.get("PROJECT_INITIAL_ADMIN_PASSWORD", "123456"))
        user.save()
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.is_onboarded = True
        profile.is_navigation_tour_completed = True
        profile.language = "zh-CN"
        profile.onboarding_step = {key: True for key in profile.onboarding_step}
        profile.save()
        LocalManagedAccount.objects.create(user=user, created_by=user)
        InstanceAdmin.objects.create(instance=instance, user=user, role=20)
        workspace = Workspace.objects.create(name="项目协作", slug="projects", owner=user, created_by=user)
        WorkspaceMember.objects.create(workspace=workspace, member=user, role=20, created_by=user)
        profile.last_workspace_id = workspace.id
        profile.save(update_fields=["last_workspace_id"])
        instance.is_setup_done = True
        instance.save(update_fields=["is_setup_done"])
        InstanceConfiguration.objects.update_or_create(
            key="ENABLE_SIGNUP", defaults={"value": "0", "category": "AUTHENTICATION"}
        )
        self.stdout.write("Project administrator initialized; change its password in account settings")
