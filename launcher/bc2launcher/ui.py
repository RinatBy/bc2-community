from pathlib import Path
from PySide6.QtCore import Qt,QThread,Signal,QUrl,QTimer
from PySide6.QtGui import QPixmap,QPainter,QLinearGradient,QColor,QDesktopServices,QFontDatabase,QFont
from PySide6.QtWidgets import (QApplication,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
                              QFrame,QFileDialog,QMessageBox,QInputDialog)
from . import VERSION
from .settings import Settings
from .service import LauncherService,CheckResult
from .game import validate_game_dir
from .manifest import UpdateError
from .ui_model import controls


class Job(QThread):
    result=Signal(object)
    progress=Signal(str)
    def __init__(self,service,action):
        super().__init__(); self.service=service; self.action=action
    def run(self):
        self.service.progress=self.progress.emit
        try: self.result.emit(self.action())
        except Exception:self.result.emit(CheckResult('ERROR','Операция не завершена. Повторите проверку.'))


class Window(QWidget):
    def __init__(self,assets):
        super().__init__(); self.assets=assets; self.settings=Settings(); self.job=None; self.state='NEED_FOLDER'
        self.background=QPixmap(str(assets/'valparaiso-original.png'))
        for name in ['Oswald.ttf','Manrope.ttf']: QFontDatabase.addApplicationFont(str(assets/name))
        self.setWindowTitle('BC2 Launcher'); self.resize(1120,720); self.setMinimumSize(930,650)
        self.setStyleSheet('''
        QWidget{color:#f1f0e6;font-family:Manrope;font-size:14px}
        QLabel{background:transparent} QFrame#panel{background:rgba(16,31,24,220);border-top:2px solid #efae42}
        QPushButton{background:rgba(23,42,31,160);border:1px solid #8e9b85;padding:12px 16px;color:#efeee2}
        QPushButton:hover{background:#314434} QPushButton:disabled{color:#9a9f92;border-color:#56634f;background:rgba(25,37,29,100)}
        QPushButton#primary{background:#efae42;color:#18211e;border:0;font-weight:700}
        QPushButton#primary:disabled{background:#80714c;color:#c1c2ae} QPushButton#link{border:0;background:transparent;padding:4px;color:#efae42}
        ''')
        outer=QVBoxLayout(self); outer.setContentsMargins(42,30,42,26); outer.setSpacing(24)
        header=QHBoxLayout(); brand=QLabel('Ⅱ  BC2'); brand.setFont(QFont('Oswald',26,600)); header.addWidget(brand); header.addStretch()
        web=QPushButton('bc2.uplay2.ru ↗'); web.setObjectName('link'); web.clicked.connect(lambda:QDesktopServices.openUrl(QUrl('https://bc2.uplay2.ru/'))); header.addWidget(web); outer.addLayout(header)
        body=QHBoxLayout(); body.setSpacing(45)
        intro=QVBoxLayout(); intro.addStretch(); intro.addWidget(QLabel('BAD COMPANY 2 / СНГ'))
        title=QLabel('СНОВА\nВ СВОЕЙ\n<span style="color:#efae42">КОМПАНИИ.</span>')
        title.setTextFormat(Qt.RichText); title.setText('СНОВА<br>В СВОЕЙ<br><span style="color:#efae42">КОМПАНИИ.</span>')
        title.setStyleSheet('font-family:Oswald;font-size:62px;font-weight:600;line-height:1.05'); intro.addWidget(title)
        copy=QLabel('Знакомые карты. Своя компания.\nВыберите папку игры — остальное сделает лаунчер.'); copy.setWordWrap(True); copy.setStyleSheet('font-size:16px;line-height:1.8'); intro.addWidget(copy); intro.addStretch(); body.addLayout(intro,1)
        panel=QFrame(); panel.setObjectName('panel'); panel.setFixedWidth(430); box=QVBoxLayout(panel); box.setContentsMargins(28,30,28,30); box.setSpacing(18)
        heading=QLabel('ПОДКЛЮЧЕНИЕ К ИГРЕ'); heading.setFont(QFont('Oswald',24,500)); box.addWidget(heading)
        box.addWidget(QLabel('Папка установленной Battlefield: Bad Company 2'))
        self.folder_label=QLabel('Папка не выбрана'); self.folder_label.setWordWrap(True); self.folder_label.setTextFormat(Qt.PlainText); box.addWidget(self.folder_label)
        self.choose=QPushButton('Выбрать папку'); self.choose.clicked.connect(self.select_folder); box.addWidget(self.choose)
        self.status=QLabel('Выберите папку с BFBC2Game.exe.'); self.status.setWordWrap(True); self.status.setTextFormat(Qt.PlainText); self.status.setMinimumHeight(65); self.status.setStyleSheet('font-size:16px;color:#efe2ba'); box.addWidget(self.status)
        self.release=QLabel(''); self.release.setTextFormat(Qt.PlainText); box.addWidget(self.release)
        row=QHBoxLayout(); self.check=QPushButton('Проверить'); self.update=QPushButton('Обновить'); self.update.setObjectName('primary'); row.addWidget(self.check); row.addWidget(self.update); box.addLayout(row)
        self.play=QPushButton('ИГРАТЬ  →'); self.play.setObjectName('primary'); self.play.setFont(QFont('Oswald',20,500)); box.addWidget(self.play)
        row=QHBoxLayout(); self.rollback=QPushButton('Откатить'); self.cancel=QPushButton('Отменить'); row.addWidget(self.rollback); row.addWidget(self.cancel); box.addLayout(row)
        self.check.clicked.connect(lambda:self.work('check')); self.update.clicked.connect(lambda:self.work('update')); self.play.clicked.connect(lambda:self.work('play')); self.rollback.clicked.connect(self.select_backup); self.cancel.clicked.connect(self.cancel_job)
        body.addWidget(panel,0,Qt.AlignVCenter); outer.addLayout(body,1)
        footer=QLabel('BC2 Launcher '+VERSION+'    ·    Файлы игры и аккаунт остаются у вас'); footer.setStyleSheet('color:#c7d0be;font-size:12px'); outer.addWidget(footer)
        try:
            self.service=LauncherService((assets/'public-key.bin').read_bytes(),self.settings)
            self.folder=self.settings.load().get('game_dir','')
        except Exception:
            self.service=None; self.folder=''; self.status.setText('Не удалось прочитать настройки или ключ проверки. Переустановите лаунчер.')
        self.folder_label.setText(self.folder or 'Папка не выбрана'); self.buttons()
        if self.folder and self.service: QTimer.singleShot(0,lambda:self.work('check'))

    def paintEvent(self,event):
        p=QPainter(self)
        p.fillRect(self.rect(),QColor('#17231d'))
        if not self.background.isNull():
            image=self.background.scaled(self.size(),Qt.KeepAspectRatioByExpanding,Qt.SmoothTransformation)
            p.drawPixmap((self.width()-image.width())//2,(self.height()-image.height())//2,image)
        gradient=QLinearGradient(0,0,self.width(),0); gradient.setColorAt(0,QColor(10,22,18,235)); gradient.setColorAt(.55,QColor(10,22,18,130)); gradient.setColorAt(1,QColor(10,22,18,60)); p.fillRect(self.rect(),gradient)

    def buttons(self):
        values=controls(self.state,bool(self.folder and self.service),bool(self.job))
        for name,value in values.items():getattr(self,name).setEnabled(value)

    def select_folder(self):
        folder=QFileDialog.getExistingDirectory(self,'Выберите папку Battlefield: Bad Company 2',self.folder)
        if not folder:return
        try:
            game=validate_game_dir(Path(folder)); self.settings.remember_folder(game.root)
            self.folder=str(game.root); self.folder_label.setText(self.folder); self.work('check')
        except (UpdateError,OSError) as exc: QMessageBox.warning(self,'Папка игры',str(exc))

    def work(self,name,backup=None):
        if self.job or not self.service or not self.folder:return
        self.service.cancel.clear(); self.state='UPDATING' if name=='update' else 'CHECKING'
        self.status.setText('Проверка обновлений…' if name!='rollback' else 'Восстановление…')
        fn=lambda:getattr(self.service,name)(Path(self.folder),backup) if backup else getattr(self.service,name)(Path(self.folder))
        self.job=Job(self.service,fn); self.job.progress.connect(self.status.setText); self.job.result.connect(self.completed); self.job.finished.connect(self.finished); self.buttons(); self.job.start()

    def completed(self,result):
        self.state=result.state; self.status.setText(result.message)
        if result.release:self.release.setText('Выпуск '+result.release.package_id+' · ревизия '+str(result.release.revision))

    def finished(self):
        self.job.deleteLater(); self.job=None; self.buttons()

    def cancel_job(self):
        if self.service:self.service.cancel.set(); self.status.setText('Отмена после безопасного завершения текущего шага…')

    def select_backup(self):
        try: backups=self.service.backups(Path(self.folder))
        except (UpdateError,OSError):backups=[]
        if not backups:QMessageBox.information(self,'Откат','Резервных копий пока нет.'); return
        labels=[f'{b[1][:19]} · {b[2]} · {b[0][:8]}' for b in backups]
        item,ok=QInputDialog.getItem(self,'Восстановить файлы','Выберите копию. Перед запуском обязательная версия будет проверена снова.',labels,0,False)
        if ok:self.work('rollback',backups[labels.index(item)][0])

    def closeEvent(self,event):
        if self.job:
            self.cancel_job(); event.ignore()
        else:event.accept()


def run(assets):
    app=QApplication([]); app.setApplicationName('BC2Launcher'); app.setOrganizationName('UPLAY2')
    window=Window(assets); window.show(); return app.exec()
