import base64
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import os
import time
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from file_browser import local_request, dispatch
ARTIFACTS=Path('/home/engram/Documents/tmp/artifacts/remote-file-tests-20261118')
ARTIFACTS.mkdir(parents=True,exist_ok=True)
class FileTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ARTIFACTS);self.root=Path(self.temp.name)/'home';self.root.mkdir();self.spool=Path(self.temp.name)/'downloads'
    def tearDown(self):self.temp.cleanup()
    def call(self,action,**kw):return local_request(self.root,self.spool,{'action':action,**kw})
    def test_list_binary_file_and_folder_download_hash(self):
        (self.root/'logs').mkdir();data=b'\x00\xffrobot\x00';(self.root/'logs'/'sample.bin').write_bytes(data)
        rows=self.call('list',path='')['entries'];self.assertEqual(rows[0]['name'],'logs');self.assertEqual(rows[0]['kind'],'directory')
        file=self.call('prepare',path='logs/sample.bin');chunk=self.call('chunk',ticket=file['ticket'],offset=0)
        self.assertEqual(base64.b64decode(chunk['data']),data);self.assertEqual(file['sha256'],hashlib.sha256(data).hexdigest())
        folder=self.call('prepare',path='logs');raw=base64.b64decode(self.call('chunk',ticket=folder['ticket'],offset=0)['data'])
        with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as t:self.assertEqual(t.extractfile('logs/sample.bin').read(),data)
    def test_path_escape_links_and_credentials_denied(self):
        (self.root/'link').symlink_to('/etc');(self.root/'.env').write_text('secret')
        for path in ('../outside','/etc/passwd','link/passwd','.env','.ssh/key','.config/engram/token'):
            with self.subTest(path=path),self.assertRaises(ValueError):self.call('prepare',path=path)
        self.assertEqual(self.call('list',path='')['entries'],[])
    def test_archive_skips_secrets_and_symlinks(self):
        (self.root/'ok.txt').write_text('okay');(self.root/'.env').write_text('secret');(self.root/'link').symlink_to('/etc')
        result=self.call('prepare',path='');self.assertGreaterEqual(result['skipped'],2)
        data=base64.b64decode(self.call('chunk',ticket=result['ticket'],offset=0)['data'])
        with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive:
            self.assertEqual(archive.getnames(),['home/ok.txt'])
    def test_invalid_ticket_offset_and_upload_refused(self):
        for payload in ({'action':'chunk','ticket':'../etc','offset':0},{'action':'chunk','ticket':'a'*32,'offset':-1},{'action':'upload','path':'x'}):
            with self.assertRaises((ValueError,FileNotFoundError)):local_request(self.root,self.spool,payload)
    def test_directory_listing_is_bounded_and_paginated(self):
        for n in range(120):(self.root/f'file-{n:03}.txt').write_text('x')
        first=self.call('list',path='');second=self.call('list',path='',offset=100)
        self.assertEqual(first['total'],120);self.assertEqual(len(first['entries']),100)
        self.assertEqual(len(second['entries']),20)
    def test_upload_binary_chunks_integrity_and_no_overwrite(self):
        data=b'robot archive\x00\xff';digest=hashlib.sha256(data).hexdigest()
        created=self.call('upload_start',path='',filename='patch.zip',size=len(data),sha256=digest)
        part={'ticket':created['ticket'],'offset':0,'data':base64.b64encode(data).decode()}
        self.call('upload_chunk',**part);self.call('upload_chunk',**part)
        result=self.call('upload_finish',ticket=created['ticket'])
        self.assertEqual((self.root/'patch.zip').read_bytes(),data);self.assertEqual(result['sha256'],digest)
        with self.assertRaises(ValueError):self.call('upload_start',path='',filename='patch.zip',size=len(data),sha256=digest)
    def test_upload_rejects_bad_hash_name_and_out_of_order_chunk(self):
        for filename in ('../x','/absolute','.env','id_rsa','a/b'):
            with self.assertRaises(ValueError):self.call('upload_start',path='',filename=filename,size=3,sha256='0'*64)
        ticket=self.call('upload_start',path='',filename='good.zip',size=3,sha256='0'*64)['ticket']
        with self.assertRaises(ValueError):self.call('upload_chunk',ticket=ticket,offset=2,data='eA==')
        self.call('upload_chunk',ticket=ticket,offset=0,data='YWJj')
        with self.assertRaises(ValueError):self.call('upload_finish',ticket=ticket)
        self.assertFalse((self.root/'good.zip').exists())
    def test_hardlinks_never_listed_downloaded_or_archived(self):
        outside=Path(self.temp.name)/'credential-source';outside.write_text('must-not-read')
        os.link(outside,self.root/'innocent.txt')
        self.assertEqual(self.call('list',path='')['entries'],[])
        with self.assertRaises(ValueError):self.call('prepare',path='innocent.txt')
        archive=self.call('prepare',path='')
        raw=base64.b64decode(self.call('chunk',ticket=archive['ticket'],offset=0)['data'])
        with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as stream:self.assertFalse(stream.getnames())
    def test_expired_upload_removes_only_its_part(self):
        ticket=self.call('upload_start',path='',filename='expires.bin',size=3,sha256='0'*64)['ticket']
        part=self.root/('.engram-upload-'+ticket+'.part')
        old=time.time()-1900
        os.utime(self.spool/(ticket+'.upload'),(old,old))
        self.call('list',path='')
        self.assertFalse(part.exists())
        self.assertFalse((self.spool/(ticket+'.upload')).exists())
    def test_upload_directory_replaced_during_transfer_is_refused(self):
        (self.root/'destination').mkdir()
        ticket=self.call('upload_start',path='destination',filename='file.bin',size=1,sha256=hashlib.sha256(b'x').hexdigest())['ticket']
        (self.root/'destination').rename(self.root/'original')
        (self.root/'destination').mkdir()
        (self.root/'destination'/('.engram-upload-'+ticket+'.part')).write_bytes(b'')
        with self.assertRaisesRegex(ValueError,'changed'):
            self.call('upload_chunk',ticket=ticket,offset=0,data='eA==')
    def test_completed_upload_is_immutable_and_retry_finish_is_safe(self):
        ticket=self.call('upload_start',path='',filename='done.bin',size=1,sha256=hashlib.sha256(b'x').hexdigest())['ticket']
        self.call('upload_chunk',ticket=ticket,offset=0,data='eA==')
        result=self.call('upload_finish',ticket=ticket)
        self.assertEqual(self.call('upload_finish',ticket=ticket),result)
        with self.assertRaisesRegex(ValueError,'completed'):
            self.call('upload_chunk',ticket=ticket,offset=0,data='eA==')
        self.call('upload_abort',ticket=ticket)
        self.assertEqual((self.root/'done.bin').read_bytes(),b'x')
    def test_download_uses_anchored_parent_after_initial_resolution(self):
        (self.root/'folder').mkdir();(self.root/'folder'/'ok.txt').write_text('safe')
        original=__import__('file_browser').resolve
        def swap(root,relative):
            path=original(root,relative)
            (self.root/'folder').rename(self.root/'original')
            (self.root/'folder').symlink_to(Path(self.temp.name))
            return path
        with patch('file_browser.resolve',side_effect=swap),self.assertRaises(OSError):
            self.call('prepare',path='folder/ok.txt')
        self.assertFalse([item for item in self.spool.iterdir() if len(item.name)==32])
    def test_robot_daq_api_failure_does_not_fallback_to_fixed_peer(self):
        credential=self.root/'api-private';credential.write_text('synthetic-only-local-credential');credential.chmod(0o600)
        config={'url':'http://127.0.0.1:11452/api/launcher/remote-robot-files','token_file':str(credential)}
        with patch('file_browser.build_opener') as opener,patch('robot_peer.peer_config') as fixed:
            opener.return_value.open.side_effect=OSError('unavailable')
            with self.assertRaisesRegex(ValueError,'DAQ'):
                dispatch(self.root,{'action':'list','target':'robot'},config)
            fixed.assert_not_called()
    def test_fixed_simulation_tickets_reject_changed_robot_identity(self):
        peer={'host':'10.10.10.177','username':'engram','remote_root':'/isolated','ssh_key':'/key','known_hosts':'/hosts'}
        process=Mock(returncode=0,stdout=json.dumps({'username':'engram','ticket':'a'*32}).encode())
        with patch('robot_peer.peer_config',return_value=peer),patch('file_browser.subprocess.run',return_value=process):
            prepared=dispatch(self.root,{'action':'prepare','target':'robot','path':'log'})
        self.assertTrue(prepared['ticket'].startswith('r1.'))
        with patch('robot_peer.peer_config',return_value=peer),patch('file_browser.subprocess.run') as execute:
            with self.assertRaisesRegex(ValueError,'robot_identity_changed'):
                dispatch(self.root,{'action':'chunk','target':'robot','ticket':prepared['ticket'][:-32]+'b'*32,'offset':0})
            execute.assert_not_called()
        with patch('robot_peer.peer_config',return_value={**peer,'host':'10.10.10.178'}),patch('file_browser.subprocess.run') as execute:
            with self.assertRaisesRegex(ValueError,'robot_identity_changed'):
                dispatch(self.root,{'action':'chunk','target':'robot','ticket':prepared['ticket'],'offset':0})
            execute.assert_not_called()
    def test_upload_finish_recovers_crash_after_publish_before_ack(self):
        ticket=self.call('upload_start',path='',filename='recovery.bin',size=1,sha256=hashlib.sha256(b'x').hexdigest())['ticket']
        self.call('upload_chunk',ticket=ticket,offset=0,data='eA==')
        part=self.root/('.engram-upload-'+ticket+'.part')
        os.link(part,self.root/'recovery.bin')
        result=self.call('upload_finish',ticket=ticket)
        self.assertTrue(result['uploaded'])
        self.assertFalse(part.exists())
        self.assertEqual((self.root/'recovery.bin').read_bytes(),b'x')
