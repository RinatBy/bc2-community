import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


class SelfUpdateUiTests(unittest.TestCase):
    def test_background_download_shows_percentage_and_cancel_stops_only_update(self):
        code='''
import json,time,threading
from pathlib import Path
from PySide6.QtWidgets import QApplication
from bc2launcher import ui
from bc2launcher.selfupdate import service
class EmptySettings:
 def load(self):return {'game_dir':''}
class Updates:
 cancel=threading.Event()
 def check_and_prepare(self):
  self.progress(service.AppUpdateProgress(25*1024*1024,50*1024*1024))
  while not self.cancel.is_set():time.sleep(.005)
  return service.AppUpdateStatus('CANCELLED',False,False)
app=QApplication([])
updates=Updates()
w=ui.Window(Path('launcher/assets').resolve(),settings=EmptySettings(),app_updates=updates,auto_check=False)
w.show();w.start_app_updates()
deadline=time.monotonic()+2
while '50%' not in w.app_update_label.text() and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
text=w.app_update_label.text();enabled=w.cancel.isEnabled();w.cancel.click()
deadline=time.monotonic()+2
while w.app_job and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
stopped=w.app_job is None;cancelled=updates.cancel.is_set()
w.close();app.processEvents()
print(json.dumps(dict(text=text,enabled=enabled,stopped=stopped,cancelled=cancelled)))
'''
        result=subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).resolve().parents[2],
                              env=dict(os.environ,QT_QPA_PLATFORM='offscreen',PYTHONUTF8='1'),
                              capture_output=True,text=True,encoding='utf-8',timeout=12)
        self.assertEqual(result.returncode,0,result.stderr)
        values=json.loads(result.stdout)
        self.assertIn('50%',values['text']);self.assertIn('25.0 / 50.0',values['text'])
        self.assertTrue(values['enabled']);self.assertTrue(values['stopped']);self.assertTrue(values['cancelled'])

    def test_required_update_overrides_ready_game_and_close_waits_for_worker(self):
        code='''
import json,time,threading
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from bc2launcher import ui
from bc2launcher.selfupdate.service import AppUpdateStatus
class EmptySettings:
 def load(self):return {'game_dir':''}
class Updates:
 cancel=threading.Event()
 status=AppUpdateStatus('REQUIRED',False,False)
 def check_and_prepare(self):
  while not self.cancel.is_set():time.sleep(.005)
  return AppUpdateStatus('CANCELLED',False,False)
app=QApplication([])
with patch.object(ui,'Settings',EmptySettings):
 w=ui.Window(Path('launcher/assets').resolve());w.show();app.processEvents()
 w.folder='fixture';w.state='READY';w.app_updates=Updates()
 w.app_update_received(AppUpdateStatus('REQUIRED',False,False));blocked=not w.play.isEnabled()
 w.app_update_received(AppUpdateStatus('STAGED',False,True));restart=w.app_update_button.isVisible() and w.app_update_button.isEnabled()
 w.start_app_updates();w.close()
 deadline=time.monotonic()+4
 while w.isVisible() and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
 print(json.dumps(dict(blocked=blocked,restart=restart,closed=not w.isVisible())))
'''
        result=subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).resolve().parents[2],
                              env=dict(os.environ,QT_QPA_PLATFORM='offscreen',PYTHONUTF8='1'),
                              capture_output=True,text=True,encoding='utf-8',timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),dict(blocked=True,restart=True,closed=True))
