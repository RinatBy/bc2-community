import unittest
from bc2launcher.ui_model import controls


class UiModelTests(unittest.TestCase):
    def test_play_only_ready(self):
        for state in ['NEED_FOLDER','CHECKING','UPDATE_REQUIRED','UPDATING','ERROR','RECOVERY_REQUIRED']:
            self.assertFalse(controls(state,True,False)['play'])
        self.assertTrue(controls('READY',True,False)['play'])

    def test_busy_and_no_folder(self):
        for b in ['check','update','play','rollback','choose']:
            self.assertFalse(controls('READY',True,True)[b])
        self.assertTrue(controls('READY',True,True)['cancel'])
        self.assertFalse(controls('READY',False,False)['play'])
