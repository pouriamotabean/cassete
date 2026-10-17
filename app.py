import sys, os, json, shutil, subprocess
from pathlib import Path
from PIL import Image
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QRect, QSize
from PySide6.QtGui import QImage, QPixmap, QFont, QFontMetrics, QPainter, QColor, QFontDatabase, QIcon
from PySide6.QtWidgets import (QApplication, QWidget, QMainWindow, QHBoxLayout, QVBoxLayout, QFormLayout,
                               QLabel, QPushButton, QLineEdit, QComboBox, QDoubleSpinBox, QCheckBox,
                               QProgressBar, QFileDialog, QMessageBox, QListWidget, QListWidgetItem,
                               QToolButton, QSizePolicy, QListView)
import core

FROZEN = getattr(sys, "frozen", False)
APP_DIR = Path(sys.executable).parent if FROZEN else Path(__file__).parent
ASSETS = APP_DIR / "assets"
SCENES = ASSETS / "scenes"
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
        self.setWindowTitle("Cassette Reels")
        self.setAcceptDrops(True)
        self.setMinimumSize(760, 520)
        self.resize(1040, 700)
        self.S = dict(core.DEFAULTS)
        try:
            self.S.update(json.loads(SETTINGS.read_text(encoding="utf-8")))
        except Exception:
            pass
        self.audio = ""
        self.worker = None
        self.st = None
        self.dirty = True
        self.frame_img = None
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
    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        lay = QHBoxLayout(root)
        self.preview = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.preview.setMinimumSize(200, 355)
        lay.addWidget(self.preview, 3)
        right = QVBoxLayout()
        lay.addLayout(right, 2)

        self.btn_audio = QPushButton("1.  Choose MP3  (or drag it into the window)")
        self.btn_audio.setMinimumHeight(38)
        self.btn_audio.clicked.connect(self.pick_audio)
        right.addWidget(self.btn_audio)

        right.addWidget(QLabel("2.  Scene"))
        self.lst = QListWidget()
        self.lst.setViewMode(QListView.ViewMode.IconMode)
        self.lst.setResizeMode(QListView.ResizeMode.Adjust)
        self.lst.setMovement(QListView.Movement.Static)
        self.lst.setIconSize(QSize(78, 138))
        self.lst.setSpacing(6)
        self.lst.setWordWrap(True)
        self.lst.setUniformItemSizes(True)
        for key in self.order:
            sc = json.loads((SCENES / f"{key}.json").read_text(encoding="utf-8"))
            it = QListWidgetItem(QIcon(self.thumb(SCENES / sc["image"])), sc["name"])
            it.setData(Qt.ItemDataRole.UserRole, key)
            it.setSizeHint(QSize(100, 178))
            self.lst.addItem(it)
            if key == self.S["scene"]:
                self.lst.setCurrentItem(it)
        if self.lst.currentRow() < 0:
            self.lst.setCurrentRow(0)
        self.lst.currentItemChanged.connect(self.on_scene)
        right.addWidget(self.lst, 1)

        row = QHBoxLayout()
        row.addWidget(QLabel("3.  Size"))
        self.cb_q = QComboBox()
        for q, (w, h) in QUALITY.items():
            self.cb_q.addItem(f"{q}p   ({w}x{h})", q)
        self.cb_q.setCurrentIndex(list(QUALITY).index(self.S["quality"]) if self.S["quality"] in QUALITY else 1)
        self.cb_q.currentIndexChanged.connect(lambda _: self.S.update(quality=self.cb_q.currentData()))
        row.addWidget(self.cb_q, 1)
        right.addLayout(row)

        # گزینه‌های پیشرفته (پیش‌فرض بسته)
        self.adv_btn = QToolButton(text="Advanced", checkable=True)
        self.adv_btn.setArrowType(Qt.ArrowType.RightArrow)
        self.adv_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.adv_btn.toggled.connect(self.toggle_adv)
        right.addWidget(self.adv_btn)
        self.adv = QWidget(); f = QFormLayout(self.adv); f.setContentsMargins(0, 0, 0, 0)
        self.ed_label = QLineEdit(self.S["label"]); self.ed_label.textChanged.connect(self.on_label)
        f.addRow("Text on the tape", self.ed_label)
        self.btn_font = QPushButton(os.path.basename(self.S["font_hand"]) or "Choose handwriting font (ttf / otf)...")
        self.btn_font.clicked.connect(self.pick_font)
        f.addRow("Font", self.btn_font)
        s1 = QDoubleSpinBox(maximum=3600, suffix=" s", value=self.S["start"]); s1.valueChanged.connect(lambda v: self.S.update(start=v))
        f.addRow("Start at", s1)
        s2 = QDoubleSpinBox(minimum=5, maximum=180, suffix=" s", value=self.S["dur"]); s2.valueChanged.connect(lambda v: self.S.update(dur=v))
        f.addRow("Length", s2)
        sp = QDoubleSpinBox(minimum=20, maximum=600, suffix=" deg/s", value=self.S["spin_speed"]); sp.valueChanged.connect(lambda v: self.S.update(spin_speed=v))
        f.addRow("Reel speed", sp)
        self.adv.setVisible(False)
        right.addWidget(self.adv)

        self.bar = QProgressBar(); right.addWidget(self.bar)
        self.status = QLabel(""); self.status.setWordWrap(True); right.addWidget(self.status)
        row = QHBoxLayout(); right.addLayout(row)
        self.btn_go = QPushButton("Make video"); self.btn_go.setMinimumHeight(44)
        self.btn_go.clicked.connect(self.start_render); row.addWidget(self.btn_go, 1)
        self.btn_stop = QPushButton("Cancel"); self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(lambda: self.worker and setattr(self.worker, "cancel", True)); row.addWidget(self.btn_stop)

    def thumb(self, path):
        im = Image.open(path).convert("RGB"); im.thumbnail((156, 276))
        q = QImage(im.tobytes(), im.width, im.height, im.width * 3, QImage.Format.Format_RGB888).copy()
        return QPixmap.fromImage(q)

    def toggle_adv(self, on):
        self.adv.setVisible(on)
        self.adv_btn.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)

    # ---------------- logic
    def on_scene(self, cur, _prev):
        if cur is not None:
            self.S["scene"] = cur.data(Qt.ItemDataRole.UserRole)
            self.dirty = True
            self.debounce.start()

    def on_label(self, v):
        self.S["label"] = v
        self.dirty = True
        self.debounce.start()

    def pick_font(self):
        p, _ = QFileDialog.getOpenFileName(self, "Font", str(ASSETS / "fonts"), "Fonts (*.ttf *.otf)")
        if p:
            self.S["font_hand"] = p
            self.btn_font.setText(os.path.basename(p))
            self.dirty = True
            self.debounce.start()

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
        return core.compose_scene(sc, str(SCENES), self.S, text_fn, load_font(self.S["font_hand"]) or "Ink Free")

    def rebuild(self):
        try:
            self.st = self.compose()
            self.dirty = False
            self.status.setText("")
        except Exception as e:
            self.status.setText("Preview error: " + str(e))

    def tick(self):
        if self.st is None or self.worker is not None and self.worker.isRunning():
            return
        try:
            s = self.preview.size()
            H = max(320, min(s.height(), 960)); W = int(H * 9 / 16)
            self.fi = (self.fi + 1) % self.demo.n
            img = core.render_frame(self.st, self.demo, self.S, self.fi, W, H)
            q = QImage(img.tobytes(), W, H, W * 3, QImage.Format.Format_RGB888).copy()
            self.preview.setPixmap(QPixmap.fromImage(q).scaled(s, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
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
        self.status.setText("Rendering...")
        self.worker.start()

    def on_done(self, out):
        self.btn_go.setEnabled(True); self.btn_stop.setEnabled(False)
        self.status.setText("Done: " + out)

    def on_fail(self, msg):
        self.btn_go.setEnabled(True); self.btn_stop.setEnabled(False)
        self.status.setText("Failed: " + msg)

    def closeEvent(self, e):
        try:
            SETTINGS.write_text(json.dumps({k: self.S[k] for k in ("scene", "quality", "font_hand")}, indent=1), encoding="utf-8")
        except Exception:
            pass
        e.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = Main()
    w.show()
    sys.exit(app.exec())
