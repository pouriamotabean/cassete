import sys, os, json, shutil, subprocess
from pathlib import Path
from PIL import Image
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QRect
from PySide6.QtGui import QImage, QPixmap, QFont, QFontMetrics, QPainter, QColor, QFontDatabase
from PySide6.QtWidgets import (QApplication, QWidget, QMainWindow, QHBoxLayout, QVBoxLayout, QFormLayout,
                               QLabel, QPushButton, QLineEdit, QComboBox, QDoubleSpinBox, QFileDialog,
                               QMessageBox, QScrollArea, QFrame)
import core
import ui

VERSION = "2.5"
FROZEN = getattr(sys, "frozen", False)
APP_DIR = Path(sys.executable).parent if FROZEN else Path(__file__).parent
ASSETS = APP_DIR / "assets"
SCENES = ASSETS / "scenes"
UI_DIR = ASSETS / "ui"
SETTINGS = APP_DIR / "settings.json"
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac"}
QUALITY = {480: (480, 854), 720: (720, 1280), 1080: (1080, 1920)}


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


def text_fn(text, family, px, color, bold=False):
    """Text is drawn with Qt so Persian shaping and right-to-left text render correctly (6px left / 4px top margin)."""
    f = QFont(family) if family else QFont()
    f.setPixelSize(max(4, int(px)))
    f.setBold(bold)
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
                raise RuntimeError("Could not read the audio, or the start time is past the end of the song.")
            dur = len(y) / core.SR
            A = core.analyze(y)
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
                    self.failed.emit("Cancelled.")
                    return
                p.stdin.write(core.render_frame(self.st, A, S, i, W, H).tobytes())
                if i % 6 == 0:
                    self.progress.emit(int(100 * i / A.n))
            p.stdin.close()
            err = p.stderr.read().decode(errors="ignore")
            p.wait()
            if p.returncode != 0:
                raise RuntimeError(err[-500:] or "ffmpeg error")
            self.progress.emit(100)
            self.done.emit(self.out)
        except Exception as e:
            self.failed.emit(str(e))


class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Cassette Reels v" + VERSION)
        self.setMinimumSize(900, 660)
        self.resize(1120, 780)
        self.S = dict(core.DEFAULTS)
        try:
            self.S.update(json.loads(SETTINGS.read_text(encoding="utf-8")))
        except Exception:
            pass
        self.audio = ""
        self.worker = None
        self.st = None
        self.fi = 0
        self.demo = core.demo_analysis()
        self.order = json.loads((SCENES / "order.json").read_text(encoding="utf-8"))
        self.build_ui()
        self.debounce = QTimer(self, singleShot=True, interval=250)
        self.debounce.timeout.connect(self.rebuild)
        self.anim = QTimer(self, interval=66)
        self.anim.timeout.connect(self.tick)
        self.rebuild()
        self.anim.start()

    # ---------------- UI
    def heading(self, num, text, right=False):
        w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(12)
        b = QLabel(str(num)); b.setObjectName("badge"); b.setFixedSize(30, 30); b.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t = QLabel(text); t.setObjectName("heading")
        h.addWidget(b); h.addWidget(t); h.addStretch(1)
        r = None
        if right:
            r = QLabel(""); r.setObjectName("headingRight"); h.addWidget(r)
        return w, r

    def divider(self):
        f = QFrame(); f.setObjectName("div"); f.setFixedHeight(1); return f

    def build_ui(self):
        self.setStyleSheet(ui.build_qss(UI_DIR))
        root = ui.Faceplate(UI_DIR, VERSION)
        self.setCentralWidget(root)
        lay = QHBoxLayout(root)
        lay.setContentsMargins(ui.WOOD + 26, ui.TOP + 8, ui.WOOD + 26, ui.BOT + 6)
        lay.setSpacing(30)
        self.bezel = ui.Bezel(UI_DIR)
        lay.addWidget(self.bezel, 5)

        right = QVBoxLayout(); right.setSpacing(10)
        lay.addLayout(right, 6)

        content = QWidget(); cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 10, 0); cl.setSpacing(9)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False); content.setAutoFillBackground(False)
        scroll.setWidget(content); self.scroll = scroll
        right.addWidget(scroll, 1)

        h1, _ = self.heading(1, "Add your MP3")
        cl.addWidget(h1)
        self.drop = ui.DropZone(UI_DIR, AUDIO_EXT)
        self.drop.browse.connect(self.pick_audio)
        self.drop.dropped.connect(self.set_audio)
        cl.addWidget(self.drop)
        cl.addWidget(self.divider())

        h2, self.scene_name = self.heading(2, "Choose your scene", right=True)
        cl.addWidget(h2)
        self.strip = ui.SceneStrip(UI_DIR)
        items = []
        for key in self.order:
            sc = json.loads((SCENES / f"{key}.json").read_text(encoding="utf-8"))
            items.append((key, sc["name"], self.thumb(SCENES / sc["image"])))
        if self.S["scene"] not in self.order:
            self.S["scene"] = self.order[0]
        self.strip.set_items(items, self.S["scene"])
        self.strip.changed.connect(self.on_scene)
        cl.addWidget(self.strip, 1)
        self.scene_name.setText(self.strip.current()[1])
        cl.addWidget(self.divider())

        h3, _ = self.heading(3, "Select output size")
        cl.addWidget(h3)
        self.cb_q = QComboBox()
        for q, (w, h) in QUALITY.items():
            self.cb_q.addItem(f"{q}p   ({w} x {h})", q)
        self.cb_q.setCurrentIndex(list(QUALITY).index(self.S["quality"]) if self.S["quality"] in QUALITY else 1)
        self.cb_q.currentIndexChanged.connect(lambda _: self.S.update(quality=self.cb_q.currentData()))
        self.cb_q.setFixedHeight(48)
        cl.addWidget(self.cb_q)

        self.adv_t = ui.AdvToggle()
        cl.addWidget(self.adv_t)
        self.adv = QWidget(); f = QFormLayout(self.adv); f.setContentsMargins(4, 0, 0, 0); f.setVerticalSpacing(10)
        def lab(t):
            l = QLabel(t); l.setObjectName("formLabel"); return l
        self.ed_label = QLineEdit(self.S["label"]); self.ed_label.textChanged.connect(self.on_label)
        f.addRow(lab("Text on the tape"), self.ed_label)
        self.btn_font = QPushButton(os.path.basename(self.S["font_hand"]) or "English handwriting font (ttf / otf)...")
        self.btn_font.setObjectName("sec"); self.btn_font.setFixedHeight(40); self.btn_font.clicked.connect(lambda: self.pick_font("font_hand", self.btn_font))
        f.addRow(lab("English font"), self.btn_font)
        self.btn_font_fa = QPushButton(os.path.basename(self.S["font_fa"]) or "Dast Nevis (built in)")
        self.btn_font_fa.setObjectName("sec"); self.btn_font_fa.setFixedHeight(40); self.btn_font_fa.clicked.connect(lambda: self.pick_font("font_fa", self.btn_font_fa))
        f.addRow(lab("Persian font"), self.btn_font_fa)
        s1 = QDoubleSpinBox(maximum=3600, suffix=" s", value=self.S["start"]); s1.valueChanged.connect(lambda v: self.S.update(start=v))
        f.addRow(lab("Start at"), s1)
        s2 = QDoubleSpinBox(minimum=5, maximum=180, suffix=" s", value=self.S["dur"]); s2.valueChanged.connect(lambda v: self.S.update(dur=v))
        f.addRow(lab("Length"), s2)
        sp = QDoubleSpinBox(minimum=20, maximum=600, suffix=" deg/s", value=self.S["spin_speed"]); sp.valueChanged.connect(lambda v: self.S.update(spin_speed=v))
        f.addRow(lab("Reel speed"), sp)
        self.adv.setVisible(False)
        self.adv_t.toggled.connect(self.on_adv)
        cl.addWidget(self.adv)

        # bottom bar: always visible
        self.status = QLabel(""); self.status.setObjectName("status"); self.status.setWordWrap(True)
        right.addWidget(self.status)
        row = QHBoxLayout(); row.setSpacing(14); right.addLayout(row)
        self.bar = ui.Progress(); row.addWidget(self.bar, 1)
        self.btn_stop = QPushButton("Cancel"); self.btn_stop.setObjectName("sec"); self.btn_stop.setFixedSize(120, 45); self.btn_stop.setVisible(False)
        self.btn_stop.clicked.connect(lambda: self.worker and setattr(self.worker, "cancel", True))
        row.addWidget(self.btn_stop)
        self.btn_go = QPushButton("Make video"); self.btn_go.setObjectName("primary"); self.btn_go.setFixedSize(259, 75)
        self.btn_go.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_go.clicked.connect(self.start_render); row.addWidget(self.btn_go)

    def on_adv(self, on):
        self.adv.setVisible(on)
        if on:
            QTimer.singleShot(60, lambda: self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum()))

    def thumb(self, path):
        im = Image.open(path).convert("RGB"); im.thumbnail((200, 356))
        q = QImage(im.tobytes(), im.width, im.height, im.width * 3, QImage.Format.Format_RGB888).copy()
        return QPixmap.fromImage(q)

    # ---------------- logic
    def on_scene(self, key):
        self.S["scene"] = key
        self.scene_name.setText(self.strip.current()[1])
        self.debounce.start()

    def on_label(self, v):
        self.S["label"] = v
        self.debounce.start()

    def pick_font(self, key, btn):
        p, _ = QFileDialog.getOpenFileName(self, "Font", str(ASSETS / "fonts"), "Fonts (*.ttf *.otf)")
        if p:
            self.S[key] = p
            btn.setText(os.path.basename(p))
            self.debounce.start()

    def pick_audio(self):
        p, _ = QFileDialog.getOpenFileName(self, "Song", "", "Audio (*.mp3 *.wav *.m4a *.flac *.ogg *.aac)")
        if p:
            self.set_audio(p)

    def set_audio(self, p):
        self.audio = p
        self.drop.set_name(os.path.basename(p))
        self.ed_label.setText(Path(p).stem.replace("_", " "))

    def compose(self):
        sc = json.loads((SCENES / f"{self.S['scene']}.json").read_text(encoding="utf-8"))
        fa = load_font(self.S["font_fa"]) or load_font(str(ASSETS / "fonts" / "danstevis.otf"))
        la = load_font(self.S["font_hand"]) or "Ink Free"
        persian = any("\u0600" <= ch <= "\u06ff" for ch in self.S["label"])
        return core.compose_scene(sc, str(SCENES), self.S, text_fn, fa if (persian and fa) else la)

    def rebuild(self):
        try:
            self.st = self.compose()
            self.status.setText("")
        except Exception as e:
            self.status.setText("Preview error: " + str(e))

    def tick(self):
        if self.st is None or (self.worker is not None and self.worker.isRunning()):
            return
        try:
            s = self.bezel.screen_rect()
            H = int(max(320, min(s.height(), 1000))); W = int(H * 9 / 16)
            self.fi = (self.fi + 1) % self.demo.n
            img = core.render_frame(self.st, self.demo, self.S, self.fi, W, H)
            q = QImage(img.tobytes(), W, H, W * 3, QImage.Format.Format_RGB888).copy()
            self.bezel.set_pixmap(QPixmap.fromImage(q))
        except Exception as e:
            self.status.setText("Preview error: " + str(e))

    def start_render(self):
        if not self.audio:
            QMessageBox.information(self, "Song", "Choose an MP3 first.")
            return
        out, _ = QFileDialog.getSaveFileName(self, "Save video", str(Path(self.audio).with_suffix("")) + "_reels.mp4", "Video (*.mp4)")
        if not out:
            return
        W, H = QUALITY[self.S["quality"]]
        try:
            st = self.compose()
        except Exception as e:
            self.status.setText("Error: " + str(e)); return
        self.worker = Worker(dict(self.S), st, W, H, self.audio, out)
        self.worker.progress.connect(self.bar.set_value)
        self.worker.done.connect(self.on_done)
        self.worker.failed.connect(self.on_fail)
        self.btn_go.setEnabled(False); self.btn_stop.setVisible(True)
        self.bar.set_value(0)
        self.status.setText("Rendering...")
        self.worker.start()

    def on_done(self, out):
        self.btn_go.setEnabled(True); self.btn_stop.setVisible(False)
        self.status.setText("Done: " + out)

    def on_fail(self, msg):
        self.btn_go.setEnabled(True); self.btn_stop.setVisible(False)
        self.status.setText("Failed: " + msg)

    def closeEvent(self, e):
        try:
            SETTINGS.write_text(json.dumps({k: self.S[k] for k in ("scene", "quality", "font_hand", "font_fa")}, indent=1), encoding="utf-8")
        except Exception:
            pass
        e.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = Main()
    w.show()
    sys.exit(app.exec())
