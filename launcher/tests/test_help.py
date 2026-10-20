import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

root=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('build_help',root/'tools'/'build_help.py')
tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)


class HelpTests(unittest.TestCase):
    def test_shared_source_builds_offline_asset_and_escaped_website(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);source=base/'help.md'
            source.write_text('# Help\n\n## A <script> question\n\nUse **x86** and [Microsoft](https://www.microsoft.com/test).\n',encoding='utf-8')
            tool.build_help(source,base/'help.html',base/'assets'/'FAQ_RU.md')
            self.assertEqual((base/'assets'/'FAQ_RU.md').read_bytes(),source.read_bytes())
            html=(base/'help.html').read_text(encoding='utf-8')
            self.assertIn('&lt;script&gt;',html);self.assertNotIn('<script>',html)
            self.assertIn('href="https://www.microsoft.com/test"',html)
            self.assertIn('<strong>x86</strong>',html)

    def test_launcher_help_opens_website_without_dialog(self):
        code='''
import json,tempfile
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QPushButton
from bc2launcher.ui import Window
class Settings:
 def load(self):return {'game_dir':''}
app=QApplication([])
with tempfile.TemporaryDirectory() as folder:
 assets=Path(folder)
 w=Window(assets,settings=Settings(),auto_check=False)
 with patch('bc2launcher.ui.QDesktopServices.openUrl',return_value=True) as opened, patch('bc2launcher.ui.QDialog.exec') as modal:
  button=next(b for b in w.findChildren(QPushButton) if b.text()=='Помощь')
  button.click()
  result={'urls':[call.args[0].toString() for call in opened.call_args_list],'modal_calls':modal.call_count}
 print(json.dumps(result))
'''
        result=subprocess.run([sys.executable,'-c',code],cwd=root,
                              env=dict(os.environ,QT_QPA_PLATFORM='offscreen',PYTHONUTF8='1'),
                              capture_output=True,text=True,encoding='utf-8',timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        values=json.loads(result.stdout)
        self.assertEqual(values['urls'],['https://bc2.uplay2.ru/help.html'])
        self.assertEqual(values['modal_calls'],0)
