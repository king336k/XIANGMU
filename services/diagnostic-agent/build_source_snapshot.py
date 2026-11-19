#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Build read-only source evidence from an exact local Git commit, never worktree files."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit,urlunsplit

SPEC=importlib.util.spec_from_file_location('snapshot_contract',Path(__file__).resolve().parents[2]/'ProjectServer/plane/quality/remote_source_snapshots.py')
contract=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(contract)
MAX_TOTAL_BYTES=contract.MAX_TOTAL_BYTES


def _git(repo,*args):
    return subprocess.check_output(['git','-C',str(repo),*args],stderr=subprocess.DEVNULL,timeout=60,
        env={**os.environ,'GIT_CONFIG_NOSYSTEM':'1','GIT_TERMINAL_PROMPT':'0','GIT_NO_REPLACE_OBJECTS':'1'})


def _origin(repo):
    try:value=_git(repo,'remote','get-url','origin').decode().strip()
    except (subprocess.SubprocessError,UnicodeError):return ''
    if re.fullmatch(r'[^@\s]+@[^:\s]+:.+',value):value='ssh://'+value.replace(':','/',1)
    try:
        parts=urlsplit(value)
        if parts.scheme not in {'https','http','ssh','git'} or not parts.hostname:return ''
        host=parts.hostname+(':'+str(parts.port) if parts.port else '')
        return urlunsplit((parts.scheme,host,parts.path,'',''))
    except ValueError:return ''


def build(repo,commit,output,source_id,project_id):
    if not isinstance(commit,str) or not contract.COMMIT.fullmatch(commit):raise ValueError('exact_commit_required')
    if not isinstance(source_id,str) or not contract.SOURCE_ID.fullmatch(source_id):raise ValueError('invalid_source_id')
    project_id=str(project_id)
    if not 0<len(project_id)<=100 or any(ord(char)<32 for char in project_id):raise ValueError('invalid_project_id')
    repo=Path(repo).absolute();output=Path(output).absolute()
    if output.exists() or output.is_symlink():raise FileExistsError('snapshot_output_exists')
    if repo.resolve()!=repo or output.parent.resolve()!=output.parent:raise ValueError('snapshot_symlink_rejected')
    resolved=_git(repo,'rev-parse','--verify',commit+'^{commit}').decode().strip()
    if resolved!=commit:raise ValueError('exact_commit_required')
    tree=_git(repo,'ls-tree','-r','-l','-z','--full-tree',commit)
    if len(tree)>16*1024*1024:raise ValueError('snapshot_tree_too_large')
    manifest={'schema':contract.SCHEMA,'source_id':source_id,'project_ids':[project_id],
        'repository_commit':commit,'source_repository':_origin(repo),'files':{},'omitted':[]}
    output.mkdir(mode=0o700);files_root=output/'files';files_root.mkdir(mode=0o700)
    total=0
    process=subprocess.Popen(['git','-C',str(repo),'cat-file','--batch'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,env={**os.environ,'GIT_NO_REPLACE_OBJECTS':'1','GIT_TERMINAL_PROMPT':'0'})
    try:
        for entry in tree.split(b'\x00'):
            if not entry:continue
            header,raw_path=entry.split(b'\t',1);mode,kind,oid,tree_size=header.decode('ascii').split()
            try:path=raw_path.decode('utf-8')
            except UnicodeError:
                manifest['omitted'].append({'path':'[non-UTF8 path]','reason':'unsafe_path'});continue
            reason='symlink_not_allowed' if mode=='120000' else 'submodule_requires_separate_snapshot' if kind=='commit' else contract.omitted_path_reason(path)
            if not reason and int(tree_size)>contract.MAX_FILE_BYTES:reason='file_too_large'
            if reason:
                manifest['omitted'].append({'path':path,'reason':reason});continue
            process.stdin.write(oid.encode()+b'\n');process.stdin.flush()
            details=process.stdout.readline().decode('ascii').strip().split(' ')
            if len(details)!=3 or details[1]!='blob':raise ValueError('git_blob_unavailable')
            size=int(details[2])
            if size>contract.MAX_FILE_BYTES:
                remaining=size
                while remaining:
                    chunk=process.stdout.read(min(65536,remaining))
                    if not chunk:raise ValueError('git_blob_invalid')
                    remaining-=len(chunk)
                if process.stdout.read(1)!=b'\n':raise ValueError('git_blob_invalid')
                manifest['omitted'].append({'path':path,'reason':'file_too_large'});continue
            data=process.stdout.read(size);newline=process.stdout.read(1)
            if len(data)!=size or newline!=b'\n':raise ValueError('git_blob_invalid')
            if any(value<32 and value not in {9,10,12,13} for value in data):reason='binary_not_allowed'
            else:
                try:text=data.decode('utf-8')
                except UnicodeError:reason='non_utf8_not_allowed'
                else:
                    if contract.sensitive_content(text):reason='sensitive_content'
            if reason:
                manifest['omitted'].append({'path':path,'reason':reason});continue
            if total+size>MAX_TOTAL_BYTES:raise ValueError('snapshot_total_bytes_exceeded')
            target=files_root/path;target.parent.mkdir(parents=True,exist_ok=True)
            descriptor=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o400)
            with os.fdopen(descriptor,'wb') as stream:stream.write(data)
            target.chmod(0o444)
            manifest['files'][path]={'sha256':hashlib.sha256(data).hexdigest(),'size':size};total+=size
        manifest['total_bytes']=total
        encoded=json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2).encode()
        if len(encoded)>contract.MAX_MANIFEST_BYTES:raise ValueError('snapshot_manifest_too_large')
        (output/'manifest.json').write_bytes(encoded);(output/'manifest.json').chmod(0o444)
        for directory in sorted((path for path in output.rglob('*') if path.is_dir()),key=lambda path:len(path.parts),reverse=True):directory.chmod(0o555)
        output.chmod(0o555)
        return manifest
    finally:
        process.stdin.close();process.stdout.close();process.wait(timeout=10)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('repo','commit','output','source-id','project-id'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    try:
        result=build(args.repo,args.commit,args.output,args.source_id,args.project_id)
        print(json.dumps({'source_id':result['source_id'],'repository_commit':result['repository_commit'],
            'files':len(result['files']),'omitted':len(result['omitted']),'total_bytes':result['total_bytes']}))
    except (OSError,ValueError,subprocess.SubprocessError):
        raise SystemExit('source_snapshot_build_failed') from None


if __name__=='__main__':main()
