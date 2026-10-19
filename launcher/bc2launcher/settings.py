import json
import os
from pathlib import Path
from .manifest import UpdateError
from .transaction import atomic_write


class Settings:
    def __init__(self,path=None):
        self.path=Path(path) if path else Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData'/'Local'))/'UPLAY2'/'BC2Launcher'/'settings.json'

    def load(self):
        if not self.path.exists(): return {'highest_revision':0,'game_dir':''}
        try:
            if self.path.stat().st_size>16384: raise ValueError()
            data=json.loads(self.path.read_bytes())
            if type(data.get('highest_revision')) is not int or data['highest_revision']<0: raise ValueError()
            return data
        except (ValueError,KeyError,TypeError,OSError) as exc:
            raise UpdateError("Повреждены настройки лаунчера. Сохраните settings.json и обратитесь к администратору.") from exc

    def save(self,data):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        atomic_write(self.path,json.dumps(data,ensure_ascii=False,indent=2).encode('utf-8'))

    def remember_folder(self,folder):
        data=self.load(); data['game_dir']=str(folder); self.save(data)
