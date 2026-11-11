"""A workspace duty grants access to each current and future project in that workspace."""

from plane.db.models import WorkspaceMember, ProjectMember


def inherit_project_access(sender, instance, created, raw=False, **kwargs):
    if not created or raw:
        return
    for row in WorkspaceMember.objects.filter(
        workspace_id=instance.workspace_id, is_active=True, role__gte=15, member__is_active=True
    ).exclude(business_roles=[]):
        ProjectMember.objects.get_or_create(
            project=instance, member_id=row.member_id, defaults={"workspace_id": instance.workspace_id, "role": 15}
        )

    from plane.knowledge.base_knowledge import share_base_knowledge

    share_base_knowledge(instance)
