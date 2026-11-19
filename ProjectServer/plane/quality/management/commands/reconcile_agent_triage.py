"""Explicitly scoped reconciliation; safe preview is the default."""
import json
from django.core.management.base import BaseCommand
from django.db.models import OuterRef, Subquery
from plane.quality.remote_models import RemoteAgentRun
from plane.quality.agent_lifecycle import reconcile


class Command(BaseCommand):
    help='Preview latest Agent triage per defect in one project; --apply changes only eligible rows.'

    def add_arguments(self, parser):
        parser.add_argument('--project-id',required=True)
        parser.add_argument('--defect-id',action='append',default=[])
        parser.add_argument('--apply',action='store_true')

    def handle(self,*args,**options):
        newest=RemoteAgentRun.objects.filter(defect_id=OuterRef('defect_id')).order_by('-created_at','-id').values('id')[:1]
        rows=RemoteAgentRun.objects.filter(defect__project_id=options['project_id'],id=Subquery(newest))
        if options['defect_id']:rows=rows.filter(defect_id__in=options['defect_id'])
        for row in rows.order_by('created_at','id').iterator():
            self.stdout.write(json.dumps(reconcile(row,apply=options['apply']),ensure_ascii=False))
