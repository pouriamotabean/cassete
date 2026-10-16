import sys, os, json, shutil, subprocess
from pathlib import Path
from PIL import Image
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QRect, QUrl
from PySide6.QtGui import (QImage, QPixmap, QFont, QFontMetrics, QPainter, QColor,
                           QFontDatabase, QDesktopServices)
from PySide6.QtWidgets import (QApplication, QWidget, QMainWindow, QHBoxLayout, QVBoxLayout, QFormLayout,
                               QLabel, QPushButton, QLineEdit, QComboBox, QSlider, QDoubleSpinBox,
                               QCheckBox, QTabWidget, QProgressBar, QFileDialog, QColorDialog,
                               QScrollArea, QMessageBox)
import core

FROZEN = getattr(sys, "frozen", False)
APP_DIR = Path(sys.executable).parent if FROZEN else Path(__file__).parent
ASSETS = APP_DIR / "assets"
CASS_DIR = ASSETS / "cassettes"
SETTINGS = APP_DIR / "settings.json"
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac"}
IMG_EXT = {".png", ".webp"}
STYLE_NAMES = {"bars": "میله‌های نوری", "wave": "موج‌های پشت‌سرهم", "rings": "حلقه‌های موجی",
               "circle": "اسپکتروم دایره‌ای", "dust": "ذرات نور"}
QUALITY = {480: (480, 854), 720: (720, 1280), 1080: (1080, 1920)}
SLIDERS = [
    ("کاست", [("cas_x", "جای کاست – افقی", .2, .8), ("cas_y", "جای کاست – عمودی", .15, .6), ("cas_w", "اندازه کاست", .2, .7)]),
    ("ریل‌ها", [("reel_l", "ریل چپ – افقی", .1, .5), ("reel_r", "ریل راست – افقی", .5, .9),
               ("reel_y", "ریل‌ها – عمودی", .15, .7), ("reel_s", "اندازه ریل", .03, .13)]),
    ("برچسب کاست", [("lab_x", "برچسب – چپ", 0, .4), ("lab_y", "برچسب – بالا", 0, .6),
                    ("lab_w", "برچسب – عرض", .2, 1), ("lab_h", "برچسب – ارتفاع", .05, .4)]),
    ("متن‌های بالا", [("txt_x", "جای متن – افقی", 0, .8), ("txt_y", "جای متن – عمودی", .05, .5), ("txt_s", "اندازه متن", .02, .1)]),
    ("زمین", [("fl_cx", "مرکز زمین", .3, .7), ("fl_top", "لبه دور – بالا", .4, .9), ("fl_bot", "لبه نزدیک – پایین", .6, 1),
              ("fl_tw", "نیم‌عرض لبه دور", .05, .5), ("fl_bw", "نیم‌عرض لبه نزدیک", .1, .6)]),
]


def find_ffmpeg():
    if FROZEN and (Path(sys._MEIPASS) / "ffmpeg.exe").exists():
        return str(Path(sys._MEIPASS) / "ffmpeg.exe")
    for p in (APP_DIR / "ffmpeg.exe", APP_DIR / "ffmpeg"):
        if p.exists():
            return str(p)
    return shutil.which("ffmpeg") or "ffmpeg"


FFMPEG = find_ffmpeg()
_fonts = {}


def load_font(path):
    if not path or not os.path.exists(path):
        return ""
    if path not in _fonts:
        fid = QFontDatabase.addApplicationFont(path)
        fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
        _fonts[path] = fams[0] if fams else ""
    return _fonts[path]


def text_fn(text, family, px, color):
    """متن با Qt رسم می‌شود تا فارسی درست (اتصال حروف و راست‌به‌چپ) نمایش داده شود."""
    f = QFont(family) if family else QFont()
    f.setPixelSize(max(4, int(px)))
    fm = QFontMetrics(f)
    w, h = fm.horizontalAdvance(text) + 12, fm.height() + 8
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setFont(f)
    p.setPen(QColor(color))
    p.drawText(QRect(6, 4, w - 12, h - 8), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
    p.end()
    img = img.convertToFormat(QImage.Format.Format_RGBA8888)
    return Image.frombuffer("RGBA", (w, h), bytes(img.constBits()), "raw", "RGBA", 0, 1).copy()


class Worker(QThread):
    progress = Signal(int)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, S, st, W, H, audio, out):
        super().__init__()
        self.S, self.st, self.W, self.H, self.audio, self.out = S, st, W, H, audio, out
        self.cancel = False

    def run(self):
        try:
            S, W, H = self.S, self.W, self.H
            y = core.load_audio(FFMPEG, self.audio, S["start"], S["dur"])
            if len(y) < core.SR:
                raise RuntimeError("فایل صوتی خوانده نشد یا نقطه شروع بعد از پایان آهنگ است.")
            dur = len(y) / core.SR
            A = core.analyze(y)
            viz = core.Viz(S, W, H, A)
            cmd = [FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                   "-r", str(core.FPS), "-i", "-", "-ss", str(S["start"]), "-t", str(dur), "-i", self.audio,
                   "-map", "0:v", "-map", "1:a", "-t", str(A.n / core.FPS),
                   "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                   "-c:a", "aac", "-b:a", "192k", "-af", f"afade=t=out:st={max(0, dur - 1):.2f}:d=1",
                   "-movflags", "+faststart", self.out]
            p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=core.NOWIN)
            for i in range(A.n):
                if self.cancel:
                    p.kill()
                    self.failed.emit("لغو شد.")
                    return
                p.stdin.write(core.render_frame(self.st, viz, i, spin=S["spin"]).tobytes())
                if i % 6 == 0:
                    self.progress.emit(int(100 * i / A.n))
            p.stdin.close()
            err = p.stderr.read().decode(errors="ignore")
            p.wait()
            if p.returncode != 0:
                raise RuntimeError(err[-500:] or "خطای اِف‌اف‌ام‌پگ")
            self.progress.emit(100)
            self.done.emit(self.out)
        except Exception as e:
            self.failed.emit(str(e))


class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("قاب کاست – ساخت ریلز")
        self.setAcceptDrops(True)
        self.S = dict(core.DEFAULTS)
        try:
            self.S.update(json.loads(SETTINGS.read_text(encoding="utf-8")))
        except Exception:
            pass
        self.audio = ""
        self.worker = None
        self.timer = QTimer(self, singleShot=True, interval=140)
        self.timer.timeout.connect(self.refresh)
        self.build_ui()
        self.refresh()

    # ---------------- رابط
    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        lay = QHBoxLayout(root)
        self.preview = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.preview.setFixedSize(432, 768)
        lay.addWidget(self.preview)
        right = QVBoxLayout()
        lay.addLayout(right, 1)
        tabs = QTabWidget()
        right.addWidget(tabs, 1)

        # تب محتوا
        t1 = QWidget(); f = QFormLayout(t1); tabs.addTab(t1, "محتوا")
        self.btn_audio = QPushButton("انتخاب ام‌پی‌تری (یا بکشید و رها کنید)")
        self.btn_audio.clicked.connect(self.pick_audio)
        f.addRow(self.btn_audio)
        for key, label in (("line1", "متن بزرگ (برند)"), ("line2", "خط مدل"), ("line3", "خط ریز"), ("label", "نام آهنگ روی کاست")):
            e = QLineEdit(self.S[key])
            e.textChanged.connect(lambda v, k=key: self.set(k, v))
            if key == "label":
                self.ed_label = e
            f.addRow(label, e)
        self.add_file_btn(f, "font_top", "فونت متن‌های بالا", "فونت (*.ttf *.otf)")
        self.add_file_btn(f, "font_hand", "فونت دست‌نویس برچسب", "فونت (*.ttf *.otf)")
        for key, label in (("col_text", "رنگ متن‌های بالا"), ("col_ink", "رنگ جوهر برچسب"), ("col_viz", "رنگ نور زمین")):
            f.addRow(label, self.color_btn(key))
        self.cb_cas = QComboBox()
        self.fill_cassettes()
        self.cb_cas.currentIndexChanged.connect(self.on_cassette)
        row = QHBoxLayout(); row.addWidget(self.cb_cas, 1)
        b = QPushButton("پوشه کاست‌ها"); b.clicked.connect(self.open_cass_dir); row.addWidget(b)
        b2 = QPushButton("بازخوانی"); b2.clicked.connect(self.fill_cassettes); row.addWidget(b2)
        f.addRow("مدل کاست", row)
        self.cb_style = QComboBox()
        for k in core.STYLES:
            self.cb_style.addItem(STYLE_NAMES[k], k)
        self.cb_style.setCurrentIndex(max(0, core.STYLES.index(self.S["style"])))
        self.cb_style.currentIndexChanged.connect(lambda _: self.set("style", self.cb_style.currentData()))
        f.addRow("طرح نور روی زمین", self.cb_style)

        # تب خروجی
        t2 = QWidget(); f2 = QFormLayout(t2); tabs.addTab(t2, "خروجی")
        self.cb_q = QComboBox()
        for q, (w, h) in QUALITY.items():
            self.cb_q.addItem(f"{q}  ({w}×{h})", q)
        self.cb_q.setCurrentIndex(list(QUALITY).index(self.S["quality"]) if self.S["quality"] in QUALITY else 1)
        self.cb_q.currentIndexChanged.connect(lambda _: self.set("quality", self.cb_q.currentData(), False))
        f2.addRow("کیفیت", self.cb_q)
        self.sp_start = QDoubleSpinBox(maximum=3600, suffix=" ثانیه", value=self.S["start"])
        self.sp_start.valueChanged.connect(lambda v: self.set("start", v, False))
        f2.addRow("شروع از", self.sp_start)
        self.sp_dur = QDoubleSpinBox(minimum=5, maximum=180, suffix=" ثانیه", value=self.S["dur"])
        self.sp_dur.valueChanged.connect(lambda v: self.set("dur", v, False))
        f2.addRow("مدت ویدیو", self.sp_dur)
        self.ck_spin = QCheckBox("چرخش ریل‌ها"); self.ck_spin.setChecked(self.S["spin"])
        self.ck_spin.toggled.connect(lambda v: self.set("spin", v))
        f2.addRow(self.ck_spin)

        # تب چیدمان
        t3 = QWidget(); f3 = QFormLayout(t3)
        sc = QScrollArea(widgetResizable=True); sc.setWidget(t3); tabs.addTab(sc, "چیدمان")
        for grp, items in SLIDERS:
            f3.addRow(QLabel(f"<b>{grp}</b>"))
            for key, label, lo, hi in items:
                f3.addRow(label, self.slider(key, lo, hi))
        reset = QPushButton("بازگشت چیدمان به پیش‌فرض"); reset.clicked.connect(self.reset_layout)
        f3.addRow(reset)

        self.bar = QProgressBar(); right.addWidget(self.bar)
        self.status = QLabel(""); self.status.setWordWrap(True); right.addWidget(self.status)
        row = QHBoxLayout(); right.addLayout(row)
        self.btn_go = QPushButton("ساخت ویدیو"); self.btn_go.setMinimumHeight(40)
        self.btn_go.clicked.connect(self.start_render); row.addWidget(self.btn_go, 1)
        self.btn_stop = QPushButton("لغو"); self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(lambda: self.worker and setattr(self.worker, "cancel", True)); row.addWidget(self.btn_stop)

    def slider(self, key, lo, hi):
        w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0)
        s = QSlider(Qt.Orientation.Horizontal); s.setRange(0, 1000)
        lab = QLabel(f"{self.S[key]:.3f}"); lab.setFixedWidth(46)
        s.setValue(int((self.S[key] - lo) / (hi - lo) * 1000))
        def ch(v, key=key, lo=lo, hi=hi, lab=lab):
            val = lo + (hi - lo) * v / 1000
            lab.setText(f"{val:.3f}"); self.set(key, val)
        s.valueChanged.connect(ch)
        h.addWidget(s); h.addWidget(lab)
        self.sliders = getattr(self, "sliders", {}); self.sliders[key] = (s, lo, hi)
        return w

    def reset_layout(self):
        for grp, items in SLIDERS:
            for key, _, lo, hi in items:
                s = self.sliders[key][0]
                s.setValue(int((core.DEFAULTS[key] - lo) / (hi - lo) * 1000))

    def color_btn(self, key):
        b = QPushButton(self.S[key])
        def paint():
            b.setText(self.S[key]); b.setStyleSheet(f"background:{self.S[key]};color:#fff;padding:4px")
        def pick():
            c = QColorDialog.getColor(QColor(self.S[key]), self)
            if c.isValid():
                self.set(key, c.name()); paint()
        b.clicked.connect(pick); paint()
        return b

    def add_file_btn(self, form, key, label, flt):
        b = QPushButton(os.path.basename(self.S[key]) or "انتخاب فایل فونت…")
        def pick():
            p, _ = QFileDialog.getOpenFileName(self, label, str(ASSETS / "fonts"), flt)
            if p:
                self.set(key, p); b.setText(os.path.basename(p))
        b.clicked.connect(pick)
        form.addRow(label, b)

    # ---------------- منطق
    def set(self, key, val, preview=True):
        self.S[key] = val
        if preview:
            self.timer.start()

    def fill_cassettes(self):
        self.cb_cas.blockSignals(True)
        self.cb_cas.clear()
        self.cb_cas.addItem("کاست پیش‌فرض (ساده)", "")
        CASS_DIR.mkdir(parents=True, exist_ok=True)
        for p in sorted(CASS_DIR.iterdir()):
            if p.suffix.lower() in IMG_EXT:
                self.cb_cas.addItem(p.stem, str(p))
        i = self.cb_cas.findData(self.S["cassette"])
        self.cb_cas.setCurrentIndex(max(0, i))
        self.cb_cas.blockSignals(False)

    def on_cassette(self, _):
        self.set("cassette", self.cb_cas.currentData())

    def open_cass_dir(self):
        CASS_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(CASS_DIR)))

    def pick_audio(self):
        p, _ = QFileDialog.getOpenFileName(self, "آهنگ", "", "فایل صوتی (*.mp3 *.wav *.m4a *.flac *.ogg *.aac)")
        if p:
            self.set_audio(p)

    def set_audio(self, p):
        self.audio = p
        self.btn_audio.setText("آهنگ: " + os.path.basename(p))
        self.ed_label.setText(Path(p).stem.replace("_", " "))

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            if Path(u.toLocalFile()).suffix.lower() in AUDIO_EXT:
                self.set_audio(u.toLocalFile()); break

    def assets(self):
        fr = next((str(p) for ext in (".png", ".jpg", ".jpeg", ".webp") for p in [ASSETS / f"frame{ext}"] if p.exists()), None)
        return dict(frame=fr, cassette=self.S["cassette"] or None,
                    fam_top=load_font(self.S["font_top"]) or "Segoe UI",
                    fam_hand=load_font(self.S["font_hand"]) or "Ink Free")

    def refresh(self):
        W, H = 432, 768
        try:
            st = core.compose_static(self.S, W, H, text_fn, self.assets())
            img = core.render_frame(st, core.Viz(self.S, W, H, core.demo_analysis()), 60, spin=self.S["spin"])
            q = QImage(img.tobytes(), W, H, W * 3, QImage.Format.Format_RGB888).copy()
            self.preview.setPixmap(QPixmap.fromImage(q))
        except Exception as e:
            self.status.setText("خطا در پیش‌نمایش: " + str(e))

    def start_render(self):
        if not self.audio:
            QMessageBox.information(self, "آهنگ", "اول یه ام‌پی‌تری انتخاب کن.")
            return
        out, _ = QFileDialog.getSaveFileName(self, "ذخیره ویدیو", str(Path(self.audio).with_suffix("")) + "_reels.mp4", "ویدیو (*.mp4)")
        if not out:
            return
        W, H = QUALITY[self.S["quality"]]
        st = core.compose_static(self.S, W, H, text_fn, self.assets())
        self.worker = Worker(dict(self.S), st, W, H, self.audio, out)
        self.worker.progress.connect(self.bar.setValue)
        self.worker.done.connect(self.on_done)
        self.worker.failed.connect(self.on_fail)
        self.btn_go.setEnabled(False); self.btn_stop.setEnabled(True)
        self.status.setText("در حال ساخت… (برای ۱۰۸۰ چند دقیقه طول می‌کشد)")
        self.worker.start()

    def on_done(self, out):
        self.btn_go.setEnabled(True); self.btn_stop.setEnabled(False)
        self.status.setText("تمام شد: " + out)

    def on_fail(self, msg):
        self.btn_go.setEnabled(True); self.btn_stop.setEnabled(False)
        self.status.setText("ناموفق: " + msg)

    def closeEvent(self, e):
        try:
            SETTINGS.write_text(json.dumps(self.S, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:
            pass
        e.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    w = Main()
    w.show()
    sys.exit(app.exec())
