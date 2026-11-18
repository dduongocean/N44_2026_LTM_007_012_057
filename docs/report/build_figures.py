#!/usr/bin/env python3
"""Vẽ lại các sơ đồ của báo cáo thành SVG và PNG (Arial, chữ 13 px, rộng 605 px = 16 cm).

Nguồn của từng hình:
  Hình 2.1, 2.2, 3.1, 4.1 : khối sơ đồ ASCII trong docs/report/noi-dung/*.txt
  Hình 3.2               : docs/diagrams/network-overview/network-overview.mmd
  Hình 3.3               : docs/diagrams/timesync-rtt/timesync-rtt.mmd
  Hình 5.1               : docs/diagrams/measure-loop/measure-loop.mmd
Chữ trong hình chép nguyên văn từ nguồn (chỉ đổi chỗ xuống dòng). Không cần mermaid-cli:
bố cục được tính trong script này, cùng một bố cục xuất ra cả SVG lẫn PNG (PNG vẽ bằng Pillow).

Chạy:  python docs/report/build_figures.py        (cần Pillow và font Arial)
Đầu ra: docs/report/hinh/hinh-x-y.svg, hinh-x-y.png (300 dpi). Không ghi vào docs/diagrams/.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "report" / "hinh"

# ---------------------------------------------------------------- hằng số trình bày
W = 605.0            # chiều rộng gốc (px) = khổ chữ 16 cm
FS = 13.0            # cỡ chữ mọi nhãn (px ở kích thước gốc)
LH = 16.25           # khoảng cách dòng
PAD = 8.0            # lề trong của khung
SEP_H = 9.0          # chiều cao vạch ngăn trong khung
DPI = 300
WIDTH_CM = 16.0
SS = 2               # vẽ PNG gấp đôi rồi thu nhỏ để khử răng cưa

INK = "#1a1a1a"
LINE = "#333333"
GRAY = "#4d4d4d"
WHITE = "#ffffff"
CONT_FILL = "#f4f4f4"
CONT_STROKE = "#7a7a7a"
ACC_FILL = "#e3eef9"      # màu nhấn duy nhất
ACC_STROKE = "#2b6cb0"

FONT_PATHS = {
    False: [r"C:\Windows\Fonts\arial.ttf",
            "/usr/share/fonts/truetype/msttcorefonts/Arial.ttf",
            "/usr/share/fonts/truetype/msttcorefonts/arial.ttf",
            "/usr/share/fonts/TTF/arial.ttf",
            "/Library/Fonts/Arial.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf"],
    True: [r"C:\Windows\Fonts\arialbd.ttf",
           "/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf",
           "/usr/share/fonts/truetype/msttcorefonts/arialbd.ttf",
           "/usr/share/fonts/TTF/arialbd.ttf",
           "/Library/Fonts/Arial Bold.ttf",
           "/System/Library/Fonts/Supplemental/Arial Bold.ttf"],
}
MACRON = "\u0304"


def _font_path(bold: bool) -> str:
    for p in FONT_PATHS[bold]:
        if Path(p).exists():
            return p
    sys.exit("Không tìm thấy font Arial (Ubuntu: sudo apt install ttf-mscorefonts-installer).")


_MEASURE = {b: ImageFont.truetype(_font_path(b), 130) for b in (False, True)}


def tw(s: str, bold: bool = False) -> float:
    """Chiều rộng chuỗi (px) ở cỡ FS."""
    return _MEASURE[bold].getlength(s.replace(MACRON, "")) / 130 * FS


NBSP = " "


def _glue_parens(text: str, maxlen: int = 22) -> str:
    """Giữ cụm ngắn trong ngoặc, ví dụ "(khác 0)", trên cùng một dòng."""
    out, i = [], 0
    while i < len(text):
        if text[i] == "(":
            j = text.find(")", i)
            if j != -1 and j - i <= maxlen:
                out.append(text[i:j + 1].replace(" ", NBSP))
                i = j + 1
                continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _split_long(word: str, maxw: float, bold: bool) -> list[str]:
    """Từ dài hơn khung: ngắt sau '.', '(' hoặc ',' (không đổi ký tự nào)."""
    parts, cur = [], ""
    for ch in word:
        cur += ch
        if ch in ".(," and tw(cur, bold) <= maxw:
            parts.append(cur)
            cur = ""
    parts.append(cur)
    lines, acc = [], ""
    for p in parts:
        if acc and tw(acc + p, bold) > maxw:
            lines.append(acc)
            acc = p
        else:
            acc += p
    if acc:
        lines.append(acc)
    return lines


def wrap(text: str, maxw: float, bold: bool = False, glue: bool = True) -> list[str]:
    """Ngắt dòng theo khoảng trắng, không cắt giữa từ (trừ từ dài hơn cả khung)."""
    words = (_glue_parens(text) if glue else text).split(" ")
    lines, cur = [], ""
    for w_ in words:
        cand = w_ if not cur else cur + " " + w_
        if tw(cand.replace(NBSP, " "), bold) <= maxw:
            cur = cand
            continue
        if cur:
            lines.append(cur)
        if tw(w_.replace(NBSP, " "), bold) > maxw:
            if NBSP in w_:
                pieces = wrap(w_.replace(NBSP, " "), maxw, bold, glue=False)
            else:
                pieces = _split_long(w_, maxw, bold)
            lines.extend(pieces[:-1])
            cur = pieces[-1]
        else:
            cur = w_
    if cur:
        lines.append(cur)
    return [l.replace(NBSP, " ") for l in lines]


# ---------------------------------------------------------------- mô hình bản vẽ
class Fig:
    def __init__(self):
        self.items: list[dict] = []
        self.h = 0.0

    def add(self, **kw):
        self.items.append(kw)
        if "y" in kw and "h" in kw:
            self.h = max(self.h, kw["y"] + kw["h"])
        for p in kw.get("pts", []):
            self.h = max(self.h, p[1])
        return kw

    # văn bản: lines = [(chuỗi, đậm)], top = mép trên khối chữ
    def text_block(self, lines, x, top, align="center", color=INK):
        for i, (s, b) in enumerate(lines):
            base = top + i * LH + LH / 2 + FS * 0.36
            w_ = tw(s, b)
            x0 = x - w_ / 2 if align == "center" else (x - w_ if align == "right" else x)
            self.add(kind="text", x=x0, y=base, s=s, bold=b, color=color)
        self.h = max(self.h, top + len(lines) * LH)

    def label(self, text, x, top, maxw, align="center", color=INK, bold=False, lines=None):
        ls = lines if lines is not None else wrap(text, maxw, bold)
        self.text_block([(l, bold) for l in ls], x, top, align, color)
        return len(ls) * LH

    def arrow(self, pts, end=True, start=False, sw=1.3, color=LINE, dash=False):
        self.add(kind="line", pts=[tuple(p) for p in pts], sw=sw, color=color, dash=dash,
                 head_end=end, head_start=start)

    # -------------------------------------------------------------- xuất SVG
    def svg(self) -> str:
        H = self.h + 2
        out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:g}" height="{H:.1f}" '
               f'viewBox="0 0 {W:g} {H:.1f}">',
               f'<rect x="0" y="0" width="{W:g}" height="{H:.1f}" fill="#ffffff"/>',
               '<g font-family="Arial, Helvetica, sans-serif">']
        for it in self.items:
            k = it["kind"]
            if k == "rect":
                dash = ' stroke-dasharray="5 3"' if it.get("dash") else ""
                out.append(f'<rect x="{it["x"]:.1f}" y="{it["y"]:.1f}" width="{it["w"]:.1f}" '
                           f'height="{it["h"]:.1f}" rx="{it["rx"]:.1f}" fill="{it["fill"]}" '
                           f'stroke="{it["stroke"]}" stroke-width="{it["sw"]}"{dash}/>')
            elif k == "poly":
                pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in it["pts"])
                out.append(f'<polygon points="{pts}" fill="{it["fill"]}" stroke="{it["stroke"]}" '
                           f'stroke-width="{it["sw"]}"/>')
            elif k == "circle":
                out.append(f'<circle cx="{it["cx"]:.1f}" cy="{it["cy"]:.1f}" r="{it["r"]:.1f}" '
                           f'fill="{it["fill"]}"/>')
            elif k == "line":
                pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in it["pts"])
                dash = ' stroke-dasharray="5 4"' if it["dash"] else ""
                out.append(f'<polyline points="{pts}" fill="none" stroke="{it["color"]}" '
                           f'stroke-width="{it["sw"]}" stroke-linejoin="round"{dash}/>')
                for head in _heads(it):
                    hp = " ".join(f"{x:.1f},{y:.1f}" for x, y in head)
                    out.append(f'<polygon points="{hp}" fill="{it["color"]}"/>')
            elif k == "text":
                s = (it["s"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
                wgt = ' font-weight="bold"' if it["bold"] else ""
                out.append(f'<text x="{it["x"]:.1f}" y="{it["y"]:.1f}" font-size="{FS:g}"{wgt} '
                           f'fill="{it["color"]}">{s}</text>')
        out.append("</g></svg>")
        return "\n".join(out) + "\n"

    # -------------------------------------------------------------- xuất PNG
    def png(self, path: Path):
        H = self.h + 2
        scale = DPI / 2.54 * WIDTH_CM / W        # px ảnh trên 1 px gốc
        k = scale * SS
        img = Image.new("RGB", (round(W * k), round(H * k)), "white")
        d = ImageDraw.Draw(img)
        fonts = {b: ImageFont.truetype(_font_path(b), round(FS * k)) for b in (False, True)}

        def P(p):
            return (p[0] * k, p[1] * k)

        for it in self.items:
            kd = it["kind"]
            if kd == "rect":
                box = [it["x"] * k, it["y"] * k, (it["x"] + it["w"]) * k, (it["y"] + it["h"]) * k]
                sw = max(1, round(it["sw"] * k))
                if it.get("dash"):
                    d.rounded_rectangle(box, radius=it["rx"] * k, fill=it["fill"])
                    x0, y0, x1, y1 = box
                    for a, b in [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)),
                                 ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]:
                        _dashed(d, a, b, it["stroke"], sw, 5 * k, 3 * k)
                else:
                    d.rounded_rectangle(box, radius=it["rx"] * k, fill=it["fill"],
                                        outline=it["stroke"], width=sw)
            elif kd == "poly":
                d.polygon([P(p) for p in it["pts"]], fill=it["fill"])
                pts = [P(p) for p in it["pts"]] + [P(it["pts"][0])]
                d.line(pts, fill=it["stroke"], width=max(1, round(it["sw"] * k)), joint="curve")
            elif kd == "circle":
                cx, cy, r = it["cx"] * k, it["cy"] * k, it["r"] * k
                d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=it["fill"])
            elif kd == "line":
                pts = [P(p) for p in it["pts"]]
                sw = max(1, round(it["sw"] * k))
                if it["dash"]:
                    for a, b in zip(pts, pts[1:]):
                        _dashed(d, a, b, it["color"], sw, 5 * k, 4 * k)
                else:
                    d.line(pts, fill=it["color"], width=sw, joint="curve")
                for head in _heads(it):
                    d.polygon([P(p) for p in head], fill=it["color"])
            elif kd == "text":
                _draw_text(d, it["x"] * k, it["y"] * k, it["s"], fonts[it["bold"]], it["color"], k)
        img = img.resize((round(W * scale), round(H * scale)), Image.LANCZOS)
        img.save(path, dpi=(DPI, DPI))


def _heads(it):
    heads = []
    pts = it["pts"]
    L, Wd = 9.0, 4.5
    if it["head_end"]:
        heads.append(_tri(pts[-2], pts[-1], L, Wd))
    if it["head_start"]:
        heads.append(_tri(pts[1], pts[0], L, Wd))
    return heads


def _tri(a, b, L, Wd):
    import math
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy) or 1
    ux, uy = dx / n, dy / n
    bx, by = b[0] - ux * L, b[1] - uy * L
    return [b, (bx - uy * Wd, by + ux * Wd), (bx + uy * Wd, by - ux * Wd)]


def _dashed(d, a, b, color, sw, on, off):
    import math
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy)
    if n == 0:
        return
    ux, uy = dx / n, dy / n
    t = 0.0
    while t < n:
        t2 = min(t + on, n)
        d.line([(a[0] + ux * t, a[1] + uy * t), (a[0] + ux * t2, a[1] + uy * t2)], fill=color, width=sw)
        t = t2 + off


def _draw_text(d, x, y, s, font, color, k):
    """Vẽ chữ theo đường chân chữ; tự vẽ dấu ngang trên (U+0304) vì Pillow không có raqm."""
    if MACRON not in s:
        d.text((x, y), s, font=font, fill=color, anchor="ls")
        return
    cur = x
    i = 0
    while i < len(s):
        ch = s[i]
        if i + 1 < len(s) and s[i + 1] == MACRON:
            w_ = font.getlength(ch)
            d.text((cur, y), ch, font=font, fill=color, anchor="ls")
            top = y - font.size * 0.86
            d.line([(cur + w_ * 0.12, top), (cur + w_ * 0.88, top)], fill=color,
                   width=max(1, round(font.size * 0.07)))
            cur += w_
            i += 2
        else:
            j = i
            while j < len(s) and not (j + 1 < len(s) and s[j + 1] == MACRON):
                j += 1
            seg = s[i:j]
            d.text((cur, y), seg, font=font, fill=color, anchor="ls")
            cur += font.getlength(seg)
            i = j


class Box:
    """Khung chữ. paras: list (chuỗi, đậm) hoặc 'SEP'. Chữ căn giữa (align='left' cho danh sách)."""

    def __init__(self, fig, x, y, w, paras, fill=WHITE, stroke=LINE, sw=1.2, rx=4.0,
                 align="center", shape="rect", minh=0.0):
        self.fig, self.x, self.y, self.w = fig, x, y, w
        self.fill, self.stroke, self.sw, self.rx = fill, stroke, sw, rx
        self.align, self.shape = align, shape
        self.inset = 18.0 if shape == "hex" else 0.0
        inner = w - 2 * PAD - 2 * self.inset
        self.lines = []          # (chuỗi, đậm) hoặc 'SEP'
        for p in paras:
            if p == "SEP":
                self.lines.append("SEP")
                continue
            text, bold = p
            hang = ""
            if align == "left" and text.startswith("• "):
                hang = "   "
            first = True
            for ln in wrap(text, inner - (tw(hang) if hang else 0), bold):
                self.lines.append(((ln if first else ln), bold, (hang and not first)))
                first = False
        ch = sum(SEP_H if l == "SEP" else LH for l in self.lines)
        self.h = max(ch + 2 * PAD, minh)
        if shape == "pill":
            self.rx = self.h / 2

    @property
    def cx(self): return self.x + self.w / 2
    @property
    def cy(self): return self.y + self.h / 2
    @property
    def right(self): return self.x + self.w
    @property
    def bottom(self): return self.y + self.h

    def draw(self):
        f = self.fig
        if self.shape == "hex":
            i = self.inset
            pts = [(self.x + i, self.y), (self.right - i, self.y), (self.right, self.cy),
                   (self.right - i, self.bottom), (self.x + i, self.bottom), (self.x, self.cy)]
            f.add(kind="poly", pts=pts, fill=self.fill, stroke=self.stroke, sw=self.sw, y=self.y, h=self.h)
        else:
            rx = self.h / 2 if self.shape == "pill" else self.rx
            f.add(kind="rect", x=self.x, y=self.y, w=self.w, h=self.h, rx=rx, fill=self.fill,
                  stroke=self.stroke, sw=self.sw)
        ch = sum(SEP_H if l == "SEP" else LH for l in self.lines)
        top = self.cy - ch / 2
        hang_w = tw("   ")
        for l in self.lines:
            if l == "SEP":
                yy = top + SEP_H / 2
                f.add(kind="line", pts=[(self.x + PAD, yy), (self.right - PAD, yy)], sw=0.8,
                      color=GRAY, dash=False, head_end=False, head_start=False)
                top += SEP_H
                continue
            s, b, hang = l
            if self.align == "left":
                f.text_block([(s, b)], self.x + PAD + self.inset + (hang_w if hang else 0), top, "left")
            else:
                f.text_block([(s, b)], self.cx, top, "center")
            top += LH


class Container:
    """Khung nhóm (nét đứt) có tiêu đề in đậm ở góc trên trái."""

    def __init__(self, fig, x, y, w, title, fill=CONT_FILL, stroke=CONT_STROKE, tx=None):
        self.fig, self.x, self.y, self.w, self.title = fig, x, y, w, title
        self.fill, self.stroke = fill, stroke
        self.tx = tx if tx is not None else x + PAD      # mép trái tiêu đề
        self.tlines = wrap(title, x + w - PAD - self.tx, True)
        self.top = y + 6 + len(self.tlines) * LH + 4     # mép trên vùng nội dung
        self.idx = len(fig.items)                        # chèn khung xuống dưới nội dung
        self.h = 0

    def close(self, bottom):
        self.h = bottom - self.y
        rect = dict(kind="rect", x=self.x, y=self.y, w=self.w, h=self.h, rx=6, fill=self.fill,
                    stroke=self.stroke, sw=1.1, dash=True)
        self.fig.items.insert(self.idx, rect)
        self.fig.h = max(self.fig.h, bottom)
        n0 = len(self.fig.items)
        self.fig.text_block([(t, True) for t in self.tlines], self.tx, self.y + 6, "left")
        added = self.fig.items[n0:]
        del self.fig.items[n0:]
        for j, it in enumerate(added):
            self.fig.items.insert(self.idx + 1 + j, it)

    @property
    def bottom(self): return self.y + self.h


def equal_h(*boxes):
    h = max(b.h for b in boxes)
    for b in boxes:
        b.h = h
    return h


# ---------------------------------------------------------------- Hình 2.1
def fig_2_1():
    f = Fig()
    bw = 196.0
    left = Box(f, 0, 0, bw, [("TRẠM MẶT ĐẤT (GCS)", True), ("người vận hành, máy tính", False)])
    right = Box(f, W - bw, 0, bw, [("XE (rover, autopilot PX4)", True),
                                   ("nhận lệnh, điều khiển động cơ", False),
                                   ("gửi trạng thái liên tục", False)])
    mx0, mx1 = bw, W - bw
    mcx, mw = (mx0 + mx1) / 2, mx1 - mx0 - 24
    l1 = wrap("lệnh: arm, đổi chế độ, lái", mw)
    l2 = wrap("trạng thái: vị trí, tốc độ", mw)
    nt = wrap("(bản tin MAVLink, truyền qua Wi-Fi)", mw)
    if len(nt) > 1:                       # ngắt ở dấu phẩy cho dễ đọc
        nt = ["(bản tin MAVLink,", "truyền qua Wi-Fi)"]
    stack = len(l1) * LH + 4 + 12 + len(l2) * LH + 4 + 12 + len(nt) * LH
    H = max(stack + 2 * 14, left.h, right.h)
    left.h = right.h = H
    left.draw(); right.draw()
    y = (H - stack) / 2
    f.label("", mcx, y, mw, lines=l1); y += len(l1) * LH + 4
    f.arrow([(mx0, y), (mx1, y)]); y += 12
    f.label("", mcx, y, mw, lines=l2); y += len(l2) * LH + 4
    f.arrow([(mx1, y), (mx0, y)]); y += 12
    f.label("", mcx, y, mw, lines=nt, color=GRAY)
    return f


# ---------------------------------------------------------------- Hình 2.2
def fig_2_2():
    f = Fig()
    bw = 128.0
    gap = (W - 4 * bw) / 3
    xs = [i * (bw + gap) for i in range(4)]
    m1 = Box(f, xs[0], 0, bw, [("M1: dựng hệ thống, gói tin không đi tắt", False)])
    m2 = Box(f, xs[1], 0, bw, [("M2: có công cụ đo đã kiểm chứng", False)])
    m3 = Box(f, xs[2], 0, bw, [("M3: đo theo khoảng cách", False)])
    m4 = Box(f, xs[2], 0, bw, [("M4: thử mất lệnh điều khiển", False)])
    a1 = Box(f, xs[3], 0, bw, [("bài toán khoảng cách tin cậy", False)], fill=ACC_FILL, stroke=ACC_STROKE)
    a2 = Box(f, xs[3], 0, bw, [("bài toán mất lệnh điều khiển", False)], fill=ACC_FILL, stroke=ACC_STROKE)
    h = equal_h(m1, m2, m3, m4, a1, a2)
    rowgap = 26.0
    m3.y = a1.y = 0
    m4.y = a2.y = h + rowgap
    m1.y = m2.y = (h + rowgap) / 2
    for b in (m1, m2, m3, m4, a1, a2):
        b.draw()
    f.arrow([(m1.right, m1.cy), (m2.x, m2.cy)])
    ex = m2.right + gap / 2
    f.arrow([(m2.right, m2.cy), (ex, m2.cy), (ex, m3.cy), (m3.x, m3.cy)])
    f.arrow([(ex, m2.cy), (ex, m4.cy), (m4.x, m4.cy)])
    f.arrow([(m3.right, m3.cy), (a1.x, a1.cy)])
    f.arrow([(m4.right, m4.cy), (a2.x, a2.cy)])
    return f


# ---------------------------------------------------------------- Hình 3.1
def fig_3_1():
    f = Fig()
    gap = 58.0
    bw = (W - 2 * gap) / 3
    a = Box(f, 0, 0, bw, [("VÙNG TRẠM (ns-gcs)", True), ("chương trình đo", False),
                          ("hoặc script lái xe", False), ("địa chỉ 10.0.0.1", False)])
    b = Box(f, bw + gap, 0, bw, [("VÙNG GIỮA (namespace chính)", True), ("ns-3: hai node Wi-Fi", False),
                                 ("cách nhau d mét", False)], fill=ACC_FILL, stroke=ACC_STROKE)
    c = Box(f, 2 * (bw + gap), 0, bw, [("VÙNG XE (ns-rover)", True), ("PX4 SITL + Gazebo", False),
                                       ("(xe gz_r1_rover)", False), ("địa chỉ 10.0.0.2", False)])
    equal_h(a, b, c)
    for x in (a, b, c):
        x.draw()
    f.arrow([(a.right + 2, a.cy), (b.x - 2, b.cy)], start=True, sw=2.2)
    f.arrow([(b.right + 2, b.cy), (c.x - 2, c.cy)], start=True, sw=2.2)
    return f


# ---------------------------------------------------------------- Hình 4.1
def fig_4_1():
    f = Fig()
    items = [
        ("khoảng cách d", None),
        ("suy hao PL(d)", "(4.2, công thức 4.1)"),
        ("công suất thu trung bình P\u0304rx(d)", "(4.2, công thức 4.3)"),
        ("fading: công suất từng khung dao động quanh P\u0304rx", "(4.2, công thức 4.4)"),
        ("so với ngưỡng θ = -82 dBm: khung nhận được hay không", "(4.2, công thức 4.5)"),
        ("tầng MAC phát mỗi khung tối đa 7 lần (1 lần đầu và tối đa 6 lần phát lại); "
         "mỗi khung tốn nhiều thời gian phục vụ hơn", "(4.3)"),
        ("hàng đợi: nếu kênh không phục vụ kịp thì khung chờ tới 500 ms rồi bị bỏ", "(4.3)"),
        ("các số đo: mất gói, RTT, jitter, mất kết nối, thông lượng", "(4.4)"),
        ("xếp loại tin cậy / suy giảm / không tin cậy", "(4.5)"),
    ]
    refw = max(tw(r) for _, r in items if r)
    bw, g = 400.0, 14.0
    x0 = (W - (bw + g + refw)) / 2
    y, prev = 0.0, None
    for i, (t, r) in enumerate(items):
        last = i == len(items) - 1
        bx = Box(f, x0, y, bw, [(t, False)],
                 fill=ACC_FILL if last else WHITE, stroke=ACC_STROKE if last else LINE)
        bx.draw()
        if r:
            f.text_block([(r, False)], bx.right + g, bx.cy - LH / 2, "left", GRAY)
        if prev:
            f.arrow([(prev.cx, prev.bottom), (bx.cx, bx.y)])
        prev = bx
        y = bx.bottom + 18
    return f


# ---------------------------------------------------------------- Hình 4.2 (mục 4.6, bảng 4.5)
def fig_4_2():
    """Dòng thời gian khi xe mất lệnh điều khiển: ba giai đoạn, hai mốc (4.27), (4.28)."""
    f = Fig()
    sw, gap = 195.0, 10.0
    ms = [0.0, sw + gap, 2 * (sw + gap)]
    ev = [Box(f, ms[0], 0, sw, [("t0", True), ("xe bắt đầu không nhận được lệnh lái", False)]),
          Box(f, ms[1], 0, sw, [("Phát hiện mất tín hiệu (4.27)", True), ("chuyển AUTO/LOITER và phanh", False)]),
          Box(f, ms[2], 0, sw, [("Return (4.28)", True),
                                ("chuyển AUTO/RTL, tự chạy về điểm xuất phát", False)])]
    equal_h(*ev)
    yb = ev[0].bottom + 26
    seg = [Box(f, ms[0], yb, sw, [("MANUAL", True), ("chạy theo lệnh lái cuối", False)]),
           Box(f, ms[1], yb, sw, [("AUTO/LOITER", True), ("phanh rồi đứng yên", False)],
               fill=ACC_FILL, stroke=ACC_STROKE),
           Box(f, ms[2], yb, sw, [("AUTO/RTL", True), ("tự chạy về, tối đa 2 m/s", False)],
               fill=CONT_FILL)]
    equal_h(*seg)
    yax = seg[0].bottom + 18
    for b in ev + seg:
        b.draw()
    for m in ms:                                           # mốc thời gian: từ khung sự kiện xuống trục
        f.arrow([(m + 1, ev[0].bottom), (m + 1, yax + 5)], end=False, sw=1.0, color=GRAY, dash=True)
    f.arrow([(0, yax), (W - 1, yax)], sw=1.4)
    f.label("thời gian", W - 2, yax + 4, 0, align="right", lines=["thời gian"], color=GRAY)
    ybr = yax + 26
    spans = [(ms[0], ms[1], ["COM_RC_LOSS_T = 0,5 s + ε", "xe đi thêm quãng đường (4.29)"]),
             (ms[1], ms[2], ["COM_FAIL_ACT_T = 5 s", "xe đứng yên"])]
    for a, c, lines in spans:
        f.arrow([(a + 3, ybr), (c - 3, ybr)], start=True, sw=1.1)
        f.label("", (a + c) / 2, ybr + 4, 0, lines=lines)
    f.label("", ms[2] + sw / 2, ybr + 4, 0, color=GRAY,
            lines=["(không theo tỉ lệ thời gian)"])
    return f


# ---------------------------------------------------------------- Hình 3.3 (timesync-rtt.mmd)
def fig_3_3():
    f = Fig()
    xs = [95.0, W / 2, W - 95.0]
    hw = 180.0
    heads = [Box(f, x - hw / 2, 0, hw, [(t, True)]) for x, t in zip(
        xs, ["Trạm (chương trình đo, ns-gcs)", "ns-3 (kênh Wi-Fi)", "PX4 (xe, ns-rover)"])]
    equal_h(*heads)
    for h in heads:
        h.draw()
    y = heads[0].bottom + 18
    nw = 182.0
    seq = [
        ("note", 0, ["mỗi 0,2 s (5 probe/giây)", "ghi: probe i gửi lúc t_gửi,i (đồng hồ trạm)"]),
        ("msg", 0, 1, ["TIMESYNC (tc1 = 0, ts1 = i)"]),
        ("msg", 1, 2, ["chuyển khung", "(có thể trễ hoặc mất)"]),
        ("note", 2, ["giữ nguyên ts1 = i", "điền tc1 = giờ của xe (khác 0)"]),
        ("msg", 2, 1, ["TIMESYNC (tc1 ≠ 0, ts1 = i)"]),
        ("note", 1, ["xếp sau telemetry trong hàng đợi phía xe"]),
        ("msg", 1, 0, ["chuyển khung", "(có thể trễ hoặc mất)"]),
        ("note", 0, ["nhận lúc t_nhận,i (đọc mỗi 10 ms)", "RTT_i = t_nhận,i − t_gửi,i"]),
        ("note", 0, ["không có phản hồi sau 2 s", "thì probe i tính là mất"]),
    ]
    later = []
    n = 0
    for ev in seq:
        if ev[0] == "note":
            _, who, paras = ev
            b = Box(f, xs[who] - nw / 2, y, nw, [(p, False) for p in paras], fill=ACC_FILL,
                    stroke=ACC_STROKE)
            later.append(b)
            y = b.bottom + 14
        else:
            _, a, c, lab = ev
            n += 1
            lines = []
            for p in lab:
                lines += wrap(p, abs(xs[c] - xs[a]) - 30)
            mid = (xs[a] + xs[c]) / 2
            f.label("", mid, y, 0, lines=lines)
            y += len(lines) * LH + 6
            later.append(("arrow", xs[a], xs[c], y, n))
            y += 18
    bottom = y
    for x in xs:   # đường đời
        f.arrow([(x, heads[0].bottom), (x, bottom)], end=False, sw=1.0, color=GRAY, dash=True)
    for it in later:
        if isinstance(it, Box):
            it.draw()
        else:
            _, xa, xc, yy, num = it
            sgn = 1 if xc > xa else -1
            f.arrow([(xa, yy), (xc - sgn * 1.5, yy)])
            f.add(kind="circle", cx=xa + sgn * 12, cy=yy, r=8.5, fill=LINE)
            f.text_block([(str(num), True)], xa + sgn * 12, yy - LH / 2, "center", WHITE)
    f.h = bottom
    return f


# ---------------------------------------------------------------- Hình 3.2 (network-overview.mmd)
def fig_3_2():
    f = Fig()
    gap = 112.0                     # khe giữa hai cột (chứa nhãn mũi tên)
    vgap = 36.0                     # khe giữa hai khung lớn (chứa nhãn "Cặp cáp ảo veth")
    tgap = 46.0                     # khe chứa nhãn TapBridge
    sx0, sx1 = 8.0, W - 8.0         # khung con trong HOST
    ix0, ix1 = sx0 + 8, sx1 - 8     # vùng đặt khối trong khung con
    bw3 = max(tw("(Chuyển mạch Ethernet L2)"), tw("Tọa độ: (distance, 0.0, 0.0)"),
              tw("Ghost Node 1 (Rover)", True)) + 2 * PAD + 6
    xv = ix0 + bw3 / 2              # đường cặp veth (hai phía) chạy dọc tại x này
    ttx = xv + 14                   # tiêu đề khung có mũi tên đi qua: đặt sau mũi tên
    lw = 215.0                      # cột trái hàng A và C
    rw = W - 16 - lw - gap          # cột phải

    # Hàng A: ns-gcs
    cA = Container(f, 0, 0, W, "Network Namespace: ns-gcs (Trạm mặt đất)")
    veth_gcs = Box(f, 8, cA.top, lw, [("Cổng mạng veth-gcs", False),
                                      ("IP: 10.0.0.1/24 | MAC: 02:00:00:00:00:01 (cố định)", False)])
    app = Box(f, W - 8 - rw, cA.top, rw, [("Chương trình đo (run_experiment.py)", False),
                                          ("hoặc Lái thử (drive_check.py)", False),
                                          ("IP: 10.0.0.1 | Port: 14540 (UDP)", False)])
    equal_h(veth_gcs, app)
    veth_gcs.draw(); app.draw()
    cA.close(veth_gcs.bottom + 8)
    lab = wrap("Socket UDP / Linux IP Stack", gap - 14)
    f.label("", (veth_gcs.right + app.x) / 2, veth_gcs.cy - 4 - len(lab) * LH, 0, lines=lab)
    f.arrow([(veth_gcs.right, veth_gcs.cy), (app.x, app.cy)], start=True)

    # HOST
    cH = Container(f, 0, cA.bottom + vgap, W, "Namespace chính của máy (Linux Host OS)", tx=ttx)
    mid3 = (ix0 + ix1) / 2 - bw3 / 2

    def bridge_row(title, y, order, tx=None):
        c = Container(f, sx0, y, sx1 - sx0, title, tx=tx)
        bxs = [Box(f, x, c.top, bw3, paras) for x, paras in zip((ix0, mid3, ix1 - bw3), order)]
        equal_h(*bxs)
        for b in bxs:
            b.draw()
        f.arrow([(bxs[0].right, bxs[0].cy), (bxs[1].x, bxs[1].cy)], end=False)
        f.arrow([(bxs[1].right, bxs[1].cy), (bxs[2].x, bxs[2].cy)], end=False)
        c.close(bxs[0].bottom + 8)
        return c, bxs

    cG, (veth_gcs_br, br_gcs, tap_gcs) = bridge_row(
        "Cầu nối mạng phía GCS", cH.top,
        [[("Cổng veth-gcs-br", False)],
         [("Linux Bridge: br-gcs", False), ("(Chuyển mạch Ethernet L2)", False)],
         [("Cổng TAP ảo: tap-gcs", False), ("(Chế độ promisc on)", False)]], tx=ttx)
    f.arrow([(xv, veth_gcs.bottom), (xv, veth_gcs_br.y)], start=True, sw=2.2)
    f.label("Cặp cáp ảo veth (veth pair)", xv + 10, (cA.bottom + cH.y) / 2 - LH / 2, 400, align="left")

    # ns-3
    cN = Container(f, sx0, cG.bottom + tgap, sx1 - sx0, "ns-3 Realtime Simulation Engine (rover-wifi)",
                   fill=ACC_FILL, stroke=ACC_STROKE)
    wgap = 116.0
    gx = ix1 - bw3
    wifi = Box(f, ix0, cN.top, gx - wgap - ix0, [
        ("Kênh truyền vô tuyến ns-3 (YansWifiChannel)", True), "SEP",
        ("• Chuẩn: 802.11g Ad-hoc (AdhocWifiMac)", False),
        ("• Tốc độ: ErpOfdmRate6Mbps", False),
        ("• Suy hao: LogDistance (n = 3.0, L0 = 40.046 dB)", False),
        ("• Fading: Nakagami (m = 1.5)", False),
        ("• Ngưỡng thu: -82 dBm", False),
        ("• Trễ truyền sóng: ConstantSpeed", False),
        ("• Khoảng cách đo: d = 10 đến 100 m", False),
        ("• Gửi lại MAC: tối đa 7 lần; hàng đợi 500 gói, MaxDelay 500 ms", False)], align="left")
    g0 = Box(f, gx, cN.top, bw3, [("Ghost Node 0 (GCS)", True), ("WifiNetDevice (802.11g)", False),
                                  ("Tọa độ: (0.0, 0.0, 0.0)", False)])
    g1 = Box(f, gx, cN.top, bw3, [("Ghost Node 1 (Rover)", True), ("WifiNetDevice (802.11g)", False),
                                  ("Tọa độ: (distance, 0.0, 0.0)", False)])
    equal_h(g0, g1)
    span = max(wifi.h, 2 * g0.h + 2 * LH + 12)
    wifi.h = span
    g1.y = cN.top + span - g1.h
    wifi.draw(); g0.draw(); g1.draw()
    for g in (g0, g1):
        lab = wrap("Khung vô tuyến 802.11", wgap - 14)
        f.label("", (wifi.right + g.x) / 2, g.cy - 4 - len(lab) * LH, 0, lines=lab)
        f.arrow([(wifi.right, g.cy), (g.x, g.cy)], start=True)
    cN.close(wifi.bottom + 8)

    def tapbridge(x, ytop, ybot, gap_top, gap_bot):
        f.arrow([(x, ytop), (x, ybot)], start=True)
        f.label("", x - 10, (gap_top + gap_bot) / 2 - LH, 0, align="right",
                lines=["TapBridge (UseLocal)", "Chuyển khung Ethernet"])

    tapbridge(tap_gcs.cx, tap_gcs.bottom, g0.y, cG.bottom, cN.y)

    cR, (veth_rover_br, br_rover, tap_rover) = bridge_row(
        "Cầu nối mạng phía Rover", cN.bottom + tgap,
        [[("Cổng veth-rover-br", False)],
         [("Linux Bridge: br-rover", False), ("(Chuyển mạch Ethernet L2)", False)],
         [("Cổng TAP ảo: tap-rover", False), ("(Chế độ promisc on)", False)]])
    tapbridge(tap_rover.cx, g1.bottom, tap_rover.y, cN.bottom, cR.y)
    cH.close(cR.bottom + 8)

    # Hàng C: ns-rover
    cC = Container(f, 0, cH.bottom + vgap, W, "Network Namespace: ns-rover (Xe Rover PX4)", tx=ttx)
    veth_rover = Box(f, 8, cC.top, lw, [("Cổng mạng veth-rover", False),
                                        ("IP: 10.0.0.2/24 | MAC: 02:00:00:00:00:02 (cố định)", False)])
    logger = Box(f, 8, 0, lw, [("failsafe_logger.py (NET-04)", False),
                               ("nghe 127.0.0.1:14550, ghi vị trí xe", False)])
    px4 = Box(f, W - 8 - rw, cC.top, rw, [
        ("PX4 SITL + Gazebo gz-sim 8 (gz_r1_rover)", False), ("IP: 10.0.0.2", False),
        ("• UDP 14581 -> 10.0.0.1:14540 (Onboard, qua ns-3)", False),
        ("• UDP 18570 -> 127.0.0.1:14550 (nội bộ ns-rover, không qua ns-3)", False)], align="left")
    px4.h = max(px4.h, veth_rover.h + 18 + logger.h)
    logger.y = cC.top + px4.h - logger.h
    veth_rover.draw(); logger.draw(); px4.draw()
    cC.close(px4.bottom + 8)
    f.arrow([(xv, veth_rover_br.bottom), (xv, veth_rover.y)], start=True, sw=2.2)
    f.label("Cặp cáp ảo veth (veth pair)", xv + 10, (cH.bottom + cC.y) / 2 - LH / 2, 400, align="left")
    mx = (veth_rover.right + px4.x) / 2
    lab = wrap("Socket UDP / Linux IP Stack", gap - 14)
    f.label("", mx, veth_rover.cy - 4 - len(lab) * LH, 0, lines=lab)
    f.arrow([(veth_rover.right, veth_rover.cy), (px4.x, veth_rover.cy)], start=True)
    lab = wrap("lo của ns-rover", gap - 14)
    f.label("", mx, logger.cy - 4 - len(lab) * LH, 0, lines=lab)
    f.arrow([(px4.x, logger.cy), (logger.right, logger.cy)])
    return f


# ---------------------------------------------------------------- Hình 5.1 (measure-loop.mmd)
def fig_5_1():
    f = Fig()
    mx0, mw = 60.0, 270.0
    mcx = mx0 + mw / 2
    sx0 = 400.0
    sw_ = W - sx0
    G = 26.0      # khoảng cách giữa hai khối liên tiếp
    GL = 44.0     # khoảng cách khi có nhãn và đường nhập
    main = lambda y, paras, shape="rect", **kw: Box(f, mx0, y, mw, paras, shape=shape, **kw)
    side = lambda y, paras, **kw: Box(f, sx0, y, sw_, paras, **kw)

    start = main(0, [("Bắt đầu: đọc tham số --duration, --label, --probe-hz, ...", False)], "pill")
    init = main(start.bottom + G, [("Mở socket MAVLink udpin:0.0.0.0:14540", False),
                                   ("Tạo LinkMonitor, SeqTracker, RttTracker, IntervalStats", False),
                                   ("Ghi phần đầu file data/raw/<label>.csv", False)])
    loop = main(init.bottom + G, [("Đã hết thời gian đo", False), ("hoặc nhấn Ctrl+C?", False)], "hex",
                fill=ACC_FILL, stroke=ACC_STROKE)
    poll = main(loop.bottom + GL - 10, [("(1) poll(): đọc mọi bản tin đang chờ trên socket", False)])
    ev = main(poll.bottom + G, [("Loại sự kiện?", False)], "hex", fill=ACC_FILL, stroke=ACC_STROKE)
    bx0, bg = 40.0, 20.0
    bw3 = (W - bx0 - 2 * bg) / 3
    ytri = ev.bottom + 34
    hb = Box(f, bx0, ytri, bw3, [("HEARTBEAT:", False), ("LinkMonitor ghi thời điểm", False),
                                 ("IntervalStats ghi khoảng cách 2 nhịp", False)])
    ps = Box(f, bx0 + bw3 + bg, ytri, bw3, [("Bản tin bất kỳ của xe:", False),
                                            ("SeqTracker.on_packet(nguồn, seq)", False)])
    ts = Box(f, bx0 + 2 * (bw3 + bg), ytri, bw3, [("TIMESYNC phản hồi (tc1 ≠ 0):", False),
                                                  ("RttTracker.on_reply(mã probe = ts1, now)", False)])
    equal_h(hb, ps, ts)
    state = main(hb.bottom + 34, [("(2) Trạng thái chuyển", False), ("sang LOST? (quá 3 s", False),
                                  ("không có HEARTBEAT)", False)], "hex", fill=ACC_FILL, stroke=ACC_STROKE)
    probe = main(state.bottom + GL, [("(3) Đến lúc gửi probe?", False), ("(mỗi 1/probe_hz giây)", False)],
                 "hex", fill=ACC_FILL, stroke=ACC_STROKE)
    exp = main(probe.bottom + GL, [("(4) RttTracker.expire(now):", False),
                                   ("probe chờ quá 2 s tính là mất", False)])
    sec = main(exp.bottom + G, [("(5) Tròn thêm 1 giây?", False)], "hex", fill=ACC_FILL, stroke=ACC_STROKE)
    sleep = main(sec.bottom + GL, [("Ngủ 10 ms", False)])
    cnt = side(0, [("lost_events += 1", False)])
    send = side(0, [("Gửi TIMESYNC tc1 = 0, ts1 = mã probe", False), ("RttTracker ghi thời điểm gửi", False)])
    row = side(0, [("Tính RTT tb, p95, jitter; ghi 1 dòng CSV", False)])
    fin = side(0, [("Tính chỉ số tổng kết", False),
                   ("Ghi 1 dòng vào summary.csv (nối thêm, không ghi đè)", False)])
    stop = Box(f, sx0, 0, sw_, [("Kết thúc", False)], shape="pill")
    for s_, d_ in ((cnt, state), (send, probe), (row, sec), (fin, loop)):
        s_.y = d_.cy - s_.h / 2
    stop.y = fin.bottom + G
    for b in (start, init, loop, poll, ev, hb, ps, ts, state, probe, exp, sec, sleep,
              cnt, send, row, fin, stop):
        b.draw()

    def down(a, b, label=None):
        f.arrow([(mcx, a.bottom), (mcx, b.y)])
        if label:
            f.label(label, mcx + 8, a.bottom + 2, 200, align="left")

    def right(a, b, label):
        f.arrow([(a.right, a.cy), (b.x, b.cy)])
        lines = wrap(label, b.x - a.right - 10)
        f.label("", (a.right + b.x) / 2, a.cy - 4 - len(lines) * LH, 0, lines=lines)

    def merge(s_, tgt, ymid):
        f.arrow([(s_.cx, s_.bottom), (s_.cx, ymid), (mcx, ymid), (mcx, tgt.y)])

    down(start, init); down(init, loop)
    down(loop, poll, "Chưa"); down(poll, ev)
    right(loop, fin, "Rồi")
    f.arrow([(fin.cx, fin.bottom), (fin.cx, stop.y)])
    bus1 = ev.bottom + 17
    for b in (hb, ps, ts):
        f.arrow([(mcx, ev.bottom), (mcx, bus1), (b.cx, bus1), (b.cx, b.y)])
    bus2 = hb.bottom + 17
    for b in (hb, ps, ts):
        f.arrow([(b.cx, b.bottom), (b.cx, bus2), (mcx, bus2), (mcx, state.y)])
    right(state, cnt, "Có"); down(state, probe, "Không")
    merge(cnt, probe, probe.y - 12)
    right(probe, send, "Có, đã thấy xe"); down(probe, exp, "Không")
    merge(send, exp, exp.y - 12)
    down(exp, sec)
    right(sec, row, "Có"); down(sec, sleep, "Không")
    merge(row, sleep, sleep.y - 12)
    xl = 20.0
    f.arrow([(mx0, sleep.cy), (xl, sleep.cy), (xl, loop.cy), (mx0, loop.cy)])
    return f


FIGURES = {
    "2-1": fig_2_1, "2-2": fig_2_2, "3-1": fig_3_1, "3-2": fig_3_2,
    "3-3": fig_3_3, "4-1": fig_4_1, "4-2": fig_4_2, "5-1": fig_5_1,
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for key, fn in FIGURES.items():
        fig = fn()
        (OUT / f"hinh-{key}.svg").write_text(fig.svg(), encoding="utf-8")
        fig.png(OUT / f"hinh-{key}.png")
        print(f"hinh-{key}: {W:g} x {fig.h:.0f} px ({WIDTH_CM:g} x {fig.h / W * WIDTH_CM:.1f} cm)")


if __name__ == "__main__":
    main()
