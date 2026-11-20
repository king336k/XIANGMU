import fcntl,os,time,tempfile,unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from file_browser import cleanup_expired_transfers

class OwnedCleanupTests(unittest.TestCase):
    def setUp(self):
        base=Path('/home/engram/Documents/tmp/artifacts/daq-safe-cleanup-20261120/tests');base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.home=Path(self.temp.name)
        self.spool=self.home/'.cache/engram/remote-downloads';self.spool.mkdir(parents=True,mode=0o700)
    def tearDown(self):self.temp.cleanup()
    def test_only_expired_own_tickets_are_removed(self):
        expired=self.spool/('a'*32);expired.write_text('temporary transfer');os.utime(expired,(time.time()-1900,)*2)
        fresh=self.spool/('b'*32);fresh.write_text('active transfer')
        foreign=self.spool/'notes.txt';foreign.write_text('user data');os.utime(foreign,(time.time()-1900,)*2)
        identity=self.home/'.config/engram/remote-diagnostics/token';identity.parent.mkdir(parents=True);identity.write_text('synthetic-private-identity')
        result=cleanup_expired_transfers(self.home)
        self.assertEqual(result['removed'],1);self.assertFalse(expired.exists());self.assertTrue(fresh.exists())
        self.assertEqual(foreign.read_text(),'user data');self.assertEqual(identity.read_text(),'synthetic-private-identity')
    def test_active_transfer_lock_prevents_cleanup(self):
        expired=self.spool/('a'*32);expired.write_text('active locked file');os.utime(expired,(time.time()-1900,)*2)
        with (self.spool/'.transfer.lock').open('w')as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.assertTrue(cleanup_expired_transfers(self.home)['busy'])
        self.assertTrue(expired.exists())
    def test_symlink_or_hardlink_ticket_never_removes_its_target(self):
        other=self.home/'keep.txt';other.write_text('must survive');os.utime(other,(time.time()-1900,)*2)
        (self.spool/('a'*32)).symlink_to(other);os.link(other,self.spool/('b'*32))
        cleanup_expired_transfers(self.home)
        self.assertEqual(other.read_text(),'must survive');self.assertTrue((self.spool/('b'*32)).exists())
    def test_missing_cache_does_not_create_directories(self):
        root=self.home/'fresh';self.assertEqual(cleanup_expired_transfers(root),{'removed':0});self.assertFalse(root.exists())
    def test_symlinked_cache_parent_is_rejected_without_removing_anything(self):
        actual=self.home/'external';actual.mkdir()
        linked=self.home/'linked-home';linked.mkdir();(linked/'.cache').symlink_to(actual,target_is_directory=True)
        foreign=actual/'engram/remote-downloads';foreign.mkdir(parents=True,mode=0o700)
        ticket=foreign/('a'*32);ticket.write_text('foreign cache');os.utime(ticket,(time.time()-1900,)*2)
        with self.assertRaisesRegex(ValueError,'symlink'):cleanup_expired_transfers(linked)
        self.assertTrue(ticket.exists())

if __name__=='__main__':unittest.main()
