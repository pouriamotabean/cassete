"""Custom-drawn widgets and skin for Cassette Reels: matte graphite faceplate, walnut sides, amber indicators."""
import math
from pathlib import Path

from PySide6.QtCore import Qt, QRectF, QPointF, QRect, Signal
from PySide6.QtGui import (QPainter, QPixmap, QColor, QPen, QBrush, QLinearGradient, QRadialGradient,
                           QPainterPath, QFont)
from PySide6.QtWidgets import QWidget

AMBER = QColor("#e8a54b")
AMBER_DIM = QColor("#8d6f43")
TEXT = QColor("#cfcfcf")
TEXT_DIM = QColor("#8a8a8a")

WOOD, TOP, BOT = 38, 44, 34

_cache = {}


def pm(ui_dir, name):
    key = (str(ui_dir), name)
    if key not in _cache:
        _cache[key] = QPixmap(str(Path(ui_dir) / name))
    return _cache[key]


def nine(p, pix, rect, sl):
    """Draw pix into rect as a 9-slice; sl = (left, top, right, bottom) in source pixels."""
    rect = QRectF(rect)
    w, h = pix.width(), pix.height()
    l, t, r, b = sl
    k = min(1.0, rect.width() / (l + r + 1), rect.height() / (t + b + 1))
    dl, dt, dr, db = l * k, t * k, r * k, b * k
    X = [0, l, w - r, w]
    Y = [0, t, h - b, h]
    DX = [rect.left(), rect.left() + dl, rect.right() - dr, rect.right()]
    DY = [rect.top(), rect.top() + dt, rect.bottom() - db, rect.bottom()]
    for i in range(3):
        for j in range(3):
            src = QRectF(X[i], Y[j], X[i + 1] - X[i], Y[j + 1] - Y[j])
            dst = QRectF(DX[i], DY[j], DX[i + 1] - DX[i], DY[j + 1] - DY[j])
            if src.width() > 0 and src.height() > 0 and dst.width() > 0 and dst.height() > 0:
                p.drawPixmap(dst, pix, src)


def cassette_icon(p, rect, color, lw=1.4):
    rect = QRectF(rect)
    p.save()
    p.setPen(QPen(color, lw))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(rect, rect.height() * .12, rect.height() * .12)
    win = QRectF(rect.left() + rect.width() * .14, rect.top() + rect.height() * .22, rect.width() * .72, rect.height() * .36)
    p.drawRoundedRect(win, win.height() * .5, win.height() * .5)
    r = win.height() * .30
    for cx in (win.left() + win.width() * .27, win.right() - win.width() * .27):
        p.drawEllipse(QPointF(cx, win.center().y()), r, r)
    y = rect.bottom() - rect.height() * .14
    p.drawLine(QPointF(rect.left() + rect.width() * .30, y), QPointF(rect.right() - rect.width() * .30, y))
    p.restore()


def screw(p, c, r=6.5):
    g = QRadialGradient(QPointF(c.x() - r * .3, c.y() - r * .3), r * 1.4)
    g.setColorAt(0, QColor("#7a7a7c"))
    g.setColorAt(1, QColor("#1d1d1f"))
    p.setPen(QPen(QColor("#0a0a0a"), 1))
    p.setBrush(QBrush(g))
    p.drawEllipse(c, r, r)
    p.setPen(QPen(QColor("#101010"), 1.6))
    a = math.radians(32)
    dx, dy = math.cos(a) * r * .65, math.sin(a) * r * .65
    p.drawLine(QPointF(c.x() - dx, c.y() - dy), QPointF(c.x() + dx, c.y() + dy))


class Faceplate(QWidget):
    def __init__(self, ui_dir, version):
        super().__init__()
        self.ui = ui_dir
        self.version = version

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        p.drawTiledPixmap(self.rect(), pm(self.ui, "tex.png"))
        # soft vignette
        v = QRadialGradient(QPointF(w / 2, h / 2), max(w, h) * .75)
        v.setColorAt(0, QColor(0, 0, 0, 0))
        v.setColorAt(1, QColor(0, 0, 0, 110))
        p.fillRect(self.rect(), QBrush(v))
        # walnut sides
        for x, name in ((0, "wood_l.png"), (w - WOOD, "wood_r.png")):
            p.drawPixmap(QRect(x, 0, WOOD, h), pm(self.ui, name))
            g = QLinearGradient(x, 0, x + WOOD, 0)
            if x == 0:
                g.setColorAt(0, QColor(0, 0, 0, 20)); g.setColorAt(.8, QColor(0, 0, 0, 0)); g.setColorAt(1, QColor(0, 0, 0, 150))
            else:
                g.setColorAt(0, QColor(0, 0, 0, 150)); g.setColorAt(.2, QColor(0, 0, 0, 0)); g.setColorAt(1, QColor(0, 0, 0, 20))
            p.fillRect(QRect(x, 0, WOOD, h), QBrush(g))
        for x in (WOOD / 2, w - WOOD / 2):
            screw(p, QPointF(x, 20))
            screw(p, QPointF(x, h - 20))
        # inset panel
        r = QRectF(WOOD + 8, TOP - 8, w - 2 * (WOOD + 8), h - TOP - BOT + 10)
        p.setBrush(QColor(0, 0, 0, 38))
        p.setPen(QPen(QColor("#080808"), 2))
        p.drawRoundedRect(r, 14, 14)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 16), 1))
        p.drawRoundedRect(r.adjusted(1.5, 1.5, -1.5, -1.5), 13, 13)
        # header
        f = QFont(self.font()); f.setPixelSize(12); f.setWeight(QFont.Weight.DemiBold)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 4)
        p.setFont(f)
        p.setPen(AMBER)
        title = "CASSETTE REELS"
        tw = p.fontMetrics().horizontalAdvance(title)
        cx = w / 2
        p.drawText(QPointF(cx - tw / 2 + 12, 25), title)
        cassette_icon(p, QRectF(cx - tw / 2 - 20, 12, 26, 17), AMBER, 1.2)
        f2 = QFont(f); f2.setPixelSize(11); f2.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1)
        p.setFont(f2)
        p.setPen(AMBER_DIM)
        t2 = "v" + self.version
        p.drawText(QPointF(w - WOOD - 20 - p.fontMetrics().horizontalAdvance(t2), 25), t2)
        # footer credit
        f3 = QFont(self.font()); f3.setPixelSize(10); f3.setWeight(QFont.Weight.DemiBold)
        f3.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3.2)
        p.setFont(f3)
        p.setPen(AMBER_DIM)
        t3 = "BY POURIA MOTABEAN"
        p.drawText(QPointF(cx - p.fontMetrics().horizontalAdvance(t3) / 2, h - BOT / 2 + 4), t3)


class Bezel(QWidget):
    INSET = 17

    def __init__(self, ui_dir):
        super().__init__()
        self.ui = ui_dir
        self.pix = None
        self.setMinimumSize(250, 420)

    def screen_rect(self):
        a = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        iw, ih = a.width() - 2 * self.INSET, a.height() - 2 * self.INSET
        h = max(10, min(ih, iw * 16 / 9))
        w = h * 9 / 16
        return QRectF(a.center().x() - w / 2, a.center().y() - h / 2, w, h)

    def set_pixmap(self, pix):
        self.pix = pix
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        s = self.screen_rect()
        p.fillRect(s, QColor("#050505"))
        if self.pix is not None:
            path = QPainterPath(); path.addRoundedRect(s, 18, 18)
            p.save(); p.setClipPath(path)
            p.drawPixmap(s, self.pix, QRectF(self.pix.rect()))
            p.restore()
        nine(p, pm(self.ui, "bezel.png"), s.adjusted(-self.INSET, -self.INSET, self.INSET, self.INSET), (44, 44, 44, 44))


class DropZone(QWidget):
    browse = Signal()
    dropped = Signal(str)

    def __init__(self, ui_dir, exts):
        super().__init__()
        self.ui, self.exts = ui_dir, exts
        self.setAcceptDrops(True)
        self.setMinimumHeight(98)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hover = self.drag = False
        self.name = ""

    def set_name(self, n):
        self.name = n
        self.update()

    def enterEvent(self, e): self.hover = True; self.update()
    def leaveEvent(self, e): self.hover = False; self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.browse.emit()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(Path(u.toLocalFile()).suffix.lower() in self.exts for u in e.mimeData().urls()):
            self.drag = True; self.update(); e.acceptProposedAction()

    def dragLeaveEvent(self, e): self.drag = False; self.update()

    def dropEvent(self, e):
        self.drag = False; self.update()
        for u in e.mimeData().urls():
            if Path(u.toLocalFile()).suffix.lower() in self.exts:
                self.dropped.emit(u.toLocalFile()); break

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        hot = self.hover or self.drag
        nine(p, pm(self.ui, "drop_h.png" if hot else "drop_n.png"), self.rect(), (28, 28, 28, 28))
        cx, cy = self.width() / 2, self.height() / 2
        cassette_icon(p, QRectF(cx - 24, cy - 32, 48, 31), AMBER if (hot or self.name) else AMBER_DIM, 1.5)
        f = QFont(self.font()); f.setPixelSize(13)
        p.setFont(f)
        if self.name:
            f.setWeight(QFont.Weight.DemiBold); p.setFont(f)
            p.setPen(QColor("#f0c27a"))
            txt = p.fontMetrics().elidedText(self.name, Qt.TextElideMode.ElideMiddle, int(self.width() - 80))
            p.drawText(QRectF(0, cy + 2, self.width(), 22), Qt.AlignmentFlag.AlignCenter, txt)
            f.setPixelSize(11); f.setWeight(QFont.Weight.Normal); p.setFont(f)
            p.setPen(TEXT_DIM)
            p.drawText(QRectF(0, cy + 22, self.width(), 18), Qt.AlignmentFlag.AlignCenter, "click or drop to change")
        else:
            p.setPen(TEXT_DIM)
            p.drawText(QRectF(0, cy + 4, self.width(), 24), Qt.AlignmentFlag.AlignCenter, "Drop your MP3 here  (or click to browse)")


class SceneStrip(QWidget):
    changed = Signal(str)
    CW, CH, GAP, ARW = 80, 142, 12, 38

    def __init__(self, ui_dir):
        super().__init__()
        self.ui = ui_dir
        self.items = []      # (key, name, QPixmap)
        self.sel = 0
        self.off = 0
        self.hover = -1
        self.setMouseTracking(True)
        self.setFixedHeight(self.CH + 18)

    def set_items(self, items, current):
        self.items = items
        self.sel = next((i for i, it in enumerate(items) if it[0] == current), 0)
        self.fit()
        self.update()

    def current(self):
        return self.items[self.sel] if self.items else None

    def n_vis(self):
        return max(1, int((self.width() - 2 * self.ARW) // (self.CW + self.GAP)))

    def fit(self):
        n = self.n_vis()
        if self.sel < self.off: self.off = self.sel
        if self.sel >= self.off + n: self.off = self.sel - n + 1
        self.off = max(0, min(self.off, max(0, len(self.items) - n)))

    def resizeEvent(self, e):
        self.fit()

    def card_rect(self, i):
        n = self.n_vis()
        total = n * (self.CW + self.GAP) - self.GAP
        x0 = (self.width() - total) / 2
        return QRectF(x0 + (i - self.off) * (self.CW + self.GAP), 9, self.CW, self.CH)

    def arrow_rect(self, side):
        return QRectF(2 if side < 0 else self.width() - self.ARW + 4, self.height() / 2 - 15, 30, 30)

    def hit(self, pos):
        for i in range(self.off, min(len(self.items), self.off + self.n_vis())):
            if self.card_rect(i).contains(pos):
                return i
        return -1

    def mouseMoveEvent(self, e):
        h = self.hit(e.position())
        if h != self.hover:
            self.hover = h; self.update()
            self.setToolTip(self.items[h][1] if h >= 0 else "")

    def leaveEvent(self, e): self.hover = -1; self.update()

    def mousePressEvent(self, e):
        pos = e.position()
        if self.arrow_rect(-1).contains(pos): self.scroll(-1); return
        if self.arrow_rect(1).contains(pos): self.scroll(1); return
        h = self.hit(pos)
        if h >= 0 and h != self.sel:
            self.sel = h; self.update(); self.changed.emit(self.items[h][0])

    def wheelEvent(self, e):
        self.scroll(-1 if e.angleDelta().y() > 0 else 1)

    def scroll(self, d):
        self.off = max(0, min(self.off + d, max(0, len(self.items) - self.n_vis())))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        n = self.n_vis()
        for side in (-1, 1):
            r = self.arrow_rect(side)
            on = (self.off > 0) if side < 0 else (self.off + n < len(self.items))
            g = QLinearGradient(r.topLeft(), r.bottomLeft())
            g.setColorAt(0, QColor("#2a2a2a")); g.setColorAt(1, QColor("#161616"))
            p.setBrush(QBrush(g)); p.setPen(QPen(QColor("#0a0a0a"), 1.5))
            p.drawEllipse(r)
            p.setPen(QPen(AMBER if on else QColor("#4a4a4a"), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            c = r.center(); d = 4.5 * side
            p.drawPolyline([QPointF(c.x() - d * .6, c.y() - 6), QPointF(c.x() + d * .6, c.y()), QPointF(c.x() - d * .6, c.y() + 6)])
        for i in range(self.off, min(len(self.items), self.off + n)):
            r = self.card_rect(i)
            inner = r.adjusted(5, 5, -5, -5)
            pix = self.items[i][2]
            path = QPainterPath(); path.addRoundedRect(inner, 9, 9)
            p.save(); p.setClipPath(path)
            k = max(inner.width() / pix.width(), inner.height() / pix.height())
            sw, sh = inner.width() / k, inner.height() / k
            src = QRectF((pix.width() - sw) / 2, (pix.height() - sh) / 2, sw, sh)
            p.drawPixmap(inner, pix, src)
            if i != self.sel:
                p.fillRect(inner, QColor(0, 0, 0, 70 if i != self.hover else 20))
            p.restore()
            nine(p, pm(self.ui, "card.png"), r, (18, 18, 18, 18))
            if i == self.sel:
                for w_, a in ((7, 28), (4.5, 60), (2.4, 255)):
                    p.setPen(QPen(QColor(232, 165, 75, a), w_)); p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRoundedRect(r.adjusted(2, 2, -2, -2), 11, 11)


class Progress(QWidget):
    def __init__(self):
        super().__init__()
        self.value = 0
        self.setFixedHeight(18)

    def set_value(self, v):
        self.value = max(0, min(100, v)); self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(1, 3, self.width() - 2, 12)
        p.setBrush(QColor("#0b0b0b")); p.setPen(QPen(QColor("#2b2b2b"), 1.2))
        p.drawRoundedRect(r, 6, 6)
        p.setPen(QPen(QColor(0, 0, 0, 160), 1))
        p.drawLine(QPointF(r.left() + 6, r.top() + 1.5), QPointF(r.right() - 6, r.top() + 1.5))
        w = (r.width() - 4) * self.value / 100
        if w > 3:
            f = QRectF(r.left() + 2, r.top() + 2, w, r.height() - 4)
            for gw, a in ((6, 22), (3, 40)):
                p.setPen(QPen(QColor(232, 165, 75, a), gw)); p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(f, 4, 4)
            g = QLinearGradient(f.topLeft(), f.bottomLeft())
            g.setColorAt(0, QColor("#ffc766")); g.setColorAt(1, QColor("#dd8a22"))
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(g))
            p.drawRoundedRect(f, 4, 4)


class AdvToggle(QWidget):
    toggled = Signal(bool)

    def __init__(self):
        super().__init__()
        self.on = False
        self.setFixedHeight(32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, e):
        self.on = not self.on; self.update(); self.toggled.emit(self.on)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(QPen(QColor("#262626"), 1))
        p.drawLine(0, 8, w, 8)
        tw, th = 138, 26
        x0 = (w - tw) / 2
        path = QPainterPath()
        path.moveTo(x0 - 14, 8); path.cubicTo(x0 - 4, 8, x0 - 6, 8 + th, x0 + 8, 8 + th)
        path.lineTo(x0 + tw - 8, 8 + th); path.cubicTo(x0 + tw + 6, 8 + th, x0 + tw + 4, 8, x0 + tw + 14, 8)
        path.closeSubpath()
        g = QLinearGradient(0, 8, 0, 8 + th); g.setColorAt(0, QColor("#1a1a1a")); g.setColorAt(1, QColor("#121212"))
        p.setBrush(QBrush(g)); p.setPen(QPen(QColor("#2e2e2e"), 1))
        p.drawPath(path)
        p.setPen(QPen(AMBER, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        cx, cy = x0 + 28, 8 + th / 2 + 1
        d = -3 if self.on else 3
        p.drawPolyline([QPointF(cx - 5, cy - d / 1.0 * .8), QPointF(cx, cy + d * .8), QPointF(cx + 5, cy - d * .8)])
        f = QFont(self.font()); f.setPixelSize(12); p.setFont(f)
        p.setPen(TEXT)
        p.drawText(QRectF(x0 + 40, 8, tw - 44, th), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "Advanced")


def build_qss(ui_dir):
    u = Path(ui_dir).as_posix()
    return f"""
* {{ color:#cfcfcf; font-family:'Segoe UI','Inter','Helvetica Neue',sans-serif; font-size:13px; }}
QToolTip {{ background:#141414; color:#f0c27a; border:1px solid #3a3a3a; padding:4px 8px; }}
QLabel {{ background:transparent; }}
QLabel#heading {{ font-size:15px; color:#d8d8d8; }}
QLabel#headingRight {{ font-size:12px; color:#9a7440; }}
QLabel#badge {{ border:1.5px solid rgba(232,165,75,170); border-radius:15px; color:#e8a54b; font-size:14px; background:rgba(0,0,0,60); }}
QLabel#status {{ font-size:12px; color:#8a8a8a; }}
QLabel#formLabel {{ color:#a0a0a0; }}
QFrame#div {{ background:#262626; min-height:1px; max-height:1px; border:none; }}
QScrollArea {{ background:transparent; border:none; }}
QScrollArea > QWidget > QWidget {{ background:transparent; }}
QScrollBar:vertical {{ background:transparent; width:8px; margin:0; }}
QScrollBar::handle:vertical {{ background:#3a3a3a; border-radius:4px; min-height:30px; }}
QScrollBar::handle:vertical:hover {{ background:#5a4a30; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background:transparent; }}

QPushButton#primary {{ border-image:url({u}/btn_p_n.png) 26 40 26 40 stretch stretch; border-width:26px 40px 26px 40px;
    color:#f2b867; font-size:17px; font-weight:600; letter-spacing:.5px; min-width:178px; min-height:23px; padding:0; }}
QPushButton#primary:hover {{ border-image:url({u}/btn_p_h.png) 26 40 26 40 stretch stretch; color:#ffd08a; }}
QPushButton#primary:pressed {{ border-image:url({u}/btn_p_p.png) 26 40 26 40 stretch stretch; color:#e8a54b; }}
QPushButton#primary:disabled {{ border-image:url({u}/btn_p_p.png) 26 40 26 40 stretch stretch; color:#6e5a3a; }}

QPushButton#sec {{ border-image:url({u}/btn_s_n.png) 16 22 16 22 stretch stretch; border-width:16px 22px 16px 22px;
    color:#d8d8d8; font-size:13px; min-height:12px; padding:0 4px; }}
QPushButton#sec:hover {{ border-image:url({u}/btn_s_h.png) 16 22 16 22 stretch stretch; color:#ffd08a; }}
QPushButton#sec:pressed {{ border-image:url({u}/btn_s_p.png) 16 22 16 22 stretch stretch; }}
QPushButton#sec:disabled {{ color:#555; }}

QComboBox {{ border-image:url({u}/combo.png) 17 38 17 20 stretch stretch; border-width:17px 38px 17px 20px;
    color:#e4e4e4; font-size:14px; min-height:16px; padding:0 0 0 2px; }}
QComboBox::drop-down {{ width:0; border:none; }}
QComboBox::down-arrow {{ image:none; width:0; height:0; }}
QComboBox QAbstractItemView {{ background:#141414; color:#e4e4e4; border:1px solid #333; outline:0;
    selection-background-color:#3a2a14; selection-color:#f2b867; padding:4px; }}

QLineEdit, QDoubleSpinBox {{ background:#0f0f0f; border:1px solid #2c2c2c; border-radius:8px; padding:6px 10px; color:#e6e6e6;
    selection-background-color:#7a5320; selection-color:#fff; min-height:18px; }}
QLineEdit:focus, QDoubleSpinBox:focus {{ border:1px solid #8a6a38; }}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width:0; border:none; }}
QMessageBox, QFileDialog {{ background:#1a1a1a; }}
"""
