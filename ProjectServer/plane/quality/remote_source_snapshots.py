# SPDX-License-Identifier: AGPL-3.0-only
"""Project-scoped, immutable local source snapshots; no Git/network or model paths."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import time

SCHEMA='remote-source-snapshot-v1'
MAX_FILE_BYTES=256*1024
MAX_TOTAL_BYTES=128*1024*1024
MAX_MANIFEST_BYTES=16*1024*1024
MAX_SEARCH_BYTES=32*1024*1024
SOURCE_ID=re.compile(r'[a-z0-9][a-z0-9_-]{0,59}\Z')
COMMIT=re.compile(r'(?:[a-f0-9]{40}|[a-f0-9]{64})\Z')
SUFFIXES={'.py','.cpp','.hpp','.h','.c','.cc','.cxx','.cmake','.yaml','.yml','.json','.xml','.toml',
          '.ini','.cfg','.md','.rst','.sh','.bash','.txt','.msg','.srv','.action','.launch','.ts','.tsx',
          '.js','.jsx','.mjs','.cjs','.html','.css','.sql','.proto','.urdf','.xacro'}


def safe_path(path, allow_empty=False):
    if not isinstance(path,str) or len(path)>700 or (not path and not allow_empty):
        raise ValueError('invalid_source_path')
    if not path and allow_empty:return ''
    if (path.startswith('/') or any(char in path for char in ('\\','%',':','\x00','?','#'))
            or any(ord(char)<32 for char in path) or any(part in {'','.','..'} for part in path.split('/'))):
        raise ValueError('invalid_source_path')
    return path


def omitted_path_reason(path):
    try:safe_path(path)
    except ValueError:return 'unsafe_path'
    parts=PurePosixPath(path).parts
    if any(part in {'.git','.ssh','.aws','.azure','.kube'} or part.lower().startswith('.env') or
           re.search(r'(?i)(?:^|[._-])(?:secret|password|passwd|credentials?|tokens?|id_rsa|id_ed25519)(?:[._-]|$)',part)
           for part in parts):return 'sensitive_path'
    name=parts[-1]
    if name.lower().endswith(('.pem','.key','.p12','.pfx','.keystore')):return 'key_material'
    if Path(name).suffix.lower() not in SUFFIXES and name not in {'.gitmodules','Makefile','Dockerfile','CMakeLists.txt'}:
        return 'unsupported_source_type'
    return None


def sensitive_content(text):
    # A conservative build-time omission, not a promise of complete secret detection.
    return bool(re.search(r'https?://[^/\s:]+:[^/\s@]+@|-----BEGIN [^-\n]*PRIVATE KEY-----|\b(?:gh[pousr]_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})\b|'
        r'^\s*[\"\']?[\w.]*\b(?:api[_-]?key|password|passwd|access[_-]?token|client[_-]?secret)[\"\']?\s*[:=]\s*[\"\'][^\"\'\n]{8,}[\"\']|^\s*[\"\']?(?:password|passwd|api[_-]?key|access[_-]?token|client[_-]?secret)[\"\']?\s*[:=]\s*[A-Za-z0-9_./+-]{8,}\s*$',text,flags=re.I|re.M))


def _directory(path):
    path=Path(path).absolute()
    if path.resolve()!=path:raise ValueError('snapshot_symlink_rejected')
    return path


def _bytes(base, relative, maximum):
    """Open each component without following symlinks; immutable files only."""
    parts=safe_path(relative).split('/')
    descriptor=os.open(_directory(base),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=descriptor)
            os.close(descriptor);descriptor=child
            if os.fstat(descriptor).st_mode&0o222:raise ValueError('snapshot_directory_writable')
        file=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=descriptor)
        with os.fdopen(file,'rb') as stream:
            before=os.fstat(stream.fileno())
            if (not stat.S_ISREG(before.st_mode) or before.st_mode&0o222 or before.st_nlink!=1
                    or before.st_size>maximum):raise ValueError('snapshot_file_not_immutable')
            data=stream.read(maximum+1)
            after=os.fstat(stream.fileno())
            if len(data)>maximum or (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):
                raise ValueError('snapshot_file_changed')
            return data
    except OSError:
        raise ValueError('snapshot_path_unavailable_or_symlink') from None
    finally:os.close(descriptor)


def _manifest(directory):
    if _directory(directory).stat().st_mode&0o222:raise ValueError('snapshot_directory_writable')
    data=_bytes(directory,'manifest.json',MAX_MANIFEST_BYTES)
    value=json.loads(data)
    if (not isinstance(value,dict) or value.get('schema')!=SCHEMA or
            not SOURCE_ID.fullmatch(str(value.get('source_id',''))) or
            not COMMIT.fullmatch(str(value.get('repository_commit',''))) or
            not isinstance(value.get('project_ids'),list) or not value['project_ids'] or
            not all(isinstance(item,str) and 0<len(item)<=100 for item in value['project_ids']) or
            not isinstance(value.get('files'),dict) or len(value['files'])>100000):
        raise ValueError('snapshot_manifest_invalid')
    total=0
    for path,metadata in value['files'].items():
        if omitted_path_reason(path) or not isinstance(metadata,dict):raise ValueError('snapshot_manifest_invalid')
        size=metadata.get('size');digest=metadata.get('sha256')
        if type(size) is not int or not 0<=size<=MAX_FILE_BYTES or not re.fullmatch(r'[a-f0-9]{64}',str(digest)):
            raise ValueError('snapshot_manifest_invalid')
        total+=size
    if total>MAX_TOTAL_BYTES:raise ValueError('snapshot_total_bytes_exceeded')
    return value,hashlib.sha256(data).hexdigest()


def _sources(root,project_id):
    root=_directory(root)
    if not root.is_dir():return []
    candidates=[root] if (root/'manifest.json').exists() else sorted(root.iterdir())
    found=[];seen=set()
    for directory in candidates[:100]:
        if not directory.is_dir():continue
        try:manifest,digest=_manifest(directory)
        except (OSError,ValueError):continue
        if str(project_id) not in manifest['project_ids']:continue
        if manifest['source_id'] in seen:raise ValueError('duplicate_snapshot_source_id')
        seen.add(manifest['source_id']);found.append((directory,manifest,digest))
    return found


def _provenance(directory,manifest,digest):
    return {'source':'local_source_snapshot','source_id':manifest['source_id'],
            'source_repository':manifest.get('source_repository',''),
            'repository_commit':manifest['repository_commit'],'manifest_sha256':digest,
            'rootlabel':directory.name,'untrusted_reference':True}


def catalog(root,project_id):
    return {'source':'trusted_local_source_catalog','sources':[
        {'id':manifest['source_id'],'kind':'local_snapshot',**_provenance(directory,manifest,digest)}
        for directory,manifest,digest in _sources(root,project_id)]}


def _text(directory,manifest,path):
    metadata=manifest['files'].get(path)
    if not metadata:raise ValueError('source_path_not_in_manifest')
    data=_bytes(directory,'files/'+path,MAX_FILE_BYTES)
    if len(data)!=metadata['size'] or hashlib.sha256(data).hexdigest()!=metadata['sha256']:
        raise ValueError('snapshot_content_hash_mismatch')
    if any(value<32 and value not in {9,10,12,13} for value in data):raise ValueError('snapshot_binary_rejected')
    try:return data.decode('utf-8'),metadata
    except UnicodeDecodeError:raise ValueError('snapshot_text_encoding_invalid') from None


def _clean_text(text,cleaner):
    """Redact complete context before slicing; never claim shifted source lines."""
    def block(match):
        return ''.join('[PRIVATE KEY REDACTED]'+('\n' if line.endswith('\n') else '')
                       for line in match.group().splitlines(keepends=True))
    masked=re.sub(r'-----BEGIN [^-\n]*PRIVATE KEY-----.*?(?:-----END [^-\n]*PRIVATE KEY-----|\Z)',block,text,flags=re.S)
    cleaned=cleaner(masked)
    if not isinstance(cleaned,str):raise ValueError('source_redactor_invalid')
    trailing=len(text)-len(text.rstrip('\n'))
    cleaned=cleaned.rstrip('\n')+'\n'*trailing
    if cleaned.count('\n')!=text.count('\n'):
        # Structured redactors may reserialize JSON or collapse sensitive blocks.
        # Fail closed rather than invent a correspondence to original source lines.
        return ''.join('[REDACTED]'+('\n' if line.endswith('\n') else '')
                       for line in text.splitlines(keepends=True))
    return cleaned


def _redactor(callback):
    if callback is not None:return callback
    from .diagnostic_materials import redact
    return redact


def read(root,project_id,source_id,path='',operation='read_source',query=None,offset=0,redact_fn=None):
    if not isinstance(source_id,str) or not SOURCE_ID.fullmatch(source_id):raise ValueError('source_not_authorized')
    if operation not in {'read_source','list_source_paths','search_source'}:raise ValueError('unsupported_source_operation')
    maximum_offset=MAX_FILE_BYTES if operation=='read_source' else 100000
    if type(offset) is not int or not 0<=offset<=maximum_offset:raise ValueError('invalid_source_offset')
    path=safe_path(path,allow_empty=operation!='read_source')
    selected=[row for row in _sources(root,project_id) if row[1]['source_id']==source_id]
    if not selected:raise ValueError('source_not_authorized')
    directory,manifest,digest=selected[0]
    response={**_provenance(directory,manifest,digest),'path':path}
    if operation=='read_source':
        text,metadata=_text(directory,manifest,path)
        text=_clean_text(text,_redactor(redact_fn))
        stop=offset+20000
        response.update(content=text[offset:stop],blob_sha256=metadata['sha256'],
            size=metadata['size'],content_offset=offset,content_start_line=text[:offset].count('\n')+1,
            truncated=len(text)>stop,next_offset=stop if len(text)>stop else None)
        return response
    prefix=path+'/' if path else ''
    files=[name for name in sorted(manifest['files']) if name.startswith(prefix)]
    if operation=='list_source_paths':
        entries={}
        for name in files:
            tail=name[len(prefix):];first,slash,_=tail.partition('/')
            entries[first]={'name':first,'path':prefix+first,'type':'dir' if slash else 'file'}
            if not slash:entries[first].update(blob_sha256=manifest['files'][name]['sha256'],size=manifest['files'][name]['size'])
        values=list(entries.values());response.update(entries=values[offset:offset+40],truncated=len(values)>offset+40,
            next_offset=offset+40 if len(values)>offset+40 else None,total=len(values));return response
    if not isinstance(query,str) or not 1<=len(query)<=100 or any(ord(char)<32 for char in query):
        raise ValueError('invalid_literal_source_query')
    deadline=time.monotonic()+2;scanned=0;matches=[];scanned_files=0;truncated=False;continuation=None
    cleaner=_redactor(redact_fn)
    for name in files[offset:]:
        size=manifest['files'][name]['size']
        if time.monotonic()>=deadline or scanned+size>MAX_SEARCH_BYTES or len(matches)>=20:
            truncated=True;break
        text,metadata=_text(directory,manifest,name);scanned+=size;scanned_files+=1
        sanitized_lines=_clean_text(text,cleaner).splitlines()
        for line,content in enumerate(text.splitlines(),1):
            if query in content:
                position=content.index(query);safe_line=sanitized_lines[line-1]
                excerpt=safe_line[max(0,min(position,len(safe_line))-150):min(position,len(safe_line))+len(query)+250]
                matches.append({'path':name,'line':line,'excerpt':excerpt,'blob_sha256':metadata['sha256']})
                if len(matches)>=20:
                    truncated=True
                    continuation={'operation':'read_source','path':name,'line':line,
                        'offset':sum(len(part) for part in text.splitlines(keepends=True)[:line])}
                    break
    response.update(query=query,matches=matches,scanned_bytes=scanned,scanned_files=scanned_files,truncated=truncated,
        next_offset=offset+scanned_files if truncated else None,per_file_truncated=continuation is not None,continuation=continuation)
    return response
