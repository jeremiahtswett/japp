"""Render the tailored resume as a dense, single-column serif .docx.

ADR 0005 (amended): python-docx, matching the master resume's look — Times New
Roman, all black, bold section headings ("Education", "Work Experience", ...)
with a thin horizontal rule, company/location and title/dates on two-column
lines via right tab stops, tight spacing for a one-page density. Layout uses
paragraph borders and tab stops ONLY — never tables or text boxes, keeping the
file machine-parseable per spec Stage 3.

Experience entries render in CORPUS order (reverse-chronological, as the
master resume was written); the model's relevance ordering applies to bullet
selection and to project/leadership sections.
"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

FONT = "Times New Roman"
NAME_SIZE = Pt(17)
HEADING_SIZE = Pt(12)
BODY_SIZE = Pt(10.5)
MARGIN_TB = Inches(0.5)
MARGIN_LR = Inches(0.75)
BULLET_INDENT = Inches(0.25)
GROUP_ORDER = [
    ("experience", "Work Experience"),
    ("project", "Projects"),
    ("leadership", "Leadership"),
]

# w:pPr child order per the OOXML schema — everything that may follow w:pBdr.
_PBDR_SUCCESSORS = (
    "w:shd", "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap",
    "w:overflowPunct", "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN",
    "w:bidi", "w:adjustRightInd", "w:snapToGrid", "w:spacing", "w:ind",
    "w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap", "w:jc",
    "w:textDirection", "w:textAlignment", "w:textboxTightWrap",
    "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange",
)


def _style_base(doc: Document) -> None:
    """Times New Roman / black / dense everywhere, via style inheritance."""
    for style_name in ("Normal", "List Bullet"):
        style = doc.styles[style_name]
        style.font.name = FONT  # sets w:ascii + w:hAnsi
        style.font.size = BODY_SIZE
        style.font.color.rgb = RGBColor(0, 0, 0)
        # font.name does not set w:eastAsia; Word falls back to the theme
        # (Calibri) for it unless set explicitly.
        rfonts = style.element.get_or_add_rPr().get_or_add_rFonts()
        rfonts.set(qn("w:eastAsia"), FONT)
        style.paragraph_format.space_before = Pt(0)
        style.paragraph_format.space_after = Pt(0)
        style.paragraph_format.line_spacing = 1.0
    doc.styles["List Bullet"].paragraph_format.left_indent = BULLET_INDENT


def _add_bottom_border(paragraph) -> None:
    pPr = paragraph._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")  # eighths of a point: thin rule
    bottom.set(qn("w:space"), "2")
    bottom.set(qn("w:color"), "000000")
    pBdr.append(bottom)
    pPr.insert_element_before(pBdr, *_PBDR_SUCCESSORS)


def _heading(doc: Document, text: str):
    """Bold section heading with a rule underneath. Never the built-in
    Heading styles (they carry the theme's blue Calibri)."""
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = True
    run.font.size = HEADING_SIZE
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(2)
    _add_bottom_border(p)
    return p


def _two_col_line(doc: Document, content_width, left: str, right: str,
                  left_bold: bool = False, left_italic: bool = False,
                  right_italic: bool = False):
    p = doc.add_paragraph()
    p.paragraph_format.tab_stops.add_tab_stop(content_width, WD_TAB_ALIGNMENT.RIGHT)
    run = p.add_run(left)
    run.bold = left_bold
    run.italic = left_italic
    if right:
        p.add_run("\t")
        r = p.add_run(right)
        r.italic = right_italic
    return p


def _entry_header(doc: Document, content_width, sec: dict) -> None:
    if sec.get("title"):
        _two_col_line(doc, content_width, sec["name"], sec.get("location", ""),
                      left_bold=True)
        _two_col_line(doc, content_width, sec["title"], sec.get("dates", ""),
                      left_italic=True, right_italic=True)
    else:
        # Projects typically have no role title: one line, name + dates.
        _two_col_line(doc, content_width, sec["name"], sec.get("dates", ""),
                      left_bold=True, right_italic=True)


def _ordered_group(corpus: dict, validated: dict, group_type: str) -> list[dict]:
    """Included sections of one type. Experience keeps CORPUS (master resume)
    order; other groups keep the model's relevance order."""
    included = [s for s in validated["sections"] if s["section_type"] == group_type]
    if group_type != "experience":
        return included
    by_ref = {s["ref_id"]: s for s in included}
    return [by_ref[c["id"]] for c in corpus.get("sections", []) if c["id"] in by_ref]


def render_resume(corpus: dict, validated: dict, output_path: Path) -> None:
    doc = Document()
    _style_base(doc)
    section = doc.sections[0]
    section.left_margin = section.right_margin = MARGIN_LR
    section.top_margin = section.bottom_margin = MARGIN_TB
    content_width = section.page_width - section.left_margin - section.right_margin

    contact = corpus.get("contact", {})
    name_p = doc.add_paragraph()
    name_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    name_run = name_p.add_run(contact.get("name") or "")
    name_run.bold = True
    name_run.font.size = NAME_SIZE

    contact_bits = [contact.get("location", ""), contact.get("email", ""), *contact.get("links", [])]
    contact_line = " | ".join(b for b in contact_bits if b)
    if contact_line:
        cp = doc.add_paragraph(contact_line)
        cp.alignment = WD_ALIGN_PARAGRAPH.CENTER

    if validated.get("summary_line"):
        sp = doc.add_paragraph()
        run = sp.add_run(validated["summary_line"])
        run.italic = True

    if corpus.get("education"):
        _heading(doc, "Education")
        for edu in corpus["education"]:
            _two_col_line(doc, content_width, edu["institution"], edu.get("dates", ""),
                          left_bold=True)
            if edu.get("detail"):
                doc.add_paragraph(edu["detail"])
            for highlight in edu.get("highlights", []):
                doc.add_paragraph(highlight, style="List Bullet")

    for group_type, group_heading in GROUP_ORDER:
        entries = _ordered_group(corpus, validated, group_type)
        if not entries:
            continue
        _heading(doc, group_heading)
        for sec in entries:
            _entry_header(doc, content_width, sec)
            for bullet in sec["bullets"]:
                doc.add_paragraph(bullet["tailored_text"], style="List Bullet")

    if corpus.get("skills"):
        _heading(doc, "Skills")
        doc.add_paragraph(", ".join(corpus["skills"]))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
