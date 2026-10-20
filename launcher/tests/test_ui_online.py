import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


class OnlineUiTests(unittest.TestCase):
    def test_counter_failure_does_not_block_play_and_close_cancels_poll(self):
        code = '''
import json,time
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from bc2launcher import ui
from bc2launcher.online import OnlineStatus
class EmptySettings:
    def load(self): return {'game_dir':''}
app = QApplication([])
calls = []
def pending(*,cancelled):
    calls.append(1)
    while not cancelled(): time.sleep(.005)
    return None
with patch.object(ui,'Settings',EmptySettings),patch.object(ui,'fetch_online',pending):
    window = ui.Window(Path('launcher/assets').resolve())
    window.show(); app.processEvents()
    window.folder='fixture'; window.state='READY'; window.buttons()
    window.online_received(OnlineStatus(players=20,servers=2))
    success = window.online.text()
    window.online_received(None)
    unavailable = window.online.text()
    allowed = window.play.isEnabled()
    window.start_online(); window.poll_online()
    window.close()
    deadline=time.monotonic()+3
    while window.isVisible() and time.monotonic()<deadline:
        app.processEvents();time.sleep(.005)
    print(json.dumps({'success':success,'unavailable':unavailable,'allowed':allowed,
                     'closed':not window.isVisible(),'polls':len(calls),
                     'timer_stopped':not window.online_timer.isActive()}))
'''
        result = subprocess.run(
            [sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[2],
            env=dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONUTF8='1'),
            capture_output=True, text=True, encoding='utf-8', timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        values = json.loads(result.stdout)
        self.assertEqual(values['success'], 'Онлайн: 20')
        self.assertEqual(values['unavailable'], 'Онлайн: —')
        self.assertTrue(values['allowed'])
        self.assertTrue(values['closed'])
        self.assertTrue(values['timer_stopped'])
        self.assertEqual(values['polls'], 1)
