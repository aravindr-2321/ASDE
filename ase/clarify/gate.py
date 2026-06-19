"""Question generation, clarification memory, and scoped answer recall."""
import json
import anthropic
from ase.config import MODEL, MAX_TOKENS
from ase.schemas.models import ClarificationRecord, TemplateBlueprint, ContentModel

_client = anthropic.Anthropic()

_SYSTEM = """You are an academic documentation assistant. Generate minimal, precise clarification questions.
Return only valid JSON."""

_PROMPT = """Given this template blueprint and content analysis, identify what information is missing or ambiguous
that prevents accurate generation of a university syllabus document.

BLUEPRINT CONFIDENCE:
{confidence}

BLUEPRINT LABELS:
{labels}

HAS SECTIONS:
{has_sections}

CONTENT (first subject summary):
{content_summary}

CUSTOM INSTRUCTIONS:
{instructions}

Generate only NECESSARY questions (max 5). Skip questions if already answered in custom instructions.
Return JSON array:
[
  {{
    "trigger": "what caused this question",
    "question": "Clear question for the user",
    "options": ["Option A", "Option B", "Option C"],
    "scope": "this_university"
  }}
]

Always include the textbook/reference question if has_sections shows textbooks or references = true:
{{
  "trigger": "textbooks section present in template",
  "question": "Would you like me to auto-generate IEEE-formatted Textbooks and References with verified ISBN numbers based on the syllabus content and university level?",
  "options": ["Yes, generate with ISBNs", "No, leave blank"],
  "scope": "this_university"
}}

Return empty array [] if nothing is ambiguous."""


def generate_questions(
    blueprint: TemplateBlueprint,
    content: ContentModel,
    memory: list[ClarificationRecord],
    instructions: str = "",
) -> list[ClarificationRecord]:
    """Ask Claude which questions are needed; filter out already-answered ones."""
    answered = {r.question for r in memory if r.answer}

    content_summary = (
        f"Program: {content.program}, Semester: {content.semester}, "
        f"Subjects: {[s.name for s in content.subjects[:3]]}"
    )

    resp = _client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=_SYSTEM,
        messages=[{"role": "user", "content": _PROMPT.format(
            confidence=json.dumps(blueprint.confidence),
            labels=json.dumps(blueprint.label_dictionary),
            has_sections=json.dumps(blueprint.has_sections),
            content_summary=content_summary,
            instructions=instructions or "None",
        )}],
    )

    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    items = json.loads(raw) if raw.strip() != "[]" else []
    return [
        ClarificationRecord(**item)
        for item in items
        if item["question"] not in answered
    ]


def apply_memory(
    questions: list[ClarificationRecord],
    memory: list[ClarificationRecord],
) -> tuple[list[ClarificationRecord], list[ClarificationRecord]]:
    """Split questions into auto-answered (from memory) and pending."""
    mem_map = {r.question: r.answer for r in memory if r.answer}
    auto, pending = [], []
    for q in questions:
        if q.question in mem_map:
            q.answer = mem_map[q.question]
            auto.append(q)
        else:
            pending.append(q)
    return auto, pending


def get_ref_decision(memory: list[ClarificationRecord]) -> str | None:
    """Look up stored answer to the ISBN/textbook question."""
    for r in memory:
        if "textbook" in r.trigger.lower() or "isbn" in r.question.lower():
            return r.answer
    return None
