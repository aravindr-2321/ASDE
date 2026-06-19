"""Blueprint-driven DOCX assembler + PDF export using python-docx."""
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from pathlib import Path
from ase.schemas.models import TemplateBlueprint, ContentModel, SubjectContent


def _hex_to_rgb(h: str) -> RGBColor:
    h = h.lstrip("#").upper()
    if len(h) != 6:
        return RGBColor(0x66, 0x00, 0x66)
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _shade_cell(cell, hex_color: str):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color.upper().lstrip("#"))
    tcPr.append(shd)


def _set_cell(cell, text: str, bold=False, color="", size=10,
              align=WD_ALIGN_PARAGRAPH.LEFT, font="Calibri"):
    cell.text = ""
    para = cell.paragraphs[0]
    para.alignment = align
    run = para.add_run(text)
    run.bold = bold
    run.font.name = font
    run.font.size = Pt(size)
    if color:
        run.font.color.rgb = _hex_to_rgb(color)


def _banner(table, label: str, bg: str, fg="FFFFFF"):
    row = table.add_row()
    if len(row.cells) > 1:
        row.cells[0].merge(row.cells[-1])
    _shade_cell(row.cells[0], bg)
    _set_cell(row.cells[0], label, bold=True, color=fg, size=10)


def build_docx(blueprint: TemplateBlueprint, content: ContentModel, output_path: str) -> str:
    doc = Document()
    ct = blueprint.color_tokens
    primary = ct.get("table_header", "660066")
    accent = ct.get("title_box", "F7931D")
    heading_color = ct.get("heading", "6F1952")
    ld = blueprint.label_dictionary
    obj_code = ld.get("objective_code", "CLO")
    dfont = blueprint.typography.get("default_font", "Calibri")
    bfont = blueprint.typography.get("body_font", "Times New Roman")

    # Page setup
    sec = doc.sections[0]
    sec.page_width = Inches(8.5)
    sec.page_height = Inches(11)
    for attr in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, attr, Inches(1))

    # Title page
    tp = doc.add_paragraph()
    tp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = tp.add_run(f"{blueprint.university_id.upper()}\nSyllabus Document\n{content.program} — Semester {content.semester}")
    run.bold, run.font.name, run.font.size = True, dfont, Pt(16)
    run.font.color.rgb = _hex_to_rgb(heading_color)
    doc.add_page_break()

    # Credit structure table
    _heading(doc, "CREDIT STRUCTURE", heading_color, dfont)
    cols = ["S.No", "Subject Name", "Code", "L", "T", "P", "Credits", "Marks"]
    tbl = doc.add_table(rows=1, cols=len(cols))
    tbl.style = "Table Grid"
    for i, cell in enumerate(tbl.rows[0].cells):
        _shade_cell(cell, primary)
        _set_cell(cell, cols[i], bold=True, color="FFFFFF", size=9, align=WD_ALIGN_PARAGRAPH.CENTER, font=dfont)

    for idx, subj in enumerate(content.subjects, 1):
        ltp = subj.ltp.split("-") if subj.ltp and "-" in (subj.ltp or "") else ["—", "—", "—"]
        vals = [str(idx), subj.name, subj.code or "—", *ltp[:3], subj.credits or "—", subj.marks or "—"]
        row = tbl.add_row()
        for j, cell in enumerate(row.cells):
            _set_cell(cell, vals[j] if j < len(vals) else "—", size=9, font=bfont)

    doc.add_page_break()

    # Subject detail pages
    for subj in content.subjects:
        _subject_page(doc, subj, blueprint, content.program, content.semester,
                      primary, accent, heading_color, dfont, bfont, obj_code, ld)
        doc.add_page_break()

    # References section
    if blueprint.has_sections.get("textbooks") or blueprint.has_sections.get("references"):
        _refs_section(doc, content.subjects, heading_color, dfont, bfont)

    doc.save(output_path)
    return output_path


def _heading(doc, text, color, font):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold, run.font.name, run.font.size = True, font, Pt(12)
    run.font.color.rgb = _hex_to_rgb(color)


def _subject_page(doc, subj: SubjectContent, bp, program, semester,
                  primary, accent, heading_color, dfont, bfont, obj_code, ld):
    tbl = doc.add_table(rows=0, cols=1)
    tbl.style = "Table Grid"

    _banner(tbl, f"COURSE: {subj.name}  |  {program}  |  Semester {semester}", primary)

    # Level row
    level_label = ld.get("level_row_label", "Level (UG/PG) and NcRF")
    row = tbl.add_row()
    _shade_cell(row.cells[0], "F2F2F2")
    _set_cell(row.cells[0], f"{level_label}: Undergraduate (UG)", size=9, font=bfont)

    # Objectives (CLO)
    _banner(tbl, ld.get("objectives_banner", f"Course Learning Objectives ({obj_code}):"), accent)
    objs = subj.generated_objectives or subj.objectives
    row = tbl.add_row()
    _set_cell(row.cells[0], "\n".join(objs) if objs else "—", size=9, font=bfont)

    # Outcomes (CO)
    _banner(tbl, ld.get("outcomes_banner", "Course Outcomes (CO):"), accent)
    outs = subj.generated_outcomes or subj.outcomes
    row = tbl.add_row()
    _set_cell(row.cells[0], "\n".join(outs) if outs else "—", size=9, font=bfont)

    # Course content
    _banner(tbl, ld.get("content_banner", "Course Content:"), primary)
    for mod in subj.modules:
        row = tbl.add_row()
        _shade_cell(row.cells[0], "E8E8E8")
        _set_cell(row.cells[0], f"{mod.label}: {mod.title}", bold=True, size=9, font=dfont)
        row = tbl.add_row()
        _set_cell(row.cells[0], mod.topics, size=9, font=bfont)

    # CO-PO mapping
    _banner(tbl, ld.get("copo_banner", "CO-PO Mapping:"), primary)
    copo = subj.copo
    if copo:
        po_count = copo.get("po_count", 12)
        rows_data = copo.get("rows", [])
        scale = copo.get("scale", ["H", "M", "L", "-"])
        lines = ["CO\t" + "\t".join(f"PO{i+1}" for i in range(po_count))]
        for i, rv in enumerate(rows_data):
            lines.append(f"CO{i+1}\t" + "\t".join(str(v) for v in rv))
        lines.append(f"Scale: {' / '.join(scale)}")
        row = tbl.add_row()
        _set_cell(row.cells[0], "\n".join(lines), size=8, font=bfont)
    else:
        row = tbl.add_row()
        _set_cell(row.cells[0], "CO-PO mapping not provided.", size=9, font=bfont)


def _refs_section(doc, subjects: list[SubjectContent], heading_color, dfont, bfont):
    _heading(doc, "TEXTBOOKS AND REFERENCES", heading_color, dfont)
    for subj in subjects:
        p = doc.add_paragraph(subj.name)
        p.runs[0].bold = True
        refs = subj.generated_references or subj.textbooks
        for r in refs:
            bp = doc.add_paragraph(style="List Bullet")
            bp.add_run(r).font.size = Pt(9)


def export_pdf(docx_path: str) -> str | None:
    """Convert DOCX to PDF. Returns PDF path or None if conversion unavailable."""
    pdf_path = docx_path.replace(".docx", ".pdf")
    try:
        from docx2pdf import convert
        convert(docx_path, pdf_path)
        return pdf_path
    except Exception:
        return None
