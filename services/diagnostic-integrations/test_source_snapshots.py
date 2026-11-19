"""Fixed Git-object snapshots: pure stdlib tests, no database or provider access."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

REPO=Path(__file__).resolve().parents[2]
BASE=Path('/home/engram/Documents/tmp/artifacts/td-d-498-20261119/source-snapshot-tests')


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class SourceSnapshotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adapter=load('source_snapshots_test',REPO/'ProjectServer/plane/quality/remote_source_snapshots.py')
        cls.builder=load('snapshot_builder_test',REPO/'services/diagnostic-agent/build_source_snapshot.py')

    def setUp(self):
        BASE.mkdir(parents=True,exist_ok=True)
        self.temp=Path(tempfile.mkdtemp(dir=BASE));self.repo=self.temp/'repo';self.repo.mkdir()
        self.git('init','-q');self.git('config','user.name','Synthetic');self.git('config','user.email','synthetic@example.invalid')
        self.git('remote','add','origin','https://synthetic-user:synthetic-password@git.example.invalid/team/repo.git?token=synthetic')
        (self.repo/'src').mkdir();(self.repo/'src/main.py').write_text('def reset():\n    return "original"\n')
        (self.repo/'src/config.yaml').write_text('mode: baseline\n')
        (self.repo/'.env').write_text('SYNTHETIC_ENV=secret')
        (self.repo/'src/private_key.pem').write_text('synthetic private fixture')
        (self.repo/'src/binary.py').write_bytes(b'x\x00y')
        (self.repo/'src/large.py').write_bytes(b'x'*(256*1024+1))
        (self.repo/'src/link.py').symlink_to('/etc/passwd')
        (self.repo/'src/credentials.py').write_text('synthetic fixture')
        (self.repo/'src/secret_literal.py').write_text('api_key = "synthetic-private-api-key-value"\n')
        self.git('add','.');self.git('commit','-qm','synthetic baseline')
        self.commit=self.git('rev-parse','HEAD').strip();self.root=self.temp/'snapshots';self.root.mkdir()
        self.output=self.root/'daq-source'

    def tearDown(self):
        for path in self.temp.rglob('*'):
            if not path.is_symlink():path.chmod(0o700 if path.is_dir() else 0o600)
        shutil.rmtree(self.temp)

    def git(self,*args):
        return subprocess.check_output(['git','-C',str(self.repo),*args],text=True,stderr=subprocess.DEVNULL)

    def build(self):
        return self.builder.build(self.repo,self.commit,self.output,'daq-source','project-a')

    def test_build_reads_exact_commit_objects_ignoring_dirty_and_new_worktree_files(self):
        (self.repo/'src/main.py').write_text('operator changed worktree')
        (self.repo/'src/dirty.py').write_text('uncommitted')
        manifest=self.build()
        self.assertEqual(manifest['repository_commit'],self.commit)
        self.assertNotIn('synthetic-password',json.dumps(manifest))
        self.assertNotIn('synthetic-user',manifest['source_repository'])
        self.assertNotIn('token=',manifest['source_repository'])
        result=self.adapter.read(self.root,'project-a','daq-source','src/main.py',redact_fn=lambda text:text)
        self.assertIn('original',result['content']);self.assertNotIn('operator changed',result['content'])
        self.assertNotIn('src/dirty.py',manifest['files'])
        self.assertEqual(result['repository_commit'],self.commit)
        self.assertEqual(result['blob_sha256'],manifest['files']['src/main.py']['sha256'])
        self.assertNotEqual(result['repository_commit'],result['blob_sha256'])
        self.assertFalse(self.output.joinpath('manifest.json').stat().st_mode&0o222)

    def test_filter_secrets_binary_symlinks_and_large_files(self):
        manifest=self.build();omitted={row['path']:row['reason'] for row in manifest['omitted']}
        for path in ('.env','src/private_key.pem','src/credentials.py','src/secret_literal.py','src/binary.py','src/link.py','src/large.py'):
            self.assertNotIn(path,manifest['files']);self.assertIn(path,omitted)
        self.assertEqual(omitted['src/link.py'],'symlink_not_allowed')
        self.assertEqual(omitted['src/large.py'],'file_too_large')

    def test_project_scope_and_model_path_traversal_are_rejected(self):
        self.build()
        self.assertEqual(self.adapter.catalog(self.root,'other-project')['sources'],[])
        with self.assertRaisesRegex(ValueError,'source_not_authorized'):
            self.adapter.read(self.root,'other-project','daq-source','src/main.py')
        for path in ('/etc/passwd','../src/main.py','src/../src/main.py','src\\main.py','src/%2e%2e/main.py'):
            with self.assertRaises(ValueError):self.adapter.read(self.root,'project-a','daq-source',path)

    def test_tampered_content_and_symlink_escape_fail_closed(self):
        self.build();file=self.output/'files/src/main.py';file.chmod(0o600);file.write_text('changed')
        with self.assertRaises(ValueError):self.adapter.read(self.root,'project-a','daq-source','src/main.py')
        file.parent.chmod(0o755)
        file.unlink();file.symlink_to(self.repo/'src/main.py')
        with self.assertRaises(ValueError):self.adapter.read(self.root,'project-a','daq-source','src/main.py')

    def test_catalog_directory_listing_literal_search_and_redaction(self):
        self.build();catalog=self.adapter.catalog(self.root,'project-a')
        self.assertEqual(catalog['sources'][0]['repository_commit'],self.commit)
        listed=self.adapter.read(self.root,'project-a','daq-source','src',operation='list_source_paths')
        self.assertEqual({row['name'] for row in listed['entries']},{'main.py','config.yaml'})
        searched=self.adapter.read(self.root,'project-a','daq-source','src',operation='search_source',query='reset',redact_fn=lambda text:text.replace('reset','[redacted]'))
        self.assertEqual(searched['matches'][0]['line'],1)
        self.assertEqual(searched['matches'][0]['path'],'src/main.py')
        self.assertIn('[redacted]',searched['matches'][0]['excerpt'])
        literal=self.adapter.read(self.root,'project-a','daq-source','src',operation='search_source',query='.*',redact_fn=lambda text:text)
        self.assertEqual(literal['matches'],[])
        with self.assertRaises(ValueError):self.adapter.read(self.root,'project-a','daq-source','',operation='search_source',query='x'*101)

    def test_directory_pagination_and_search_budgets_are_explicit(self):
        for index in range(50):(self.repo/f'src/file{index:02}.py').write_text(f'needle {index}\n')
        self.git('add','.');self.git('commit','-qm','many files');self.commit=self.git('rev-parse','HEAD').strip()
        self.build()
        first=self.adapter.read(self.root,'project-a','daq-source','src',operation='list_source_paths')
        second=self.adapter.read(self.root,'project-a','daq-source','src',operation='list_source_paths',offset=first['next_offset'])
        self.assertEqual(len(first['entries']),40);self.assertTrue(first['truncated'])
        self.assertEqual(len(second['entries']),12);self.assertFalse(second['truncated'])
        search=self.adapter.read(self.root,'project-a','daq-source','src',operation='search_source',query='needle',redact_fn=lambda text:text)
        self.assertEqual(len(search['matches']),20);self.assertTrue(search['truncated'])
        with patch.object(self.adapter,'MAX_SEARCH_BYTES',1):
            limited=self.adapter.read(self.root,'project-a','daq-source','',operation='search_source',query='needle',redact_fn=lambda text:text)
        self.assertEqual(limited['scanned_bytes'],0);self.assertTrue(limited['truncated'])
        with patch.object(self.adapter.time,'monotonic',side_effect=[0,3]):
            expired=self.adapter.read(self.root,'project-a','daq-source','',operation='search_source',query='needle',redact_fn=lambda text:text)
        self.assertEqual(expired['scanned_files'],0);self.assertTrue(expired['truncated'])

    def test_duplicate_alias_and_mutable_manifest_are_rejected(self):
        self.build();duplicate=self.root/'duplicate';shutil.copytree(self.output,duplicate)
        with self.assertRaisesRegex(ValueError,'duplicate_snapshot_source_id'):self.adapter.catalog(self.root,'project-a')
        for path in duplicate.rglob('*'):
            if not path.is_symlink():path.chmod(0o700 if path.is_dir() else 0o600)
        for directory in duplicate.rglob('*'):
            if directory.is_dir():directory.chmod(0o755)
        duplicate.chmod(0o755)
        shutil.rmtree(duplicate)
        (self.output/'manifest.json').chmod(0o644)
        self.assertEqual(self.adapter.catalog(self.root,'project-a')['sources'],[])
        with self.assertRaisesRegex(ValueError,'source_not_authorized'):
            self.adapter.read(self.root,'project-a','daq-source','src/main.py')

    def test_non_null_binary_control_bytes_are_filtered(self):
        (self.repo/'src/control.py').write_bytes(b'abc\x01def')
        self.git('add','.');self.git('commit','-qm','binary control');self.commit=self.git('rev-parse','HEAD').strip()
        manifest=self.build()
        self.assertNotIn('src/control.py',manifest['files'])

    def test_source_content_pages_remain_bounded_and_hash_refers_to_whole_blob(self):
        (self.repo/'src/paged.py').write_text('x'*125000+'\nlast_line\n')
        self.git('add','.');self.git('commit','-qm','paged');self.commit=self.git('rev-parse','HEAD').strip()
        manifest=self.build()
        first=self.adapter.read(self.root,'project-a','daq-source','src/paged.py',redact_fn=lambda text:text)
        second=self.adapter.read(self.root,'project-a','daq-source','src/paged.py',offset=120000,redact_fn=lambda text:text)
        self.assertEqual(len(first['content']),20000);self.assertTrue(first['truncated'])
        self.assertIn('last_line',second['content']);self.assertFalse(second['truncated'])
        self.assertEqual(first['blob_sha256'],second['blob_sha256'])
        self.assertEqual(first['blob_sha256'],manifest['files']['src/paged.py']['sha256'])

    def test_full_redaction_precedes_page_boundaries_and_preserves_line_positions(self):
        content='x'*19994+'\npassword=TOPSECRET\nlast\n'
        (self.repo/'src/paged.py').write_text(content)
        self.git('add','.');self.git('commit','-qm','redact page');self.commit=self.git('rev-parse','HEAD').strip()
        with patch.object(self.builder.contract,'sensitive_content',return_value=False):self.build()
        def clean(text):return text.replace('password=TOPSECRET','[REDACTED]')
        pages=[self.adapter.read(self.root,'project-a','daq-source','src/paged.py',offset=offset,redact_fn=clean)
               for offset in (0,20000)]
        self.assertNotIn('TOPSECRET',''.join(page['content'] for page in pages))
        # Reformatting a structured secret must fail closed while keeping source line count.
        collapsed=self.adapter.read(self.root,'project-a','daq-source','src/paged.py',redact_fn=lambda text:'[REDACTED]')
        self.assertNotIn('TOPSECRET',collapsed['content'])
        self.assertEqual(collapsed['content'].count('\n'),content.count('\n'))

    def test_unquoted_yaml_secret_is_omitted_during_build(self):
        (self.repo/'src/settings.yaml').write_text('password: TOPSECRET-NO-QUOTES\n')
        self.git('add','.');self.git('commit','-qm','unquoted');self.commit=self.git('rev-parse','HEAD').strip()
        manifest=self.build()
        self.assertNotIn('src/settings.yaml',manifest['files'])

    def test_twenty_hit_limit_exposes_same_file_continuation(self):
        (self.repo/'src/many.py').write_text('needle\n'*25)
        self.git('add','.');self.git('commit','-qm','many hits');self.commit=self.git('rev-parse','HEAD').strip()
        self.build()
        result=self.adapter.read(self.root,'project-a','daq-source','src',operation='search_source',query='needle',redact_fn=lambda text:text)
        self.assertEqual(len(result['matches']),20);self.assertTrue(result['truncated'])
        self.assertTrue(result['per_file_truncated']);self.assertEqual(result['continuation']['path'],'src/many.py')
        rest=self.adapter.read(self.root,'project-a','daq-source',result['continuation']['path'],
            offset=result['continuation']['offset'],redact_fn=lambda text:text)
        self.assertEqual(rest['content'].count('needle'),5)

    def test_non_exact_commit_and_existing_output_are_never_overwritten(self):
        for ref in ('HEAD',self.commit[:8]):
            with self.assertRaises(ValueError):self.builder.build(self.repo,ref,self.output,'daq-source','project-a')
        self.build()
        with self.assertRaises((ValueError,FileExistsError)):self.build()

    def test_total_build_budget_is_hard_bounded(self):
        with patch.object(self.builder,'MAX_TOTAL_BYTES',10):
            with self.assertRaisesRegex(ValueError,'snapshot_total_bytes_exceeded'):self.build()


if __name__=='__main__':unittest.main()
