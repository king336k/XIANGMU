"""Central research security regressions; no Django database or network required."""
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import socket
from types import SimpleNamespace
import sys
import types
from unittest.mock import MagicMock
from contextlib import contextmanager
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('plane.quality.remote_research', Path(__file__).parents[2] / 'ProjectServer/plane/quality/remote_research.py')
research = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(research)
research.__package__ = 'plane.quality'


@contextmanager
def fake_modules(rows=(), previous=(), permitted=lambda *args:True):
    model = MagicMock()
    model.objects.filter.return_value.exclude.return_value.select_related.return_value.order_by.return_value.__getitem__.return_value = list(previous)
    modules = {}
    for name in ['plane','plane.quality','plane.knowledge','plane.knowledge.retrieval','plane.quality.diagnostic_materials','plane.quality.remote_models','plane.quality.remote_diagnostics']:
        modules[name] = types.ModuleType(name)
    modules['plane.knowledge.retrieval'].search = lambda project,query:list(rows)
    modules['plane.quality.diagnostic_materials'].redact = lambda value:str(value).replace('synthetic-secret','[REDACTED]')
    modules['plane.quality.remote_models'].RemoteAgentRun = model
    modules['plane.quality.remote_diagnostics'].permitted = permitted
    with patch.dict(sys.modules,modules):
        yield model


class ResearchBoundaryTest(unittest.TestCase):
    def test_private_repository_requires_project_grant(self):
        config = json.dumps({'private': {'kind':'gitea', 'host':'git.transcengram.com', 'repository':'org/repo', 'ref':'test/branch',
            'project_ids':['project-a'], 'allowed_cidrs':['10.0.0.0/24'], 'token_env':'TEST_RESEARCH_TOKEN'}})
        with patch.dict(os.environ, {'REMOTE_RESEARCH_SOURCES':config, 'TEST_RESEARCH_TOKEN':'synthetic-secret'}):
            self.assertNotIn('private', research.sources_for('project-b'))
            self.assertIn('private', research.sources_for('project-a'))
            self.assertNotIn('synthetic-secret', json.dumps(research.source_catalog('project-a')))

    def test_paths_cannot_choose_host_query_or_escape_source_root(self):
        for path in ['https://evil.example/x', '//evil.example/x', '../secret', '%2e%2e/secret', 'a/../../secret', 'x?token=abc', 'x#fragment', 'x\\secret']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                research.safe_path(path)

    def test_all_dns_records_are_checked_and_ip_is_pinned(self):
        source = {'kind':'github', 'repository':'nasa-jpl/rosa', 'ref':'main'}
        dns = [(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443)),
               (socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',443))]
        with patch.object(research.socket, 'getaddrinfo', return_value=dns):
            with self.assertRaises(ValueError):
                research.resolve_addresses('api.github.com', source)
        with patch.object(research.socket, 'getaddrinfo', return_value=dns[:1]):
            self.assertEqual(research.resolve_addresses('api.github.com', source), ['93.184.216.34'])

    def test_private_cidr_never_allows_metadata_or_loopback(self):
        source = {'kind':'gitea', 'host':'git.transcengram.com', 'allowed_cidrs':['0.0.0.0/0']}
        for address in ['127.0.0.1','169.254.169.254','0.0.0.0','224.0.0.1']:
            with self.subTest(address=address):
                self.assertFalse(research.address_allowed(ipaddress.ip_address(address), source))

    def test_redirect_is_refused_without_followup_and_token_not_returned(self):
        source = {'kind':'github', 'repository':'nasa-jpl/rosa', 'ref':'main'}
        response = type('Response', (), {'status':302, 'getheader':lambda self,key,default='':default,
            'read':lambda self,n:b'credential=synthetic-secret'})()
        connection = type('Connection', (), {'request':lambda *a,**k:None, 'getresponse':lambda self:response,
            'close':lambda self:None})()
        with patch.object(research, 'resolve_addresses', return_value=['93.184.216.34']), \
             patch.object(research, 'PinnedHTTPSConnection', return_value=connection):
            with self.assertRaises(ValueError):
                research.fetch_bytes('https://api.github.com/repos/nasa-jpl/rosa/contents/README.md',source)

    def test_private_gitlab_configuration_is_not_misinterpreted_as_gitea(self):
        with patch.dict(os.environ, {'REMOTE_RESEARCH_SOURCES':json.dumps({'wrong':{'kind':'gitlab',
            'host':'git.transcengram.com','repository':'org/repo','ref':'main','project_ids':['a']}})}):
            self.assertNotIn('wrong', research.sources_for('a'))

    def test_tls_connection_pins_ip_but_verifies_original_hostname(self):
        connection = research.PinnedHTTPSConnection('api.github.com','93.184.216.34')
        context = MagicMock()
        connection._context = context
        with patch.object(research.socket, 'create_connection') as create:
            connection.connect()
        self.assertEqual(create.call_args.args[0], ('93.184.216.34',443))
        self.assertEqual(context.wrap_socket.call_args.kwargs['server_hostname'], 'api.github.com')

    def test_knowledge_counts_and_failed_history_keep_permission_scope_and_evidence(self):
        station = SimpleNamespace(agent=SimpleNamespace(project_id='project-a'))
        run = SimpleNamespace(pk='current',owner='owner-a',workstation=station,workstation_id='station-a')
        commands = MagicMock()
        commands.filter.return_value.order_by.return_value.__getitem__.return_value = [SimpleNamespace(pk='cmd1',
            payload={'kind':'run'}, result={'exit_code':1,'ok':False,'stdout':'telemetry disabled synthetic-secret'})]
        failed = SimpleNamespace(pk='old-failed',owner='owner-a',workstation=station,workstation_id='station-a',
            status='failed', mode='repair', result={'repaired':False,'root_cause':'telemetry disabled','verification':['failed']},
            problem='telemetry unavailable',identity_key='old-identity',created_at=datetime.now(timezone.utc),remotecommand_set=commands)
        denied = SimpleNamespace(**{**failed.__dict__,'pk':'forbidden','workstation':'denied'})
        row = SimpleNamespace(id='kb1',title='telemetry guide',version=2,content='reference synthetic-secret')
        with fake_modules([row],[denied,failed],lambda owner,station:station!='denied') as model:
            value = research.knowledge('project-a','telemetry',run=run)
        self.assertEqual(value['counts'],{'published_knowledge':1,'historical_cases':1})
        self.assertEqual(value['case_history'][0]['outcome'],'not_repaired')
        self.assertEqual(value['case_history'][0]['execution_evidence'][0]['exit_code'],1)
        self.assertNotIn('synthetic-secret',json.dumps(value))
        self.assertEqual(model.objects.filter.call_args.kwargs['owner'],'owner-a')
        self.assertEqual(model.objects.filter.call_args.kwargs['workstation__agent__project_id'],'project-a')

    def test_gitea_uses_explicit_repo_ref_and_strips_root_prefix(self):
        source = {'kind':'gitea','host':'git.transcengram.com','repository':'org/repo','ref':'test/branch','root':'src/'}
        value = [{'name':'main.py','path':'src/main.py','type':'file','sha':'a'*40}]
        with fake_modules(),patch.object(research,'sources_for',return_value={'private':source}), \
             patch.object(research,'fetch_bytes',return_value=json.dumps(value).encode()) as fetch:
            result = research.read_source('project-a','private','',operation='list_source_paths')
        self.assertIn('/api/v1/repos/org/repo/contents/src/?ref=test%2Fbranch',fetch.call_args.args[0])
        self.assertEqual(result['entries'][0]['path'],'main.py')

    def test_private_credential_cannot_escape_in_source_content_or_revision(self):
        import base64
        source={'kind':'gitea','host':'git.transcengram.com','repository':'org/repo','ref':'test','root':'','token_env':'SYNTHETIC_RESEARCH_TOKEN'}
        value={'type':'file','encoding':'base64','content':base64.b64encode(b'opaque credential-value-alone').decode(),'sha':'credential-value-alone'}
        with fake_modules(),patch.dict(os.environ,{'SYNTHETIC_RESEARCH_TOKEN':'credential-value-alone'}), \
             patch.object(research,'sources_for',return_value={'private':source}),patch.object(research,'fetch_bytes',return_value=json.dumps(value).encode()):
            result=research.read_source('project','private','README.md')
        self.assertNotIn('credential-value-alone',json.dumps(result))
        self.assertIsNone(result['revision'])


if __name__ == '__main__':
    unittest.main()

class RepositorySwitchTest(unittest.TestCase):
    def test_repository_switch_keeps_only_documentation_and_blocks_private_sources(self):
        source={'kind':'gitea','host':'git.transcengram.com','repository':'owner/repo','ref':'test','project_ids':['a']}
        with patch.dict(os.environ,{'REMOTE_RESEARCH_REPOSITORIES_ENABLED':'false','REMOTE_RESEARCH_SOURCES':json.dumps({'private':source})}):
            sources=research.sources_for('a')
            self.assertTrue(sources)
            self.assertTrue(all(item['kind']=='docs' for item in sources.values()))
            self.assertNotIn('private',sources)
