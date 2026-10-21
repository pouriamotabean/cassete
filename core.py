"""Render engine v2: every scene is a finished photo; we animate its reels, write the song name on the tape label and drive its visualizer."""
import json, math, os, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageChops

NB = 48
SR = 22050
FPS = 30
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
LANCZOS = Image.Resampling.LANCZOS

DEFAULTS = dict(scene="golden_frame", quality=720, start=0.0, dur=60.0,
                label="Song name", font_hand="", font_fa="", spin=True, spin_speed=120.0)


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# ---------------------------------------------------------------- صدا
def load_audio(ffmpeg, path, start, dur):
    cmd = [ffmpeg, "-v", "error", "-ss", str(start), "-t", str(dur), "-i", path,
           "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NOWIN)
    return np.frombuffer(r.stdout, dtype="<f4")


class Analysis:
    pass


def analyze(y, fps=FPS):
    n = int(len(y) / SR * fps)
    N = 4096
    win = np.hanning(N)
    freqs = np.fft.rfftfreq(N, 1 / SR)
    edges = np.geomspace(50, 9000, NB + 1)
    idx = []
    for k in range(NB):
        ix = np.where((freqs >= edges[k]) & (freqs < edges[k + 1]))[0]
        if len(ix) == 0:
            ix = [int(round(math.sqrt(edges[k] * edges[k + 1]) / (SR / N)))]
        idx.append(ix)
    pad = np.pad(y, (N, N))
    B = np.zeros((n, NB), "f4")
    rms = np.zeros(n, "f4")
    for i in range(n):
        c = int(i / fps * SR) + N
        seg = pad[c - N // 2:c + N // 2]
        sp = np.abs(np.fft.rfft(seg * win))
        for k in range(NB):
            B[i, k] = sp[idx[k]].mean()
        rms[i] = math.sqrt(float(np.mean(seg ** 2)))
    B = np.log1p(B / (np.percentile(B, 99) + 1e-9) * 30) / math.log1p(30)
    ref = np.percentile(B, 95, axis=0) + 1e-6
    B = np.clip(B / (ref * 1.1), 0, 1) ** 1.3
    out = np.zeros_like(B)
    cur = np.zeros(NB)
    for i in range(n):
        cur = np.where(B[i] > cur, cur + (B[i] - cur) * .7, cur + (B[i] - cur) * .18)
        out[i] = cur
    r = np.clip(rms / (np.percentile(rms, 97) + 1e-9), 0, 1)
    A = Analysis()
    A.n, A.fps, A.B, A.rms = n, fps, out, r
    A.bass = out[:, :8].mean(1)
    pk = np.zeros_like(out)
    cur = np.zeros(NB)
    for i in range(n):
        cur = np.maximum(out[i], cur - .014)
        pk[i] = cur
    A.peak = pk
    births, last = [], -999
    for i in range(n):
        lo = max(0, i - 20)
        ref_ = A.bass[lo:i].mean() if i > lo else 0
        if A.bass[i] > ref_ * 1.22 + .04 and A.bass[i] > .35 and i - last > int(.35 * fps):
            births.append(i)
            last = i
    A.births = births
    return A


def demo_analysis():
    A = Analysis()
    n = 120
    p = .85 * np.exp(-np.linspace(0, 2.5, NB)) + .15
    t = np.arange(n)[:, None]
    A.B = np.clip(p[None, :] * (.72 + .28 * np.sin(t * .3 + np.arange(NB)[None, :] * .4)), 0, 1).astype("f4")
    A.n, A.fps = n, FPS
    A.rms = np.full(n, .6, "f4")
    A.bass = A.B[:, :8].mean(1)
    A.births = [20, 45, 70, 95]
    A.peak = np.minimum(1, A.B + .08)
    return A




def fill_face(img, led, f, ss=1):
    ax, ay = led["a"]; bx, by = led["b"]
    x0, x1 = f["x"]
    ys0 = int(min(ay, by) - f["top_a"] - 4); ys1 = int(max(ay, by) + f["bot_a"] + 4)
    xs = np.arange(x0, x1)[None, :]; ys = np.arange(ys0, ys1)[:, None]
    u = ((xs - ax) / (bx - ax)).clip(0, 1)
    base = ay + ((xs - ax) / (bx - ax)) * (by - ay)
    top = base - (f["top_a"] + (f["top_b"] - f["top_a"]) * u)
    bot = base + (f["bot_a"] + (f["bot_b"] - f["bot_a"]) * u)
    v = ((ys - top) / (bot - top)).clip(0, 1)[..., None]
    col = np.array(f["c_top"], float) * (1 - v) + np.array(f["c_bot"], float) * v
    col += np.random.default_rng(4).normal(0, 1.0, col.shape[:2])[..., None]
    inside = ((ys >= top) & (ys <= bot)).astype("u1") * 255
    mask = Image.fromarray(inside, "L").filter(ImageFilter.GaussianBlur(1.4 * ss))
    img = img.copy()
    img.paste(Image.fromarray(col.clip(0, 255).astype("u1")), (x0, ys0), mask)
    return img


def min_patch(img, poly, size=15, blur=5, feather=7, ss=1):
    size, blur, feather = (size * ss) | 1, blur * ss, feather * ss
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).polygon([tuple(q) for q in poly], fill=255)
    bb = m.getbbox()
    box = (max(0, bb[0] - 20), max(0, bb[1] - 20), min(img.width, bb[2] + 20), min(img.height, bb[3] + 20))
    reg = img.crop(box).filter(ImageFilter.MinFilter(size)).filter(ImageFilter.GaussianBlur(blur))
    img = img.copy()
    img.paste(reg, box[:2], m.crop(box).filter(ImageFilter.GaussianBlur(feather)))
    return img





# ---------------------------------------------------------------- پاک‌کردن / پر کردن
def fill_label(img, box, paper_x):
    """Fill the whole label box with the paper colour (row-wise median of the clean paper columns)."""
    x0, y0, x1, y1 = [int(v) for v in box]
    a = np.asarray(img, float)
    rngs = paper_x if isinstance(paper_x[0], (list, tuple)) else [paper_x]
    cols = np.concatenate([a[y0:y1, int(r[0]):int(r[1])] for r in rngs], axis=1)
    rows = np.median(cols, axis=1)
    out = np.repeat(rows[:, None, :], x1 - x0, axis=1)
    out += np.random.default_rng(2).normal(0, 1.4, out.shape[:2])[..., None]
    m = Image.new("L", (x1 - x0, y1 - y0), 0)
    ImageDraw.Draw(m).rectangle([1, 1, x1 - x0 - 2, y1 - y0 - 2], fill=255)
    img = img.copy()
    img.paste(Image.fromarray(out.clip(0, 255).astype("u1")), (x0, y0), m.filter(ImageFilter.GaussianBlur(1.2)))
    return img


def fill_rows_pct(img, rect, pct=25):
    """Remove baked bars from a dark display: every row gets the low-percentile colour of that row."""
    x0, y0, x1, y1 = [int(v) for v in rect]
    a = np.asarray(img, float)
    reg = a[y0:y1, x0:x1]
    rows = np.percentile(reg, pct, axis=1)
    k = np.ones(5) / 5
    rows = np.stack([np.convolve(np.pad(rows[:, c], 2, mode="edge"), k, "valid") for c in range(3)], 1)
    out = np.repeat(rows[:, None, :], x1 - x0, axis=1)
    out += np.random.default_rng(5).normal(0, 1.2, out.shape[:2])[..., None]
    m = Image.new("L", (x1 - x0, y1 - y0), 0)
    ImageDraw.Draw(m).rectangle([3, 3, x1 - x0 - 4, y1 - y0 - 4], fill=255)
    img = img.copy()
    img.paste(Image.fromarray(out.clip(0, 255).astype("u1")), (x0, y0), m.filter(ImageFilter.GaussianBlur(2.5)))
    return img


def persp(dst, src):
    A, b = [], []
    for (x, y), (u, v) in zip(dst, src):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y]); b.append(v)
    return tuple(np.linalg.solve(np.array(A, float), np.array(b, float)))


def fit_text(text_fn, text, fam, px, color, max_w, bold=False):
    while True:
        t = text_fn(text, fam, max(5, int(px)), color, bold)
        if t.width - 12 <= max_w or px < 6:
            return t
        px *= .94


# ---------------------------------------------------------------- نمایشگر (پنل شیشه‌ای دستگاه)
GLOW_LUT = [min(255, int(v * 2.0)) for v in range(256)]
GLOW_MIX = [int(v * .5) for v in range(256)]


def gradient(w, h, bottom, top):
    t = np.linspace(1, 0, h)[:, None, None]
    c = np.array(bottom, float) * (1 - t) + np.array(top, float) * t
    return Image.fromarray(np.broadcast_to(c, (h, w, 3)).clip(0, 255).astype("u1"), "RGB")


class Panel:
    """Animated visualizer drawn flat, then warped into the display glass of the photo and added as light."""

    def __init__(self, cfg):
        self.c = cfg
        q = cfg["quad"]
        xs, ys = [p[0] for p in q], [p[1] for p in q]
        self.x0, self.y0 = int(min(xs)), int(min(ys))
        self.bw = int(math.ceil(max(xs))) - self.x0
        self.bh = int(math.ceil(max(ys))) - self.y0
        wq = (math.dist(q[0], q[1]) + math.dist(q[3], q[2])) / 2
        hq = (math.dist(q[0], q[3]) + math.dist(q[1], q[2])) / 2
        self.cw, self.ch = int(wq * 2), int(hq * 2)
        dst = [(p[0] - self.x0, p[1] - self.y0) for p in q]
        self.coef = persp(dst, [(0, 0), (self.cw, 0), (self.cw, self.ch), (0, self.ch)])
        cols = cfg.get("colors", ["#ffb04a"])
        self.grad = gradient(self.cw, self.ch, rgb(cols[0]), rgb(cols[-1]))
        self.n = cfg.get("count", 40)
        self.style = cfg.get("style", "segments")
        self.gain = cfg.get("gain", 1.0)
        # عمل پنل داخل شیشه: حاشیه‌ی کوچک
        self.mx, self.top, self.bot = .035 * self.cw, .12 * self.ch, .90 * self.ch

    def _bands(self, A, i):
        b = A.B[i]
        idx = np.linspace(0, NB - 1, self.n)
        return np.interp(idx, np.arange(NB), b), np.interp(idx, np.arange(NB), A.peak[i])

    def draw(self, d, A, i):
        b, pk = self._bands(A, i)
        cw, ch, n = self.cw, self.ch, self.n
        step = (cw - 2 * self.mx) / n
        H = self.bot - self.top
        if self.style == "segments":
            seg = 14
            sh = H / seg
            for k in range(n):
                x = self.mx + k * step
                lit = int(b[k] * seg + .5)
                for s in range(lit):
                    y = self.bot - s * sh
                    d.rectangle([x + step * .16, y - sh * .78, x + step * .84, y], fill=int(200 + 55 * s / seg))
                pp = min(seg - 1, int(pk[k] * seg + .5))
                if pp > lit:
                    y = self.bot - pp * sh
                    d.rectangle([x + step * .16, y - sh * .78, x + step * .84, y], fill=255)
        elif self.style == "bars":
            for k in range(n):
                x = self.mx + k * step
                h = (.04 + .96 * b[k]) * H
                d.rectangle([x + step * .3, self.bot - h, x + step * .7, self.bot], fill=235)
        elif self.style == "mirror":
            mid = (self.top + self.bot) / 2
            for k in range(n):
                x = self.mx + k * step
                h = (.03 + .97 * b[k]) * H / 2
                d.rounded_rectangle([x + step * .28, mid - h, x + step * .72, mid + h], radius=step * .2, fill=235)
        else:  # line
            xs = np.linspace(self.mx, cw - self.mx, 160)
            v = np.interp(np.linspace(0, NB - 1, 160), np.arange(NB), A.B[i])
            v = np.convolve(v, np.ones(7) / 7, "same")
            ys = self.bot - (.04 + .96 * v) * H
            pts = list(zip(xs, ys))
            d.polygon(pts + [(xs[-1], self.bot), (xs[0], self.bot)], fill=70)
            d.line(pts, fill=255, width=max(2, int(ch * .018)))

    def paint(self, img, A, i):
        i = min(i, A.n - 1)
        m = Image.new("L", (self.cw, self.ch), 0)
        self.draw(ImageDraw.Draw(m), A, i)
        g = m.filter(ImageFilter.GaussianBlur(self.ch * .03)).point(GLOW_LUT).point(GLOW_MIX)
        m = ImageChops.lighter(m, g)
        if self.gain != 1.0:
            m = m.point(lambda v: min(255, int(v * self.gain)))
        col = Image.composite(self.grad, Image.new("RGB", m.size, (0, 0, 0)), m)
        w = col.transform((self.bw, self.bh), Image.Transform.PERSPECTIVE, self.coef, Image.Resampling.BICUBIC)
        box = (self.x0, self.y0, self.x0 + self.bw, self.y0 + self.bh)
        img.paste(ImageChops.add(img.crop(box), w), box[:2])


# ---------------------------------------------------------------- استوانه‌ی سفید روی سطح
class Cylinder:
    """A realistic white cylindrical LED bar lying on the surface, with contact shadow, reflection and light spill."""

    def __init__(self, cfg):
        self.c = cfg
        self.L, self.R = int(cfg["length"]), int(cfg["radius"])
        self.cx, self.cy = cfg["center"]
        self.light = np.array(cfg.get("light", [1, .93, .82]), float)
        self.amb = cfg.get("amb", 1.0)
        self.col = rgb(cfg.get("color", "#ffb04a"))
        self.n = cfg.get("count", 36)
        self.build()

    def build(self):
        L, R = self.L, self.R
        H = int(R * 1.9)
        cap = int(R * .42)
        t = np.linspace(0, 1, H)[:, None]
        prof = np.interp(t, [0, .10, .30, .55, .80, 1.0], [.62, 1.0, .96, .80, .58, .40])
        base = np.broadcast_to(prof, (H, L))[..., None] * 255 * self.light * self.amb
        # شیب افقی ملایم و تیره‌شدن دو سر
        xg = np.linspace(0, 1, L)[None, :, None]
        base = base * (0.92 + .08 * np.sin(np.pi * xg))
        mask = Image.new("L", (L, H), 0)
        d = ImageDraw.Draw(mask)
        d.rectangle([cap, 0, L - cap, H - 1], fill=255)
        d.ellipse([0, 0, cap * 2, H - 1], fill=255)
        d.ellipse([L - cap * 2, 0, L - 1, H - 1], fill=255)
        body = Image.fromarray(base.clip(0, 255).astype("u1"), "RGB")
        # سرپوش‌ها
        bd = ImageDraw.Draw(body)
        bd.ellipse([L - cap * 2 + 1, 2, L - 3, H - 3], fill=tuple(int(v) for v in (214, 210, 202) * np.array(self.light) * self.amb), outline=(150, 146, 140))
        bd.ellipse([L - cap * 2 + 5, int(H * .22), L - 9, int(H * .78)], fill=tuple(int(v) for v in (186, 182, 174) * np.array(self.light) * self.amb))
        bd.ellipse([0, 0, cap * 2, H - 1], outline=(110, 106, 100))
        # شیار نمایشگر
        self.sx0, self.sx1 = int(L * .09), int(L * .90)
        self.sy0, self.sy1 = int(H * .40), int(H * .74)
        sl = Image.new("L", (L, H), 0)
        ImageDraw.Draw(sl).rounded_rectangle([self.sx0, self.sy0, self.sx1, self.sy1], radius=int(R * .16), fill=255)
        self.slit = sl.filter(ImageFilter.GaussianBlur(.8))
        body.paste((22, 19, 17), (0, 0), self.slit)
        self.body = body
        self.mask = mask.filter(ImageFilter.GaussianBlur(.9))
        self.H = H

    def paint(self, img, A, i):
        i = min(i, A.n - 1)
        L, H, R = self.L, self.H, self.R
        b, pk = A.B[i], A.peak[i]
        bars = Image.new("RGB", (L, H)); d = ImageDraw.Draw(bars)
        n = self.n
        sw = (self.sx1 - self.sx0 - 8) / n
        hmax = (self.sy1 - self.sy0) - 6
        for k in range(n):
            u = k / (n - 1)
            v = np.interp(u * (NB - 1), np.arange(NB), b)
            p = np.interp(u * (NB - 1), np.arange(NB), pk)
            x = self.sx0 + 4 + k * sw
            hh = max(2, (.06 + .94 * v) * hmax)
            d.rectangle([x + sw * .18, self.sy1 - 3 - hh, x + sw * .82, self.sy1 - 3], fill=self.col)
            yp = self.sy1 - 3 - max(2, (.06 + .94 * p) * hmax) - 2
            d.rectangle([x + sw * .18, yp - 1.5, x + sw * .82, yp], fill=tuple(min(255, int(c + (255 - c) * .5)) for c in self.col))
        glow = bars.filter(ImageFilter.GaussianBlur(R * .12)).point(lambda v: int(v * .7))
        light = ImageChops.add(bars, glow)
        light = Image.composite(light, Image.new("RGB", light.size), self.slit.point(lambda v: min(255, int(v * 1.0))))
        # توهم نور روی بدنه: درخشش کم بالای شیار
        spr = ImageChops.add(self.body, light)
        x0 = int(self.cx - L / 2); y0 = int(self.cy - H / 2)
        yb = y0 + H
        # سایه‌ی تماس
        sh = Image.new("L", img.size, 0)
        ImageDraw.Draw(sh).ellipse([x0 - 6, yb - R * .30, x0 + L + 6, yb + R * .38], fill=170)
        sh = sh.filter(ImageFilter.GaussianBlur(R * .30))
        img.paste((10, 7, 5), (0, 0), sh)
        # بازتاب
        rh = int(H * .8)
        refl = ImageChops.add(self.body, light).transpose(Image.Transpose.FLIP_TOP_BOTTOM).crop((0, 0, L, rh))
        fade = np.linspace(.42, 0, rh)[:, None]
        am = (np.asarray(self.mask.transpose(Image.Transpose.FLIP_TOP_BOTTOM).crop((0, 0, L, rh)), float) * fade).astype("u1")
        refl = refl.filter(ImageFilter.GaussianBlur(1.6))
        img.paste(refl, (x0, yb + 2), Image.fromarray(am, "L").filter(ImageFilter.GaussianBlur(1.4)))
        # نور ریخته‌شده روی سطح
        spill = Image.new("RGB", (L + 120, int(R * 2.4)), (0, 0, 0))
        sd = ImageDraw.Draw(spill)
        e = float(np.mean(b[:20]) * .6 + .25)
        sd.ellipse([40, 0, L + 80, int(R * 2.2)], fill=tuple(int(c * .30 * e) for c in self.col))
        spill = spill.filter(ImageFilter.GaussianBlur(R * .7))
        reg = img.crop((x0 - 60, yb - 2, x0 - 60 + spill.width, yb - 2 + spill.height))
        img.paste(ImageChops.add(reg, spill), (x0 - 60, yb - 2))
        img.paste(spr, (x0, y0), self.mask)


# ---------------------------------------------------------------- صحنه
class Static:
    pass


def compose_scene(scene, scene_dir, S, text_fn, fam_hand):
    img = Image.open(os.path.join(scene_dir, scene["image"])).convert("RGB")
    st = Static()
    st.cfg = scene
    viz = scene.get("viz", {})
    vt = viz.get("type")
    # پاک‌کردن ویژوالایزر پخته‌شده در عکس
    if vt == "led":
        if viz.get("face"):
            img = fill_face(img, viz, viz["face"], 1)
        if viz.get("refl_clean"):
            img = min_patch(img, viz["refl_clean"], ss=1)
    if viz.get("clean"):
        img = fill_rows_pct(img, viz["clean"], viz.get("clean_pct", 25))
    # نام آهنگ روی برچسب نوار
    lb = scene.get("label")
    if lb and S["label"].strip():
        img = fill_label(img, lb["box"], lb["paper_x"])
        x0, y0, x1, y1 = lb["box"]
        fa = any("\u0600" <= ch <= "\u06ff" for ch in S["label"])
        # fit by the real ink bounds (ascenders / descenders / dots), so nothing leaves the label strip
        bw, bh = (x1 - x0) * .92, (y1 - y0) * .78
        px = (y1 - y0) * lb.get("k", 1.0) * (1.9 if fa else 1.3)
        for _ in range(40):
            t = text_fn(S["label"], fam_hand, max(5, int(px)), lb.get("ink", "#2a241e"))
            bb = t.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()
            if not bb:
                break
            iw, ih = bb[2] - bb[0], bb[3] - bb[1]
            if (iw <= bw and ih <= bh) or px < 6:
                break
            px *= min(bw / iw, bh / ih, .97)
        if bb:
            t = t.crop((max(0, bb[0] - 3), max(0, bb[1] - 3), bb[2] + 3, bb[3] + 3))
        t = t.filter(ImageFilter.GaussianBlur(lb.get("soft", .45)))
        a = t.getchannel("A").point(lambda v: int(v * lb.get("opacity", .88)))
        t.putalpha(a)
        ang = lb.get("angle", 0)
        if ang:
            t = t.rotate(ang, resample=Image.Resampling.BICUBIC, expand=True)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        img.paste(t, (int(cx - t.width / 2), int(cy - t.height / 2)), t)
    st.base = img
    # ریل‌ها: تکه‌ی واقعی عکس می‌چرخد
    st.reels = []
    rc = scene.get("reels")
    if rc:
        R = int(rc["radius"]); D = 2 * (R + 3)
        mask = Image.new("L", (D * 4, D * 4), 0)
        ImageDraw.Draw(mask).ellipse([(D * 4 - R * 8) / 2, (D * 4 - R * 8) / 2, (D * 4 + R * 8) / 2, (D * 4 + R * 8) / 2], fill=255)
        mask = mask.resize((D, D), LANCZOS).filter(ImageFilter.GaussianBlur(.8))
        for cx, cy in rc["centers"]:
            bx, by = int(cx) - D // 2, int(cy) - D // 2
            patch = img.crop((bx, by, bx + D, by + D))
            st.reels.append((bx, by, [patch.rotate(a, resample=Image.Resampling.BICUBIC) for a in range(0, 360, 3)], mask))
    st.viz = None
    if vt == "led":
        st.viz = LED(viz, {"led_style": viz.get("style", "bars"), "col_led": viz.get("color", "#ffb85c")}, img, 1)
    elif vt == "panel":
        st.viz = Panel(viz)
    elif vt == "cylinder":
        st.viz = Cylinder(viz)
    return st


def render_frame(st, A, S, i, W, H, fps=FPS):
    img = st.base.copy()
    v = st.viz
    if v is not None:
        if isinstance(v, LED):
            img.paste(v.region(A, i), (v.ox, v.oy))
        else:
            v.paint(img, A, i)
    if S["spin"]:
        idx = int(i / fps * S["spin_speed"] / 3) % 120
        for x, y, rots, mask in st.reels:
            img.paste(rots[idx], (x, y), mask)
    return img.resize((W, H), LANCZOS)



class LED:
    def __init__(self, cfg, S, base, ss=1):
        self.ss = ss
        self.c = cfg
        self.col = rgb(S["led_col"] if "led_col" in S else S["col_led"])
        self.style = S["led_style"]
        ax, ay = cfg["a"]; bx, by = cfg["b"]
        pad = 50 * ss
        self.ox = int(min(ax, bx) - pad); self.oy = int(min(ay, by) - cfg["h_a"] - pad)
        self.w = int(abs(bx - ax) + 2 * pad)
        self.h = int(max(ay, by) + cfg["refl_off"] * 2 + cfg["h_a"] * 1.4 + pad - self.oy)
        self.base = base.crop((self.ox, self.oy, self.ox + self.w, self.oy + self.h))

    def region(self, A, i):
        c, N = self.c, self.c["count"]
        i = min(i, A.n - 1)
        b, pk = A.B[i], A.peak[i]
        bars = Image.new("RGB", (self.w, self.h)); d = ImageDraw.Draw(bars)
        refl = Image.new("RGB", (self.w, self.h)); dr = ImageDraw.Draw(refl)
        amber = self.col
        core_c = tuple(min(255, int(v + (255 - v) * .42)) for v in amber)
        ax, ay = c["a"]; bx, by = c["b"]
        for k in range(N):
            u = (k + .5) / N
            x = ax + u * (bx - ax) - self.ox
            y = ay + u * (by - ay) - self.oy
            hm = c["h_a"] + (c["h_b"] - c["h_a"]) * u
            bw = (c["w_a"] + (c["w_b"] - c["w_a"]) * u) / 2
            hh = hm * (.05 + .95 * b[k])
            if self.style == "segments":
                sg = hm / 10
                n = max(1, int(hh / sg + .5))
                for s in range(n):
                    y1 = y - s * sg
                    d.rectangle([x - bw, y1 - sg * .78, x + bw, y1], fill=amber)
                    d.rectangle([x - bw * .45, y1 - sg * .78, x + bw * .45, y1], fill=core_c)
                hh = n * sg
            else:
                d.rectangle([x - bw, y - hh, x + bw, y], fill=amber)
                d.rectangle([x - bw * .45, y - hh, x + bw * .45, y], fill=core_c)
            yp = y - hm * (.05 + .95 * pk[k]) - 3
            d.rectangle([x - bw, yp - 2, x + bw, yp], fill=core_c)
            off = c["refl_off"] * 2
            for s in range(5):
                f = (1 - s * .2) * .55
                dr.rectangle([x - bw, y + off + s * hh * .18, x + bw, y + off + (s + 1) * hh * .18],
                             fill=tuple(int(v * f) for v in amber))
        glow = bars.filter(ImageFilter.GaussianBlur(5 * self.ss)).point(lambda v: int(v * .6))
        light = ImageChops.add(ImageChops.add(bars, glow), refl.filter(ImageFilter.GaussianBlur(1.7 * self.ss)))
        return ImageChops.add(self.base, light)


