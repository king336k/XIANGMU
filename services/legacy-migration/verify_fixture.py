"""Persist a complete isolated fixture, prove rerun/guarded rollback, then remove imported graph."""
import json
from pathlib import Path
import sys
import uuid
from django.db import connection
from plane.db.models import User, Workspace, WorkspaceMember, Project, ProjectMember
from plane.quality.models import PlatformIdentity, LegacyMigrationRun, LegacyMigrationRecord
from plane.quality.legacy_migration import build_plan, preview_plan, apply_plan, rollback, model_snapshot, digest
from plane.tests.contract.app.test_legacy_migration import complete_snapshot

if connection.settings_dict['NAME']!='test_legacy_full_finish':raise RuntimeError('Fixture runner only allows its dedicated test database')
root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=True)
user=User.objects.create(email='migration-fixture-'+uuid.uuid4().hex+'@accounts.invalid',username='migration-fixture-'+uuid.uuid4().hex,display_name='隔离迁移验收')
user.set_unusable_password();user.save()
workspace=Workspace.objects.create(name='全业务迁移隔离验收',slug='migration-fixture-'+uuid.uuid4().hex[:12],owner=user)
WorkspaceMember.objects.create(workspace=workspace,member=user,role=20)
project=Project.objects.create(workspace=workspace,name='旧库全业务独立fixture',identifier='LEGFIX',network=0)
ProjectMember.objects.create(project=project,member=user,role=20)
PlatformIdentity.objects.create(project=project,created_by=user,source_instance='legacy-fixture',external_user_id=1,user=user)
source=complete_snapshot();source['source']['database']='fixture-'+uuid.uuid4().hex
mapping={'projects':{'9':str(project.id)},'users':{'1':str(user.id)},'source_instance':'legacy-fixture'}
plan=build_plan(source,mapping)
assert not plan['conflicts']
preview=preview_plan(plan,user);assert not LegacyMigrationRun.objects.filter(source_key=plan['source_key']).exists()
first=apply_plan(plan,user);second=apply_plan(plan,user)
assert second['unchanged_records']==first['created_records']
records=list(LegacyMigrationRecord.objects.filter(run_id=first['run_id']).values('source_table','source_id','source_hash','disposition','targets'))
(root/'source-export.json').write_text(json.dumps(source,ensure_ascii=False,indent=2))
(root/'mapping.json').write_text(json.dumps(mapping,indent=2))
(root/'dry-run.json').write_text(json.dumps({'counts':plan['counts'],'dispositions':plan['dispositions'],'conflicts':plan['conflicts'],'absent_tables':plan['absent_tables'],'manifest_hash':plan['manifest_hash'],'preview':preview},ensure_ascii=False,indent=2))
rolled=rollback(first['run_id'],user)
assert rolled['status']=='rolled_back'
proof={'scope':'isolated complete-schema fixture, no source157/DP connections or production cutover','project_id':str(project.id),'workspace':workspace.slug,'native_password_usable':user.has_usable_password(),'first':first,'second':second,'rollback':rolled,'records':records,'counts':plan['counts'],'retained_source_audit_records':LegacyMigrationRecord.objects.filter(run_id=first['run_id']).count()}
(root/'verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2))
for path in root.glob('*.json'):path.chmod(0o600)
print(json.dumps({'created_source_records':first['created_records'],'created_targets':first['native_targets'],'unchanged':second['unchanged_records'],'rollback':rolled['status'],'evidence':str(root)},ensure_ascii=False))
