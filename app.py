import sys, os, json, shutil, subprocess
from pathlib import Path
from PIL import Image
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QRect, QUrl
from PySide6.QtGui import QImage, QPixmap, QFont, QFontMetrics, QPainter, QColor, QFontDatabase, QDesktopServices
from PySide6.QtWidgets import (QApplication, QWidget, QMainWindow, QHBoxLayout, QVBoxLayout, QFormLayout,
                               QLabel, QPushButton, QLineEdit, QComboBox, QSlider, QDoubleSpinBox,
                               QCheckBox, QTabWidget, QProgressBar, QFileDialog, QColorDialog, QMessageBox)
import core

FROZEN = getattr(sys, "frozen", False)
APP_DIR = Path(sys.executable).parent if FROZEN else Path(__file__).parent
ASSETS = APP_DIR / "assets"
SCENES = ASSETS / "scenes"
SETTINGS = APP_DIR / "settings.json"
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac"}
QUALITY = {480: (480, 854), 720: (720, 1280), 1080: (1080, 1920)}
LED_NAMES = {"bars": "Solid bars", "segments": "LED segments"}


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
    """Text is drawn with Qt so Persian shaping and right-to-left text render correctly.
    Returned image has a 6px left / 4px top margin."""
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
        self.setWindowTitle("Cassette Reels")
        self.setAcceptDrops(True)
        self.S = dict(core.DEFAULTS)
        try:
            self.S.update(json.loads(SETTINGS.read_text(encoding="utf-8")))
        except Exception:
            pass
        self.audio = ""
        self.worker = None
        self.st = None
        self.dirty = True
        self.demo = core.demo_analysis()
        self.prog = 0.0
        self.timer = QTimer(self, singleShot=True, interval=220)
        self.timer.timeout.connect(self.refresh)
        self.build_ui()
        self.refresh()

    # ---------------- UI
    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        lay = QHBoxLayout(root)
        pv = QVBoxLayout()
        self.preview = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.preview.setFixedSize(432, 768)
        pv.addWidget(self.preview)
        sl = QSlider(Qt.Orientation.Horizontal); sl.setRange(0, 100)
        sl.valueChanged.connect(lambda v: self.set_prog(v / 100))
        pv.addWidget(QLabel("Preview position (camera pan)")); pv.addWidget(sl)
        lay.addLayout(pv)
        right = QVBoxLayout()
        lay.addLayout(right, 1)
        tabs = QTabWidget()
        right.addWidget(tabs, 1)

        t1 = QWidget(); f = QFormLayout(t1); tabs.addTab(t1, "Content")
        self.btn_audio = QPushButton("Choose MP3 (or drag it into the window)")
        self.btn_audio.clicked.connect(self.pick_audio)
        f.addRow(self.btn_audio)
        self.cb_scene = QComboBox()
        for p in sorted(SCENES.glob("*.json")):
            try:
                self.cb_scene.addItem(json.loads(p.read_text(encoding="utf-8")).get("name", p.stem), p.stem)
            except Exception:
                pass
        i = self.cb_scene.findData(self.S["scene"])
        self.cb_scene.setCurrentIndex(max(0, i))
        self.cb_scene.currentIndexChanged.connect(lambda _: self.set("scene", self.cb_scene.currentData()))
        row = QHBoxLayout(); row.addWidget(self.cb_scene, 1)
        b = QPushButton("Scenes folder"); b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(SCENES)))); row.addWidget(b)
        f.addRow("Scene", row)
        self.cb_cas = QComboBox()
        self.cb_cas.addItem("Original (in the photo)", "")
        for p in sorted((ASSETS / "cassettes").glob("*.json")):
            try:
                self.cb_cas.addItem(json.loads(p.read_text(encoding="utf-8")).get("name", p.stem), p.stem)
            except Exception:
                pass
        self.cb_cas.setCurrentIndex(max(0, self.cb_cas.findData(self.S["cassette"])))
        self.cb_cas.currentIndexChanged.connect(lambda _: self.set("cassette", self.cb_cas.currentData()))
        row = QHBoxLayout(); row.addWidget(self.cb_cas, 1)
        b = QPushButton("Cassettes folder"); b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(ASSETS / "cassettes")))); row.addWidget(b)
        f.addRow("Cassette", row)
        self.ck_label = QCheckBox("Write the song name on the cassette label"); self.ck_label.setChecked(self.S["label_on"])
        self.ck_label.toggled.connect(lambda v: self.set("label_on", v))
        f.addRow(self.ck_label)
        self.ed_label = QLineEdit(self.S["label"]); self.ed_label.textChanged.connect(lambda v: self.set("label", v))
        f.addRow("Label text", self.ed_label)
        self.ck_top = QCheckBox("Replace the printed text on the player"); self.ck_top.setChecked(self.S["top_on"])
        self.ck_top.toggled.connect(lambda v: self.set("top_on", v))
        f.addRow(self.ck_top)
        for key, label in (("line1", "Big text"), ("line2", "Model line"), ("line3", "Small line")):
            e = QLineEdit(self.S[key]); e.textChanged.connect(lambda v, k=key: self.set(k, v)); f.addRow(label, e)
        self.add_file_btn(f, "font_top", "Font for player text")
        self.add_file_btn(f, "font_hand", "Handwriting font for label")

        t2 = QWidget(); f2 = QFormLayout(t2); tabs.addTab(t2, "Look")
        self.cb_led = QComboBox()
        for k in core.LED_STYLES:
            self.cb_led.addItem(LED_NAMES[k], k)
        self.cb_led.setCurrentIndex(core.LED_STYLES.index(self.S["led_style"]))
        self.cb_led.currentIndexChanged.connect(lambda _: self.set("led_style", self.cb_led.currentData()))
        f2.addRow("LED bar style", self.cb_led)
        for key, label in (("col_led", "LED color"), ("col_text", "Player text color"), ("col_ink", "Label ink color")):
            f2.addRow(label, self.color_btn(key))
        self.ck_spin = QCheckBox("Spin the reels"); self.ck_spin.setChecked(self.S["spin"])
        self.ck_spin.toggled.connect(lambda v: self.set("spin", v, static=False))
        f2.addRow(self.ck_spin)
        sp = QDoubleSpinBox(minimum=20, maximum=600, suffix=" deg/s", value=self.S["spin_speed"])
        sp.valueChanged.connect(lambda v: self.set("spin_speed", v, static=False))
        f2.addRow("Reel speed", sp)
        f2.addRow(QLabel("<b>Camera</b>"))
        f2.addRow("Zoom", self.slider("zoom", 1, 4, False))
        f2.addRow("Start X", self.slider("cx", 0, 1, False))
        f2.addRow("Vertical", self.slider("cy", 0, 1, False))
        self.ck_pan = QCheckBox("Pan during the video"); self.ck_pan.setChecked(self.S["pan"])
        self.ck_pan.toggled.connect(lambda v: self.set("pan", v, static=False))
        f2.addRow(self.ck_pan)
        f2.addRow("End X", self.slider("cx_end", 0, 1, False))
        row = QHBoxLayout()
        b1 = QPushButton("Vertical fill (zoom 2.7)"); b1.clicked.connect(lambda: self.preset(2.7))
        b2 = QPushButton("Full scene (blurred bars)"); b2.clicked.connect(lambda: self.preset(1.0))
        row.addWidget(b1); row.addWidget(b2); f2.addRow(row)

        t3 = QWidget(); f3 = QFormLayout(t3); tabs.addTab(t3, "Output")
        self.cb_q = QComboBox()
        for q, (w, h) in QUALITY.items():
            self.cb_q.addItem(f"{q}  ({w}x{h})", q)
        self.cb_q.setCurrentIndex(list(QUALITY).index(self.S["quality"]) if self.S["quality"] in QUALITY else 1)
        self.cb_q.currentIndexChanged.connect(lambda _: self.set("quality", self.cb_q.currentData(), static=False, preview=False))
        f3.addRow("Size", self.cb_q)
        s1 = QDoubleSpinBox(maximum=3600, suffix=" s", value=self.S["start"])
        s1.valueChanged.connect(lambda v: self.set("start", v, static=False, preview=False)); f3.addRow("Start at", s1)
        s2 = QDoubleSpinBox(minimum=5, maximum=180, suffix=" s", value=self.S["dur"])
        s2.valueChanged.connect(lambda v: self.set("dur", v, static=False, preview=False)); f3.addRow("Length", s2)

        self.bar = QProgressBar(); right.addWidget(self.bar)
        self.status = QLabel(""); self.status.setWordWrap(True); right.addWidget(self.status)
        row = QHBoxLayout(); right.addLayout(row)
        self.btn_go = QPushButton("Make video"); self.btn_go.setMinimumHeight(40)
        self.btn_go.clicked.connect(self.start_render); row.addWidget(self.btn_go, 1)
        self.btn_stop = QPushButton("Cancel"); self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(lambda: self.worker and setattr(self.worker, "cancel", True)); row.addWidget(self.btn_stop)

    def slider(self, key, lo, hi, static):
        w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0)
        s = QSlider(Qt.Orientation.Horizontal); s.setRange(0, 1000)
        lab = QLabel(f"{self.S[key]:.2f}"); lab.setFixedWidth(40)
        s.setValue(int((self.S[key] - lo) / (hi - lo) * 1000))
        def ch(v):
            val = lo + (hi - lo) * v / 1000
            lab.setText(f"{val:.2f}"); self.set(key, val, static=static)
        s.valueChanged.connect(ch)
        self.sliders = getattr(self, "sliders", {}); self.sliders[key] = (s, lo, hi)
        h.addWidget(s); h.addWidget(lab)
        return w

    def preset(self, z):
        s, lo, hi = self.sliders["zoom"]
        s.setValue(int((z - lo) / (hi - lo) * 1000))
        self.ck_pan.setChecked(z > 1.5)

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

    def add_file_btn(self, form, key, label):
        b = QPushButton(os.path.basename(self.S[key]) or "Choose font file...")
        def pick():
            p, _ = QFileDialog.getOpenFileName(self, label, str(ASSETS / "fonts"), "Fonts (*.ttf *.otf)")
            if p:
                self.set(key, p); b.setText(os.path.basename(p))
        b.clicked.connect(pick)
        form.addRow(label, b)

    # ---------------- logic
    def set(self, key, val, static=True, preview=True):
        self.S[key] = val
        if static:
            self.dirty = True
        if preview:
            self.timer.start()

    def set_prog(self, p):
        self.prog = p
        self.timer.start()

    def pick_audio(self):
        p, _ = QFileDialog.getOpenFileName(self, "Song", "", "Audio (*.mp3 *.wav *.m4a *.flac *.ogg *.aac)")
        if p:
            self.set_audio(p)

    def set_audio(self, p):
        self.audio = p
        self.btn_audio.setText("Song: " + os.path.basename(p))
        self.ed_label.setText(Path(p).stem.replace("_", " "))

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            if Path(u.toLocalFile()).suffix.lower() in AUDIO_EXT:
                self.set_audio(u.toLocalFile()); break

    def compose(self):
        sc = json.loads((SCENES / f"{self.S['scene']}.json").read_text(encoding="utf-8"))
        return core.compose_scene(sc, str(SCENES), self.S, text_fn,
                                  load_font(self.S["font_top"]) or "Georgia",
                                  load_font(self.S["font_hand"]) or "Ink Free", str(ASSETS / "cassettes"))

    def refresh(self):
        try:
            if self.dirty or self.st is None:
                self.st = self.compose(); self.dirty = False
            W, H = 432, 768
            img = core.render_frame(self.st, self.demo, self.S, 60, W, H, prog=self.prog)
            q = QImage(img.tobytes(), W, H, W * 3, QImage.Format.Format_RGB888).copy()
            self.preview.setPixmap(QPixmap.fromImage(q))
            self.status.setText("")
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
        self.worker.progress.connect(self.bar.setValue)
        self.worker.done.connect(self.on_done)
        self.worker.failed.connect(self.on_fail)
        self.btn_go.setEnabled(False); self.btn_stop.setEnabled(True)
        self.status.setText("Rendering... (1080 takes several minutes)")
        self.worker.start()

    def on_done(self, out):
        self.btn_go.setEnabled(True); self.btn_stop.setEnabled(False)
        self.status.setText("Done: " + out)

    def on_fail(self, msg):
        self.btn_go.setEnabled(True); self.btn_stop.setEnabled(False)
        self.status.setText("Failed: " + msg)

    def closeEvent(self, e):
        try:
            SETTINGS.write_text(json.dumps(self.S, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:
            pass
        e.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = Main()
    w.show()
    sys.exit(app.exec())
