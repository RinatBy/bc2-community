import importlib.util
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from bc2launcher.manifest import UpdateError

path=Path(__file__).resolve().parents[2]/'tools'/'test_frozen_update.py'
spec=importlib.util.spec_from_file_location('frozen_runner',path)
tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)


class RunnerTests(unittest.TestCase):
    def test_quarantine_fixture_waits_for_native_image_to_unmap(self):
        fixture = unittest.mock.Mock()
        fixture.unlink.side_effect = [PermissionError('image still mapped'), None]
        with patch.object(tool.time, 'sleep'):
            tool.remove_closed_image(fixture)
        self.assertEqual(fixture.unlink.call_count, 2)

    def test_diagnostic_runner_refuses_arbitrary_install_or_game_roots(self):
        for bad in (Path('E:/games'),Path.home(),tool.TEST_BASE,tool.TEST_BASE/'..'/'other'):
            with self.subTest(path=str(bad)),self.assertRaises(UpdateError):tool.validate_test_root(bad)
        good=tool.TEST_BASE/'isolated-case'
        self.assertEqual(tool.validate_test_root(good),good.absolute())
