import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


class InstallPanelTests(unittest.TestCase):
    def test_installed_game_offers_only_confirmed_native_uninstall(self):
        code = '''
import tempfile,threading,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QMessageBox
from bc2launcher import ui
app=QApplication([])
with tempfile.TemporaryDirectory() as folder:
 game=Path(folder)
 exe=game/'BFBC2Game.exe'
 exe.write_bytes(b'MZfixture')
 saved=[]
 settings=SimpleNamespace(load=lambda:{'game_dir':folder},remember_folder=saved.append)
 installer=SimpleNamespace(cancel=threading.Event())
 w=ui.Window(Path('launcher/assets').resolve(),settings=settings,game_installer=installer,auto_check=False)
 w.state='READY';w.show();w.buttons()
 assert w.install_game_button.isHidden()
 uninstaller=game/'Uninstall'/'unins000.exe'
 uninstaller.parent.mkdir()
 uninstaller.write_bytes(b'MZfixture')
 uninstaller.with_suffix('.dat').write_bytes(b'fixture')
 w.buttons()
 assert w.install_game_button.text()=='Удалить игру' and w.install_game_button.isVisible()
 with patch.object(ui.QMessageBox,'question',return_value=QMessageBox.No),patch.object(ui,'run_uninstall') as run:
  w.install_game_button.click()
  run.assert_not_called()
 def wait():
  deadline=time.monotonic()+4
  while w.install_job and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
  assert not w.install_job
 with patch.object(ui.QMessageBox,'question',return_value=QMessageBox.Yes),patch.object(ui,'run_uninstall',return_value=False) as run:
  w.install_game_button.click();wait()
  run.assert_called_once_with(game)
  assert w.folder==folder and w.play.isEnabled() and saved==[]
 def remove_fixture(root):
  assert root==game
  exe.unlink()
  return True
 with patch.object(ui.QMessageBox,'question',return_value=QMessageBox.Yes),patch.object(ui,'run_uninstall',side_effect=remove_fixture):
  w.install_game_button.click();wait()
  assert w.folder=='' and not w.play.isEnabled() and saved==['']
  assert w.install_game_button.text()=='Установить игру'
 w.close()
'''
        self.run_ui(code)

    def test_cancel_install_status_survives_queued_download_progress(self):
        code = '''
import threading
from pathlib import Path
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication
from bc2launcher import ui
from bc2launcher.game_install import InstallProgress
app=QApplication([])
settings=SimpleNamespace(load=lambda:{'game_dir':''})
installer=SimpleNamespace(cancel=threading.Event())
w=ui.Window(Path('launcher/assets').resolve(),settings=settings,game_installer=installer,auto_check=False)
w.install_job=object()
w.install_phase='DOWNLOAD'
w.cancel_job()
assert installer.cancel.is_set()
assert w.status.text()=='Останавливаем установку…', w.status.text()
w.install_progress(InstallProgress('FINALIZE_DOWNLOAD'))
assert w.status.text()=='Останавливаем установку…', w.status.text()
w.install_job=None
w.close()
'''
        self.run_ui(code)

    def test_install_dialog_starts_in_last_library_after_restart(self):
        code = '''
import tempfile,threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from bc2launcher import ui
from bc2launcher.settings import Settings
app=QApplication([])
with tempfile.TemporaryDirectory() as folder:
 library=Path(folder)
 settings=Settings(library/'settings.json')
 installer=SimpleNamespace(cancel=threading.Event())
 w=ui.Window(Path('launcher/assets').resolve(),settings=settings,game_installer=installer,auto_check=False)
 with patch.object(ui.QFileDialog,'getExistingDirectory',return_value=folder),patch.object(w,'_start_install_job'):
  w.install_game_button.click()
 w.close()
 settings.remember_folder('')
 reopened=ui.Window(Path('launcher/assets').resolve(),settings=settings,game_installer=installer,auto_check=False)
 with patch.object(ui.QFileDialog,'getExistingDirectory',return_value='') as choose:
  reopened.install_game_button.click()
  assert choose.call_args.args[-1]==folder, choose.call_args
 reopened.close()
'''
        self.run_ui(code)

    def test_folder_selected_first_install_updates_path_and_offers_cleanup(self):
        code = '''
import json,tempfile,threading,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QMessageBox
from bc2launcher import ui
from bc2launcher.game_install import InstallProgress
events=[]
class Settings:
 def load(self):return {'game_dir':''}
 def remember_folder(self,folder):events.append(['saved',str(folder)])
 def update_fields(self,**fields):pass
class Installer:
 cancel=threading.Event()
 def install(self,library):
  events.append(['install',str(library)])
  self.progress(InstallProgress('DOWNLOAD', 2000000, 4000000, 12500000))
  self.progress(InstallProgress('SETUP', 2000000, 4000000))
  return SimpleNamespace(game_dir=Path(library)/'Battlefield_BC2')
 def cleanup(self,result):events.append(['cleanup',str(result.game_dir)])
app=QApplication([])
with tempfile.TemporaryDirectory() as folder:
 w=ui.Window(Path('launcher/assets').resolve(),settings=Settings(),game_installer=Installer(),auto_check=False)
 on_progress=w.install_progress
 def display(event):
  on_progress(event);events.append(['progress',w.status.text(),w.install_meter.value()])
 w.install_progress=display
 w.work=lambda action:events.append(['connection',action]);w.show();app.processEvents()
 def choose(*args):events.append(['choose',folder]);return folder
 def ask(*args,**kwargs):events.append(['offer',w.folder]);return QMessageBox.Yes
 with patch.object(ui.QFileDialog,'getExistingDirectory',side_effect=choose),patch.object(ui.QMessageBox,'question',side_effect=ask):
  w.install_game_button.click()
  deadline=time.monotonic()+4
  while w.install_job and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
  w.close();app.processEvents()
 print(json.dumps(events))
'''
        events = json.loads(self.run_ui(code))
        self.assertEqual([e[0] for e in events], ['choose', 'install', 'progress', 'progress', 'saved', 'offer', 'cleanup', 'connection'])
        self.assertEqual(events[0][1], events[1][1])
        self.assertIn('100.0 Мбит/с', events[2][1])
        self.assertEqual(events[3][2], 50)
        self.assertTrue(events[4][1].endswith('Battlefield_BC2'))
        self.assertEqual(events[-1], ['connection', 'update'])

    def run_ui(self, code):
        result = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[2],
                                env=dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONUTF8='1'),
                                capture_output=True, text=True, encoding='utf-8', timeout=12)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout
