"""Extract ContentModels for all semesters from a NIAT standard syllabus via Claude."""
import json
import anthropic
from ase.config import MODEL, MAX_TOKENS
from ase.schemas.models import ContentModel

_client = anthropic.Anthropic()

_SYSTEM = """You are an academic content extractor. Extract syllabus content into structured JSON.
Preserve all text VERBATIM — never paraphrase or reorder. Return only valid JSON."""

_PROMPT = """Extract the complete syllabus content for ALL {num_semesters} semester(s) from this NIAT document.

SYLLABUS TEXT:
{text}

For each semester, extract every subject with full details.
Return this exact JSON structure:

{{
  "program": "Full Program Name (e.g. B.Tech CSE Data Science)",
  "semesters": {{
    "1": {{
      "subjects": [
        {{
          "name": "Subject Name",
          "code": "SUB101 or null",
          "credits": "3 or null",
          "ltp": "3-0-0 or null",
          "marks": "100 or null",
          "objectives": ["verbatim objective 1", "objective 2"],
          "outcomes": ["verbatim outcome 1", "outcome 2"],
          "modules": [
            {{"label": "Module I", "title": "Module Title", "topics": "topic1, topic2, ..."}}
          ],
          "copo": {{
            "po_count": 12,
            "scale": ["H", "M", "L", "-"],
            "rows": [["H", "M", "-", "L", "M", "H", "-", "-", "M", "-", "L", "H"]]
          }},
          "textbooks": ["verbatim textbook entry if present"],
          "references": ["verbatim reference entry if present"]
        }}
      ]
    }},
    "2": {{ "subjects": [...] }},
    "3": {{ "subjects": [...] }}
  }}
}}

Rules:
- Include all {num_semesters} semester keys ("1" through "{num_semesters}") even if a semester has no subjects (use empty array).
- Preserve every word verbatim from the source document.
- If the document only covers one semester, put all subjects under "1" and leave the rest empty."""


def extract_all_semesters(
    syllabus_data: dict,
    num_semesters: int,
) -> tuple[str, dict[int, ContentModel]]:
    """
    Parse the full NIAT syllabus and return content for all N semesters.
    Returns (program_name, {1: ContentModel, 2: ContentModel, ...}).
    """
    text = (
        syllabus_data.get("full_text", "")
        or "\n".join(syllabus_data.get("paragraphs", []))
    )

    tables_text = ""
    for t in syllabus_data.get("tables", [])[:30]:
        for row in t.get("rows", []):
            tables_text += " | ".join(str(c) for c in row if c) + "\n"

    full_input = f"{text}\n\nTABLE DATA:\n{tables_text}"

    resp = _client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=_SYSTEM,
        messages=[{"role": "user", "content": _PROMPT.format(
            num_semesters=num_semesters,
            text=full_input[:14000],
        )}],
    )

    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip().rstrip("```")

    data = json.loads(raw)
    program = data.get("program", "Unknown Program")
    semesters_raw = data.get("semesters", {})

    result: dict[int, ContentModel] = {}
    for sem_num in range(1, num_semesters + 1):
        sem_data = semesters_raw.get(str(sem_num), {})
        result[sem_num] = ContentModel(
            program=program,
            semester=sem_num,
            subjects=sem_data.get("subjects", []),
        )

    return program, result
