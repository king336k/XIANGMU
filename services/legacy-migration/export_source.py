"""Offline JSON or explicitly selected local MySQL read-only snapshot export; never logs credentials."""
import argparse
import base64
from datetime import datetime, UTC
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('migration_helpers',ROOT/'ProjectServer/plane/knowledge/legacy_migration.py')
helpers=importlib.util.module_from_spec(spec);spec.loader.exec_module(helpers)
CATALOG=json.loads((ROOT/'ProjectServer/plane/quality/legacy_schema.json').read_text())
RUNTIME={'project_hub_sessions','issue_idempotency_records','seq_problem_package','seq_agent_task','seq_agent_report','issue_ticket_number_sequences'}
SECRET=re.compile(r'password|passwd|token|secret|credential|authorization|cookie',re.I)


def clean(value):
    if isinstance(value,dict):return {key:clean(item) for key,item in value.items() if not SECRET.search(key)}
    if isinstance(value,list):return [clean(item) for item in value]
    if isinstance(value,str):
        try:
            parsed=json.loads(value)
            if isinstance(parsed,(dict,list)):
                safe=clean(parsed)
                if safe!=parsed:return helpers.canonical(safe)
        except ValueError:pass
    return helpers.redact(value)


def mysql_export(container,database):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',container) or not re.fullmatch(r'[A-Za-z0-9_]{1,100}',database):raise ValueError('Invalid local source handle')
    def query(sql):
        response=subprocess.run(['docker','exec',container,'sh','-c','MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --default-character-set=utf8mb4 -uroot -N -B -r -e "$1"','readonly-export',sql],text=True,capture_output=True,timeout=120)
        if response.returncode:raise ValueError('Local readonly export failed; credentials and server errors suppressed')
        return response.stdout.splitlines()
    found={}
    for line in query("SELECT TABLE_NAME,COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='"+database+"' ORDER BY TABLE_NAME,ORDINAL_POSITION"):
        table,column=line.split('\t')
        found.setdefault(table,[]).append(column)
    unknown=set(found)-set(CATALOG)-{'flyway_schema_history'}
    if unknown:raise ValueError('Unreviewed source tables: '+','.join(sorted(unknown)))
    statements=['SET TRANSACTION ISOLATION LEVEL REPEATABLE READ','SET TRANSACTION READ ONLY','START TRANSACTION WITH CONSISTENT SNAPSHOT']
    for table,fields in found.items():
        if table in RUNTIME or table=='flyway_schema_history':continue
        unknown=set(fields)-set(CATALOG[table]['columns'])
        unknown={column for column in unknown if not SECRET.search(column)}
        if unknown:raise ValueError('Unreviewed source columns: '+table+':'+','.join(sorted(unknown)))
        columns=[field for field in fields if field in CATALOG[table]['columns'] and not SECRET.search(field)]
        pairs=','.join("'"+field+"',`"+field+"`" for field in columns if field!='content' or table not in {'embedded_test_artifacts','embedded_task_package_imports'})
        statements.append("SELECT JSON_OBJECT('table','"+table+"','row',JSON_OBJECT("+pairs+")) FROM `"+database+'`.`'+table+'`')
    statements.append('COMMIT')
    tables={table:[] for table in found if table in CATALOG and table not in RUNTIME}
    for line in query(';'.join(statements)):
        value=json.loads(line);tables[value['table']].append(value['row'])
    return tables,{'runtime_tables':sorted(set(found)&RUNTIME),'blob_note':'Binary BLOB bytes require explicit privacy-reviewed attachment export; metadata is not claimed restored'}


def make_export(tables,host,database):
    excluded={table:{'count':len(rows),'reason':'runtime_credentials_or_sequence_state_not_migrated'} for table,rows in tables.items() if table in RUNTIME}
    result={}
    for table,rows in tables.items():
        if table in RUNTIME:continue
        if table not in CATALOG:raise ValueError('Unknown source table: '+table)
        cleaned=[]
        for row in rows:
            unknown=set(row)-set(CATALOG[table]['columns'])
            if any(not SECRET.search(key) for key in unknown):raise ValueError('Unknown source columns: '+table)
            cleaned.append(clean(row))
        result[table]=cleaned
    return {'schema':'hub-full-export-v1','source':{'host':host,'database':database,'source_verified':True,'captured_at':datetime.now(UTC).isoformat(),'read_only':True},'tables':result,'counts':{key:len(rows) for key,rows in result.items()},'table_sha256':{key:helpers.digest(rows) for key,rows in result.items()},'attachments':[],'excluded':excluded}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    group=parser.add_mutually_exclusive_group(required=True);group.add_argument('--input-json',type=Path);group.add_argument('--mysql-container')
    parser.add_argument('--database',required=True);parser.add_argument('--host-label',required=True)
    parser.add_argument('--attachment-manifest',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:
        if args.input_json:
            tables=json.loads(args.input_json.read_text());notes={}
        else:tables,notes=mysql_export(args.mysql_container,args.database)
        result=make_export(tables,args.host_label,args.database);result['export_notes']=notes
        if args.attachment_manifest:result['attachments']=json.loads(args.attachment_manifest.read_text())
        if clean(result)!=result:raise ValueError('Attachment or source metadata needs credential sanitization')
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');args.output.chmod(0o600)
        print(json.dumps({'tables':len(result['tables']),'rows':sum(result['counts'].values()),'output':str(args.output)},ensure_ascii=False))
    except (ValueError,OSError) as error:
        print(str(error),file=sys.stderr);raise SystemExit(2)
