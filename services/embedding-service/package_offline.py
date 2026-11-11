"""Package only verified public model + allowlisted service sources. No runtime secrets or DB."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import secrets
import shutil
import subprocess
import tarfile
import tempfile

HERE=Path(__file__).resolve().parent
SOURCE_FILES=('app.py','Dockerfile','requirements.txt','README.md','start_local.py','configure_platform.py',
              'setup_platform.py','platform.override.yml','model-manifest.json','package_offline.py')
OFFLINE_TAG='engramproject/embedding:offline-bge-small-zh-v1.5'

def model_manifest():return json.loads((HERE/'model-manifest.json').read_text())
def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as handle:
  for block in iter(lambda:handle.read(2*1024*1024),b''):h.update(block)
 return h.hexdigest()

def export_image(source_image,path):
 """Save a temporary independent tag, never export the source tag into the bundle."""
 if not re.fullmatch(r'engramproject/embedding:[A-Za-z0-9_.-]+',source_image):raise ValueError('only embedding image repository is allowed')
 import docker
 c=docker.from_env();temporary='engramproject/embedding:offline-export-'+secrets.token_hex(8)
 try:
  image=c.images.get(source_image)
  for item in image.attrs.get('Config',{}).get('Env',[]) or []:
   name,_,value=item.partition('=')
   if value and any(word in name.lower() for word in ['password','secret','api_key','access_token','authorization']):raise ValueError('image contains credential environment; refusing export')
  image.tag(temporary)
  with path.open('xb') as output:
   for part in c.images.get(temporary).save(named=temporary):output.write(part)
  return {'source_id':image.id,'archive_tag':temporary,'recommended_runtime_tag':OFFLINE_TAG,'image_bytes':image.attrs['Size']}
 finally:
  try:c.images.remove(temporary)
  except Exception:pass
  c.close()

def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--model-dir');p.add_argument('--output',help='Create a new .tar.gz; existing output is always rejected');p.add_argument('--include-image',action='store_true');p.add_argument('--package-kind',choices=['dependencies','code'],default='dependencies');p.add_argument('--image',default='engramproject/embedding:bge-small-zh-v1.5');args=p.parse_args(argv)
 try:
  manifest=model_manifest();entries=[]
  if args.package_kind=='code' and args.include_image:raise ValueError('code package cannot include images')
  if args.package_kind=='dependencies':
   if not args.model_dir:raise ValueError('--model-dir is required for dependency package')
   model=Path(args.model_dir).expanduser().resolve(strict=True)
   for entry in manifest['files']:
    path=model/entry['name']
    if path.is_symlink() or not path.is_file() or path.stat().st_size!=entry['size'] or digest(path)!=entry['sha256']:raise ValueError('model verification failed; nothing packaged')
    entries.append((path,entry['name']))
  for name in SOURCE_FILES:
   path=HERE/name
   if path.is_symlink() or not path.is_file():raise ValueError('allowlisted source missing or unsafe')
  result={'packaged':False,'model_verified':args.package_kind=='dependencies','package_kind':args.package_kind,'model':manifest['model'],'image_requested':args.include_image,'source_files':list(SOURCE_FILES),'credentials_included':False}
  if not args.output:print(json.dumps(result));return 0
  output=Path(args.output).expanduser().absolute()
  if output.exists() or output.is_symlink():raise ValueError('output already exists; refusing overwrite')
  if not output.parent.is_dir():raise ValueError('output parent must already exist')
  # Work only next to user's persistent output, never system /tmp.
  with tempfile.TemporaryDirectory(prefix='embedding-bundle-',dir=output.parent) as task:
   stage=Path(task)/('embedding-'+args.package_kind);sources=stage/'service';models=stage/'models';stage.mkdir()
   if args.package_kind=='code':sources.mkdir()
   else:models.mkdir()
   for (path,name),entry in zip(entries,manifest['files']):
    shutil.copyfile(path,models/name)
    if (models/name).stat().st_size!=entry['size'] or digest(models/name)!=entry['sha256']:raise ValueError('model changed while packaging')
   for name in (SOURCE_FILES if args.package_kind=='code' else []):
    before=digest(HERE/name);shutil.copyfile(HERE/name,sources/name)
    if digest(sources/name)!=before or digest(HERE/name)!=before:raise ValueError('source changed while packaging; retry after freeze')
   if args.package_kind=='dependencies':shutil.copyfile(HERE/'model-manifest.json',stage/'model-manifest.json')
   image_info=None
   if args.include_image:image_info=export_image(args.image,stage/'embedding-image.tar')
   (stage/'OFFLINE.md').write_text('''# 独立组件包（不是平台统一部署包或在线冷下载验收）
依赖包与代码包分别校验/独立分发；日常业务更新只更新总平台部署包内组件代码，不重新打包/传输模型权重。
组件code可直接收进Controller总平台部署包，用户不必分别管理多个代码包。
依赖包models和可选image属于低频公开依赖；代码包service属于业务部署材料。
先校验bundle-manifest.json中每个文件的size/SHA256，再加载可选embedding-image.tar。
镜像归档只带独立offline-export随机tag，不覆盖原主tag；docker load后按manifest image.archive_tag使用--image，或显式重tag到你自己的新tag。
平台本身的镜像、Docker/Python Docker SDK与现有平台.env由目标安装环境提供；本包不含平台DB/密钥/.env。
解压到新目录后：
python3 <code-directory>/service/setup_platform.py --project-root /your/platform --model-dir <dependency-directory>/models --image <loaded-independent-tag>
python3 <code-directory>/service/setup_platform.py --apply --project-root /your/platform --model-dir <dependency-directory>/models --image <loaded-independent-tag>
setup会复用包内override启用builtin-embedding，无宿主端口。API/worker使用平台已构建镜像。
平台需包含builtin provider支持；旧start.sh不替代本入口。此包只含公开模型与白名单源码，OCR/模型聊天不在包内。
''')
   files={str(path.relative_to(stage)):{'size':path.stat().st_size,'sha256':digest(path)} for path in sorted(stage.rglob('*')) if path.is_file()}
   bundle={'format':'engramproject-embedding-split-v1','package_kind':args.package_kind,'model':manifest['model'],'model_files':manifest['files'],'image':image_info,'files':files,'credentials_included':False};(stage/'bundle-manifest.json').write_text(json.dumps(bundle,ensure_ascii=False,indent=2)+'\n')
   temporary=Path(task)/'bundle.tar.gz'
   with tarfile.open(temporary,'w:gz',compresslevel=1) as archive:archive.add(stage,arcname=stage.name)
   os.link(temporary,output)
   result.update(packaged=True,output=str(output),bytes=output.stat().st_size,sha256=digest(output),files=len(files),image_included=image_info is not None)
  print(json.dumps(result));return 0
 except (ValueError,FileNotFoundError) as error:print(json.dumps({'packaged':False,'error':str(error) if isinstance(error,ValueError) else 'required path missing'}));return 1
 except Exception:print(json.dumps({'packaged':False,'error':'offline packaging failed; sensitive diagnostics suppressed'}));return 1
if __name__=='__main__':raise SystemExit(main())
