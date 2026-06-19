"""Extract a ContentModel from a NIAT standard syllabus via Claude."""
import json
import anthropic
from ase.config import MODEL, MAX_TOKENS
from ase.schemas.models import ContentModel

_client = anthropic.Anthropic()

_SYSTEM = """You are an academic content extractor. Extract syllabus content into structured JSON.
Preserve all text VERBATIM — never paraphrase or reorder. Return only valid JSON."""

_PROMPT = """Extract the complete content model from this NIAT syllabus document.

SYLLABUS TEXT:
{text}

Return this exact JSON (preserve all text verbatim from source):
{{
  "program": "Program name (e.g. B.Tech CSE Data Science)",
  "semester": 1,
  "subjects": [
    {{
      "name": "Subject Name",
      "code": "SUB101 or null",
      "credits": "3 or null",
      "ltp": "3-0-0 or null",
      "marks": "100 or null",
      "objectives": ["objective 1 verbatim", "objective 2 verbatim"],
      "outcomes": ["outcome 1 verbatim", "outcome 2 verbatim"],
      "modules": [
        {{"label": "Module I", "title": "Module Title", "topics": "topic1, topic2, ..."}}
      ],
      "copo": {{
        "po_count": 12,
        "scale": ["H","M","L","-"],
        "rows": [["H","M","-","L","M","H","-","-","M","-","L","H"]]
      }},
      "textbooks": ["verbatim textbook entry if any"],
      "references": ["verbatim reference entry if any"]
    }}
  ]
}}"""


def extract_content(syllabus_data: dict, program: str = "", semester: int = 1) -> ContentModel:
    """Use Claude to parse the syllabus into a structured ContentModel."""
    text = (
        syllabus_data.get("full_text", "")
        or "\n".join(syllabus_data.get("paragraphs", []))
    )

    # Also include table data as structured text
    tables_text = ""
    for t in syllabus_data.get("tables", [])[:20]:
        for row in t.get("rows", []):
            tables_text += " | ".join(str(c) for c in row if c) + "\n"

    full_input = f"{text}\n\nTABLE DATA:\n{tables_text}"

    resp = _client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=_SYSTEM,
        messages=[{"role": "user", "content": _PROMPT.format(text=full_input[:14000])}],
    )

    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    data = json.loads(raw)
    if program:
        data["program"] = program
    if semester:
        data["semester"] = semester

    return ContentModel(**data)
