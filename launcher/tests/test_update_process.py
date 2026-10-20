import os
import sys
import tempfile
import unittest
from pathlib import Path
from bc2launcher.manifest import UpdateError
from bc2launcher.selfupdate.process import spawn_ready, wait_for_old_process


class ProcessTests(unittest.TestCase):
    def test_ready_accepts_nonce_pid_and_version_from_actual_child(self):
        script='''import json,os,sys,time
h=int(sys.argv[1]);token=sys.argv[2]
if os.name=='nt':
 import msvcrt
 h=msvcrt.open_osfhandle(h,os.O_WRONLY)
os.write(h,json.dumps(dict(nonce=token,pid=os.getpid(),version="0.2.1")).encode()+b"\\n")
os.close(h)
time.sleep(4)
'''
        child=spawn_ready([sys._base_executable,'-c',script],Path.cwd(),'0.2.1',append_arguments=False)
        try:child.wait_ready(timeout=3)
        finally:child.stop();child.close()

    def test_wrong_reply_and_early_exit_cannot_confirm(self):
        for script in ('print("nothing")','import time;time.sleep(4)'):
            child=spawn_ready([sys._base_executable,'-c',script],Path.cwd(),'0.2.1',append_arguments=False)
            try:
                with self.assertRaises(UpdateError):child.wait_ready(timeout=.15)
            finally:child.stop();child.close()

    @unittest.skipUnless(os.name=='nt','Windows process identity')
    def test_old_pid_must_match_expected_executable(self):
        with self.assertRaises(UpdateError):wait_for_old_process(os.getpid(),Path('C:/not-our-client.exe'),timeout=.01)
