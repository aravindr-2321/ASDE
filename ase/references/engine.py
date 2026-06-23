"""Generate IEEE-formatted references with ISBN via LLM."""
import json
from ase.config import MAX_TOKENS
from ase.llm import complete
from ase.schemas.models import SubjectContent, TemplateBlueprint

_SYSTEM = """You are an academic librarian and IEEE citation expert.
Generate accurate, verifiable academic references. Return only valid JSON."""

_REF_PROMPT = """Generate IEEE-formatted Textbooks and References for this subject.

SUBJECT: {name}
PROGRAM LEVEL: {level}
MODULES COVERED: {modules}

Requirements:
- Minimum 3 Textbooks, minimum 5 References
- Prefer well-known, widely-adopted university textbooks
- Match difficulty to program level ({level})
- Include realistic ISBN-13 numbers (format: 978-X-XXXX-XXXX-X)
- IEEE format: [n] Author(s), "Title," Edition ed. Publisher, Year, ISBN: XXX-X-XXXX-XXXX-X
- Use recent editions (prefer 2015–2024)
- Prefer standard authors for the field

Return JSON:
{{
  "textbooks": [
    "[1] A. Author, B. Author, \\"Book Title,\\" 3rd ed. Publisher, 2022, ISBN: 978-X-XXXX-XXXX-X.",
    "[2] ..."
  ],
  "references": [
    "[1] A. Author, \\"Paper/Book Title,\\" Publisher/Journal, Year.",
    "[2] ..."
  ]
}}"""


def generate_references(
    subject: SubjectContent,
    blueprint: TemplateBlueprint,
    program: str,
    semester: int,
) -> tuple[list[str], list[str]]:
    level = "Undergraduate (UG)"
    prog_lower = program.lower()
    if "diploma" in prog_lower:
        level = "Diploma"
    elif any(x in prog_lower for x in ("m.tech", "mba", "msc", "pg")):
        level = "Postgraduate (PG)"

    modules_summary = "; ".join(f"{m.label}: {m.title}" for m in subject.modules[:5])

    raw = complete(_SYSTEM, _REF_PROMPT.format(
        name=subject.name, level=level,
        modules=modules_summary, program=program,
    ), MAX_TOKENS).strip()

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    data = json.loads(raw.strip().rstrip("```"))
    return data.get("textbooks", []), data.get("references", [])


def has_ref_sections(blueprint: TemplateBlueprint) -> bool:
    hs = blueprint.has_sections
    return hs.get("textbooks", False) or hs.get("references", False) or hs.get("suggested_reading", False)
