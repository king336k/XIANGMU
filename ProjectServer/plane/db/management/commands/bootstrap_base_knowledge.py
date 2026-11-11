"""Create the editable base knowledge edition once in each administered workspace."""

from django.core.management.base import BaseCommand
from plane.db.models import WorkspaceMember
from plane.quality.permissions import is_administrator
from plane.knowledge.base_knowledge import initialize_base_knowledge


class Command(BaseCommand):
    help = "Initialize the combined base knowledge without overwriting existing data"

    def handle(self, *args, **options):
        seen = set()
        created = 0
        for member in (
            WorkspaceMember.objects.filter(is_active=True, role__gte=15, member__is_active=True)
            .select_related("workspace", "member")
            .order_by("created_at")
        ):
            if member.workspace_id in seen or not is_administrator(member.member):
                continue
            result = initialize_base_knowledge(member.workspace, member.member)
            created += result["created"]
            seen.add(member.workspace_id)
        self.stdout.write(f"Base knowledge ready: {created} new articles; existing editions preserved")
