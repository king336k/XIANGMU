"""Installer contract: immutable checked packages, no live Docker target writes."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import pytest

spec=importlib.util.spec_from_file_location('release_install',Path(__file__).with_name('install.py'))
mod=importlib.util.module_from_spec(spec)
if Path(spec.origin).exists():spec.loader.exec_module(mod)

def package(tmp_path, mutation=None, entries=None):
    image={'service':'api','ref':'example/runtime:v1','id':'sha256:'+'a'*64,'platform':'linux/amd64','dependency_sha256':'b'*64}
    manifest={'schema_version':1,'project_key':'engram_project','runtime_set_version':'v1','platform':'linux/amd64','images':[image]}
    files={'ProjectServer/manage.py':b'pass\n','ProjectServer/plane/__init__.py':b'', 'ProjectServer/bin/docker-entrypoint-api.sh':b'exit 0\n','ProjectFront/build/client/index.html':b'html','services/collaboration/dist/start.mjs':b'export {};','deploy/release/compose.yml':b'services: {}\n','deploy/release/install.py':b'# install','deploy/release/launcher.py':b'# launcher','deploy/release/frp_control.py':b'# frp manager','deploy/release/runtime-manifest.json':json.dumps(manifest).encode()}
    files['services/embedding-service/model-manifest.json']=b'{"model":"bge-small-zh-v1.5","files":[]}'
    tree=hashlib.sha256(json.dumps({p:hashlib.sha256(v).hexdigest() for p,v in files.items()},sort_keys=True,separators=(',',':')).encode()).hexdigest()
    info={'schema_version':1,'project_key':'engram_project','package_type':'code','version':'v1','release_id':'v1','platform':'linux/amd64','runtime_set_version':'v1','required_images':[image],'runtime_manifest_sha256':hashlib.sha256(files['deploy/release/runtime-manifest.json']).hexdigest(),'source_tree_sha256':tree,'git':{'available':False,'head':None},'autostart':False}
    files['version_info.json']=json.dumps(info).encode()
    if mutation:mutation(files)
    files['SHA256SUMS']=''.join(hashlib.sha256(v).hexdigest()+'  '+p+'\n' for p,v in files.items()).encode()
    path=tmp_path/'code.tar.gz'
    with tarfile.open(path,'w:gz') as t:
        for name,raw in files.items():
            item=tarfile.TarInfo('EngramProject_code_v1/'+name);item.size=len(raw);t.addfile(item,io.BytesIO(raw))
        for item in entries or []:t.addfile(item,io.BytesIO(b'x') if item.isreg() else None)
    return path

def test_valid_working_tree_package_and_no_extraction_in_check(tmp_path):
    path=package(tmp_path); before=set(tmp_path.iterdir());value=mod.validate_package(path)
    assert value['info']['git']['head'] is None and value['release_id']=='v1'
    assert set(tmp_path.iterdir())==before

@pytest.mark.parametrize('name',['../escape','/root/escape','ProjectServer/.env','ProjectServer/plane/private.key','other/new.py'])
def test_unsafe_or_unknown_file_rejected(tmp_path,name):
    with pytest.raises(ValueError):mod.validate_package(package(tmp_path,lambda f:f.__setitem__(name,b'secret')))

@pytest.mark.parametrize('kind',[tarfile.SYMTYPE,tarfile.LNKTYPE,tarfile.FIFOTYPE])
def test_links_and_special_files_rejected(tmp_path,kind):
    item=tarfile.TarInfo('EngramProject_code_v1/ProjectServer/plane/link');item.type=kind;item.linkname='../../outside'
    with pytest.raises(ValueError):mod.validate_package(package(tmp_path,entries=[item]))

def test_duplicate_members_and_checksum_tree_mismatch_rejected(tmp_path):
    duplicate=tarfile.TarInfo('EngramProject_code_v1/ProjectServer/manage.py');duplicate.size=1
    with pytest.raises(ValueError):mod.validate_package(package(tmp_path,entries=[duplicate]))
    with pytest.raises(ValueError):mod.validate_package(package(tmp_path,lambda f:f.__setitem__('ProjectServer/manage.py',b'mutated')))

def test_unknown_manifest_and_metadata_mismatch_rejected(tmp_path):
    def change(f):
        v=json.loads(f['deploy/release/runtime-manifest.json']);v['schema_version']=2;f['deploy/release/runtime-manifest.json']=json.dumps(v).encode()
    with pytest.raises(ValueError):mod.validate_package(package(tmp_path,change))

def test_default_cli_check_never_creates_deploy_root_or_mutates_docker(tmp_path,monkeypatch):
    target=tmp_path/'uncreated';path=package(tmp_path);commands=[]
    monkeypatch.setattr(mod,'verify_images',lambda m:commands.append('inspect'))
    monkeypatch.setattr(mod,'verify_models',lambda *a:None)
    monkeypatch.setattr(mod,'command',lambda *a,**kw:b'')
    assert mod.main(['--package',str(path),'--deploy-root',str(target)])==0
    assert not target.exists() and commands==['inspect']

def test_secret_initialization_no_overwrite_and_mode0600(tmp_path):
    shared=tmp_path/'shared';shared.mkdir();a=mod.initialize_env(shared,18890,'127.0.0.1',('10.247.1.0/28','10.247.2.0/28'))
    original=(shared/'.env').read_bytes();assert a['BUILTIN_EMBEDDING_KEY'] and (shared/'.env').stat().st_mode&0o777==0o600
    assert mod.initialize_env(shared,18890,'127.0.0.1',('10.247.3.0/28','10.247.4.0/28'))==a
    assert (shared/'.env').read_bytes()==original

def test_prepare_record_rejects_ownership_reuse_and_profile_loss(tmp_path):
    root=tmp_path/'deploy';root.mkdir();(root/'shared').mkdir();(root/'shared/deployment.json').write_text(json.dumps({'schema_version':1,'deploy_root':str(root),'project_name':'owned','profiles':['helpers']}))
    with pytest.raises(ValueError):mod.deployment_options(root,'other',['helpers'])
    with pytest.raises(ValueError):mod.deployment_options(root,'owned',[])

def test_safe_root_rejects_symlink_and_relative(tmp_path):
    target=tmp_path/'real';target.mkdir();link=tmp_path/'link';link.symlink_to(target,target_is_directory=True)
    with pytest.raises(ValueError):mod.safe_root(str(link/'child'))
    with pytest.raises(ValueError):mod.safe_root('relative')


def test_image_checks_are_exact_identity_and_arch(tmp_path,monkeypatch):
    checked=mod.validate_package(package(tmp_path));manifest=checked['manifest']
    def run(args,**kw):
        return json.dumps({'OSType':'linux','Architecture':'x86_64'} if args[1]=='info' else [{'Id':'sha256:'+'c'*64,'Os':'linux','Architecture':'amd64'}]).encode()
    monkeypatch.setattr(mod,'command',run)
    with pytest.raises(ValueError):mod.verify_images(manifest)


def test_existing_project_cannot_be_adopted_without_owned_current(monkeypatch):
    def run(args,**kw):
        return b'container-id\n' if args[1]=='ps' else json.dumps([{'Config':{'Labels':{'com.docker.compose.project.working_dir':'/other/deploy/releases/v1'}}}]).encode()
    monkeypatch.setattr(mod,'command',run)
    with pytest.raises(ValueError):mod.owned_containers({'project_name':'engramproject'},Path('/target/releases/v1'))


def test_symlink_parent_inside_shared_environment_is_rejected(tmp_path):
    real=tmp_path/'private';real.mkdir();shared=tmp_path/'shared';shared.symlink_to(real,target_is_directory=True)
    with pytest.raises(ValueError):mod.initialize_env(shared,18890,'127.0.0.1',('a','b'))


def test_extracted_release_cannot_escape_through_releases_symlink(tmp_path):
    path=package(tmp_path);checked=mod.validate_package(path);root=tmp_path/'root';root.mkdir();outside=tmp_path/'outside';outside.mkdir();(root/'releases').symlink_to(outside,target_is_directory=True)
    with pytest.raises(ValueError):mod.extract_release(path,root,checked)
    assert not list(outside.iterdir())


def test_backup_checks_dump_content_and_pg_restore_before_any_migration(tmp_path,monkeypatch):
    root=tmp_path/'root';(root/'shared').mkdir(parents=True);calls=[]
    def fake(root,old,record,args,**kw):
        calls.append(args)
        if 'pg_dump' in args:kw['output'].write(b'PGDMP'+b'x'*100)
        else:assert kw['input_data'].startswith(b'PGDMP')
    monkeypatch.setattr(mod,'compose_run',fake)
    backup=Path(mod.backup_database(root,root/'releases/v1',{'project_name':'test'},{'POSTGRES_USER':'u','POSTGRES_DB':'d'}))
    assert backup.exists() and backup.stat().st_mode&0o777==0o600
    assert 'pg_dump' in calls[0] and 'pg_restore' in calls[1] and '--list' in calls[1]


def test_backup_list_failure_never_claims_validated(tmp_path,monkeypatch):
    root=tmp_path/'root';(root/'shared').mkdir(parents=True)
    def fake(*args,**kw):
        if kw.get('output'):kw['output'].write(b'PGDMP'+b'x'*100)
        else:raise ValueError('not restorable')
    monkeypatch.setattr(mod,'compose_run',fake)
    with pytest.raises(ValueError):mod.backup_database(root,root/'releases/v1',{}, {})
    receipts=list((root/'shared/backups').glob('*.json'))
    assert len(receipts)==1 and receipts[0].name.endswith('.failed.json')
    assert json.loads(receipts[0].read_text())['stage']=='database_backup_verify_failed'
    assert json.loads(receipts[0].read_text())['validated'] is False


def test_log_export_captures_stderr_and_honors_since_mode(tmp_path,monkeypatch):
    root=tmp_path/'root';(root/'shared').mkdir(parents=True);calls=[]
    def fake(args,**kw):
        calls.append((args,kw));kw['stdout'].write(b'owned stdout and stderr')
        return type('Result',(),{'returncode':0})()
    monkeypatch.setattr(mod.subprocess,'run',fake)
    mod.export_logs(root,{},[{'Id':'container','Config':{'Labels':{'com.docker.compose.service':'api'}}}],'2h')
    assert '--since' in calls[0][0] and '2h' in calls[0][0]
    assert calls[0][1]['stderr'] is calls[0][1]['stdout']
    assert next((root/'shared/logs/api').glob('*.log')).stat().st_mode&0o777==0o600


def test_failure_after_migration_keeps_old_pointer_and_records_no_schema_rollback(tmp_path,monkeypatch):
    root=tmp_path/'deploy';old=root/'releases/old';old.mkdir(parents=True);(root/'shared').mkdir();(root/'current').symlink_to('releases/old')
    (root/'shared/deployment.json').write_text(json.dumps({'schema_version':1,'deploy_root':str(root),'project_name':'engramproject','profiles':['helpers']}))
    archive=package(tmp_path);calls=[]
    monkeypatch.setattr(mod,'verify_images',lambda *a:None);monkeypatch.setattr(mod,'verify_models',lambda *a:None)
    monkeypatch.setattr(mod,'owned_containers',lambda *a:[{'Config':{'Labels':{'com.docker.compose.service':'plane-db'}}}])
    monkeypatch.setattr(mod,'initialize_env',lambda *a:{'HTTP_PORT':'18890'});monkeypatch.setattr(mod,'choose_subnets',lambda:('a','b'));monkeypatch.setattr(mod,'export_logs',lambda *a:None);monkeypatch.setattr(mod,'backup_database',lambda *a:'validated.dump')
    def compose_stub(*a,**kw):
        calls.append(a[3])
        return b'{"services":{},"volumes":{}}' if a[3][0]=='config' else b''
    monkeypatch.setattr(mod,'compose_run',compose_stub)
    def fail(*a,**kw):raise ValueError('not healthy')
    monkeypatch.setattr(mod,'wait_health',fail)
    assert mod.main(['--apply','--package',str(archive),'--deploy-root',str(root)])==1
    assert (root/'current').resolve()==old
    receipt=json.loads((root/'shared/last-install.json').read_text())
    assert receipt['status']=='failed' and receipt['schema_rollback_attempted'] is False
    assert receipt['last_successful_phase']=='migrated'
    assert not any('down' in call or '--build' in call or 'always' in call for call in calls)


def test_target_directory_with_unrelated_existing_files_is_refused(tmp_path,monkeypatch):
    root=tmp_path/'deploy';root.mkdir();(root/'user-file').write_text('keep');archive=package(tmp_path)
    monkeypatch.setattr(mod,'verify_images',lambda *a:pytest.fail('target refusal precedes docker'))
    assert mod.main(['--apply','--package',str(archive),'--deploy-root',str(root)])==1
    assert (root/'user-file').read_text()=='keep'


def test_package_rejects_inline_private_material_in_whitelisted_source(tmp_path):
    def add(f):
        f['ProjectServer/plane/accidental.py']=b"API_KEY = 'sk-proj-"+b'A'*40+b"'\n"
        info=json.loads(f['version_info.json'])
        info['source_tree_sha256']=hashlib.sha256(json.dumps({p:hashlib.sha256(v).hexdigest() for p,v in f.items() if p!='version_info.json'},sort_keys=True,separators=(',',':')).encode()).hexdigest()
        f['version_info.json']=json.dumps(info).encode()
    with pytest.raises(ValueError,match='credential'):mod.validate_package(package(tmp_path,add))


def test_stable_env_takes_precedence_over_host_environment(tmp_path,monkeypatch):
    root=tmp_path/'deploy';(root/'shared').mkdir(parents=True);env=root/'shared/.env';env.write_text('POSTGRES_PASSWORD=preserved\nBUILTIN_EMBEDDING_KEY=existing\n')
    calls=[];monkeypatch.setenv('POSTGRES_PASSWORD','wrong-host-value')
    def fake(args,**kw):calls.append(kw);return type('Result',(),{'returncode':0,'stdout':b''})()
    monkeypatch.setattr(mod.subprocess,'run',fake)
    mod.compose_run(root,root/'releases/v1',{'project_name':'p','profiles':['helpers']},['config','--quiet'])
    assert calls[0]['env']['POSTGRES_PASSWORD']=='preserved'


def test_existing_project_volume_without_owner_record_refused(tmp_path,monkeypatch):
    archive=package(tmp_path);root=tmp_path/'new'
    monkeypatch.setattr(mod,'verify_images',lambda *a:None);monkeypatch.setattr(mod,'verify_models',lambda *a:None);monkeypatch.setattr(mod,'command',lambda *a,**kw:b'engramproject_pgdata\n')
    assert mod.main(['--apply','--package',str(archive),'--deploy-root',str(root)])==1
    assert not root.exists()


def test_compose_rejects_unknown_image_privileged_and_external_bind(tmp_path):
    release=tmp_path/'deploy/releases/v1';root=tmp_path/'deploy';manifest={'images':[{'ref':'fixed:v1'}]}
    base={'services':{'api':{'image':'fixed:v1','volumes':[{'type':'bind','source':str(release/'ProjectServer'),'target':'/code','read_only':True}]}},'volumes':{}}
    mod.validate_compose(base,root,release,manifest,{'project_name':'owned'})
    for change in [{'image':'other:v1'},{'privileged':True},{'network_mode':'host'},{'volumes':[{'type':'bind','source':'/etc','target':'/host','read_only':True}]},{'build':'Dockerfile'}]:
        broken=json.loads(json.dumps(base));broken['services']['api'].update(change)
        with pytest.raises(ValueError):mod.validate_compose(broken,root,release,manifest,{'project_name':'owned'})


def test_compose_refuses_reusing_external_named_data_volume(tmp_path):
    root=tmp_path/'deploy';release=root/'releases/v1'
    config={'services':{'api':{'image':'fixed:v1'}},'volumes':{'pgdata':{'external':True,'name':'main_pgdata'}}}
    with pytest.raises(ValueError):mod.validate_compose(config,root,release,{'images':[{'ref':'fixed:v1'}]},{'project_name':'isolated'})


def test_stage_seed_only_checks_and_preserves_draft_no_import(tmp_path,monkeypatch):
    root=tmp_path/'deploy';release=root/'releases/v1';source=release/'deploy/release/initial-knowledge';source.mkdir(parents=True)
    raw=b'{"schema":"engramproject-initial-knowledge-v1","records":[]}'
    (source/'knowledge-bundle.json').write_bytes(raw);(source/'manifest.json').write_text(json.dumps({'schema':'engramproject-initial-knowledge-manifest-v1','seed_version':'seed-v1','files':{'knowledge-bundle.json':{'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}}}))
    calls=[];monkeypatch.setattr(mod,'command',lambda args,**kw:calls.append(args) or b'{}')
    result=mod.stage_seed(root,release)
    assert result['status']=='staged_pending_admin' and result['imported']==0 and '--check' in calls[0] and '--apply' not in calls[0]
    assert (root/'shared/initial-knowledge/seed-v1/knowledge-bundle.json').read_bytes()==raw
    assert mod.stage_seed(root,release)==result
    (root/'shared/initial-knowledge/seed-v1/knowledge-bundle.json').write_text('user-change')
    with pytest.raises(ValueError):mod.stage_seed(root,release)


def test_package_requires_model_manifest_for_bundled_model_identity(tmp_path):
    with pytest.raises(ValueError):mod.validate_package(package(tmp_path,lambda f:f.pop('services/embedding-service/model-manifest.json')))


def test_unknown_seed_file_does_not_get_staged_by_default(tmp_path,monkeypatch):
    root=tmp_path/'deploy';release=root/'releases/v1';source=release/'deploy/release/initial-knowledge';source.mkdir(parents=True)
    (source/'manifest.json').write_text(json.dumps({'schema':'engramproject-initial-knowledge-manifest-v1','seed_version':'seed-v1','files':{'accounts.json':{'size':1,'sha256':'a'*64}}}))
    monkeypatch.setattr(mod,'command',lambda *a,**kw:b'{}')
    with pytest.raises(ValueError):mod.stage_seed(root,release)


def test_shared_init_cannot_create_config_through_lock_symlink(tmp_path):
    root=tmp_path/'deploy';(root/'shared').mkdir(parents=True);outside=tmp_path/'outside';outside.write_text('do not touch');(root/'shared/.install.lock').symlink_to(outside)
    with pytest.raises(ValueError):mod.open_install_lock(root/'shared')
    assert outside.read_text()=='do not touch'


def test_upgrade_never_reads_or_stages_changed_initial_knowledge(tmp_path,monkeypatch):
    root=tmp_path/'deploy';release=root/'releases/v2';old=root/'releases/v1'
    monkeypatch.setattr(mod,'stage_seed',lambda *a:pytest.fail('upgrade must not read initial seed'))
    assert mod.initial_knowledge_step(root,release,old)=={'status':'skipped_existing_deployment','imported':0}


def test_existing_shared_initial_seed_is_preserved_without_inspecting_new_seed(tmp_path,monkeypatch):
    root=tmp_path/'deploy';(root/'shared/initial-knowledge').mkdir(parents=True);(root/'shared/initial-knowledge/first-marker').write_text('preserve')
    monkeypatch.setattr(mod,'stage_seed',lambda *a:pytest.fail('existing shared seed must remain authoritative'))
    result=mod.initial_knowledge_step(root,root/'releases/v1',None)
    assert result=={'status':'skipped_existing_deployment','imported':0}
    assert (root/'shared/initial-knowledge/first-marker').read_text()=='preserve'


def test_subnet_picker_handles_null_ipam_and_ipv6_without_reconfiguring_networks(monkeypatch):
    commands=[]
    def run(args,**kwargs):
        commands.append(args)
        if args[1:3]==['network','ls']:return b'none host dual\n'
        return json.dumps([{'IPAM':{'Config':None}}, {'IPAM':{'Config':[]}}, {'IPAM':{'Config':[{'Subnet':'fd00:123::/64'},{'Subnet':'10.246.1.0/28'}]}}]).encode()
    monkeypatch.setattr(mod,'command',run)
    chosen=mod.choose_subnets()
    assert len(chosen)==2 and '10.246.1.0/28' not in chosen
    assert all('create' not in c and 'rm' not in c for c in commands)


def test_pristine_failed_preinit_target_allows_empty_releases_and_public_models(tmp_path):
    root=tmp_path/'deploy';(root/'releases').mkdir(parents=True);(root/'shared/models').mkdir(parents=True)
    assert mod.pristine_target(root)
    (root/'releases/unknown').mkdir();assert not mod.pristine_target(root)


def test_stable_database_from_prior_release_keeps_same_deployment_ownership(tmp_path,monkeypatch):
    root=tmp_path/'deploy';old=root/'releases/v1';new=root/'releases/v2';old.mkdir(parents=True);new.mkdir()
    rows=[{'Config':{'Labels':{'com.docker.compose.project.working_dir':str(old),'com.docker.compose.project':'owned','com.docker.compose.service':'plane-db'}}}]
    monkeypatch.setattr(mod,'command',lambda args,**kw:b'db\n' if args[1]=='ps' else json.dumps(rows).encode())
    assert mod.owned_containers({'project_name':'owned','deploy_root':str(root)},new)==rows


def test_readonly_code_mount_has_all_nested_writable_volume_mountpoints(tmp_path):
    release=tmp_path/'release';release.mkdir()
    mod.prepare_mountpoints(release)
    for name in ['quality-attachments','mediafiles','plane/logs','plane/static-assets/collected-static']:
        assert (release/'ProjectServer'/name).is_dir()
    assert not list(release.rglob('*.env'))


def test_backup_explicitly_uses_local_socket_without_password_in_process_args(tmp_path,monkeypatch):
    root=tmp_path/'root';(root/'shared').mkdir(parents=True);calls=[]
    def fake(root,old,record,args,**kw):
        calls.append(args)
        if 'pg_dump' in args:kw['output'].write(b'PGDMP'+b'x'*100)
    monkeypatch.setattr(mod,'compose_run',fake)
    mod.backup_database(root,root/'releases/v1',{'project_name':'own'},{'POSTGRES_USER':'engram','POSTGRES_DB':'engramproject','POSTGRES_PASSWORD':'PRIVATE_TEST_ONLY'})
    assert '--host=/var/run/postgresql' in calls[0]
    assert all('PRIVATE_TEST_ONLY' not in str(call) for call in calls)
    assert not any('PGPASSWORD=' in part for call in calls for part in call)


def test_backup_failure_keeps_zero_byte_evidence_and_returns_private_stage(tmp_path,monkeypatch):
    root=tmp_path/'root';(root/'shared').mkdir(parents=True)
    def fake(*args,**kw):raise ValueError('fe_sendauth synthetic password must never echo')
    monkeypatch.setattr(mod,'compose_run',fake)
    with pytest.raises(ValueError,match='database_backup_dump_failed') as error:mod.backup_database(root,root/'releases/v1',{}, {})
    assert 'fe_sendauth' not in str(error.value)
    files=list((root/'shared/backups').glob('*.dump'));assert len(files)==1 and files[0].stat().st_size==0
    failure=json.loads(next((root/'shared/backups').glob('*.failed.json')).read_text())
    assert failure['stage']=='database_backup_dump_failed' and failure['bytes']==0 and failure['validated'] is False


def test_owned_deployment_wrappers_quote_spaces_and_use_current_launcher(tmp_path):
    root=tmp_path/'deployment with spaces';root.mkdir();record={'project_name':'owned','profiles':['helpers']}
    mod.preflight_wrappers(root,record);mod.install_wrappers(root,record)
    for action in ['start','stop']:
        path=root/(action+'.sh');text=path.read_text()
        assert path.stat().st_mode&0o777==0o755
        assert '"$root/current/deploy/release/launcher.py"' in text and '--deploy-root "$root"' in text and text.rstrip().endswith(action + ' "$@"')
        assert 'docker' not in text
    original=(root/'start.sh').read_bytes();mod.install_wrappers(root,record)
    assert (root/'start.sh').read_bytes()==original


def test_existing_user_wrappers_and_symlinks_are_preserved(tmp_path):
    root=tmp_path/'deployment';root.mkdir();script=root/'start.sh';script.write_text('# user-owned script\n')
    with pytest.raises(ValueError):mod.preflight_wrappers(root,{})
    assert script.read_text()=='# user-owned script\n'
    script.unlink();outside=tmp_path/'outside';outside.write_text('preserve');script.symlink_to(outside)
    with pytest.raises(ValueError):mod.preflight_wrappers(root,{})
    assert outside.read_text()=='preserve'


def test_previous_record_owned_generated_wrapper_can_be_updated(tmp_path):
    root=tmp_path/'deployment';root.mkdir();old=b'#!/bin/sh\n# generated older wrapper\n';script=root/'start.sh';script.write_bytes(old)
    record={'managed_wrappers':{'start.sh':hashlib.sha256(old).hexdigest()}}
    mod.preflight_wrappers(root,record);mod.install_wrappers(root,record)
    assert script.read_bytes()==mod.wrapper_bytes('start') and record['managed_wrappers']['start.sh']==hashlib.sha256(script.read_bytes()).hexdigest()


def test_generated_wrappers_execute_from_space_path_and_repair_owned_mode(tmp_path):
    import subprocess
    root=tmp_path/'deployment with spaces';release=root/'releases/v1';(release/'deploy/release').mkdir(parents=True);(root/'current').symlink_to('releases/v1')
    (release/'deploy/release/launcher.py').write_text('import json,sys; print(json.dumps(sys.argv[1:]))\n')
    record={};mod.install_wrappers(root,record)
    for action in ['start','stop']:
        path=root/(action+'.sh');path.chmod(0o644);mod.install_wrappers(root,record)
        assert path.stat().st_mode&0o777==0o755
        result=subprocess.run([str(path)],capture_output=True,text=True,check=True)
        assert json.loads(result.stdout)==['--deploy-root',str(root),action]


def test_new_endpoint_uses_requested_port_and_external_host(tmp_path):
    import socket
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    endpoint = mod.deployment_endpoint(tmp_path / "shared", port, "127.0.0.1", "10.10.10.4")
    assert endpoint == {"port": port, "bind": "127.0.0.1", "host": "10.10.10.4", "url": f"http://10.10.10.4:{port}"}
    assert not (tmp_path / "shared").exists()


def test_new_endpoint_skips_a_real_listening_port_without_touching_it(tmp_path):
    import socket
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0)); occupied.listen()
        port = occupied.getsockname()[1]
        endpoint = mod.deployment_endpoint(tmp_path / "shared", port, "0.0.0.0", "10.10.10.4")
        assert port < endpoint["port"] <= min(port + 99, 65535)
        assert endpoint["url"] == f"http://10.10.10.4:{endpoint['port']}"
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            pass


def test_upgrade_endpoint_keeps_owned_config_even_when_port_is_in_use(tmp_path):
    shared = tmp_path / "shared"; shared.mkdir()
    raw = "HTTP_PORT=5090\nBIND_ADDRESS=127.0.0.1\nWEB_URL=http://localhost:5090\nAPP_DOMAIN=localhost\n"
    (shared / ".env").write_text(raw)
    endpoint = mod.deployment_endpoint(shared, 8886, "0.0.0.0", "10.10.10.4")
    assert endpoint["port"] == 5090 and endpoint["url"] == "http://localhost:5090"
    assert (shared / ".env").read_text() == raw


def test_external_endpoint_initialization_sets_consistent_origin(tmp_path):
    shared = tmp_path / "shared"; shared.mkdir()
    values = mod.initialize_env(shared, 8886, "0.0.0.0", ("10.247.1.0/28", "10.247.2.0/28"), "10.10.10.4")
    assert values["WEB_URL"] == values["CORS_ALLOWED_ORIGINS"] == "http://10.10.10.4:8886"
    assert values["APP_DOMAIN"] == "10.10.10.4"


@pytest.mark.parametrize("host", ["http://10.10.10.4", "10.10.10.4:8886", "x\nSECRET=value", "bad/path", "user@host"])
def test_new_endpoint_rejects_invalid_public_host_before_writes(tmp_path, host):
    with pytest.raises(ValueError):
        mod.deployment_endpoint(tmp_path / "shared", 8886, "127.0.0.1", host)
    assert not (tmp_path / "shared").exists()


def test_file_checksum_streams_without_python311_file_digest(tmp_path, monkeypatch):
    path = tmp_path / "artifact"; path.write_bytes(b"release" * 200000)
    monkeypatch.delattr(mod.hashlib, "file_digest", raising=False)
    assert mod.file_sha(path) == hashlib.sha256(path.read_bytes()).hexdigest()


def test_port_search_is_bounded_and_does_not_write_config(tmp_path, monkeypatch):
    attempts = []
    class Occupied:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def bind(self, address):
            attempts.append(address)
            raise OSError(mod.errno.EADDRINUSE, "fixture occupied")
    monkeypatch.setattr(mod.socket, "socket", lambda *args: Occupied())
    with pytest.raises(ValueError, match="no free TCP port"):
        mod.deployment_endpoint(tmp_path / "shared", 8886, "0.0.0.0", "10.10.10.4")
    assert len(attempts) == 100 and attempts[0][1] == 8886 and attempts[-1][1] == 8985
    assert not (tmp_path / "shared").exists()

def test_frp_only_installer_switch_requires_existing_owned_release_and_apply(tmp_path,monkeypatch):
    root=tmp_path/'installed';(root/'shared').mkdir(parents=True);release=root/'releases/v1';release.mkdir(parents=True);(root/'current').symlink_to('releases/v1')
    (root/'shared/.env').write_text('HTTP_PORT=8886\n');(root/'shared/.env').chmod(0o600)
    (root/'shared/deployment.json').write_text(json.dumps({'schema_version':1,'deploy_root':str(root),'project_name':'platform','profiles':['helpers']}))
    calls=[];monkeypatch.setattr(mod,'frp_reconcile',lambda *a:calls.append(a) or {'enabled':False})
    assert mod.main(['--deploy-root',str(root),'--closefrp'])==1
    assert not calls
    assert mod.main(['--apply','--deploy-root',str(root),'--closefrp'])==0
    assert calls[0][1:3]==(8886,'close')

def test_managed_start_wrapper_forwards_explicit_frp_switch():
    assert b'start "$@"\n' in mod.wrapper_bytes('start')
