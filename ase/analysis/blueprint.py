"""Extract a Template Blueprint from a university DOCX."""
import json
from ase.config import MAX_TOKENS
from ase.llm import complete
from ase.schemas.models import TemplateBlueprint

_SYSTEM = """You are an academic document analyst. Extract template blueprints from university syllabus templates.
Return only valid JSON — no markdown fences, no commentary."""

_PROMPT = """Analyze this university syllabus template structure and return a Template Blueprint JSON.

TEMPLATE DATA:
{data}

Return this exact JSON structure (fill all fields from the template data):
{{
  "page": {{"size": "A4|Letter", "margins_dxa": {{}}, "header_dxa": 0, "footer_dxa": 0}},
  "assets": {{"logo": {{"placement": "header-left|header-center"}}}},
  "color_tokens": {{"title_box": "RRGGBB", "table_header": "RRGGBB", "heading": "RRGGBB", "header_text": "FFFFFF"}},
  "typography": {{"default_font": "Calibri", "body_font": "Times New Roman", "sizes_half_pt": {{}}}},
  "footer_template": "Page {{PAGE}} of {{TOTAL}} — UniversityName",
  "sections_order": ["title_page", "credit_structure", "subject_detail_pages", "references"],
  "table_templates": {{
    "credit_structure": {{"columns": [], "super_headers": []}},
    "detailed_page": {{"layout": "table_packed|flowing", "blocks": []}},
    "copo_matrix": {{"po_count": 12, "scale": ["H","M","L","-"]}}
  }},
  "label_dictionary": {{
    "objectives_banner": "Course Learning Objectives (CLO):",
    "objective_code": "CLO",
    "outcomes_banner": "Course Outcomes (CO):",
    "content_banner": "Course Content:",
    "copo_banner": "CO-PO Mapping:",
    "level_row_label": "Level (UG/PG) and NcRF"
  }},
  "has_sections": {{"textbooks": true, "references": true, "suggested_reading": false}},
  "tone": "formal-academic",
  "defaults": {{"missing_figures": "leave_blank", "isbn_refs": "ask"}},
  "confidence": {{"detailed_page.layout": 0.9}}
}}"""


def extract_blueprint(template_data: dict, university_id: str) -> TemplateBlueprint:
    data_str = json.dumps({
        "paragraphs": template_data.get("paragraphs", [])[:40],
        "tables": template_data.get("tables", [])[:8],
        "detected_colors": template_data.get("detected_colors", []),
        "styles": dict(list(template_data.get("styles", {}).items())[:20]),
    }, indent=2)

    raw = complete(_SYSTEM, _PROMPT.format(data=data_str[:12000]), MAX_TOKENS).strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip().rstrip("```")

    blueprint_dict = json.loads(raw)
    blueprint_dict["university_id"] = university_id
    blueprint_dict["source_doc_hash"] = template_data.get("hash", "")
    blueprint_dict["raw_analysis"] = raw[:500]

    return TemplateBlueprint(**blueprint_dict)
