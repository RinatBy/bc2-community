from pathlib import Path
from PySide6.QtCore import Qt,QThread,Signal,QUrl,QTimer,QPointF,QSize
from PySide6.QtGui import QPixmap,QPainter,QLinearGradient,QColor,QDesktopServices,QFontDatabase,QFont,QFontMetricsF,QIcon
from PySide6.QtWidgets import (QApplication,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
                              QFrame,QFileDialog,QMessageBox,QInputDialog,QSizePolicy,QDialog)
from . import VERSION
from .settings import Settings
from .service import LauncherService,CheckResult
from .game import validate_game_dir
from .manifest import UpdateError
from .ui_model import controls
from .online import fetch_online
from .selfupdate.service import AppUpdateStatus


class BrandMark(QWidget):
    def __init__(self,assets):
        super().__init__()
        self.icon=QIcon(str(assets/'brand.ico'))
        self.setFixedSize(43,48)

    def paintEvent(self,event):
        painter=QPainter(self)
        self.icon.paint(painter,self.rect(),Qt.AlignCenter)


class BrandLink(QPushButton):
    def sizeHint(self):
        # QPushButton normally sizes itself from plain text and ignores the
        # rich brand label and icon placed in its child layout.
        layout=self.layout()
        return layout.sizeHint() if layout else super().sizeHint()


class Headline(QWidget):
    # Qt rich-text uses the font's full line metrics, unlike the site's tight
    # CSS line-height. Draw the same three lines with an explicit baseline step.
    def __init__(self):
        super().__init__()
        self.display_font=QFont('Oswald')
        self.display_font.setWeight(QFont.DemiBold)
        self.display_font.setLetterSpacing(QFont.AbsoluteSpacing,-2.5)
        self.lines=('СНОВА','В СВОЕЙ','КОМПАНИИ')
        self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed)
        self.set_viewport_width(1280)

    def set_viewport_width(self,width):
        # Same clamp(60px, 5.35vw, 102px) and line-height as the website.
        pixels=round(max(60,min(102,width*.0535)))
        if self.display_font.pixelSize()==pixels:return
        self.display_font.setPixelSize(pixels)
        metrics=QFontMetricsF(self.display_font)
        self.baseline=max(-metrics.tightBoundingRect(line).top() for line in self.lines)
        self.line_step=pixels*1.025
        self.setFixedHeight(int(self.baseline+2*self.line_step+6))
        self.updateGeometry(); self.update()

    def sizeHint(self):
        metrics=QFontMetricsF(self.display_font)
        return QSize(int(max(metrics.horizontalAdvance(line) for line in self.lines))+4,self.height())

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self,event):
        painter=QPainter(self); painter.setRenderHint(QPainter.TextAntialiasing)
        painter.setFont(self.display_font)
        for index,line in enumerate(self.lines):
            painter.setPen(QColor('#eca33d' if index==2 else '#f1f0e6'))
            painter.drawText(QPointF(0,self.baseline+index*self.line_step),line)


class Job(QThread):
    result=Signal(object)
    progress=Signal(str)
    def __init__(self,service,action):
        super().__init__(); self.service=service; self.action=action
    def run(self):
        self.service.progress=self.progress.emit
        try: self.result.emit(self.action())
        except Exception:self.result.emit(CheckResult('ERROR','Операция не завершена. Повторите проверку.'))


class OnlineJob(QThread):
    result=Signal(object)

    def run(self):
        try:self.result.emit(fetch_online(cancelled=self.isInterruptionRequested))
        except Exception:self.result.emit(None)


class AppUpdateJob(QThread):
    result=Signal(object)
    progress=Signal(str)
    def __init__(self,service,action):
        super().__init__(); self.service=service; self.action=action
    def run(self):
        self.service.progress=self.progress.emit
        try:self.result.emit(self.action())
        except Exception as exc:self.result.emit(AppUpdateStatus('ERROR',False,False,str(exc)))


class Window(QWidget):
    def __init__(self,assets,*,settings=None,app_updates=None,auto_check=True):
        super().__init__(); self.assets=assets; self.settings=settings or Settings(); self.job=None; self.state='NEED_FOLDER'
        self.app_updates=app_updates; self.app_job=None; self.app_update_status=AppUpdateStatus('UNKNOWN',False,False)
        self.online_job=None; self._closing=False
        self.online_timer=QTimer(self); self.online_timer.setInterval(30000); self.online_timer.timeout.connect(self.poll_online)
        self.background=QPixmap(str(assets/'valparaiso-original.png'))
        for name in ['Oswald.ttf','Manrope.ttf']: QFontDatabase.addApplicationFont(str(assets/name))
        self.setWindowIcon(QIcon(str(assets/'brand.ico')))
        self.setWindowTitle('BC2.uplay2.ru — Лаунчер'); self.resize(1280,800); self.setMinimumSize(1120,740)
        self.setStyleSheet('''
        QWidget{color:#f1f0e6;font-family:Manrope;font-size:17px}
        QDialog{background:#1b2b23;color:#f1f0e6}
        QDialog QComboBox{background:#14221b;color:#f1f0e6;border:1px solid #63735d;padding:8px 12px}
        QDialog QComboBox:focus{border-color:#efae42}
        QComboBox QAbstractItemView{background:#1b2b23;color:#f1f0e6;border:1px solid #63735d;selection-background-color:#efae42;selection-color:#18211e;outline:0}
        QToolTip{background:#1b2b23;color:#f1f0e6;border:1px solid #63735d;padding:6px}
        QLabel{background:transparent}
        QLabel#brand{font-family:Oswald;font-size:32px;font-weight:500}
        QLabel#panel-title{font-family:Oswald;font-size:31px;font-weight:500}
        QLabel#description{font-size:18px;color:#e0e4d8}
        QLabel#account-hint{font-size:15px;color:#cbd5bd}
        QLabel#footer{font-size:14px;color:#cbd5bd}
        QLabel#online{font-size:15px;color:#cbd5bd}
        QFrame#panel{background:rgba(18,33,26,186);border-top:2px solid #efae42}
        QPushButton{background:rgba(29,44,31,105);border:1px solid rgba(228,233,211,118);padding:9px 16px;color:#eff0e3;font-weight:600}
        QPushButton:hover{background:#314434} QPushButton:disabled{color:#9a9f92;border-color:#56634f;background:rgba(25,37,29,100)}
        QPushButton#brand-link{background:transparent;border:0;padding:0}
        QPushButton#brand-link:hover{background:transparent}
        QPushButton#primary{background:#efae42;color:#18211e;border:0;font-weight:600}
        QPushButton#primary:hover{background:#ffc16a}
        QPushButton#primary:disabled{background:#80714c;color:#c1c2ae}
        QPushButton#play{font-family:Manrope;font-size:18px;font-weight:600;background:#efae42;color:#18211e;border:0;padding:12px 16px}
        QPushButton#play:hover{background:#ffc16a}
        QPushButton#play:disabled{background:#80714c;color:#c1c2ae}
        QPushButton#quiet{border:0;background:transparent;padding:4px;color:#d7dfcb;font-size:14px}
        QPushButton#quiet:hover{color:#efae42}
        QPushButton#quiet:disabled{color:#828f7d}
        ''')
        outer=QVBoxLayout(self); outer.setContentsMargins(56,30,56,24); outer.setSpacing(24)
        header=QHBoxLayout()
        brand_link=BrandLink(); brand_link.setObjectName('brand-link'); brand_link.setSizePolicy(QSizePolicy.Fixed,QSizePolicy.Fixed)
        brand_link.setCursor(Qt.PointingHandCursor); brand_link.setAccessibleName('BC2.uplay2.ru — открыть сайт')
        brand_link.clicked.connect(lambda:QDesktopServices.openUrl(QUrl('https://bc2.uplay2.ru/')))
        brand_box=QHBoxLayout(brand_link); brand_box.setContentsMargins(0,0,0,0); brand_box.setSpacing(13)
        mark=BrandMark(assets); mark.setAttribute(Qt.WA_TransparentForMouseEvents); brand_box.addWidget(mark)
        brand=QLabel('BC2<span style="color:#efae42">.uplay2.ru</span>'); brand.setObjectName('brand'); brand.setAttribute(Qt.WA_TransparentForMouseEvents); brand_box.addWidget(brand)
        header.addWidget(brand_link); header.addStretch()
        self.online=QLabel('Онлайн: —'); self.online.setObjectName('online'); self.online.setTextFormat(Qt.PlainText)
        self.online.setToolTip('Игроки на всех игровых серверах мастера'); header.addWidget(self.online); outer.addLayout(header)
        body=QHBoxLayout(); body.setSpacing(64)
        intro=QVBoxLayout(); intro.setSpacing(0); intro.addStretch()
        self.headline=Headline(); intro.addWidget(self.headline); intro.addSpacing(28)
        copy=QLabel('Площадка для СНГ игроков в\nBattlefield: Bad Company 2.'); copy.setObjectName('description'); copy.setWordWrap(True); intro.addWidget(copy)
        intro.addSpacing(16); hint=QLabel('Аккаунт создаётся в самой игре.'); hint.setObjectName('account-hint'); intro.addWidget(hint)
        intro.addStretch(); body.addLayout(intro,1)
        panel=QFrame(); panel.setObjectName('panel'); panel.setFixedWidth(430); box=QVBoxLayout(panel); box.setContentsMargins(28,24,28,24); box.setSpacing(12)
        heading=QLabel('Подключение к игре'); heading.setObjectName('panel-title'); box.addWidget(heading); box.addSpacing(3)
        box.addWidget(QLabel('Папка установленной игры'))
        self.folder_label=QLabel('Папка не выбрана'); self.folder_label.setWordWrap(True); self.folder_label.setTextFormat(Qt.PlainText); self.folder_label.setMinimumHeight(44); box.addWidget(self.folder_label)
        self.choose=QPushButton('Выбрать папку'); self.choose.clicked.connect(self.select_folder); box.addWidget(self.choose)
        self.status=QLabel('Выберите папку с BFBC2Game.exe.'); self.status.setWordWrap(True); self.status.setTextFormat(Qt.PlainText); self.status.setMinimumHeight(58); self.status.setStyleSheet('font-size:17px;color:#efe2ba'); box.addWidget(self.status)
        row=QHBoxLayout(); self.check=QPushButton('Проверить'); self.update=QPushButton('Обновить'); self.update.setObjectName('primary'); row.addWidget(self.check); row.addWidget(self.update); box.addLayout(row)
        self.play=QPushButton('ИГРАТЬ  →'); self.play.setObjectName('play'); box.addWidget(self.play)
        row=QHBoxLayout(); self.rollback=QPushButton('Откатить'); self.cancel=QPushButton('Отменить'); self.rollback.setObjectName('quiet'); self.cancel.setObjectName('quiet'); row.addWidget(self.rollback); row.addWidget(self.cancel); box.addLayout(row)
        self.rollback.setToolTip('Восстановить dinput8.dll и bfbc2.ini из выбранной резервной копии. Аккаунт и статистика не изменятся.')
        self.check.clicked.connect(lambda:self.work('check')); self.update.clicked.connect(lambda:self.work('update')); self.play.clicked.connect(lambda:self.work('play')); self.rollback.clicked.connect(self.select_backup); self.cancel.clicked.connect(self.cancel_job)
        body.addWidget(panel,0,Qt.AlignVCenter); outer.addLayout(body,1)
        footer_row=QHBoxLayout()
        footer=QLabel('Лаунчер '+VERSION); footer.setObjectName('footer'); footer_row.addWidget(footer)
        help_button=QPushButton('Помощь'); help_button.setObjectName('quiet'); help_button.clicked.connect(self.show_help)
        footer_row.addWidget(help_button)
        footer_row.addStretch()
        self.app_update_label=QLabel(); self.app_update_label.setObjectName('footer'); self.app_update_label.setTextFormat(Qt.PlainText)
        self.app_update_button=QPushButton('Обновить и перезапустить'); self.app_update_button.setObjectName('quiet')
        self.app_update_button.clicked.connect(self.app_update_action)
        footer_row.addWidget(self.app_update_label); footer_row.addWidget(self.app_update_button); outer.addLayout(footer_row)
        self.app_update_label.hide(); self.app_update_button.hide()
        try:
            self.service=LauncherService((assets/'public-key.bin').read_bytes(),self.settings,
                                        before_play=app_updates.require_play_allowed if app_updates else None)
            self.folder=self.settings.load().get('game_dir','')
        except Exception:
            self.service=None; self.folder=''; self.status.setText('Не удалось прочитать настройки или ключ проверки. Переустановите лаунчер.')
        self.folder_label.setText(self.folder or 'Папка не выбрана'); self.buttons()
        if auto_check and self.folder and self.service: QTimer.singleShot(0,lambda:self.work('check'))

    def resizeEvent(self,event):
        if hasattr(self,'headline'):self.headline.set_viewport_width(self.width())
        super().resizeEvent(event)

    def paintEvent(self,event):
        p=QPainter(self)
        p.fillRect(self.rect(),QColor('#17231d'))
        if not self.background.isNull():
            image=self.background.scaled(self.size(),Qt.KeepAspectRatioByExpanding,Qt.SmoothTransformation)
            p.drawPixmap((self.width()-image.width())//2,(self.height()-image.height())//2,image)
        gradient=QLinearGradient(0,0,self.width(),0)
        for stop,alpha in [(0,235),(.33,184),(.66,46),(1,26)]:gradient.setColorAt(stop,QColor(13,24,21,alpha))
        p.fillRect(self.rect(),gradient)
        bottom=QLinearGradient(0,self.height(),0,0); bottom.setColorAt(0,QColor(12,23,18,153)); bottom.setColorAt(.45,QColor(12,23,18,0)); p.fillRect(self.rect(),bottom)

    def buttons(self):
        values=controls(self.state,bool(self.folder and self.service),bool(self.job))
        if self._closing:values={name:False for name in values}
        if self.app_updates and not self.app_update_status.play_allowed:values['play']=False
        for name,value in values.items():getattr(self,name).setEnabled(value)
        self.app_update_button.setEnabled(not self.app_job and not self.job and not self._closing)

    def select_folder(self):
        folder=QFileDialog.getExistingDirectory(self,'Выберите папку Battlefield: Bad Company 2',self.folder)
        if not folder:return
        try:
            game=validate_game_dir(Path(folder)); self.settings.remember_folder(game.root)
            self.folder=str(game.root); self.folder_label.setText(self.folder); self.work('check')
        except (UpdateError,OSError) as exc: QMessageBox.warning(self,'Папка игры',str(exc))

    def work(self,name,backup=None):
        if self._closing or self.job or not self.service or not self.folder:return
        self.service.cancel.clear(); self.state='UPDATING' if name=='update' else 'CHECKING'
        self.status.setText('Проверка обновлений…' if name!='rollback' else 'Восстановление…')
        fn=lambda:getattr(self.service,name)(Path(self.folder),backup) if backup else getattr(self.service,name)(Path(self.folder))
        self.job=Job(self.service,fn); self.job.progress.connect(self.status.setText); self.job.result.connect(self.completed); self.job.finished.connect(self.finished); self.buttons(); self.job.start()

    def completed(self,result):
        self.state=result.state; self.status.setText(result.message)

    def finished(self):
        self.job.deleteLater(); self.job=None; self.buttons()
        if self._closing:self.close()

    def cancel_job(self):
        if self.service:self.service.cancel.set(); self.status.setText('Отмена после безопасного завершения текущего шага…')

    def start_online(self):
        self.online_timer.start(); self.poll_online()

    def poll_online(self):
        if self.online_job or self._closing:return
        self.online_job=OnlineJob(); self.online_job.result.connect(self.online_received)
        self.online_job.finished.connect(self.online_finished); self.online_job.start()

    def online_received(self,result):
        if self._closing:return
        self.online.setText('Онлайн: '+str(result.players) if result is not None else 'Онлайн: —')
        self.online.setToolTip('Суммарно на серверах: '+str(result.servers) if result is not None else 'Не удалось получить данные мастера. Повторная проверка через 30 секунд.')

    def online_finished(self):
        self.online_job.deleteLater(); self.online_job=None
        if self._closing:self.close()

    def start_app_updates(self):
        if not self.app_updates or self.app_job or self._closing:return
        self.app_update_label.setText('Проверка лаунчера…'); self.app_update_label.show()
        self._run_app_update(self.app_updates.check_and_prepare)

    def _run_app_update(self,action):
        if self.app_job or self._closing:return
        self.app_updates.cancel.clear()
        self.app_job=AppUpdateJob(self.app_updates,action)
        self.app_job.result.connect(self.app_update_received)
        self.app_job.progress.connect(self.app_update_progress)
        self.app_job.finished.connect(self.app_update_finished)
        self.buttons(); self.app_job.start()

    def app_update_progress(self,state):
        self.app_update_label.setText('Загрузка лаунчера…' if state=='DOWNLOAD' else 'Проверка новой версии…')
        self.app_update_label.show()

    def app_update_received(self,result):
        self.app_update_status=result
        messages={'UNKNOWN':'Проверка лаунчера…','CURRENT':'','AVAILABLE':'Доступно обновление лаунчера',
                  'REQUIRED':'Требуется обновление лаунчера','STAGED':'Обновление лаунчера готово',
                  'ERROR':'Не удалось проверить или обновить лаунчер','FAILED':'Новая версия не запустилась',
                  'CANCELLED':'Обновление лаунчера отменено','INSTALLER_REQUIRED':'Нужен новый установщик с сайта',
                  'RESTARTING':'Перезапуск лаунчера…'}
        self.app_update_label.setText(messages.get(result.state,'Не удалось обновить лаунчер'))
        self.app_update_label.setToolTip(result.error)
        self.app_update_label.setVisible(bool(self.app_update_label.text()))
        self.app_update_button.setText('Обновить и перезапустить' if result.restart_ready else 'Повторить проверку')
        self.app_update_button.setVisible(result.state not in ('UNKNOWN','CURRENT','RESTARTING'))
        if result.state=='INSTALLER_REQUIRED':self.app_update_button.setText('Открыть сайт')
        if result.state=='RESTARTING':self._closing=True
        self.buttons()

    def app_update_action(self):
        if not self.app_updates or self.app_job:return
        if self.app_update_status.state=='INSTALLER_REQUIRED':
            QDesktopServices.openUrl(QUrl('https://bc2.uplay2.ru/')); return
        if self.app_update_status.restart_ready:self._run_app_update(self.app_updates.request_restart)
        else:self._run_app_update(lambda:self.app_updates.prepare(manual=True))

    def app_update_finished(self):
        self.app_job.deleteLater(); self.app_job=None; self.buttons()
        if self._closing:self.close()

    def show_help(self):
        QDesktopServices.openUrl(QUrl('https://bc2.uplay2.ru/help.html'))

    def select_backup(self):
        try: backups=self.service.backups(Path(self.folder))
        except (UpdateError,OSError):backups=[]
        if not backups:QMessageBox.information(self,'Откат','Резервных копий пока нет.'); return
        labels=[f'{b[1][:19]} · {b[2]} · {b[0][:8]}' for b in backups]
        item,ok=QInputDialog.getItem(self,'Восстановить файлы подключения','Будут восстановлены dinput8.dll и bfbc2.ini.\nАккаунт и статистика не изменятся.\nПеред запуском обязательное обновление проверяется снова.\n\nВыберите резервную копию:',labels,0,False)
        if ok:self.work('rollback',backups[labels.index(item)][0])

    def closeEvent(self,event):
        self._closing=True; self.online_timer.stop()
        self.buttons()
        if self.job:self.cancel_job()
        if self.app_job:self.app_updates.cancel.set()
        if self.online_job:self.online_job.requestInterruption()
        if self.job or self.app_job or self.online_job:event.ignore()
        else:event.accept()


def configure_process_identity():
    import sys
    if sys.platform=='win32':
        import ctypes
        set_id=ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        set_id.argtypes=[ctypes.c_wchar_p]; set_id.restype=ctypes.c_long
        if set_id('uplay2.BC2Launcher')<0:raise RuntimeError('Cannot configure launcher process identity')


def run(assets,*,settings=None,app_updates=None,ready=None,smoke=False):
    configure_process_identity()
    app=QApplication([]); app.setApplicationName('BC2Launcher'); app.setOrganizationName('UPLAY2')
    app.setWindowIcon(QIcon(str(assets/'brand.ico')))
    window=Window(assets,settings=settings,app_updates=app_updates,auto_check=not smoke); window.show()
    if ready:QTimer.singleShot(0,ready)
    if smoke:QTimer.singleShot(2000,window.close)
    else:window.start_online();window.start_app_updates()
    return app.exec()
