"""Single-defect explicit administrator approval. Preview never changes records."""
import json
from django.core.management.base import BaseCommand,CommandError
from django.core.exceptions import ObjectDoesNotExist,ValidationError as DjangoValidationError
from rest_framework.exceptions import APIException
from plane.db.models import User
from plane.quality.daq_execution_binding import approve_execution_binding


class Command(BaseCommand):
    help='Preview a single historical DAQ feedback read-only execution binding; --apply records explicit approval.'

    def add_arguments(self,parser):
        parser.add_argument('--actor-id',required=True)
        parser.add_argument('--defect-id',required=True)
        parser.add_argument('--station-id',required=True)
        parser.add_argument('--reason',required=True)
        parser.add_argument('--expected-current-source',required=True)
        parser.add_argument('--apply',action='store_true')

    def handle(self,*args,**options):
        try:
            actor=User.objects.get(pk=options['actor_id'],is_active=True,is_bot=False)
            result=approve_execution_binding(actor=actor,defect_id=options['defect_id'],station_id=options['station_id'],
                reason=options['reason'],expected_current_source=options['expected_current_source'],apply=options['apply'])
        except (ObjectDoesNotExist,DjangoValidationError,APIException,ValueError) as error:
            raise CommandError('单条反馈绑定审批被拒绝：'+str(getattr(error,'detail','输入或当前权限无效。'))) from None
        self.stdout.write(json.dumps(result,ensure_ascii=False))
