"""Bounded local OCR subprocess; candidates require explicit human review."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import posixpath
import re
import resource
import signal
import stat
import struct
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile

MAX_BYTES=20*1024*1024
MAX_PIXELS=9_000_000
MAX_TOTAL_PIXELS=60_000_000
MAX_TEXT=100000
DEADLINE=None

class Rejected(ValueError):pass

def document_timeout(signum, frame):
    raise Rejected('document_timeout')

def command(args,timeout):
    started=time.monotonic()
    if DEADLINE is not None:
        remaining=DEADLINE-started
        if remaining<=0:raise Rejected('document_timeout')
        timeout=min(timeout,remaining)
    child=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=False,env={**os.environ,'OMP_THREAD_LIMIT':'2'})
    try:out,err=child.communicate(timeout=timeout)
    except (subprocess.TimeoutExpired, Rejected):
        child.kill();child.communicate()
        raise Rejected('command_timeout')
    if child.returncode:raise Rejected('command_failed:'+Path(args[0]).name)
    if len(out)>4*1024*1024:raise Rejected('command_output_budget')
    return out.decode('utf-8',errors='strict'),round(time.monotonic()-started,4)

def xml(raw):
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise Rejected('xml_entity')
    return ET.fromstring(raw)

def png_size(path):
    with path.open('rb') as source:header=source.read(24)
    if len(header)!=24 or header[:8]!=b'\x89PNG\r\n\x1a\n':raise Rejected('unsupported_or_broken_image')
    w,h=struct.unpack('>II',header[16:24])
    if w<=0 or h<=0 or w*h>MAX_PIXELS or max(w,h)>3508:raise Rejected('image_pixel_budget')
    return w,h

def ocr(path,timeout,locator):
    w,h=png_size(path)
    text,elapsed=command(['tesseract',str(path),'stdout','-l','chi_sim+eng','--psm','6'],timeout)
    text=text.strip()
    if not text:raise Rejected('no_recognized_text')
    if len(text)>MAX_TEXT:raise Rejected('text_budget')
    return {**locator,'method':'tesseract_ocr','language':'chi_sim+eng','text':text,'width':w,'height':h,'pixels':w*h,'elapsed_seconds':elapsed,'text_sha256':hashlib.sha256(text.encode()).hexdigest()}

def pdf(path,work,args):
    info,_=command(['pdfinfo',str(path)],args.page_timeout)
    pages=int(re.search(r'^Pages:\s+(\d+)',info,re.M).group(1))
    if re.search(r'^Encrypted:\s+yes',info,re.M):raise Rejected('encrypted_pdf')
    if pages<1 or pages>args.max_pages:raise Rejected('page_budget')
    output=[];failures=[];total=0
    for page in range(1,pages+1):
        locator={'page':page,'source':'pdf','citation':f'[PDF第{page}页 · OCR文字]'}
        page_deadline=time.monotonic()+args.page_timeout
        def remaining():
            value=page_deadline-time.monotonic()
            if value<=0:raise Rejected('page_timeout')
            return value
        try:
            details,_=command(['pdfinfo','-f',str(page),'-l',str(page),'-box',str(path)],remaining())
            size=re.search(r'(?:Page\s+\d+\s+size|Page size):\s+([0-9.]+)\s+x\s+([0-9.]+)',details)
            if not size:raise Rejected('unknown_page_dimensions')
            width,height=map(float,size.groups())
            # Reject huge native page dimensions, rather than quietly downscaling pathological documents.
            if min(width,height)<=0 or max(width,height)>1440:raise Rejected('page_dimension_budget')
            pixels=math.ceil(width*args.dpi/72)*math.ceil(height*args.dpi/72)
            if pixels>MAX_PIXELS or total+pixels>MAX_TOTAL_PIXELS:raise Rejected('page_pixel_budget')
            total+=pixels
            prefix=work/f'page-{page}'
            _,render_time=command(['pdftoppm','-f',str(page),'-l',str(page),'-r',str(args.dpi),'-singlefile','-png',str(path),str(prefix)],remaining())
            image=prefix.with_suffix('.png')
            row=ocr(image,remaining(),locator);row['render_seconds']=render_time
            output.append(row)
            image.unlink()
        except (Rejected,ValueError) as e:failures.append({**locator,'error':str(e)})
    return output,failures

def docx(path,work,args):
    rows=[];failures=[];total=0
    w='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    a='{http://schemas.openxmlformats.org/drawingml/2006/main}'
    r='{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
    with zipfile.ZipFile(path) as z:
        infos=z.infolist();names=set()
        if len(infos)>1000 or sum(x.file_size for x in infos)>24*1024*1024:raise Rejected('zip_expanded_budget')
        for item in infos:
            if item.file_size>24*1024*1024 or item.file_size>max(1,item.compress_size)*200:raise Rejected('zip_expanded_budget')
            if item.filename in names or '\\' in item.filename or ':' in item.filename or item.filename.startswith('/') or '..' in item.filename.split('/') or item.flag_bits&1 or stat.S_ISLNK(item.external_attr >> 16):raise Rejected('zip_path_or_encryption')
            names.add(item.filename)
        for item in infos:
            if item.filename.endswith(('.xml','.rels')):
                root=xml(z.read(item))
                if item.filename.endswith('.rels') and any(rel.get('TargetMode','').lower()=='external' for rel in root):raise Rejected('external_relationship')
        image_count=0
        for part in sorted(x for x in names if re.fullmatch(r'word/(document|header\d*|footer\d*|footnotes|endnotes|comments)\.xml',x)):
            content=xml(z.read(part));relfile=posixpath.join(posixpath.dirname(part),'_rels',posixpath.basename(part)+'.rels')
            relations={}
            if relfile in names:
                for rel in xml(z.read(relfile)):
                    if rel.get('TargetMode','').lower()=='external':raise Rejected('external_relationship')
                    target=rel.get('Target','');resolved=posixpath.normpath(posixpath.join(posixpath.dirname(part),target))
                    if '\\' in target or ':' in target or target.startswith('/'):raise Rejected('unsafe_relationship')
                    if not resolved.startswith('word/') or resolved not in names:raise Rejected('broken_image_relationship')
                    if not rel.get('Id') or rel.get('Id') in relations:raise Rejected('duplicate_relationship')
                    relations[rel.get('Id')]=resolved
            for paragraph,node in enumerate(content.iter(w+'p'),1):
                for blip in node.iter(a+'blip'):
                    rid=blip.get(r+'embed');image=relations.get(rid)
                    locator={'source':'docx','part':part,'paragraph':paragraph,'relationship':rid,'image':image,'page':None,'citation':f'[DOCX {part} 段落{paragraph} · {image} OCR文字]'}
                    try:
                        image_count+=1
                        if image_count>args.max_pages:raise Rejected('image_count_budget')
                        if not image or not image.lower().endswith('.png'):raise Rejected('unsupported_image_or_relationship')
                        local=work/f'image-{image_count}.png';local.write_bytes(z.read(image));width,height=png_size(local);total+=width*height
                        if total>MAX_TOTAL_PIXELS:raise Rejected('total_pixel_budget')
                        rows.append(ocr(local,args.page_timeout,locator));local.unlink()
                    except Rejected as error:failures.append({**locator,'error':str(error)})
    if not rows and not failures:failures.append({'range':'document','error':'no_embedded_images'})
    return rows,failures

def main():
    global DEADLINE
    DEADLINE=time.monotonic()+120
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('input',nargs='?');ap.add_argument('--max-pages',type=int,default=20);ap.add_argument('--page-timeout',type=float,default=15);ap.add_argument('--dpi',type=int,default=200);args=ap.parse_args()
    resource.setrlimit(resource.RLIMIT_AS,(768*1024*1024,768*1024*1024))
    resource.setrlimit(resource.RLIMIT_FSIZE,(32*1024*1024,32*1024*1024));resource.setrlimit(resource.RLIMIT_NOFILE,(64,64));resource.setrlimit(resource.RLIMIT_CPU,(120,120))
    signal.signal(signal.SIGALRM,document_timeout);signal.alarm(120)
    started=time.monotonic();child_start=resource.getrusage(resource.RUSAGE_CHILDREN);self_start=resource.getrusage(resource.RUSAGE_SELF)
    result={'valid':False,'segments':[],'failures':[],'scope':'isolated OCR experiment; not production importer','model_calls':0}
    work_parent=Path(os.environ.get('TMPDIR','/work'));work_parent.mkdir(exist_ok=True)
    try:
        path=Path(args.input)
        if path.stat().st_size>MAX_BYTES:raise Rejected('upload_size_budget')
        if not 1<=args.max_pages<=20 or not 1<=args.dpi<=300 or args.page_timeout<=0:raise Rejected('invalid_limits')
        result['original_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory(prefix='job-',dir=work_parent) as directory:
            work=Path(directory)
            if path.suffix=='.pdf':segments,failures=pdf(path,work,args)
            elif path.suffix=='.docx':segments,failures=docx(path,work,args)
            elif path.suffix=='.png':segments,failures=[ocr(path,args.page_timeout,{'source':'image','image':path.name,'citation':f'[图片 {path.name} · OCR文字]'})],[]
            else:raise Rejected('unsupported_format')
            if sum(len(x['text']) for x in segments)>MAX_TEXT:raise Rejected('text_budget')
            result.update(segments=segments,failures=failures,valid=bool(segments) and not failures)
    except Exception as error:result['failures'].append({'range':'document','error':str(error) if isinstance(error,Rejected) else type(error).__name__})
    child=resource.getrusage(resource.RUSAGE_CHILDREN);self_usage=resource.getrusage(resource.RUSAGE_SELF)
    result['metrics']={'wall_seconds':round(time.monotonic()-started,4),'child_cpu_seconds':round(child.ru_utime+child.ru_stime-child_start.ru_utime-child_start.ru_stime,4),'self_cpu_seconds':round(self_usage.ru_utime+self_usage.ru_stime-self_start.ru_utime-self_start.ru_stime,4),'max_child_rss_kib':child.ru_maxrss,'self_peak_rss_kib':self_usage.ru_maxrss,'work_entries_after_cleanup':len(list(work_parent.glob('job-*'))),'cgroup_memory_peak_bytes':int(Path('/sys/fs/cgroup/memory.peak').read_text()) if Path('/sys/fs/cgroup/memory.peak').exists() else None}
    print(json.dumps(result,ensure_ascii=False));return 0 if result['valid'] else 2
if __name__=='__main__':raise SystemExit(main())
