#!/usr/bin/env python3
"""Dựng báo cáo Word docs/report/bao-cao-cuoi-ky.docx từ các bản nháp docs/report/noi-dung/*.txt.

Chỉ chuyển định dạng: chữ lấy nguyên văn từ file nháp. Các ngoại lệ có chủ đích:
  1. Dòng "Ý chính: ..." (nếu còn) bỏ cụm "Ý chính: " và viết hoa chữ cái đầu.
  2. Bảng chưa được nhắc ở đoạn ngay trước nó: thêm một câu dẫn (LEAD_INS bên dưới), tô xanh lá.
  3. Công thức (4.x) và ký hiệu toán viết bằng công thức Word (OMML) theo docs/report/cong-thuc.tex.
  4. Các chỗ chừa nguồn [CẦN NGUỒN...] không đưa vào báo cáo.
  5. "MỤC x." thành "Chương x:"; "Bảng ký hiệu" cuối chương 4 và 00-thuat-ngu.txt được chuyển lên
     "Danh sách các ký hiệu, chữ viết tắt".
Bố cục theo mẫu của trường: A4, lề trái 3, phải 2, trên 2,5, dưới 2,5 cm; header (tên đề tài) và footer
(sinh viên, giảng viên, số trang) cách mép 1,6 cm; đánh số trang từ Chương 1.

Cần: python-docx, lxml, latex2mathml, Pillow (cài vào venv riêng, không cài vào venv dự án).
Đổi MathML sang OMML cần file MML2OMML.XSL của Microsoft Office (tự tìm trong thư mục Office;
trên Linux chép file này từ một máy có Office rồi đặt biến môi trường MML2OMML_XSL).

Chạy:
  python docs/report/build_figures.py          # vẽ lại hình vào docs/report/hinh/
  python docs/report/build_docx.py             # dựng docx; có Word (Windows) thì cập nhật mục lục và xuất PDF
  python docs/report/build_docx.py --no-word   # chỉ dựng docx (Word sẽ hỏi cập nhật trường khi mở)
"""
from __future__ import annotations

import argparse
import os
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_COLOR_INDEX, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from lxml import etree
from PIL import Image
import latex2mathml.converter

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "docs" / "report" / "noi-dung"
HINH = ROOT / "docs" / "report" / "hinh"
TEX = ROOT / "docs" / "report" / "cong-thuc.tex"
OUT = ROOT / "docs" / "report" / "bao-cao-cuoi-ky.docx"

SECTIONS = ["02-cap-thiet-y-nghia.txt", "03-kien-truc-thiet-ke.txt", "04-mo-hinh-toan.txt",
            "05-trien-khai.txt", "06-phan-tich-hieu-nang.txt", "07-ket-luan.txt"]
MEMBERS_FALLBACK = ["Vũ Duy Dương", "Trương Nhật Hoàng", "Đinh Trần Thảo Phương"]

# Câu dẫn cho bảng chưa được nhắc ở đoạn ngay trước (nội dung do người dựng viết, tô xanh lá để nhóm duyệt).
LEAD_INS = {
    "4.1": "Bảng 4.1 liệt kê các tham số được giữ cố định, kèm giá trị và nguồn của từng tham số.",
    "4.6": "Bảng 4.6 liệt kê bảy dự đoán của mô hình và công thức mà mỗi dự đoán dựa trên.",
    "5.3": "Bảng 5.3 trình bày các kênh MAVLink của PX4 trong ns-rover và việc dùng từng kênh.",
    "6.2": "Bảng 6.2 trình bày kết quả thí nghiệm A ở từng khoảng cách, đặt cạnh baseline.",
    "6.3": "Bảng 6.3 so sánh mất gói theo mô hình hết lượt phát (4.9) với mất gói đo được.",
    "6.4": "Bảng 6.4 so sánh kênh không fading (thí nghiệm B) với kênh có fading (thí nghiệm A).",
}

# Hình vẽ lại bởi build_figures.py (từ ASCII hoặc Mermaid)
DRAWN = {"2.1", "2.2", "3.1", "3.2", "3.3", "4.1", "4.2", "5.1"}
FIRST_INDENT_CM = 1.0     # thụt đầu dòng đoạn văn
FIG_W_CM = 0.75 * 16.0    # ảnh rộng 75% khổ chữ (trang dọc)

# ---------------------------------------------------------------- định dạng
FONT = "Times New Roman"
BODY_PT = 13
TABLE_PT = 11
CODE_FONT = "Consolas"
CODE_PT = 10
TEXT_W_CM = 16.0          # khổ chữ dọc: 21 − 3 − 2
TEXT_W_LAND_CM = 24.7     # khổ chữ ngang: 29,7 − 2,5 − 2,5
TEXT_H_CM = 24.7          # chiều cao vùng chữ dọc: 29,7 − 2,5 − 2,5
HF_PT = 10                # cỡ chữ header, footer

# Chữ viết tắt trong 00-thuat-ngu.txt (phần còn lại là thuật ngữ)
ABBREV = {"ACK", "ARP", "CSV", "dBm", "DCF", "GCS", "IPv6", "MAC (tầng)", "MAC (địa chỉ)", "MAVLink",
          "netem", "netns", "ns-3", "p95", "pcap", "RTT", "SITL", "SNR", "UDP", "veth"}

# Chỗ chừa nguồn [CẦN NGUỒN...] không đưa vào báo cáo (theo yêu cầu nhóm)
STRIP_CAN_NGUON = re.compile(r"\s*\[CẦN NGUỒN(?::[^\]]*)?\]")
CAN_NGUON = re.compile(r"\[CẦN NGUỒN(?::[^\]]*)?\]")
NBSP_PM = " ± "     # " ± " với khoảng trắng không ngắt
LEFTOVER = re.compile(r"\[(?:BẢNG|HÌNH)(?::[^\]]*)?\]")
MATH_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"

STATS = {"y_chinh": 0, "lead_ins": [], "yellow": [], "inline_math": 0, "display_math": 0,
         "leftover_labels": [], "fig_mention": [], "table_mention": [], "figures": []}


# ================================================================ OMML
def _find_xsl() -> Path:
    env = os.environ.get("MML2OMML_XSL")
    cands = [env] if env else []
    for base in (r"C:\Program Files\Microsoft Office", r"C:\Program Files (x86)\Microsoft Office"):
        for sub in ("root\\Office16", "Office16", "root\\Office15", "Office15", "Office14"):
            cands.append(os.path.join(base, sub, "MML2OMML.XSL"))
    for c in cands:
        if c and Path(c).exists():
            return Path(c)
    sys.exit("Không tìm thấy MML2OMML.XSL (Microsoft Office). Đặt biến môi trường MML2OMML_XSL.")


_XSLT = None


def omml(latex: str, size_pt: float) -> etree._Element:
    """LaTeX -> m:oMath (kèm cỡ chữ)."""
    global _XSLT
    if _XSLT is None:
        _XSLT = etree.XSLT(etree.parse(str(_find_xsl())))
    # latex2mathml làm mất kiểu chữ đứng của \mathrm{x} một ký tự: dùng \text cho tên/đơn vị đơn giản
    latex = re.sub(r"\\mathrm\{([^{}\\^_]+)\}", r"\\text{\1}", latex)
    mml = etree.fromstring(latex2mathml.converter.convert(latex).encode("utf-8"))
    mns = "{http://www.w3.org/1998/Math/MathML}"
    for el in list(mml.iter(f"{mns}mi")):
        if el.get("mathvariant") == "normal":      # MML2OMML bỏ qua mathvariant: đổi sang chữ đứng
            el.tag = f"{mns}mtext"
            del el.attrib["mathvariant"]
    for el in list(mml.iter(f"{mns}mspace")):        # MML2OMML bỏ mspace: thay bằng khoảng trắng thật
        w = el.get("width", "")
        el.tag = f"{mns}mtext"
        el.attrib.clear()
        el.text = " " if w.startswith(("1em", "2em")) else " "
    om = _XSLT(mml).getroot()
    for jc in om.iter(f"{{{MATH_NS}}}mcJc"):          # các cột của {cases} canh trái
        jc.set(f"{{{MATH_NS}}}val", "left")
    for r in om.iter(f"{{{MATH_NS}}}r"):
        old = r.find(qn("w:rPr"))
        if old is not None:
            r.remove(old)
        rpr = etree.Element(qn("w:rPr"))
        fonts = etree.SubElement(rpr, qn("w:rFonts"))
        for a in ("w:ascii", "w:hAnsi"):
            fonts.set(qn(a), "Cambria Math")
        for tag in ("w:sz", "w:szCs"):
            etree.SubElement(rpr, qn(tag)).set(qn("w:val"), str(int(size_pt * 2)))
        mrpr = r.find(f"{{{MATH_NS}}}rPr")
        r.insert(1 if mrpr is not None else 0, rpr)       # thứ tự: m:rPr, w:rPr, m:t
    return om


# ================================================================ cong-thuc.tex
def load_tex():
    formulas, notes, sym, cell = {}, {}, {}, {}
    for ln in TEX.read_text(encoding="utf-8").splitlines():
        if not ln.strip() or ln.startswith("%"):
            continue
        parts = ln.split("\t")
        key = parts[0]
        if key == "sym":
            sym[parts[1]] = parts[2]
        elif key == "cell":
            cell[parts[1]] = parts[2]
        elif len(parts) == 3 and parts[1] == "@":
            notes[key] = parts[2]
        else:
            formulas.setdefault(key, []).append(parts[1])
    return formulas, notes, sym, cell


FORMULAS, FNOTES, SYM, CELLSYM = load_tex()
_SYM_RE = re.compile(
    r"(?<![\w\[\]_.*^/\-])(" + "|".join(re.escape(k) for k in sorted(SYM, key=len, reverse=True))
    + r")(?![\w_^*])")


# ================================================================ tiện ích docx
def set_run_font(run, name=FONT, size=None, bold=None, italic=None):
    run.font.name = name
    rpr = run._r.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        rpr.insert(0, rf)
    for a in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rf.set(qn(a), name)
    if size:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if italic is not None:
        run.font.italic = italic


def style_font(style, name=FONT, size=None, bold=None, italic=None, color=RGBColor(0, 0, 0)):
    f = style.font
    f.name = name
    if size:
        f.size = Pt(size)
    if bold is not None:
        f.bold = bold
    if italic is not None:
        f.italic = italic
    if color is not None:
        f.color.rgb = color
    rpr = style.element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        rpr.insert(0, rf)
    for a in list(rf.attrib):
        if a.endswith("Theme"):
            del rf.attrib[a]
    for a in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rf.set(qn(a), name)


def add_field(p, instr: str, result: str = "", size=None, bold=None):
    def r_(child):
        r = p.add_run()
        set_run_font(r, size=size, bold=bold)
        r._r.append(child)
        return r
    b = OxmlElement("w:fldChar"); b.set(qn("w:fldCharType"), "begin"); r_(b)
    it = OxmlElement("w:instrText"); it.set(qn("xml:space"), "preserve"); it.text = instr; r_(it)
    s = OxmlElement("w:fldChar"); s.set(qn("w:fldCharType"), "separate"); r_(s)
    r = p.add_run(result); set_run_font(r, size=size, bold=bold)
    e = OxmlElement("w:fldChar"); e.set(qn("w:fldCharType"), "end"); r_(e)


def shade(cell, fill):
    tcpr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), fill)
    tcpr.append(shd)


def set_frame(p, w_cm):
    """Khung nổi (w:framePr): rộng w_cm, canh giữa, ở mép trên vùng chữ, chữ không chạy hai bên.
    Các đoạn liền nhau có framePr giống nhau được Word gộp vào cùng một khung."""
    ppr = p._p.get_or_add_pPr()
    fp = OxmlElement("w:framePr")
    fp.set(qn("w:w"), str(int(w_cm / 2.54 * 1440)))
    fp.set(qn("w:hSpace"), "0")
    fp.set(qn("w:vSpace"), "284")                 # 0,5 cm cách phần chữ bên dưới
    fp.set(qn("w:wrap"), "notBeside")
    fp.set(qn("w:vAnchor"), "margin")
    fp.set(qn("w:hAnchor"), "margin")
    fp.set(qn("w:xAlign"), "center")
    fp.set(qn("w:yAlign"), "top")
    idx = 0
    for i, ch in enumerate(ppr):
        if ch.tag in (qn("w:pStyle"), qn("w:keepNext"), qn("w:keepLines"), qn("w:pageBreakBefore")):
            idx = i + 1
    ppr.insert(idx, fp)


def para_border(p):
    ppr = p._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    for side in ("top", "left", "bottom", "right"):
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:val"), "single"); el.set(qn("w:sz"), "6"); el.set(qn("w:space"), "4")
        el.set(qn("w:color"), "404040")
        bdr.append(el)
    ppr.append(bdr)


def add_text(p, text, size=None, bold=None, italic=None, highlight=None, font=FONT):
    r = p.add_run(text)
    set_run_font(r, name=font, size=size, bold=bold, italic=italic)
    if highlight:
        r.font.highlight_color = highlight
    return r


def add_rich(p, text, size=BODY_PT, bold=None, italic=None, math=True, highlight=None, where=""):
    """Thêm chữ (bỏ [CẦN NGUỒN], tô vàng nhãn sót) và đổi ký hiệu toán sang OMML."""
    text = STRIP_CAN_NGUON.sub("", text)
    pos = 0
    spans = []
    for m in re.finditer(CAN_NGUON.pattern + "|" + LEFTOVER.pattern, text):
        spans.append((m.start(), m.end()))
    for a, b in spans + [(len(text), len(text))]:
        _add_math_text(p, text[pos:a], size, bold, italic, math, highlight)
        if a < b:
            add_text(p, text[a:b], size, bold, italic, WD_COLOR_INDEX.YELLOW)
            STATS["yellow"].append((where, text[a:b]))
            if LEFTOVER.fullmatch(text[a:b]):
                STATS["leftover_labels"].append((where, text[a:b]))
        pos = b


def _add_math_text(p, text, size, bold, italic, math, highlight):
    if not text:
        return
    if not math:
        add_text(p, text, size, bold, italic, highlight)
        return
    pos = 0
    for m in _SYM_RE.finditer(text):
        if m.start() > pos:
            add_text(p, text[pos:m.start()], size, bold, italic, highlight)
        p._p.append(omml(SYM[m.group(1)], size))
        STATS["inline_math"] += 1
        pos = m.end()
    if pos < len(text):
        add_text(p, text[pos:], size, bold, italic, highlight)


# ================================================================ tài liệu và kiểu
def setup_styles(doc):
    st = doc.styles
    normal = st["Normal"]
    style_font(normal, size=BODY_PT, color=None)
    pf = normal.paragraph_format
    pf.line_spacing = 1.3
    pf.space_before = Pt(0)
    pf.space_after = Pt(6)
    pf.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    # Chương: TNR đậm 14, canh giữa, sau tiêu đề để 2 dòng trống. Mục: đậm 13. Tiểu mục: đậm nghiêng 13.
    for lvl, size, italic, before, after, pb in ((1, 14, False, 0, 2 * BODY_PT * 1.3, True),
                                                 (2, 13, False, 12, 6, False),
                                                 (3, 13, True, 8, 6, False)):
        h = st[f"Heading {lvl}"]
        style_font(h, size=size, bold=True, italic=italic)
        h.paragraph_format.space_before = Pt(before)
        h.paragraph_format.space_after = Pt(after)
        h.paragraph_format.keep_with_next = True
        h.paragraph_format.line_spacing = 1.3
        h.paragraph_format.page_break_before = pb
        h.paragraph_format.alignment = (WD_ALIGN_PARAGRAPH.CENTER if lvl == 1
                                        else WD_ALIGN_PARAGRAPH.JUSTIFY)
    # Chú dẫn bảng, hình: TNR thường 13, giãn dòng 1,3, canh giữa
    cap = st["Caption"]
    style_font(cap, size=BODY_PT, bold=False, italic=False)
    cap.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap.paragraph_format.space_before = Pt(3)
    cap.paragraph_format.space_after = Pt(6)
    cap.paragraph_format.line_spacing = 1.0
    for name in ("List Bullet", "List Bullet 2"):
        s = st[name]
        style_font(s, size=BODY_PT, color=None)
        s.paragraph_format.space_after = Pt(3)
        s.paragraph_format.line_spacing = 1.3
        s.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    def new(name, base="Normal"):
        s = st.add_style(name, 1)
        s.base_style = st[base]
        return s
    s = new("Bang chu")
    style_font(s, size=TABLE_PT, color=None)
    s.paragraph_format.line_spacing = 1.0
    s.paragraph_format.space_after = Pt(1)
    s.paragraph_format.space_before = Pt(1)
    s.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    s = new("Ghi chu bang")
    style_font(s, size=TABLE_PT, color=None)
    s.paragraph_format.line_spacing = 1.1
    s.paragraph_format.space_after = Pt(2)
    s = new("Ma gia")
    style_font(s, name=CODE_FONT, size=CODE_PT, color=None)
    s.paragraph_format.line_spacing = 1.0
    s.paragraph_format.space_after = Pt(0)
    s.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    s.paragraph_format.left_indent = Cm(0.3)
    s.paragraph_format.right_indent = Cm(0.3)
    s = new("Tieu de phu")
    style_font(s, size=14, bold=True, color=None)
    s.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    s.paragraph_format.space_after = Pt(6)
    s.paragraph_format.page_break_before = True
    s.paragraph_format.keep_with_next = True
    s = new("Nhan danh sach")
    style_font(s, size=BODY_PT, bold=True, color=None)
    s.paragraph_format.space_before = Pt(12)
    s.paragraph_format.keep_with_next = True
    s.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    s = new("Cong thuc")
    s.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    s.paragraph_format.space_after = Pt(2)
    s.paragraph_format.space_before = Pt(2)
    s.paragraph_format.line_spacing = 1.0


def page_setup(section, landscape=False):
    """A4; lề trái 3, phải 2, trên 2,5, dưới 2,5 cm; header, footer cách mép 1,6 cm."""
    if landscape:
        section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width, section.page_height = Cm(29.7), Cm(21.0)
        section.left_margin = section.right_margin = Cm(2.5)
        section.top_margin = section.bottom_margin = Cm(2.5)
    else:
        section.orientation = WD_ORIENT.PORTRAIT
        section.page_width, section.page_height = Cm(21.0), Cm(29.7)
        section.top_margin = section.bottom_margin = Cm(2.5)
        section.left_margin, section.right_margin = Cm(3.0), Cm(2.0)
    section.header_distance = Cm(1.6)
    section.footer_distance = Cm(1.6)


def set_pgnum(section, fmt, start=None):
    sp = section._sectPr
    el = sp.find(qn("w:pgNumType"))
    if el is None:
        el = OxmlElement("w:pgNumType")
        sp.append(el)
    el.set(qn("w:fmt"), fmt)
    if start is None:
        if el.get(qn("w:start")) is not None:
            del el.attrib[qn("w:start")]
    else:
        el.set(qn("w:start"), str(start))


# ================================================================ đọc file nháp
UNDER = re.compile(r"^\s*[-=]{3,}\s*$")


def split_row(line):
    return [c.strip() for c in line.strip().split("|")]


def parse_section(path: Path):
    sec = int(path.name[:2])
    lines = path.read_text(encoding="utf-8").split("\n")
    for i, l in enumerate(lines):
        if l.startswith("GHI CHÚ CHO NHÓM"):
            lines = lines[:i]
            break
    blocks, i, n = [], 0, len(lines)
    while i < n:
        l = lines[i]
        s = l.strip()
        nxt = lines[i + 1] if i + 1 < n else ""
        if not s or UNDER.match(l):
            i += 1
            continue
        if s.startswith("(Bản nháp nội dung") or s.startswith("(Ghi chú cho nhóm"):
            i += 1
            continue
        if re.match(r"^BỐ CỤC MỤC \d+", s):
            i += 1
            while i < n and lines[i].strip():
                i += 1
            continue
        m = re.match(r"^MỤC (\d+)\. (.+)$", s)
        if m:
            blocks.append(("h1", f"Chương {m[1]}: {m[2]}"))
            i += 1
            continue
        if not l.startswith(" ") and UNDER.match(nxt):
            blocks.append(("h2" if re.match(r"^\d+\.\d+\. ", s) else "h2u", s))
            i += 2
            continue
        if not l.startswith(" ") and re.match(r"^\d+\.\d+\.\d+\. ", s):
            blocks.append(("h3", s))
            i += 1
            continue
        m = re.match(r"^\[BẢNG (\d+\.\d+)\] (.+)$", s)
        if m:
            i += 1
            rows = []
            while i < n and "|" in lines[i]:
                if not re.match(r"^[\s\-+|]+$", lines[i]):
                    rows.append(split_row(lines[i]))
                i += 1
            notes = []
            if i < n and lines[i].strip().startswith("Ghi chú bảng:"):
                notes.append(("p", lines[i].strip()))
                i += 1
                while i < n and lines[i].startswith(" ") and lines[i].strip():
                    mm = re.match(r"^\s+- (.*)$", lines[i])
                    notes.append(("bullet", mm[1]) if mm else ("p", lines[i].strip()))
                    i += 1
            else:
                while i < n and lines[i].strip().startswith("("):
                    notes.append(("p", lines[i].strip()))
                    i += 1
            blocks.append(("table", m[1], m[2], rows, notes))
            continue
        m = re.match(r"^\[HÌNH (\d+\.\d+)\] (.+)$", s)
        if m:
            i += 1
            while i < n and lines[i].startswith("    ") and lines[i].strip():
                i += 1                                   # khối sơ đồ ASCII: thay bằng ảnh
            blocks.append(("figure", m[1], m[2]))
            continue
        if sec == 4:
            m = re.match(r"^\s+\((4\.\d+b?)\)\s+(.*)$", l)
            if m:
                full = [m[2]]
                i += 1
                while i < n and re.match(r"^\s{5,}\S", lines[i]):
                    full.append(lines[i].strip())
                    i += 1
                blocks.append(("formula", m[1], " ".join(full)))
                continue
        if sec == 5 and re.match(r"^\s+(Dữ liệu:|on_heartbeat\()", l):
            code = []
            while i < n and lines[i].startswith("  ") and lines[i].strip():
                code.append(lines[i][2:])
                i += 1
            blocks.append(("code", code))
            continue
        if l.startswith("  ") and "|" in l and i + 1 < n and "|" in lines[i + 1]:
            rows = []
            while i < n and "|" in lines[i]:
                if not re.match(r"^[\s\-+|]+$", lines[i]):
                    rows.append(split_row(lines[i]))
                i += 1
            blocks.append(("utable", rows))
            continue
        m = re.match(r"^(\s+)- (.*)$", l)
        if m:
            blocks.append(("bullet", m[2], 1 if len(m[1]) <= 2 else 2))
            i += 1
            continue
        m = re.match(r"^(\s+)(\d+\.|\(\d+\)) (.*)$", l)
        if m:
            blocks.append(("num", m[2], m[3], 1 if len(m[1]) <= 2 else 2))
            i += 1
            continue
        if l.startswith(" "):
            blocks.append(("indent", s, 1 if len(l) - len(l.lstrip()) <= 2 else 2))
            i += 1
            continue
        blocks.append(("p", s))
        i += 1
    return blocks


def strip_y_chinh(s: str) -> str:
    m = re.match(r"^(?://\s*)?Ý chính:\s*(.*)$", s)
    if not m:
        return s
    STATS["y_chinh"] += 1
    rest = m[1]
    return rest[:1].upper() + rest[1:]


def figure_source(num: str, text: str):
    """(đường dẫn ảnh, chú thích) từ dòng [HÌNH x.y]."""
    m = re.match(r"^((?:analysis|docs/evidence|docs/diagrams)/\S+?\.(?:png|svg)):\s*(.*)$", text)
    if m:
        path, cap = m[1], m[2]
    else:
        path, cap = None, text
    cap = re.sub(r"\s*\(bản vẽ chính thức:[^)]*\)\s*$", "", cap).strip()
    cap = cap.rstrip(".")
    cap = cap[:1].upper() + cap[1:]
    if num in DRAWN:
        img = HINH / f"hinh-{num.replace('.', '-')}.png"
    else:
        img = ROOT / path
    return img, cap


# ================================================================ dựng các khối
class Builder:
    def __init__(self, doc):
        self.doc = doc
        self.sec = 0
        self.landscape = False

    # ------------------------------------------------ đoạn văn
    def para(self, text, style=None, where="", math=True, size=BODY_PT, highlight=None):
        p = self.doc.add_paragraph(style=style)
        p.paragraph_format.first_line_indent = Cm(FIRST_INDENT_CM)
        add_rich(p, text, size=size, math=math, highlight=highlight, where=where)
        return p

    def bullet(self, text, level=1, size=BODY_PT, where=""):
        """Ý con thụt theo đầu đoạn: dấu chấm tròn ở 1 cm (cấp 2: 1,6 cm), chữ cách dấu 0,6 cm."""
        p = self.doc.add_paragraph(style="List Bullet" if level == 1 else "List Bullet 2")
        pos = FIRST_INDENT_CM + 0.6 * (level - 1)
        p.paragraph_format.left_indent = Cm(pos + 0.6)
        p.paragraph_format.first_line_indent = Cm(-0.6)
        p.paragraph_format.tab_stops.add_tab_stop(Cm(pos + 0.6))
        add_rich(p, text, size=size, where=where)
        if size != BODY_PT:
            p.paragraph_format.line_spacing = 1.1
            p.paragraph_format.space_after = Pt(2)
        return p

    def numbered(self, label, text, level=1, where=""):
        p = self.doc.add_paragraph()
        ind = FIRST_INDENT_CM + 0.7 + 0.6 * (level - 1)     # số thứ tự ở 1 cm, chữ ở 1,7 cm
        p.paragraph_format.left_indent = Cm(ind)
        p.paragraph_format.first_line_indent = Cm(-0.7)
        p.paragraph_format.tab_stops.add_tab_stop(Cm(ind))
        p.paragraph_format.space_after = Pt(3)
        add_text(p, label + "\t", BODY_PT)
        add_rich(p, text, where=where)
        return p

    def indent(self, text, level=1, where=""):
        p = self.doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(FIRST_INDENT_CM * level)
        add_rich(p, text, where=where)
        return p

    # ------------------------------------------------ chú thích có SEQ
    def caption(self, kind, num, title):
        """Chú dẫn "Bảng 2.1 Tên bảng": số chương + SEQ đánh lại từ 1 sau mỗi Heading 1."""
        p = self.doc.add_paragraph(style="Caption")
        chap, idx = num.split(".")
        add_text(p, f"{kind} {chap}.", BODY_PT)
        add_field(p, f" SEQ {kind} \\* ARABIC \\s 1 ", idx, size=BODY_PT)
        add_text(p, f" {title}", BODY_PT)
        return p

    # ------------------------------------------------ bảng
    def table(self, rows, avail_cm, header=True, symbol_col0=False, yellow_empty=False, borders=True):
        ncol = max(len(r) for r in rows)
        # "x ± y" không bị ngắt dòng giữa chừng
        rows = [[re.sub(r" ± ", NBSP_PM, c) for c in r] + [""] * (ncol - len(r)) for r in rows]
        wide = ncol >= 11                      # bảng rất rộng: trang dọc, cỡ 9,5, "± độ lệch" xuống dòng
        size = 9.5 if wide else TABLE_PT
        mrows = [[c.replace(NBSP_PM, "\n± ").split("\n")[0] if wide else c for c in r] for r in rows]
        if wide:   # đo theo phần dài hơn của hai dòng; "± 0,00" đo như một từ
            mrows = [[max(c.replace(NBSP_PM, "\n±0").split("\n"), key=len) for c in r] for r in rows]
        widths = col_widths(mrows, avail_cm, size, pad=0.3 if wide else 0.6)
        t = self.doc.add_table(rows=len(rows), cols=ncol)
        if borders:
            t.style = self.doc.styles["Table Grid"]
        if wide:
            mar = OxmlElement("w:tblCellMar")
            for side in ("left", "right"):
                el = OxmlElement(f"w:{side}")
                el.set(qn("w:w"), str(int(0.08 / 2.54 * 1440))); el.set(qn("w:type"), "dxa")
                mar.append(el)
            t._tbl.tblPr.append(mar)
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        t.autofit = False
        grid = t._tbl.tblGrid
        for gc, w in zip(grid.findall(qn("w:gridCol")), widths):
            gc.set(qn("w:w"), str(int(w / 2.54 * 1440)))
        for ri, row in enumerate(rows):
            tr = t.rows[ri]._tr
            trpr = tr.get_or_add_trPr()
            cs = OxmlElement("w:cantSplit"); trpr.append(cs)
            if header and ri == 0:
                th = OxmlElement("w:tblHeader"); trpr.append(th)
            for ci, txt in enumerate(row):
                cell = t.cell(ri, ci)
                cell.width = Cm(widths[ci])
                cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                p = cell.paragraphs[0]
                p.style = self.doc.styles["Bang chu"]
                bold = header and ri == 0
                if bold:
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER     # tiêu đề cột canh giữa
                    p.paragraph_format.line_spacing = 1.0
                if bold and borders:
                    shade(cell, "D9D9D9")
                if symbol_col0 and ci == 0 and ri > 0:
                    add_symbols(p, txt)
                elif wide and NBSP_PM in txt:
                    a, c2 = txt.split(NBSP_PM, 1)
                    add_rich(p, a, size=size, bold=bold or None)
                    p.add_run().add_break()
                    add_rich(p, "± " + c2, size=size, bold=bold or None)
                else:
                    add_rich(p, txt, size=size, bold=bold or None, where=f"bảng ô {ri},{ci}")
                if yellow_empty and not txt:
                    shade(cell, "FFFF00")
                _math_only_left(p)
        # Bảng vừa một trang: giữ trọn trên một trang (không tách). Bảng dài hơn một trang: được tách,
        # nhưng mỗi phần có ít nhất 3 hàng dữ liệu (hàng tiêu đề lặp lại ở trang sau).
        n = len(t.rows)
        if est_table_cm(rows, widths, size) <= TEXT_H_CM - 3.0:
            keep = set(range(n - 1))
        else:
            keep = set(range(min(4, n - 1))) | set(range(max(0, n - 4), n - 1))
        for ri in keep:
            for c in t.rows[ri].cells:
                for p in c.paragraphs:
                    p.paragraph_format.keep_with_next = True
        tblpr = t._tbl.tblPr
        tw_ = OxmlElement("w:tblW")
        tw_.set(qn("w:w"), str(int(sum(widths) / 2.54 * 1440))); tw_.set(qn("w:type"), "dxa")
        old = tblpr.find(qn("w:tblW"))
        if old is not None:
            tblpr.remove(old)
        tblpr.append(tw_)
        lay = OxmlElement("w:tblLayout"); lay.set(qn("w:type"), "fixed"); tblpr.append(lay)
        return t

    def table_block(self, num, title, rows, notes, prev_text):
        if not re.search(rf"[Bb]ảng {re.escape(num)}(?!\d)", prev_text or ""):
            lead = LEAD_INS.get(num)
            if not lead:
                sys.exit(f"Bảng {num} chưa được nhắc ở đoạn ngay trước và chưa có câu dẫn trong LEAD_INS.")
            p = self.doc.add_paragraph()
            p.paragraph_format.first_line_indent = Cm(FIRST_INDENT_CM)
            add_rich(p, lead, highlight=WD_COLOR_INDEX.BRIGHT_GREEN, where=f"câu dẫn bảng {num}")
            STATS["lead_ins"].append((num, lead))
        STATS["table_mention"].append(num)
        cap = self.caption("Bảng", num, title)
        cap.paragraph_format.keep_with_next = True
        self.table(rows, TEXT_W_CM, symbol_col0=rows[0][0] == "Ký hiệu")
        for k, txt in notes:
            if k == "bullet":
                self.bullet(txt, size=TABLE_PT, where=f"ghi chú bảng {num}")
            else:
                p = self.doc.add_paragraph(style="Ghi chu bang")
                add_rich(p, txt, size=TABLE_PT, where=f"ghi chú bảng {num}")
        if not notes:
            sp = self.doc.add_paragraph()
            sp.paragraph_format.space_after = Pt(0)
            sp.paragraph_format.line_spacing = 0.8

    def switch(self, landscape):
        s = self.doc.add_section(WD_SECTION.NEW_PAGE)
        page_setup(s, landscape)
        set_pgnum(s, "decimal")
        self.landscape = landscape

    # ------------------------------------------------ hình
    def figure(self, num, text, prev_text):
        img, cap = figure_source(num, text)
        if not img.exists():
            sys.exit(f"Thiếu ảnh cho Hình {num}: {img} (chạy build_figures.py trước)")
        mentioned = bool(re.search(rf"[Hh]ình {re.escape(num)}(?!\d)", prev_text or ""))
        if mentioned:
            STATS["fig_mention"].append((num, True))
        else:
            STATS["fig_mention"].append((num, False))
        with Image.open(img) as im:
            wpx, hpx = im.size
        w_cm = FIG_W_CM                  # mọi ảnh rộng 75% khổ chữ
        h_cm = w_cm * hpx / wpx
        max_h = TEXT_H_CM - 2.0          # chừa chỗ cho chú dẫn
        if h_cm > max_h:
            w_cm = w_cm * max_h / h_cm
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.keep_with_next = True
        p.paragraph_format.line_spacing = 1.0
        p.paragraph_format.first_line_indent = Cm(0)
        shape = p.add_run().add_picture(str(img), width=Cm(w_cm))
        shape._inline.docPr.set("descr", f"fig-{num}")      # để Word (bước dàn trang) nhận ra hình
        c = self.caption("Hình", num, cap)
        # ảnh + chú dẫn nằm trong một khung nổi ở mép trên trang; word_finalize dời khung
        # sang đầu trang kế tiếp sau trang có câu nhắc tới hình
        set_frame(p, FIG_W_CM)
        set_frame(c, FIG_W_CM)
        STATS["figures"].append(num)

    # ------------------------------------------------ công thức
    def formula(self, key, src_text):
        lines = FORMULAS.get(key)
        if not lines:
            sys.exit(f"Thiếu công thức ({key}) trong cong-thuc.tex")
        note = FNOTES.get(key)
        if note and note not in src_text:
            sys.exit(f"Chú giải của ({key}) không có nguyên văn trong dòng gốc: {note!r}")
        t = self.doc.add_table(rows=1, cols=3)
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        t.autofit = False
        t.rows[0]._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))   # công thức không bị cắt đôi
        ws = [0.6, 13.6, 1.8]
        for gc, w in zip(t._tbl.tblGrid.findall(qn("w:gridCol")), ws):
            gc.set(qn("w:w"), str(int(w / 2.54 * 1440)))
        for ci, w in enumerate(ws):
            t.cell(0, ci).width = Cm(w)
            t.cell(0, ci).vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        mid = t.cell(0, 1)
        for j, tex in enumerate(lines):
            p = mid.paragraphs[0] if j == 0 else mid.add_paragraph()
            p.style = self.doc.styles["Cong thuc"]
            omp = OxmlElement("m:oMathPara")
            ppr = OxmlElement("m:oMathParaPr")
            jc = OxmlElement("m:jc"); jc.set(qn("m:val"), "center")
            ppr.append(jc); omp.append(ppr)
            omp.append(omml(tex, BODY_PT))
            p._p.append(omp)
        STATS["display_math"] += 1
        if note:
            p = mid.add_paragraph(style="Cong thuc")
            add_rich(p, note, size=BODY_PT, where=f"chú giải ({key})")
        pn = t.cell(0, 2).paragraphs[0]
        pn.style = self.doc.styles["Cong thuc"]
        pn.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        add_text(pn, f"({key})", BODY_PT)
        for c in t.rows[0].cells:
            for p in c.paragraphs:
                p.paragraph_format.keep_together = True
        sp = self.doc.add_paragraph()
        sp.paragraph_format.space_after = Pt(0)
        sp.paragraph_format.line_spacing = 0.6

    # ------------------------------------------------ mã giả
    def code(self, lines):
        """Khung một ô có viền; dòng dài tự xuống dòng và thụt vào thêm 4 ký tự."""
        if self.doc.paragraphs:
            self.doc.paragraphs[-1].paragraph_format.keep_with_next = True
        t = self.doc.add_table(rows=1, cols=1)
        t.style = self.doc.styles["Table Grid"]
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        cell = t.cell(0, 0)
        cell.width = Cm(TEXT_W_CM)
        cw = CODE_PT * 0.55 / 72 * 2.54          # bề rộng một ký tự Consolas (cm)
        for j, ln in enumerate(lines):
            p = cell.paragraphs[0] if j == 0 else cell.add_paragraph()
            p.style = self.doc.styles["Ma gia"]
            lead = len(ln) - len(ln.lstrip(" "))
            p.paragraph_format.left_indent = Cm((lead + 4) * cw)
            p.paragraph_format.first_line_indent = Cm(-4 * cw)
            p.paragraph_format.keep_with_next = True
            r = p.add_run(ln.lstrip(" "))
            set_run_font(r, name=CODE_FONT, size=CODE_PT)
        tr = t.rows[0]._tr.get_or_add_trPr()
        tr.append(OxmlElement("w:cantSplit"))
        sp = self.doc.add_paragraph()
        sp.paragraph_format.space_after = Pt(0)
        sp.paragraph_format.line_spacing = 0.8

    # ------------------------------------------------ một mục
    def section_blocks(self, blocks):
        prev_text = None
        skip_symbols = False
        skip_summary = False
        for b in blocks:
            k = b[0]
            # "Tóm tắt chương N" giữ trong file nháp nhưng không đưa vào báo cáo
            if k in ("h1", "h2", "h2u", "h3"):
                skip_summary = k == "h2u" and b[1].startswith("Tóm tắt chương")
                if skip_summary:
                    continue
            elif skip_summary:
                continue
            # "Bảng ký hiệu" cuối chương 4 được chuyển lên "Danh sách các ký hiệu, chữ viết tắt"
            if k == "h2u" and b[1] == "Bảng ký hiệu":
                skip_symbols = True
                continue
            if skip_symbols and k == "utable":
                skip_symbols = False
                continue
            if k == "h1":
                self.doc.add_heading(b[1], level=1)
                prev_text = None
            elif k in ("h2", "h2u"):
                self.doc.add_heading(b[1], level=2)
                prev_text = None
            elif k == "h3":
                self.doc.add_heading(b[1], level=3)
                prev_text = None
            elif k == "p":
                txt = strip_y_chinh(b[1])
                self.para(txt, where=txt[:40])
                prev_text = txt
            elif k == "indent":
                self.indent(b[1], b[2], where=b[1][:40])
                prev_text = b[1]
            elif k == "bullet":
                self.bullet(b[1], b[2], where=b[1][:40])
                prev_text = b[1]
            elif k == "num":
                self.numbered(b[1], b[2], b[3], where=b[2][:40])
                prev_text = b[2]
            elif k == "table":
                self.table_block(b[1], b[2], b[3], b[4], prev_text)
                prev_text = None
            elif k == "utable":
                self.table(b[1], TEXT_W_CM, symbol_col0=b[1][0][0] == "Ký hiệu")
                sp = self.doc.add_paragraph()
                sp.paragraph_format.space_after = Pt(0)
                prev_text = None
            elif k == "figure":
                self.figure(b[1], b[2], prev_text)
                prev_text = None
            elif k == "formula":
                self.formula(b[1], b[2])
            elif k == "code":
                self.code(b[1])
                prev_text = None


def _math_only_left(p):
    """Ô chỉ có công thức: Word coi là công thức hiển thị (canh giữa); bọc oMathPara canh trái."""
    kids = list(p._p)
    has_text = any(k.tag == qn("w:r") and (k.findtext(qn("w:t")) or "").strip() for k in kids)
    maths = [k for k in kids if k.tag == f"{{{MATH_NS}}}oMath"]
    if has_text or not maths:
        return
    para = etree.SubElement(p._p, f"{{{MATH_NS}}}oMathPara")
    ppr = etree.SubElement(para, f"{{{MATH_NS}}}oMathParaPr")
    etree.SubElement(ppr, f"{{{MATH_NS}}}jc").set(f"{{{MATH_NS}}}val", "left")
    for m in maths:
        para.append(m)


def add_symbols(p, txt):
    """Ô cột "Ký hiệu": mỗi ký hiệu (ngăn bằng dấu phẩy) thành công thức nếu có trong cong-thuc.tex."""
    items = txt.split(", ")
    for j, it in enumerate(items):
        if j:
            add_text(p, ", ", TABLE_PT)
        tex = CELLSYM.get(it) or SYM.get(it)
        if tex:
            p._p.append(omml(tex, TABLE_PT))
            STATS["inline_math"] += 1
        else:
            add_rich(p, it, size=TABLE_PT)


def est_table_cm(rows, widths, size):
    """Ước lượng chiều cao bảng (cm): số dòng chữ lớn nhất trong từng hàng × chiều cao dòng."""
    import math
    lh = size * 1.15 / 72 * 2.54
    total = 0.0
    for r in rows:
        lines = 1
        for txt, w in zip(r, widths):
            usable = max(w - 0.4, 0.5)
            parts = txt.replace(NBSP_PM, "\n").split("\n") if size < TABLE_PT else [txt]
            n = sum(max(1, math.ceil(_word_cm(p, size) / usable)) for p in parts)
            lines = max(lines, n)
        total += lines * lh + 0.12
    return total


def _word_cm(w, size):
    """Ước lượng bề rộng một từ (cm) theo Times New Roman; chữ hoa rộng hơn chữ thường."""
    return sum(0.30 if (c.isupper() or c in "±%") else 0.215 for c in w) * size / 11


def col_widths(rows, avail, size=TABLE_PT, pad=0.6):
    ncol = len(rows[0])
    want, minw, minw_word = [], [], []
    for c in range(ncol):
        texts = [r[c].replace(NBSP_PM, "±") for r in rows]
        longest = max(len(t) for t in texts)
        avg = sum(len(t) for t in texts[1:]) / max(1, len(texts) - 1)
        word = max((_word_cm(w, size) for t in texts for w in t.split()), default=0.5)
        short = max((_word_cm(t, size) for t in texts if len(t) <= 10), default=0)   # ô ngắn: không ngắt
        minw.append(max(word, short) + pad)
        minw_word.append(word + pad)
        want.append(max(0.6 * avg + 0.4 * min(longest, 80), 4) ** 0.85)
    # không bao giờ vượt khổ chữ: bỏ yêu cầu "ô ngắn không ngắt" nếu không đủ chỗ, rồi co đều
    if sum(minw) > avail:
        minw = minw_word
    if sum(minw) > avail:
        minw = [m * avail / sum(minw) for m in minw]
    tot = sum(want)
    w = [avail * x / tot for x in want]
    fixed = set()
    for _ in range(ncol + 1):                  # cột chạm mức tối thiểu thì giữ cố định
        short = [i for i in range(ncol) if i not in fixed and w[i] < minw[i] - 1e-9]
        if not short:
            break
        for i in short:
            w[i] = minw[i]
            fixed.add(i)
        free = [i for i in range(ncol) if i not in fixed]
        room = avail - sum(w[i] for i in fixed)
        ft = sum(want[i] for i in free) or 1
        for i in free:
            w[i] = room * want[i] / ft
    s = sum(w)
    if s > avail:                              # an toàn: tổng không vượt khổ chữ
        w = [x * avail / s for x in w]
    return w


# ================================================================ các phần ngoài nội dung
def read_readme():
    txt = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
    title = txt[0].lstrip("# ").strip()
    members, on = [], False
    for ln in txt:
        if ln.startswith("## "):
            on = ln.strip() == "## Thành viên"
            continue
        if on and ln.startswith("- "):
            members.append(ln[2:].strip())
    return title, members or MEMBERS_FALLBACK


def cover(doc, title, members):
    def line(text, size=13, bold=False, before=0, after=4, highlight=None, align="center"):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER if align == "center" else WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.space_before = Pt(before)
        p.paragraph_format.space_after = Pt(after)
        p.paragraph_format.line_spacing = 1.15
        add_text(p, text, size, bold, highlight=highlight)
        return p
    Y = WD_COLOR_INDEX.YELLOW
    line("[TÊN TRƯỜNG]", 14, True, highlight=Y)
    STATS["yellow"].append(("bìa", "[TÊN TRƯỜNG]"))
    line("[TÊN KHOA]", 14, True, highlight=Y)
    STATS["yellow"].append(("bìa", "[TÊN KHOA]"))
    line("", after=0)
    line("BÁO CÁO BÀI TẬP LỚN MÔN LẬP TRÌNH MẠNG", 18, True, before=110, after=18)
    line("Đề tài:", 14, False, after=4)
    line(title, 16, True, after=40)
    line("Mã nhóm: N44_2026_LTM_007_012_057", 14, False, after=18)
    line("Thành viên nhóm:", 14, True, after=4)
    for m in members:
        line(m, 14, after=2)
    p = line("Giảng viên hướng dẫn: ", 14, False, before=18)
    add_text(p, "[HỌ TÊN GIẢNG VIÊN]", 14, highlight=Y)
    STATS["yellow"].append(("bìa", "[HỌ TÊN GIẢNG VIÊN]"))
    line("Tháng 11 năm 2026", 14, False, before=120)


def symbol_rows():
    """Bảng ký hiệu cuối 04-mo-hinh-toan.txt."""
    rows, on = None, False
    for bl in parse_section(SRC / "04-mo-hinh-toan.txt"):
        if bl[0] == "h2u" and bl[1] == "Bảng ký hiệu":
            on = True
        elif on and bl[0] == "utable":
            rows = bl[1]
            break
    if not rows:
        sys.exit("Không tìm thấy 'Bảng ký hiệu' trong 04-mo-hinh-toan.txt")
    return rows


def front_matter(doc, b: Builder):
    """Mục lục; Danh sách các bảng, hình vẽ; Danh sách các ký hiệu, chữ viết tắt (theo mẫu của trường)."""
    p = doc.add_paragraph(style="Tieu de phu")
    p.paragraph_format.page_break_before = False
    add_text(p, "MỤC LỤC", 14, True)
    def trang():
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p.paragraph_format.space_after = Pt(0)
        add_text(p, "Trang", BODY_PT, True)

    def title(text):
        p = doc.add_paragraph(style="Tieu de phu")
        add_text(p, text, 14, True)

    trang()
    p = doc.add_paragraph()
    add_field(p, ' TOC \\o "1-3" \\h \\z \\u ', "Mở bằng Word và nhấn F9 để cập nhật mục lục.")

    for heading, label in (("DANH SÁCH BẢNG", "Bảng"), ("DANH SÁCH HÌNH VẼ", "Hình")):
        title(heading)
        trang()
        p = doc.add_paragraph()
        add_field(p, f' TOC \\h \\z \\c "{label}" ', f"Nhấn F9 để cập nhật danh sách {label.lower()}.")

    title("DANH SÁCH CÁC KÝ HIỆU")
    sym = symbol_rows()
    b.table([["Ký hiệu", "Tên gọi, diễn giải", "Đơn vị"]] + sym[1:], TEXT_W_CM, symbol_col0=True)
    gloss = []
    for ln in (SRC / "00-thuat-ngu.txt").read_text(encoding="utf-8").splitlines():
        if " | " in ln and not re.match(r"^[\s\-+|]+$", ln):
            gloss.append(split_row(ln))
    head, body = gloss[0], gloss[1:]
    abbr = [r for r in body if r[0] in ABBREV]
    terms = [r for r in body if r[0] not in ABBREV]
    missing = ABBREV - {r[0] for r in abbr}
    if missing:
        sys.exit(f"ABBREV có mục không thấy trong 00-thuat-ngu.txt: {sorted(missing)}")
    title("DANH SÁCH CÁC CHỮ VIẾT TẮT")
    b.table([["Chữ viết tắt", "Viết đầy đủ / tiếng Việt", "Giải thích"]] + abbr, TEXT_W_CM)
    title("DANH SÁCH THUẬT NGỮ")
    b.table([head] + terms, TEXT_W_CM)


def member_page(doc, b: Builder, members):
    doc.add_heading("Chương 1: ĐÓNG GÓP CỦA THÀNH VIÊN", level=1)
    rows = [["Thành viên", "Nhiệm vụ", "Sản phẩm (file / commit)", "Tỷ lệ đóng góp %"]]
    rows += [[m, "", "", ""] for m in members]
    t = b.table(rows, TEXT_W_CM, yellow_empty=True)
    widths = [4.2, 5.0, 4.6, 2.2]
    for r in t.rows:
        for c, w in zip(r.cells, widths):
            c.width = Cm(w)
        r.height = Cm(1.6)
    for gc, w in zip(t._tbl.tblGrid.findall(qn("w:gridCol")), widths):
        gc.set(qn("w:w"), str(int(w / 2.54 * 1440)))
    STATS["yellow"].append(("mục 1", "9 ô trống của bảng đóng góp"))


def _border(p, side):
    ppr = p._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    el = OxmlElement(f"w:{side}")
    el.set(qn("w:val"), "single"); el.set(qn("w:sz"), "4"); el.set(qn("w:space"), "1")
    el.set(qn("w:color"), "auto")
    bdr.append(el)
    ppr.append(bdr)


def header_footer(section, title, members):
    """Header: tên đề tài (nghiêng, 10, giữa). Footer: sinh viên thực hiện, giảng viên hướng dẫn, số trang (10)."""
    section.header.is_linked_to_previous = False
    hp = section.header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    hp.paragraph_format.space_after = Pt(0)
    hp.paragraph_format.line_spacing = 1.0
    add_text(hp, title, HF_PT, italic=True)
    _border(hp, "bottom")

    section.footer.is_linked_to_previous = False
    f1 = section.footer.paragraphs[0]
    f1.alignment = WD_ALIGN_PARAGRAPH.LEFT
    f1.paragraph_format.space_after = Pt(0)
    f1.paragraph_format.line_spacing = 1.0
    _border(f1, "top")
    add_text(f1, "Sinh viên thực hiện: " + ", ".join(members), HF_PT)
    r = f1.add_run()
    pt = OxmlElement("w:ptab")                       # tab canh phải theo lề (đúng cả trang ngang)
    pt.set(qn("w:relativeTo"), "margin"); pt.set(qn("w:alignment"), "right"); pt.set(qn("w:leader"), "none")
    r._r.append(pt)
    add_text(f1, "Trang ", HF_PT)
    add_field(f1, " PAGE ", "1", size=HF_PT)
    f2 = section.footer.add_paragraph()
    f2.paragraph_format.space_after = Pt(0)
    f2.paragraph_format.line_spacing = 1.0
    add_text(f2, "Giảng viên hướng dẫn: ", HF_PT)
    add_text(f2, "[HỌ TÊN GIẢNG VIÊN]", HF_PT, highlight=WD_COLOR_INDEX.YELLOW)
    STATS["yellow"].append(("footer", "[HỌ TÊN GIẢNG VIÊN]"))


# ================================================================ Word: cập nhật trường, xuất PDF
def float_figures(d, nums):
    """Đặt từng hình (ảnh + chú dẫn) theo thứ tự từ trên xuống:

    - Nếu hình vừa phần còn lại của trang chứa đoạn nhắc tới nó: đặt ngay sau đoạn nhắc (giữa trang).
    - Nếu không vừa: đặt trong khung nổi ở đầu trang kế tiếp; không chọn trang mà đầu trang là phần
      tiếp theo của một bảng (hình không chen vào giữa bảng). Hai hình rơi vào cùng một trang thì
      xếp chồng trong cùng khung.
    - Thứ tự hình luôn giữ đúng (hình sau không đứng trước hình trước).
    - Nếu trang kế tiếp là đầu chương mới, hình nằm ngay sau đoạn nhắc (không khung)."""
    PAGE, IN_TABLE = 3, 12                      # wdActiveEndPageNumber, wdWithInTable
    MAX_PT = (TEXT_H_CM - 1.5) / 2.54 * 72      # chiều cao tối đa các hình trên một trang
    report = []

    def page_at(pos):
        return d.Range(pos, pos).Information(PAGE)

    def shape_of(num):
        for i in range(1, d.InlineShapes.Count + 1):
            s = d.InlineShapes(i)
            if s.AlternativeText == f"fig-{num}":
                return s
        return None

    def fig_range(num):
        s = shape_of(num)
        pic = s.Range.Paragraphs(1)
        return s, d.Range(pic.Range.Start, pic.Next().Range.End)

    def move(src, dest):
        n = src.End - src.Start
        dr = d.Range(dest, dest)
        dr.FormattedText = src.FormattedText
        if dr.End - dr.Start < n:
            dr = d.Range(dest, dest + n)
        src.Delete()
        return dr

    def unframe(rng):
        while rng.Frames.Count:
            rng.Frames(1).Delete()

    def make_float(rng):
        if rng.Frames.Count:
            return
        f = d.Frames.Add(rng)
        f.WidthRule = 2                         # wdFrameExact
        f.Width = FIG_W_CM / 2.54 * 72
        f.RelativeHorizontalPosition = 0        # lề
        f.HorizontalPosition = -999995          # wdFrameCenter
        f.RelativeVerticalPosition = 0          # lề
        f.VerticalPosition = -999999            # wdFrameTop
        f.TextWrap = False                      # chữ không chạy hai bên
        f.VerticalDistanceFromText = 14         # cách phần chữ bên dưới khoảng 0,5 cm

    def next_para(para):
        """Đoạn kế tiếp có thể làm điểm neo (bỏ qua khung, nhảy qua bảng)."""
        para = para.Next()
        while para is not None:
            r = para.Range
            if r.Frames.Count > 0:
                para = para.Next()
                continue
            if r.Information(IN_TABLE):
                end = r.Tables(1).Range.End
                para = d.Range(end, end).Paragraphs(1)
                continue
            return para
        return None

    def table_top_pages():
        """Các trang mà đầu trang là phần tiếp theo của một bảng bị tách từ trang trước."""
        pages = set()
        for i in range(1, d.Tables.Count + 1):
            t = d.Tables(i).Range
            a, b = page_at(t.Start), page_at(t.End - 1)
            pages.update(range(a + 1, b + 1))
        return pages

    # 1. đánh dấu đoạn nhắc, đưa mọi hình xuống cuối văn bản (dàn trang khi chưa có hình)
    d.Content.InsertParagraphAfter()
    for k, num in enumerate(nums):
        s, src = fig_range(num)
        mention = src.Paragraphs(1).Previous()
        d.Bookmarks.Add(f"nhac_hinh_{k}", mention.Range)
        move(src, d.Content.End - 1)

    # 2. đặt từng hình
    last_end = 0                                # vị trí cuối hình trước (giữ thứ tự)
    group = None                                # khung nổi gần nhất: [Range, trang, chiều cao]
    for k, num in enumerate(nums):
        mention = d.Bookmarks(f"nhac_hinh_{k}").Range.Paragraphs(1)
        s, src = fig_range(num)
        need = s.Height + 45                    # ảnh + chú dẫn (ước lượng)
        d.Repaginate()
        P = page_at(mention.Range.End - 1)

        # a) thử đặt ngay sau đoạn nhắc
        if mention.Range.End >= last_end:
            dr = move(src, mention.Range.End)
            unframe(dr)
            dr.Paragraphs(1).SpaceBefore = 6
            d.Repaginate()
            if page_at(dr.Start) == P and page_at(dr.End - 1) == P:
                last_end, group = dr.End, None
                report.append((num, P, f"giữa trang {P}, ngay sau đoạn nhắc"))
                continue
            make_float(dr)                      # không vừa: chuyển sang khung nổi
            src = dr
            d.Repaginate()
            P = page_at(mention.Range.End - 1)

        # b) nối vào khung nổi của hình trước nếu khung đó ở trang sau đoạn nhắc và còn chỗ
        if group is not None and group[1] > P and group[2] + need <= MAX_PT:
            dr = move(src, group[0].End)
            group = [d.Range(group[0].Start, dr.End), group[1], group[2] + need]
            last_end = dr.End
            report.append((num, P, f"đầu trang {group[1]} (xếp dưới hình trước)"))
            continue

        # c) khung nổi ở đầu trang kế tiếp (không chen vào giữa bảng)
        para = next_para(mention)
        while para is not None and para.Range.Start < last_end:
            para = next_para(para)
        placed = False
        for _ in range(10):
            bad = table_top_pages()
            if group is not None:
                bad.add(group[1])               # trang đã có khung hình đầy
            while para is not None and (page_at(para.Range.Start) <= P
                                        or page_at(para.Range.Start) in bad):
                para = next_para(para)
            if para is None or para.OutlineLevel == 1:
                break                           # hết văn bản hoặc chương mới
            dr = move(src, para.Range.Start)
            make_float(dr)
            d.Repaginate()
            fp = page_at(dr.Start)
            if fp > P and fp not in table_top_pages():
                group, last_end = [dr, fp, need], dr.End
                report.append((num, P, f"đầu trang {fp}"))
                placed = True
                break
            src = dr                            # rơi sai trang: neo vào đoạn sau
            para = next_para(para)
        if not placed:
            s, src = fig_range(num)
            dr = move(src, max(mention.Range.End, last_end))
            unframe(dr)
            last_end, group = dr.End, None
            report.append((num, P, "ngay sau đoạn nhắc (trang sau là chương mới)"))

    # 3. dọn đoạn trống đã thêm ở cuối văn bản, xóa đánh dấu
    last = d.Paragraphs(d.Paragraphs.Count)
    if not last.Range.Text.strip():
        prev = last.Previous()
        if prev is not None:
            d.Range(prev.Range.End - 1, last.Range.End - 1).Delete()
    for k in range(len(nums)):
        if d.Bookmarks.Exists(f"nhac_hinh_{k}"):
            d.Bookmarks(f"nhac_hinh_{k}").Delete()
    d.Repaginate()
    return report


def word_finalize(docx: Path, pdf: Path):
    import win32com.client  # type: ignore
    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    d = None
    try:
        d = word.Documents.Open(str(docx), False, False, False)
        # Mục lục, danh sách bảng/hình: mọi cấp canh trái cùng một cột, cỡ 13;
        # dòng chương và mục (x.y) in đậm, tiểu mục (x.y.z) chữ thường
        for sid, bold in ((-20, True), (-21, True), (-22, False), (-36, False)):  # TOC1..3, Table of Figures
            try:
                stl = d.Styles(sid)
                stl.ParagraphFormat.LeftIndent = 0
                stl.ParagraphFormat.FirstLineIndent = 0
                stl.Font.Name = FONT
                stl.Font.Size = BODY_PT
                stl.Font.Bold = bold
                stl.ParagraphFormat.SpaceBefore = 0       # không để trống dòng giữa các mục
                stl.ParagraphFormat.SpaceAfter = 0
                stl.ParagraphFormat.LineSpacingRule = 5   # wdLineSpaceMultiple
                stl.ParagraphFormat.LineSpacing = 12 * 1.3
            except Exception:
                pass
        d.Fields.Update()
        for num, P, where in float_figures(d, STATS["figures"]):
            print(f"  Hình {num}: nhắc ở trang PDF {P} -> {where}")
        d.Fields.Update()
        for i in range(1, d.TablesOfContents.Count + 1):
            d.TablesOfContents(i).Update()
        for i in range(1, d.TablesOfFigures.Count + 1):
            d.TablesOfFigures(i).Update()
        d.Repaginate()
        for i in range(1, d.TablesOfContents.Count + 1):
            d.TablesOfContents(i).UpdatePageNumbers()
        for i in range(1, d.TablesOfFigures.Count + 1):
            d.TablesOfFigures(i).UpdatePageNumbers()
        pages = d.ComputeStatistics(2)
        d.Save()
        d.ExportAsFixedFormat(str(pdf), 17)
        d.Close(False)
        d = None
        return pages
    finally:
        if d is not None:                       # lỗi giữa chừng: đóng tài liệu, không lưu
            try:
                d.Close(False)
            except Exception:
                pass
        word.Quit(False)


def soffice_pdf(docx: Path):
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        return None
    subprocess.run([exe, "--headless", "--convert-to", "pdf", "--outdir", str(docx.parent), str(docx)],
                   check=True)
    return docx.with_suffix(".pdf")


def enable_update_fields(doc):
    settings = doc.settings.element
    el = OxmlElement("w:updateFields")
    el.set(qn("w:val"), "true")
    settings.append(el)


# ================================================================ main
def build(no_word: bool, out: Path = OUT):
    doc = Document()
    setup_styles(doc)
    s1 = doc.sections[0]
    page_setup(s1)
    title, members = read_readme()
    b = Builder(doc)
    cover(doc, title, members)

    s2 = doc.add_section(WD_SECTION.NEW_PAGE)          # phần đầu: không đánh số trang
    page_setup(s2)
    front_matter(doc, b)

    s3 = doc.add_section(WD_SECTION.NEW_PAGE)          # từ Chương 1: đánh số trang, có header/footer
    page_setup(s3)
    set_pgnum(s3, "decimal", 1)
    header_footer(s3, title, members)
    member_page(doc, b, members)

    labels = {"BẢNG": [], "HÌNH": []}
    for name in SECTIONS:
        blocks = parse_section(SRC / name)
        for bl in blocks:
            if bl[0] == "table":
                labels["BẢNG"].append(bl[1])
            elif bl[0] == "figure":
                labels["HÌNH"].append(bl[1])
        b.section_blocks(blocks)

    missing = set(FORMULAS) - {bl[1] for name in ["04-mo-hinh-toan.txt"]
                               for bl in parse_section(SRC / name) if bl[0] == "formula"}
    if missing:
        sys.exit(f"cong-thuc.tex có công thức không thấy trong bài: {sorted(missing)}")
    if no_word:
        enable_update_fields(doc)
    doc.save(out)
    print(f"Đã ghi {out}")

    pdf = out.with_suffix(".pdf")
    pages = None
    if not no_word and sys.platform == "win32":
        try:
            pages = word_finalize(out, pdf)
            print(f"Word: đã cập nhật mục lục, danh mục; xuất {pdf} ({pages} trang)")
        except Exception as e:      # không có Word
            print(f"Không dùng được Word ({e}); thử LibreOffice.")
            pdf = soffice_pdf(out)
    elif not no_word:
        pdf = soffice_pdf(out)
    return labels, pages


def summary(labels, pages):
    print("--- Tóm tắt")
    print(f"Nhãn trong bài: {len(labels['BẢNG'])} bảng, {len(labels['HÌNH'])} hình")
    print(f"Công thức hiển thị: {STATS['display_math']}; ký hiệu nội dòng (OMML): {STATS['inline_math']}")
    print(f"Đoạn đã bỏ 'Ý chính': {STATS['y_chinh']}")
    print(f"Câu dẫn bảng đã thêm: {len(STATS['lead_ins'])}")
    for num, s in STATS["lead_ins"]:
        print(f"  Bảng {num}: {s}")
    nofig = [n for n, ok in STATS["fig_mention"] if not ok]
    print(f"Hình chưa được nhắc ở đoạn ngay trước: {nofig or 'không có'}")
    print(f"Chỗ tô vàng: {len(STATS['yellow'])}")
    print(f"Nhãn [BẢNG]/[HÌNH] sót: {STATS['leftover_labels'] or 'không có'}")
    if pages:
        print(f"Số trang (Word): {pages}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-word", action="store_true", help="không mở Word để cập nhật trường và xuất PDF")
    ap.add_argument("--out", help="đường dẫn file docx đầu ra (mặc định docs/report/bao-cao-cuoi-ky.docx)")
    a = ap.parse_args()
    labels, pages = build(a.no_word, Path(a.out).resolve() if a.out else OUT)
    summary(labels, pages)


if __name__ == "__main__":
    main()
