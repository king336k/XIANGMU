"""Release-only contracts: actual Compose/Caddy parsing, no services started."""
import json
import os
from pathlib import Path
import subprocess

import yaml

ROOT=Path(__file__).resolve().parents[2]


def test_release_separates_code_from_runtime_and_keeps_logs_bounded():
    value=yaml.safe_load((ROOT/'deploy/release/compose.yml').read_text())
    for name,service in value['services'].items():
        assert 'build' not in service,name
        assert service['logging']=={'driver':'json-file','options':{'max-size':'20m','max-file':'5'}},name
    assert 'frp' not in value['services']
    for service in ['api','worker','diagnostic-worker','migrator','beat-worker']:
        assert '${RELEASE_DIR:?请使用部署入口}/ProjectServer:/code:ro' in value['services'][service]['volumes']
    assert value['services']['live']['command']==['node','/app/apps/live/dist/start.mjs']
    assert value['services']['proxy']['environment']['CERT_ACME_CA']=='${CERT_ACME_CA:-https://acme-v02.api.letsencrypt.org/directory}'


def test_real_compose_and_proxy_configuration_without_certificate_settings(tmp_path):
    env={**os.environ,'RELEASE_DIR':str(ROOT),'SHARED_DIR':str(tmp_path),'PLATFORM_SUBNET':'10.245.242.0/28','HELPERS_SUBNET':'10.245.243.0/28','BUILTIN_EMBEDDING_KEY':'public-contract-placeholder','DOCUMENT_OCR_KEY':'public-contract-placeholder'}
    command=['docker','compose','--env-file',str(ROOT/'deploy/local/.env.example'),'-f',str(ROOT/'deploy/release/compose.yml'),'--profile','helpers','config','--format','json']
    result=subprocess.run(command,env=env,capture_output=True,text=True,timeout=30)
    assert result.returncode==0
    config=json.loads(result.stdout);proxy=config['services']['proxy']
    assert proxy['environment']['CERT_ACME_CA']=='https://acme-v02.api.letsencrypt.org/directory'
    runtime=['docker','run','--rm','--network','none','--entrypoint','caddy','-v',str(ROOT/'deploy/release/Caddyfile')+':/etc/caddy/Caddyfile:ro']
    for key,value in proxy['environment'].items():
        runtime.extend(['-e',key+'='+str(value)])
    result=subprocess.run(runtime+[proxy['image'],'adapt','--config','/etc/caddy/Caddyfile','--adapter','caddyfile'],capture_output=True,text=True,timeout=30)
    assert result.returncode==0


def test_source_bundle_does_not_leave_workspace_business_imports():
    import re
    text=(ROOT/'services/collaboration/dist/start.mjs').read_text()
    assert not re.search(r'(?:from\s*|import\s*\()([\"\'])@plane/',text)
