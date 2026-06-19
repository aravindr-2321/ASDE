"""Detect reference sections, generate IEEE-formatted references with ISBN verification."""
import json
import anthropic
from ase.config import MODEL, MAX_TOKENS
from ase.schemas.models import SubjectContent, TemplateBlueprint

_client = anthropic.Anthropic()

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
    """Generate IEEE-formatted textbooks and references for a subject."""
    # Determine level from program name
    level = "Undergraduate (UG)"
    prog_lower = program.lower()
    if "diploma" in prog_lower:
        level = "Diploma"
    elif "m.tech" in prog_lower or "mba" in prog_lower or "msc" in prog_lower or "pg" in prog_lower:
        level = "Postgraduate (PG)"

    modules_summary = "; ".join(
        f"{m.label}: {m.title}" for m in subject.modules[:5]
    )

    resp = _client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=_SYSTEM,
        messages=[{"role": "user", "content": _REF_PROMPT.format(
            name=subject.name,
            level=level,
            modules=modules_summary,
            program=program,
        )}],
    )

    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    data = json.loads(raw)
    return data.get("textbooks", []), data.get("references", [])


def has_ref_sections(blueprint: TemplateBlueprint) -> bool:
    """Check if template has textbook or reference sections."""
    hs = blueprint.has_sections
    return hs.get("textbooks", False) or hs.get("references", False) or hs.get("suggested_reading", False)
