"""Release-only contracts: actual Compose/Caddy parsing, no services started."""
import json
import os
from pathlib import Path
import subprocess

import yaml

ROOT=Path(__file__).resolve().parents[2]


def test_hashed_frontend_assets_are_compressed_cached_and_html_stays_fresh():
    config=(ROOT/'deploy/release/nginx.web.conf').read_text()
    assert 'gzip on;' in config
    assert 'gzip_vary on;' in config
    assert 'gzip_min_length 1024;' in config
    assert 'gzip_comp_level 5;' in config
    assert 'gzip_types application/javascript' in config
    assets=config.split('location ^~ /assets/ {',1)[1].split('}',1)[0]
    assert 'try_files $uri =404;' in assets
    assert 'expires 1y;' in assets
    assert '"text/html" "no-cache";' in config


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


def test_default_ai_stack_is_bundled_and_custom_model_hosts_are_preserved():
    services=yaml.safe_load((ROOT/'deploy/release/compose.yml').read_text())['services']
    for name in ['api','worker','diagnostic-worker','migrator','beat-worker']:
        env=services[name]['environment']
        assert env['KNOWLEDGE_BUILTIN_EMBEDDING_MODEL']=='bge-small-zh-v1.5'
        assert env['KNOWLEDGE_BUILTIN_EMBEDDING_BASE_URL']=='http://builtin-embedding:18885/v1'
        assert env['KNOWLEDGE_LLM_ALLOWED_HOSTS']=='${KNOWLEDGE_LLM_ALLOWED_HOSTS:-api.openai.com}'
    diagnostic=services['diagnostic-worker']
    assert diagnostic['environment']['DIAGNOSTIC_AGENT_PYTHON']=='/opt/diagnostic-agent/bin/python'
    assert diagnostic['environment']['DIAGNOSTIC_AGENT_SCRIPT']=='/release-agent/runner.py'
    assert '${RELEASE_DIR:?请使用部署入口}/services/diagnostic-agent:/release-agent:ro' in diagnostic['volumes']
    assert 'pydantic-ai' in (ROOT/'services/diagnostic-agent/requirements.txt').read_text()
