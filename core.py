"""موتور رندر: بدون وابستگی به Qt. تحلیل صدا، ویژوالایزر روی زمین با پرسپکتیو، چرخش ریل‌ها."""
import math, os, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageChops

NB = 48
SR = 22050
FPS = 30
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
LANCZOS = Image.Resampling.LANCZOS

DEFAULTS = dict(
    line1="SONY", line2="CASSETTE PLAYER  WM-EX610", line3="STEREO · HI-FI", label="Song name",
    font_top="", font_hand="",
    col_text="#2b2b2b", col_ink="#22314f", col_viz="#d4832a",
    cassette="", style="bars", quality=720, start=0.0, dur=60.0, spin=True,
    cas_x=.5, cas_y=.37, cas_w=.40,
    reel_l=.29, reel_r=.72, reel_y=.385, reel_s=.07,
    lab_x=.075, lab_y=.12, lab_w=.84, lab_h=.15,
    txt_x=.22, txt_y=.185, txt_s=.045,
    fl_cx=.5, fl_top=.67, fl_bot=.95, fl_tw=.20, fl_bw=.46,
)
STYLES = ["bars", "wave", "rings", "circle", "dust"]


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
    return A


# ---------------------------------------------------------------- پرسپکتیو
def persp(dst, src):
    A, b = [], []
    for (x, y), (u, v) in zip(dst, src):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y]); b.append(v)
    return tuple(np.linalg.solve(np.array(A, float), np.array(b, float)))


def floor_quad(S, W, H):
    cx, yt, yb = S["fl_cx"] * W, S["fl_top"] * H, S["fl_bot"] * H
    tw, bw = S["fl_tw"] * W, S["fl_bw"] * W
    pts = [(cx - tw, yt), (cx + tw, yt), (cx + bw, yb), (cx - bw, yb)]
    return [(min(max(x, 0), W - 1), min(max(y, 0), H - 1)) for x, y in pts]


# ---------------------------------------------------------------- ویژوالایزر
GLOW_LUT = [min(255, int(v * 2.2)) for v in range(256)]
GLOW_MIX = [int(v * .55) for v in range(256)]


class Viz:
    def __init__(self, S, W, H, A):
        self.S, self.A = S, A
        self.s = W / 1080
        self.cw, self.ch = int(900 * self.s), int(620 * self.s)
        self.col = rgb(S["col_viz"])
        q = floor_quad(S, W, H)
        xs, ys = [p[0] for p in q], [p[1] for p in q]
        self.x0, self.y0 = int(min(xs)), int(min(ys))
        self.bw = max(2, int(math.ceil(max(xs))) - self.x0)
        self.bh = max(2, int(math.ceil(max(ys))) - self.y0)
        dst = [(p[0] - self.x0, p[1] - self.y0) for p in q]
        src = [(0, 0), (self.cw, 0), (self.cw, self.ch), (0, self.ch)]
        self.coef = persp(dst, src)
        yy = np.linspace(0, 1, self.bh)[:, None]
        m = np.clip(yy / .18, 0, 1) ** 1.2 * np.clip((1 - yy) / .06, 0, 1) * .95
        m = np.broadcast_to(m, (self.bh, self.bw))
        self.edge = Image.fromarray((m * 255).astype("u1"), "L")
        rng = np.random.default_rng(3)
        self.pa = rng.uniform(0, 6.283, 90); self.pv = rng.uniform(.08, .22, 90)
        self.pp = rng.uniform(0, 1, 90); self.pr = rng.uniform(.6, 1.4, 90)

    def mask(self, i):
        i = min(i, self.A.n - 1)
        c = Image.new("L", (self.cw, self.ch), 0)
        d = ImageDraw.Draw(c)
        getattr(self, "st_" + self.S["style"], self.st_bars)(d, i)
        g = c.filter(ImageFilter.GaussianBlur(7 * self.s)).point(GLOW_LUT).point(GLOW_MIX)
        c = ImageChops.lighter(c, g)
        w = c.transform((self.bw, self.bh), Image.Transform.PERSPECTIVE, self.coef, Image.Resampling.BICUBIC)
        return ImageChops.multiply(w, self.edge)

    # --- طرح‌ها
    def st_bars(self, d, i):
        b, cw, ch, s = self.A.B[i], self.cw, self.ch, self.s
        step = cw * .84 / (2 * NB)
        w = max(1.5, step * .46)
        for k in range(NB):
            L = (.06 + .94 * b[k]) * ch * .92
            for sg in (-1, 1):
                x = cw / 2 + sg * (k + .5) * step
                d.rectangle([x - w / 2, ch * .03, x + w / 2, ch * .03 + L], fill=235)

    def st_wave(self, d, i):
        cw, ch, s = self.cw, self.ch, self.s
        xs = np.linspace(cw * .06, cw * .94, 160)
        u = np.abs(np.linspace(-1, 1, 160)) * (NB - 1)
        taper = np.sin(np.pi * np.linspace(0, 1, 160)) ** .5
        for kk in range(6, -1, -1):
            b = self.A.B[max(0, i - kk * 4)]
            v = np.convolve(np.interp(u, np.arange(NB), b), np.ones(5) / 5, "same")
            ys = ch * (.82 - kk * .12) - v * ch * .30 * taper
            d.line(list(zip(xs, ys)), fill=int(255 * (1 - kk * .13)), width=max(1, int((3.4 - kk * .3) * s)))

    def st_rings(self, d, i):
        cw, ch, s, A = self.cw, self.ch, self.s, self.A
        cx, cy, R = cw / 2, ch / 2, ch * .47
        for b in A.births:
            age = (i - b) / A.fps
            if 0 <= age < 2.2:
                r = R * (age / 2.2) ** .7
                a = int(255 * (1 - age / 2.2) ** 1.5)
                d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=a, width=max(1, int(3 * s)))
        r0 = R * (.10 + .05 * A.bass[i])
        d.ellipse([cx - r0, cy - r0, cx + r0, cy + r0], outline=255, width=max(1, int(3.5 * s)))

    def st_circle(self, d, i):
        cw, ch, s, A = self.cw, self.ch, self.s, self.A
        cx, cy, R = cw / 2, ch / 2, ch * .47
        r0 = R * .30 * (1 + .08 * A.bass[i])
        n = 96
        for k in range(n):
            b = A.B[i][int(abs(k - n / 2) / (n / 2) * (NB - 1))]
            a = 2 * math.pi * k / n
            r1 = r0 + (.03 + .62 * b) * R * .7
            d.line([cx + math.cos(a) * r0, cy + math.sin(a) * r0, cx + math.cos(a) * r1, cy + math.sin(a) * r1],
                   fill=235, width=max(1, int(3 * s)))
        d.ellipse([cx - r0 * .94, cy - r0 * .94, cx + r0 * .94, cy + r0 * .94], outline=200, width=max(1, int(2 * s)))

    def st_dust(self, d, i):
        cw, ch, s, A = self.cw, self.ch, self.s, self.A
        cx, cy, R = cw / 2, ch / 2, ch * .47
        t = i / A.fps
        for j in range(90):
            fr = (t * self.pv[j] * self.pr[j] + self.pp[j]) % 1
            r = R * (.12 + .88 * fr)
            x, y = cx + math.cos(self.pa[j]) * r * 1.8, cy + math.sin(self.pa[j]) * r
            a = int(255 * math.sin(math.pi * fr) ** .8 * (.45 + .55 * A.bass[i]))
            q = (1.6 + 2.6 * A.rms[i]) * s
            d.ellipse([x - q, y - q, x + q, y + q], fill=a)


# ---------------------------------------------------------------- ریل‌ها
def hub_sprites(R):
    ss = 4
    D = int(R * 2.5) | 1
    big = D * ss
    base = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(base)
    c, r = big / 2, R * ss
    d.ellipse([c - 1.12 * r, c - 1.12 * r, c + 1.12 * r, c + 1.12 * r], fill=(34, 32, 30, 255))
    d.ellipse([c - r, c - r, c + r, c + r], fill=(236, 232, 222, 255))
    d.ellipse([c - .7 * r, c - .7 * r, c + .7 * r, c + .7 * r], fill=(30, 28, 27, 255))
    for k in range(6):
        a = math.radians(k * 60)
        ux, uy, px, py = math.cos(a), math.sin(a), -math.sin(a), math.cos(a)
        pts = [(c + ux * r0 + px * hw, c + uy * r0 + py * hw) for r0, hw in ((.42 * r, .09 * r), (.74 * r, .09 * r), (.74 * r, -.09 * r), (.42 * r, -.09 * r))]
        d.polygon(pts, fill=(236, 232, 222, 255))
    return [base.rotate(a, resample=Image.Resampling.BICUBIC).resize((D, D), LANCZOS) for a in range(60)]


# ---------------------------------------------------------------- صحنه ثابت
class Static:
    pass


def background(W, H, frame_path):
    if frame_path and os.path.exists(frame_path):
        im = Image.open(frame_path).convert("RGB")
        k = max(W / im.width, H / im.height)
        im = im.resize((math.ceil(im.width * k), math.ceil(im.height * k)), LANCZOS)
        l, t = (im.width - W) // 2, (im.height - H) // 2
        return im.crop((l, t, l + W, t + H))
    y = np.linspace(0, 1, H)[:, None, None]
    hz = .62
    wall = np.array([241, 228, 205.]) + (np.array([226, 206, 176.]) - np.array([241, 228, 205.])) * np.clip(y / hz, 0, 1)
    fl = np.array([210, 190, 160.]) + (np.array([236, 224, 202.]) - np.array([210, 190, 160.])) * np.clip((y - hz) / (1 - hz), 0, 1)
    arr = np.broadcast_to(np.where(y < hz, wall, fl), (H, W, 3)).astype("u1")
    im = Image.fromarray(arr, "RGB")
    fx0, fx1, fy0, fy1 = int(.16 * W), int(.84 * W), int(.135 * H), int(.605 * H)
    sh = Image.new("L", (W, H), 0)
    ImageDraw.Draw(sh).ellipse([fx0, fy1 - .008 * H, fx1, fy1 + .02 * H], fill=110)
    sh = sh.filter(ImageFilter.GaussianBlur(.012 * W))
    im.paste((70, 52, 34), (0, 0), sh)
    d = ImageDraw.Draw(im)
    d.rectangle([fx0, fy0, fx1, fy1], fill=(92, 66, 42))
    m = int(.04 * W)
    d.rectangle([fx0 + m, fy0 + m, fx1 - m, fy1 - m], fill=(241, 239, 234))
    d.rectangle([fx0 + m, fy0 + m, fx1 - m, fy0 + m + max(2, int(.004 * W))], fill=(214, 209, 200))
    return im


def proc_cassette(S, w=800):
    h = int(w * .64)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=int(w * .035), fill=(58, 57, 60, 255))
    d.rounded_rectangle([int(w * .02), int(h * .02), int(w * .98), int(h * .98)], radius=int(w * .03), outline=(92, 92, 96, 255), width=3)
    d.rectangle([S["lab_x"] * w, S["lab_y"] * h, (S["lab_x"] + S["lab_w"]) * w, (S["lab_y"] + S["lab_h"]) * h], fill=(236, 230, 214, 255))
    d.rounded_rectangle([.13 * w, .29 * h, .87 * w, .51 * h], radius=int(w * .02), fill=(26, 25, 27, 255))
    d.polygon([(.2 * w, .98 * h), (.8 * w, .98 * h), (.74 * w, .74 * h), (.26 * w, .74 * h)], fill=(36, 36, 38, 255))
    R = S["reel_s"] * w
    sp = hub_sprites(R)[0]
    for rx in (S["reel_l"], S["reel_r"]):
        cx, cy = rx * w, S["reel_y"] * h
        d.ellipse([cx - R * 1.35, cy - R * 1.35, cx + R * 1.35, cy + R * 1.35], fill=(54, 40, 30, 255))
        im.alpha_composite(sp, (int(cx - sp.width / 2), int(cy - sp.height / 2)))
    return im


def compose_static(S, W, H, text_fn, assets):
    st = Static()
    st.s = W / 1080
    base = background(W, H, assets.get("frame"))
    # متن‌های بالا
    x, y = int(S["txt_x"] * W), int(S["txt_y"] * H)
    px1 = S["txt_s"] * W
    for text, ratio in ((S["line1"], 1.0), (S["line2"], .42), (S["line3"], .26)):
        if text.strip():
            t = text_fn(text, assets.get("fam_top", ""), max(6, int(px1 * ratio)), S["col_text"])
            base.paste(t, (x, y), t)
            y += t.height + int(px1 * .12)
    # کاست
    cp = assets.get("cassette")
    cas = Image.open(cp).convert("RGBA") if cp and os.path.exists(cp) else proc_cassette(S)
    cw = int(S["cas_w"] * W)
    ch = int(cas.height * cw / cas.width)
    cas = cas.resize((cw, ch), LANCZOS)
    x0, y0 = int(S["cas_x"] * W - cw / 2), int(S["cas_y"] * H - ch / 2)
    sh = cas.getchannel("A").filter(ImageFilter.GaussianBlur(.02 * W)).point(lambda v: int(v * .32))
    base.paste((40, 30, 20), (x0, y0 + int(.006 * H)), sh)
    base.paste(cas, (x0, y0), cas)
    # نام روی برچسب
    if S["label"].strip():
        bx, by = x0 + S["lab_x"] * cw, y0 + S["lab_y"] * ch
        bw_, bh_ = S["lab_w"] * cw, S["lab_h"] * ch
        px = bh_ * .95
        while True:
            t = text_fn(S["label"], assets.get("fam_hand", ""), max(6, int(px)), S["col_ink"])
            if t.width <= bw_ * .96 or px < 8:
                break
            px *= .92
        base.paste(t, (int(bx + (bw_ - t.width) / 2), int(by + (bh_ - t.height) / 2)), t)
    st.base = base
    st.hubs = [(int(x0 + S[k] * cw), int(y0 + S["reel_y"] * ch)) for k in ("reel_l", "reel_r")]
    st.sprites = hub_sprites(S["reel_s"] * cw)
    return st


def render_frame(st, viz, i, fps=FPS, spin=True):
    img = st.base.copy()
    m = viz.mask(i)
    img.paste(viz.col, (viz.x0, viz.y0, viz.x0 + viz.bw, viz.y0 + viz.bh), m)
    if spin:
        sp = st.sprites[int(i / fps * 150) % 60]
        for hx, hy in st.hubs:
            img.paste(sp, (hx - sp.width // 2, hy - sp.height // 2), sp)
    return img
