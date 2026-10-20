import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


def contrast(first, second):
    def luminance(color):
        channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4 for value in channels]
        return sum(value * weight for value, weight in zip(linear, (.2126, .7152, .0722)))

    bright, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (bright + .05) / (dark + .05)


class DialogContrastTests(unittest.TestCase):
    def test_inherited_theme_keeps_dialog_text_and_backup_choices_readable(self):
        # A broad white-text rule used to leave native dialog surfaces light.
        # Exercise rendered dialogs with both OS palettes, not stylesheet text.
        code = '''
import json
from pathlib import Path
from unittest.mock import patch
from PySide6.QtGui import QColor,QPalette
from PySide6.QtWidgets import QApplication,QComboBox,QInputDialog,QLabel,QMessageBox,QPushButton
from bc2launcher import ui
class EmptySettings:
    def load(self): return {'game_dir': ''}
app = QApplication([])
app.setStyle('Fusion')
results = []
for scheme in ['light', 'dark']:
    palette = QPalette(app.style().standardPalette())
    if scheme == 'dark':
        for role, color in [(QPalette.Window,'#202020'),(QPalette.Base,'#161616'),
                            (QPalette.Button,'#303030'),(QPalette.WindowText,'#ffffff'),
                            (QPalette.Text,'#ffffff'),(QPalette.ButtonText,'#ffffff')]:
            palette.setColor(role,QColor(color))
    app.setPalette(palette)
    with patch.object(ui,'Settings',EmptySettings):
        window = ui.Window(Path('launcher/assets').resolve())
        dialogs = [QMessageBox(QMessageBox.Warning,'Папка игры',
                   'Выберите папку игры с файлом BFBC2Game.exe.',QMessageBox.Ok,window),
                   QMessageBox(QMessageBox.Information,'Откат',
                   'Резервных копий пока нет.',QMessageBox.Ok,window),QInputDialog(window)]
        dialogs[-1].setLabelText('Будут восстановлены dinput8.dll и bfbc2.ini.\\nВыберите резервную копию:')
        dialogs[-1].setComboBoxItems(['2026-10-19 · domain-test-1 · d97010b4','2026-10-20 · domain-test-1 · 12345678'])
        for dialog in dialogs:
            dialog.show(); app.processEvents()
            background = dialog.grab().toImage().pixelColor(8,8).name()
            for group in [QPalette.Active,QPalette.Inactive]:
                for label in dialog.findChildren(QLabel):
                    if label.text():
                        results.append([scheme,'dialog label',label.palette().color(group,label.foregroundRole()).name(),background])
                for button in dialog.findChildren(QPushButton):
                    p = button.palette()
                    results.append([scheme,'dialog button',p.color(group,QPalette.ButtonText).name(),p.color(group,QPalette.Button).name()])
            combo = dialog.findChild(QComboBox)
            if combo:
                combo.showPopup(); app.processEvents()
                for group in [QPalette.Active,QPalette.Inactive]:
                    p = combo.palette()
                    results.append([scheme,'backup field',p.color(group,combo.foregroundRole()).name(),p.color(group,combo.backgroundRole()).name()])
                    p = combo.view().palette()
                    results.append([scheme,'backup option',p.color(group,QPalette.Text).name(),p.color(group,QPalette.Base).name()])
                    results.append([scheme,'selected backup',p.color(group,QPalette.HighlightedText).name(),p.color(group,QPalette.Highlight).name()])
                combo.hidePopup()
            dialog.close()
        window.close()
print(json.dumps(results))
'''
        result = subprocess.run(
            [sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[2],
            env=dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONUTF8='1'),
            capture_output=True, text=True, encoding='utf-8', timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        samples = json.loads(result.stdout)
        self.assertGreaterEqual(len(samples), 20)
        for scheme, control, foreground, background in samples:
            with self.subTest(scheme=scheme, control=control, colors=(foreground, background)):
                self.assertGreaterEqual(contrast(foreground, background), 4.5)
