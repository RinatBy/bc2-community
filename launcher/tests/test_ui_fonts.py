import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


class UiFontTests(unittest.TestCase):
    def test_brand_mouse_and_keyboard_open_project_site(self):
        code = '''
import json
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import Qt,QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QPushButton,QWidget
from bc2launcher import ui
class EmptySettings:
    def load(self): return {'game_dir': ''}
app = QApplication([])
opened = []
with patch.object(ui,'Settings',EmptySettings), patch.object(ui.QDesktopServices,'openUrl',side_effect=lambda url: opened.append(url.toString()) or True):
    window = ui.Window(Path('launcher/assets').resolve())
    window.show(); app.processEvents()
    brand = window.findChild(QPushButton,'brand-link')
    QTest.mouseClick(brand,Qt.LeftButton,Qt.NoModifier,QPoint(10,brand.height()//2))
    brand.clearFocus(); brand.setFocus(Qt.TabFocusReason)
    QTest.keyClick(brand,Qt.Key_Space)
    app.processEvents()
    children = brand.findChildren(QWidget,options=Qt.FindDirectChildrenOnly)
    print(json.dumps({'opened':opened,'content_fits':all(brand.rect().contains(child.geometry()) for child in children)}))
    window.close()
'''
        result = subprocess.run(
            [sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[2],
            env=dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONUTF8='1'),
            capture_output=True, text=True, encoding='utf-8', timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        values = json.loads(result.stdout)
        self.assertEqual(values['opened'], ['https://bc2.uplay2.ru/'] * 2)
        self.assertTrue(values['content_fits'], 'Brand icon and label must fit inside the clickable area')

    def test_headline_scales_like_site_and_action_uses_body_font(self):
        code = '''
import json
from pathlib import Path
from unittest.mock import patch
from PySide6.QtGui import QFontInfo
from PySide6.QtWidgets import QApplication
from bc2launcher import ui
class EmptySettings:
    def load(self): return {'game_dir': ''}
app = QApplication([])
with patch.object(ui, 'Settings', EmptySettings):
    window = ui.Window(Path('launcher/assets').resolve())
    window.resize(1280,800); window.show(); app.processEvents()
    headline = window.findChild(ui.Headline)
    small = headline.display_font.pixelSize()
    window.resize(1920,1080); app.processEvents()
    print(json.dumps({'small':small,'large':headline.display_font.pixelSize(),
        'spacing':headline.display_font.letterSpacing(),
        'action_family':QFontInfo(window.play.font()).family()}))
'''
        result = subprocess.run(
            [sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[2],
            env=dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONUTF8='1'),
            capture_output=True, text=True, encoding='utf-8', timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        values = json.loads(result.stdout)
        self.assertGreater(values['large'], values['small'])
        self.assertLess(values['spacing'], 0)
        self.assertEqual(values['action_family'], 'Manrope')

    def test_brand_and_panel_heading_use_display_font(self):
        # Qt's inherited stylesheet used to override both explicit setFont calls.
        code = '''
import json
from pathlib import Path
from unittest.mock import patch
from PySide6.QtGui import QFontInfo
from PySide6.QtWidgets import QApplication,QLabel
from bc2launcher import ui
class EmptySettings:
    def load(self): return {'game_dir': ''}
app = QApplication([])
with patch.object(ui, 'Settings', EmptySettings):
    window = ui.Window(Path('launcher/assets').resolve())
    window.ensurePolished()
    labels = window.findChildren(QLabel)
    brand = next(item for item in labels if 'BC2' in item.text() and 'Launcher' not in item.text() and 'Battlefield' not in item.text())
    heading = next(item for item in labels if item.text().upper() == 'ПОДКЛЮЧЕНИЕ К ИГРЕ')
    fonts = [QFontInfo(item.font()) for item in [brand, heading]]
    print(json.dumps([{'family': f.family(), 'pixels': f.pixelSize()} for f in fonts]))
'''
        result = subprocess.run(
            [sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[2],
            env=dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONUTF8='1'),
            capture_output=True, text=True, encoding='utf-8', timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        fonts = json.loads(result.stdout)
        for font in fonts:
            self.assertEqual(font['family'], 'Oswald')
            self.assertGreaterEqual(font['pixels'], 28)
