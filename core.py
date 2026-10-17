"""Render engine (no Qt): audio analysis, LED bar, spinning reels, scene view."""
import json, math, os, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageChops

NB = 48
SR = 22050
FPS = 30
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
LANCZOS = Image.Resampling.LANCZOS

DEFAULTS = dict(
    scene="golden_floor", cassette="",
    top_on=False, line1="SONY", line2="CASSETTE PLAYER  WM-EX610", line3="TYPE I (NORMAL) POSITION  \u2022  STEREO CASSETTE PLAYER",
    label_on=True, label="Song name",
    font_top="", font_hand="",
    col_text="#2a2420", col_ink="#1f2a44", col_led="#ffb85c",
    led_style="bars", spin=True, spin_speed=120.0,
    quality=720, start=0.0, dur=60.0,
    zoom=2.7, cx=0.33, cy=0.5, pan=True, cx_end=0.745,
)
LED_STYLES = ["bars", "segments"]


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


# ---------------------------------------------------------------- inpaint (پاک‌کردن نواحی با پر کردن از اطراف)
def _blur_ch(a, r):
    return np.asarray(Image.fromarray(a.clip(0, 255).astype("u1")).filter(ImageFilter.GaussianBlur(r)), float)


def inpaint(img, polys, grow=11):
    W, H = img.size
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    for p in polys:
        d.polygon([tuple(q) for q in p], fill=255)
    bb = m.getbbox()
    if not bb:
        return img
    pad = 80
    box = (max(0, bb[0] - pad), max(0, bb[1] - pad), min(W, bb[2] + pad), min(H, bb[3] + pad))
    reg = img.crop(box)
    mm = m.crop(box).filter(ImageFilter.MaxFilter(grow))
    a = np.asarray(reg, float)
    known = 1 - np.asarray(mm, float) / 255
    fill = np.zeros_like(a)
    done = np.zeros(known.shape, bool)
    for r in (3, 8, 20, 50, 120):
        den = _blur_ch(known * 255, r) / 255
        ok = (den > .3) & (~done)
        if r == 120:
            ok = ~done
        for c in range(3):
            num = _blur_ch(a[..., c] * known, r)
            fill[..., c][ok] = num[ok] / np.maximum(den[ok], 1e-3)
        done |= ok
    fm = np.asarray(mm.filter(ImageFilter.GaussianBlur(2.2)), float)[..., None] / 255
    noise = np.random.default_rng(1).normal(0, 2.2, a.shape[:2])[..., None]
    out = a * (1 - fm) + (fill + noise) * fm
    img = img.copy()
    img.paste(Image.fromarray(out.clip(0, 255).astype("u1")), box[:2])
    return img


def fill_label(img, box, paper_x):
    x0, y0, x1, y1 = box
    a = np.asarray(img, float)
    rows = np.median(a[y0:y1, paper_x[0]:paper_x[1]], axis=1)
    out = np.repeat(rows[:, None, :], x1 - x0, axis=1)
    out += np.random.default_rng(2).normal(0, 1.5, out.shape[:2])[..., None]
    img = img.copy()
    img.paste(Image.fromarray(out.clip(0, 255).astype("u1")), (x0, y0))
    return img


# ---------------------------------------------------------------- صحنه
class Static:
    pass


def fill_lr(img, box, lx, rx):
    x0, y0, x1, y1 = box
    a = np.asarray(img, float)
    cl = np.median(a[y0:y1, lx[0]:lx[1]], axis=1)
    cr = np.median(a[y0:y1, rx[0]:rx[1]], axis=1)
    t = np.linspace(0, 1, x1 - x0)[None, :, None]
    out = cl[:, None, :] * (1 - t) + cr[:, None, :] * t
    out += np.random.default_rng(3).normal(0, 1.6, out.shape[:2])[..., None]
    m = Image.new("L", (x1 - x0, y1 - y0), 0)
    ImageDraw.Draw(m).rectangle([5, 5, x1 - x0 - 6, y1 - y0 - 6], fill=255)
    img = img.copy()
    img.paste(Image.fromarray(out.clip(0, 255).astype("u1")), (x0, y0), m.filter(ImageFilter.GaussianBlur(3.5)))
    return img


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


def fit_text(text_fn, text, fam, px, color, max_w, bold=False):
    while True:
        t = text_fn(text, fam, max(5, int(px)), color, bold)
        if t.width - 12 <= max_w or px < 6:
            return t
        px *= .94


SKIP = {"count", "c_top", "c_bot", "name", "image", "ss", "view"}


def scale_cfg(o, ss):
    if isinstance(o, dict):
        return {k: (v if k in SKIP else scale_cfg(v, ss)) for k, v in o.items()}
    if isinstance(o, list):
        return [scale_cfg(v, ss) for v in o]
    if isinstance(o, bool):
        return o
    if isinstance(o, (int, float)):
        return o * ss
    return o


_CACHE = {}


def compose_scene(scene, scene_dir, S, text_fn, fam_top, fam_hand, cas_dir=None):
    ss = scene.get("ss", 2)
    cfg = scale_cfg(scene, ss)
    key = (os.path.abspath(scene_dir), cfg["image"], ss)
    led = cfg.get("led")
    if key not in _CACHE:
        img = Image.open(os.path.join(scene_dir, cfg["image"])).convert("RGB")
        if ss != 1:
            img = img.resize((img.width * ss, img.height * ss), LANCZOS)
        if led:
            if led.get("face"):
                img = fill_face(img, led, led["face"], ss)
            if led.get("refl_clean"):
                img = min_patch(img, led["refl_clean"], ss=ss)
        _CACHE.clear()
        _CACHE[key] = img
    img = _CACHE[key].copy()
    st = Static()
    st.cfg = cfg
    tt = cfg.get("top_text")
    if tt and S["top_on"]:
        img = fill_lr(img, tt["box"], tt["left"], tt["right"])
        for line, spec in zip((S["line1"], S["line2"], S["line3"]), tt["lines"]):
            if line.strip():
                t = fit_text(text_fn, line, fam_top, spec["px"], S["col_text"], tt["max_x"] - spec["x"], spec.get("bold", False))
                t = t.filter(ImageFilter.GaussianBlur(.55 * ss))
                img.paste(t, (int(spec["x"] - 6), int(spec["y"] - 4)), t)
    # کاست: اصلی عکس یا یکی از مدل‌های پوشه‌ی cassettes
    reels, label = cfg.get("reels"), cfg.get("label")
    cc = cfg.get("cassette")
    cname = S.get("cassette", "")
    if cc and cname and cas_dir and os.path.exists(os.path.join(cas_dir, cname + ".json")):
        meta = json.load(open(os.path.join(cas_dir, cname + ".json"), encoding="utf-8"))
        cimg = Image.open(os.path.join(cas_dir, meta["image"])).convert("RGBA")
        x0, y0, x1, y1 = [int(v) for v in cc["clear"]]
        img = fill_lr(img, (x0, y0, x1, y1), [int(v) for v in cc["left"]], [int(v) for v in cc["right"]])
        cw = int(cc["width"]); ch = int(cimg.height * cw / cimg.width)
        cas = cimg.resize((cw, ch), LANCZOS)
        tint = meta.get("tint") or cc.get("tint")
        if tint:
            arr = np.asarray(cas, float)
            arr[..., :3] *= np.array(tint)
            cas = Image.fromarray(arr.clip(0, 255).astype("u1"), "RGBA")
        px, py = int(cc["center"][0] - cw / 2), int(cc["center"][1] - ch / 2)
        sh = cas.getchannel("A").filter(ImageFilter.GaussianBlur(3 * ss)).point(lambda v: int(v * .45))
        img.paste((30, 22, 16), (px, py + 2 * ss), sh)
        img.paste(cas, (px, py), cas)
        reels = {"centers": [(px + h[0] * cw, py + h[1] * ch) for h in meta["hubs"]], "radius": meta["hub_r"] * cw * .97}
        lx0, ly0, lx1, ly1 = meta["label"]
        label = {"box": [int(px + lx0 * cw), int(py + ly0 * ch), int(px + lx1 * cw), int(py + ly1 * ch)],
                 "paper_x": [int(px + meta["paper"][0] * cw), int(px + meta["paper"][1] * cw)], "k": .62}
    if label and S["label_on"]:
        img = fill_label(img, label["box"], label["paper_x"])
        x0, y0, x1, y1 = label["box"]
        if S["label"].strip():
            t = fit_text(text_fn, S["label"], fam_hand, (y1 - y0) * label.get("k", 1.05), S["col_ink"], (x1 - x0) * .94)
            t = t.filter(ImageFilter.GaussianBlur(.5 * ss))
            img.paste(t, (int(x0 + (x1 - x0 - (t.width - 12)) / 2 - 6), int(y0 + (y1 - y0 - (t.height - 8)) / 2 - 4)), t)
    st.base = img
    # ریل‌ها: تکه‌ی واقعی عکس می‌چرخد
    st.reels = []
    if reels:
        R = int(reels["radius"])
        D = 2 * (R + 3 * ss)
        mask = Image.new("L", (D * 4, D * 4), 0)
        ImageDraw.Draw(mask).ellipse([(D * 4 - R * 8) / 2, (D * 4 - R * 8) / 2, (D * 4 + R * 8) / 2, (D * 4 + R * 8) / 2], fill=255)
        mask = mask.resize((D, D), LANCZOS).filter(ImageFilter.GaussianBlur(.8 * ss))
        for cx, cy in reels["centers"]:
            bx, by = int(cx) - D // 2, int(cy) - D // 2
            patch = img.crop((bx, by, bx + D, by + D))
            rots = [patch.rotate(a, resample=Image.Resampling.BICUBIC) for a in range(0, 360, 3)]
            st.reels.append((bx, by, rots, mask))
    st.led = LED(led, S, img, ss) if led else None
    st.bg_src = img
    st.bg_cache = {}
    return st


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


# ---------------------------------------------------------------- نمای نهایی (کراپ/زوم با پس‌زمینه‌ی محو)
def view(img, W, H, S, st):
    iw, ih = img.size
    key = (W, H)
    if key not in st.bg_cache:
        k = max(W / iw, H / ih)
        bg = st.bg_src.resize((math.ceil(iw * k), math.ceil(ih * k)), LANCZOS)
        l, t = (bg.width - W) // 2, (bg.height - H) // 2
        bg = bg.crop((l, t, l + W, t + H)).filter(ImageFilter.GaussianBlur(28 * W / 1080))
        st.bg_cache[key] = bg.point(lambda v: int(v * .55))
    out = st.bg_cache[key].copy()
    z = max(1.0, S["zoom"])
    vw = iw / z
    vh = vw * H / W
    ox = min(max(S["cx"] * iw - vw / 2, 0), max(0, iw - vw))
    oy = S["cy"] * ih - vh / 2
    sc = W / vw
    ix0, iy0, ix1, iy1 = ox, max(0, oy), ox + vw, min(ih, oy + vh)
    dx0, dy0 = 0, int(round((iy0 - oy) * sc))
    dw, dh = W, max(2, int(round((iy1 - iy0) * sc)))
    fg = img.resize((dw, dh), LANCZOS, box=(ix0, iy0, ix1, iy1))
    m = np.ones((dh, dw), "f4")
    ramp = max(2, int(26 * W / 1080))
    if dy0 > 0:
        m[:ramp] *= np.linspace(0, 1, ramp)[:, None]
    if dy0 + dh < H:
        m[-ramp:] *= np.linspace(1, 0, ramp)[:, None]
    out.paste(fg, (dx0, dy0), Image.fromarray((m * 255).astype("u1"), "L"))
    return out


def render_frame(st, A, S, i, W, H, fps=FPS, prog=None):
    if prog is None:
        prog = i / max(1, A.n - 1)
    if S.get("pan"):
        e = prog * prog * (3 - 2 * prog)
        S = dict(S, cx=S["cx"] + (S["cx_end"] - S["cx"]) * e)
    img = st.base.copy()
    if st.led:
        img.paste(st.led.region(A, i), (st.led.ox, st.led.oy))
    if S["spin"]:
        idx = int(i / fps * S["spin_speed"] / 3) % 120
        for x, y, rots, mask in st.reels:
            img.paste(rots[idx], (x, y), mask)
    return view(img, W, H, S, st)
