import contextlib
import io
import json
import sys
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

import run_launcher


class StartupTests(unittest.TestCase):
    def test_smoke_plugin_failure_exits_before_native_qt_dialog(self):
        from PySide6.QtCore import QtMsgType

        with patch('PySide6.QtCore.qInstallMessageHandler') as install:
            run_launcher.configure_smoke_logging()
        handler = install.call_args.args[0]
        with patch('os._exit') as stop:
            handler(QtMsgType.QtWarningMsg, SimpleNamespace(category='qt.qpa.plugin'),
                    'Could not find the Qt platform plugin "offscreen" in ""')
            stop.assert_called_once_with(78)
        with patch('os._exit') as stop:
            handler(QtMsgType.QtWarningMsg, SimpleNamespace(category='default'), 'Unrelated warning')
            stop.assert_not_called()

    def test_self_test_checks_real_qt_without_creating_application(self):
        from PySide6.QtCore import QCoreApplication

        self.assertIsNone(QCoreApplication.instance())
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / 'startup.json'
            with patch.object(sys, 'argv', ['launcher', '--self-test', '--report', str(report)]):
                with contextlib.redirect_stdout(io.StringIO()):
                    code = run_launcher.main()
            result = json.loads(report.read_text(encoding='utf-8'))
        self.assertEqual(code, 0)
        self.assertTrue(result['qt_imports_ok'])
        self.assertTrue(result['qt_version'].startswith('6.'))
        self.assertIsNone(QCoreApplication.instance())

    def test_self_test_records_native_import_failure_and_returns_nonzero(self):
        import builtins

        original_import = builtins.__import__

        def fail_qt(name, *args, **kwargs):
            if name == 'PySide6.QtCore':
                raise ImportError('DLL load failed while importing QtCore: procedure not found')
            return original_import(name, *args, **kwargs)

        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / 'startup.json'
            with patch.object(sys, 'argv', ['launcher', '--self-test', '--report', str(report)]):
                with patch('builtins.__import__', side_effect=fail_qt):
                    with contextlib.redirect_stdout(io.StringIO()):
                        code = run_launcher.main()
            result = json.loads(report.read_text(encoding='utf-8'))
        self.assertEqual(code, 1)
        self.assertFalse(result['ok'])
        self.assertEqual(result['error_type'], 'ImportError')
        self.assertIn('QtCore', result['error'])
