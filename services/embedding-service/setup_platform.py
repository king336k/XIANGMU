"""Default built-in BGE deployment wrapper. Check-only unless --apply; never writes provider DB."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import time
from urllib.parse import urljoin, urlsplit

import docker
import requests

HERE=Path(__file__).resolve().parent
SERVICE='builtin-embedding'
MODEL='bge-small-zh-v1.5'
BASE='http://builtin-embedding:18885/v1'
DEFAULT_IMAGE='engramproject/embedding:bge-small-zh-v1.5'
DOWNLOAD_HOSTS={'huggingface.co','cdn-lfs.huggingface.co','cdn-lfs-us-1.huggingface.co',
                'cas-bridge.xethub.hf.co','cas-server.xethub.hf.co'}
RESUME_FIELDS={'version','project_root','project_name','compose_files','env_file','network','model_dir','image','api_services'}
PRESERVED_ENV={'DOCUMENT_OCR_BASE_URL','DOCUMENT_OCR_API_KEY','DOCUMENT_OCR_ALLOWED_HTTP_ORIGINS',
               'KNOWLEDGE_EMBEDDING_ALLOWED_HTTP_ORIGINS'}


def resume_options(args):
    project=Path(args.project_root).expanduser().resolve(strict=True)
    path=project/'deploy/local/builtin-embedding.json'
    descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(descriptor) as source:
        info=os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size>32768:
            raise ValueError('invalid built-in deployment record; existing services preserved')
        record=json.load(source)
    if not isinstance(record,dict) or set(record)!=RESUME_FIELDS or record['version']!=1:
        raise ValueError('invalid built-in deployment record; existing services preserved')
    if record['project_root']!=str(project) or not isinstance(record['compose_files'],list) or not record['compose_files']:
        raise ValueError('deployment record belongs to a different project; existing services preserved')
    if len(record['compose_files'])>20 or any(not isinstance(p,str) for p in record['compose_files']):
        raise ValueError('invalid deployment Compose files')
    for name in RESUME_FIELDS-{'version','compose_files'}:
        if not isinstance(record[name],str) or not record[name] or len(record[name])>4096:
            raise ValueError('invalid built-in deployment record')
    for name in ['project_name','env_file','network','model_dir','image','api_services']:
        setattr(args,name,record[name])
    args.compose_file=record['compose_files']
    return args


def save_resume(project,args,compose,env_file,model,network):
    path=project/'deploy/local/builtin-embedding.json'
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError('invalid deployment record path; refusing overwrite')
    path.parent.mkdir(parents=True,exist_ok=True)
    record={'version':1,'project_root':str(project),'project_name':args.project_name,
            'compose_files':[str(p) for p in compose],'env_file':str(env_file),'network':network,
            'model_dir':str(model),'image':args.image,'api_services':args.api_services}
    temporary=path.with_name(path.name+'.'+secrets.token_hex(8)+'.part')
    try:
        descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,'w') as output:
            json.dump(record,output);output.flush();os.fsync(output.fileno())
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)


def preserved_environment(client,project,services):
    values={}
    for container in client.containers.list(all=True,filters={'label':'com.docker.compose.project='+project}):
        config=container.attrs.get('Config',{});labels=config.get('Labels') or {}
        if labels.get('com.docker.compose.project')!=project or labels.get('com.docker.compose.service') not in services:
            continue
        for entry in config.get('Env') or []:
            name,separator,value=entry.partition('=')
            if separator and name in PRESERVED_ENV and value:
                if name in values and values[name]!=value:
                    raise ValueError('platform extension settings disagree; existing services preserved')
                values[name]=value
    return values


def load_manifest():
    return json.loads((HERE/'model-manifest.json').read_text())


def verify_file(path,entry):
    if path.is_symlink() or not path.is_file() or path.stat().st_size!=entry['size']:
        return False
    digest=hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda:source.read(2*1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()==entry['sha256']


def download_model(directory,entry):
    """Exact manifest URLs only, bounded redirects/stream, no overwrite of any existing path."""
    directory=Path(directory)
    target=directory/entry['name']
    if target.exists() or target.is_symlink():raise ValueError('model path exists; refusing overwrite')
    directory.mkdir(parents=True,exist_ok=True)
    temporary=directory/(entry['name']+'.'+secrets.token_hex(8)+'.part')
    response=None
    try:
        url=entry['url'];deadline=time.monotonic()+300
        for _ in range(6):
            parts=urlsplit(url)
            if parts.scheme!='https' or parts.hostname not in DOWNLOAD_HOSTS or parts.username or parts.password:
                raise ValueError('model redirect is outside approved official hosts')
            response=requests.get(url,stream=True,timeout=(10,30),allow_redirects=False,
                                  headers={'Accept-Encoding':'identity'})
            if response.status_code in {301,302,303,307,308}:
                next_url=urljoin(url,response.headers.get('Location',''));response.close();response=None
                if next_url==url:raise ValueError('model redirect missing')
                url=next_url;continue
            if response.status_code!=200:raise ValueError('model download unavailable; details suppressed')
            break
        else:raise ValueError('model redirect budget exceeded')
        size=0;digest=hashlib.sha256()
        descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o644)
        with os.fdopen(descriptor,'wb') as output:
            for chunk in response.iter_content(2*1024*1024):
                size+=len(chunk)
                if size>entry['size'] or time.monotonic()>deadline:raise ValueError('model download budget exceeded')
                digest.update(chunk);output.write(chunk)
            output.flush();os.fsync(output.fileno())
        if size!=entry['size'] or digest.hexdigest()!=entry['sha256']:raise ValueError('model checksum mismatch')
        # Hard-link publishes atomically with no replacement even if another installer raced.
        os.link(temporary,target)
    finally:
        if response is not None:response.close()
        temporary.unlink(missing_ok=True)


def wait_ready(client,name,seconds=90):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        try:
            container=client.containers.get(name)
            result=container.exec_run(['python','-c',"import json,urllib.request;r=json.load(urllib.request.urlopen('http://127.0.0.1:18885/health',timeout=3));assert r['status']=='ready' and r['dimensions']==512"])
            if result.exit_code==0:return True
        except Exception:pass
        time.sleep(1)
    return False


def arguments(argv):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root',default=str(HERE.parents[1]))
    parser.add_argument('--project-name',default='engramproject')
    parser.add_argument('--compose-file',action='append',default=[])
    parser.add_argument('--env-file')
    parser.add_argument('--network',help='Dedicated internal embedding network; existing network is not reconfigured')
    parser.add_argument('--model-dir',default=str(Path.home()/'Documents/tmp/artifacts/embedding-model-cache'/MODEL))
    parser.add_argument('--image',default=DEFAULT_IMAGE)
    parser.add_argument('--api-services',default='migrator,api,worker,beat-worker,diagnostic-worker')
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--resume',action='store_true',help='Reuse this project deployment record, never download or build')
    parser.add_argument('--start-platform',action='store_true',help='Start the complete saved Compose deployment')
    parser.add_argument('--download-model',action='store_true')
    parser.add_argument('--build-image',action='store_true',help='Explicit first-install build if the embedding image is missing')
    return parser.parse_args(argv)


def main(argv=None):
    args=arguments(argv);client=None
    try:
        if args.resume:
            if args.download_model or args.build_image:
                raise ValueError('resume does not download or build')
            args=resume_options(args)
        if (args.download_model or args.build_image) and not args.apply:
            raise ValueError('--download-model/--build-image require --apply')
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,62}',args.project_name):raise ValueError('invalid Compose project name')
        services=args.api_services.split(',')
        if not services or any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*',x) for x in services):raise ValueError('invalid API service names')
        project=Path(args.project_root).expanduser().resolve(strict=True)
        compose=[Path(x).expanduser().resolve(strict=True) for x in args.compose_file] or [project/'docker-compose.yml']
        if not all(x.is_file() for x in compose):raise ValueError('Compose file is missing')
        env_file=Path(args.env_file).expanduser().resolve(strict=True) if args.env_file else project/'deploy/local/.env'
        if not env_file.is_file():raise ValueError('platform environment is missing; initialize it first')
        model=Path(args.model_dir).expanduser().resolve();manifest=load_manifest()
        for entry in manifest['files']:
            path=model/entry['name']
            if path.exists() or path.is_symlink():
                if not verify_file(path,entry):raise ValueError('existing model checksum mismatch; original file preserved')
        for entry in manifest['files']:
            path=model/entry['name']
            if path.exists():continue
            if args.download_model:download_model(model,entry)
            else:raise ValueError('model files missing; use verified offline directory or --apply --download-model')
        network=args.network or args.project_name+'_embedding'
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}',network):raise ValueError('invalid network name')
        client=docker.from_env()
        retained=preserved_environment(client,args.project_name,services) if args.resume else {}
        try:image=client.images.get(args.image)
        except docker.errors.ImageNotFound:
            if not args.build_image:raise ValueError('embedding image missing; build it once or use --apply --build-image')
            result=subprocess.run(['docker','build','-t',args.image,str(HERE)],capture_output=True,text=True,timeout=600)
            if result.returncode:raise ValueError('embedding image build failed; diagnostics suppressed')
            image=client.images.get(args.image)
        network_exists=False
        try:
            existing_network=client.networks.get(network);network_exists=True
            if existing_network.attrs.get('Internal') is not True:raise ValueError('selected embedding network is not internal; existing network preserved')
        except docker.errors.NotFound:pass
        name=args.project_name+'-'+SERVICE+'-1';container=None
        try:container=client.containers.get(name)
        except docker.errors.NotFound:pass
        key=None
        if container is not None:
            attrs=container.attrs
            labels=attrs.get('Config',{}).get('Labels') or {}
            if labels.get('com.docker.compose.project')!=args.project_name or labels.get('com.docker.compose.service')!=SERVICE:
                raise ValueError('same-name container belongs to another deployment; preserved')
            mount=next((x for x in attrs.get('Mounts',[]) if x.get('Destination')=='/model'),None)
            if network not in attrs['NetworkSettings']['Networks'] or container.image.id!=image.id or not mount or mount.get('RW') or mount.get('Source')!=str(model):
                raise ValueError('existing built-in service differs from selected image/network/model; preserved')
            key=next((x.split('=',1)[1] for x in attrs['Config'].get('Env',[]) if x.startswith('EMBEDDING_API_KEY=')),None)
            if not key or len(key)<16:raise ValueError('existing built-in service key unavailable; preserved')
        command=['docker','compose','--project-directory',str(project),'--project-name',args.project_name,'--env-file',str(env_file)]
        for path in compose:command+=['-f',str(path)]
        command+=['-f',str(HERE/'platform.override.yml'),'--profile','embedding']
        public={'applied':False,'model_verified':True,'model':MODEL,'service':SERVICE,'network':network,
                'network_exists':network_exists,'existing_service_preserved':container is not None,
                'command':command+['up','-d','--no-build','--pull','never',SERVICE,*services],
                'provider_database_written':False}
        if not args.apply:
            print(json.dumps(public,ensure_ascii=False));return 0
        key=key or secrets.token_urlsafe(40)
        env={**os.environ,**retained,'EMBEDDING_MODEL_DIR':str(model),'BUILTIN_EMBEDDING_IMAGE':args.image,
             'BUILTIN_EMBEDDING_NETWORK':network,'EMBEDDING_API_KEY':key,
             'KNOWLEDGE_BUILTIN_EMBEDDING_API_KEY':key,'KNOWLEDGE_BUILTIN_EMBEDDING_BASE_URL':BASE,
             'KNOWLEDGE_BUILTIN_EMBEDDING_MODEL':MODEL}
        first=command+['up','-d','--no-build','--pull','never']+(['--no-recreate'] if container is not None else [])+[SERVICE]
        result=subprocess.run(first,env=env,capture_output=True,text=True,timeout=120)
        if result.returncode:raise ValueError('built-in Compose startup failed; diagnostics suppressed')
        if not wait_ready(client,name):raise ValueError('built-in service did not become healthy; platform env not updated')
        result=subprocess.run(command+['up','-d','--no-build','--pull','never',*([] if args.start_platform else services)],env=env,capture_output=True,text=True,timeout=180)
        if result.returncode:raise ValueError('platform Compose startup failed; diagnostics suppressed')
        save_resume(project,args,compose,env_file,model,network)
        public.update(applied=True,builtin_health_verified=True,platform_env_injected=True,provider_verified=False)
        print(json.dumps(public,ensure_ascii=False));return 0
    except (ValueError,FileNotFoundError) as error:
        print(json.dumps({'applied':False,'error':str(error) if isinstance(error,ValueError) else 'required path missing'}));return 1
    except Exception:
        print(json.dumps({'applied':False,'error':'deployment unavailable; sensitive diagnostics suppressed'}));return 1
    finally:
        if client is not None:client.close()

if __name__=='__main__':raise SystemExit(main())
