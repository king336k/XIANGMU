"""Create a credential-free schema inventory from the reviewed Java Flyway migrations."""
import argparse
import hashlib
import json
from pathlib import Path
import re

EXCLUDED = {'password_hash', 'token_hash', 'credential_hash', 'secret', 'api_key', 'access_token', 'refresh_token'}


def inventory(root):
    result = {}
    for file in sorted(root.glob('V*__*.sql'), key=lambda p: int(p.name.split('__')[0][1:])):
        sql = file.read_text()
        for match in re.finditer(r'CREATE TABLE(?: IF NOT EXISTS)?\s+`?(\w+)`?\s*\((.*?)\)\s*ENGINE', sql, re.S|re.I):
            table,body=match.groups()
            fields=[]
            for definition in re.split(r',\s*(?![^()]*\))',body):
                item=re.match(r'\s*`?(\w+)`?\s+(BIGINT|VARCHAR|TEXT|JSON|DATETIME|DATE|INT|TINYINT|BOOLEAN|LONGBLOB|BINARY|DECIMAL)',definition,re.I)
                if item and item.group(1) not in EXCLUDED:
                    fields.append(item.group(1))
            primary=re.search(r'PRIMARY KEY\s*\(([^)]+)\)',body,re.I)
            keys=[key.strip().strip('`') for key in primary.group(1).split(',')] if primary else []
            result[table]={'columns':fields,'primary_key':keys,'ddl':[file.name],'ddl_sha256':hashlib.sha256(file.read_bytes()).hexdigest()}
        for match in re.finditer(r'ALTER TABLE\s+`?(\w+)`?\s+(.*?);',sql,re.S|re.I):
            table,body=match.groups()
            if table not in result:continue
            for field in re.findall(r'ADD COLUMN\s+`?(\w+)',body,re.I):
                if field not in EXCLUDED and field not in result[table]['columns']:result[table]['columns'].append(field)
            result[table]['ddl'].append(file.name)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('migrations',type=Path);parser.add_argument('output',type=Path);args=parser.parse_args()
    args.output.write_text(json.dumps(inventory(args.migrations),ensure_ascii=False,indent=2)+'\n')
