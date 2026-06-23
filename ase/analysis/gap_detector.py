"""Detect content gaps between template sections and parsed syllabus; fill them with LLM."""
import json
from ase.config import MAX_TOKENS
from ase.llm import complete
from ase.schemas.models import TemplateBlueprint, ContentModel, SubjectContent

_DETECT_SYSTEM = "You are an academic document analyst. Return only valid JSON."

_DETECT_PROMPT = """Compare this university template's required sections against the available syllabus content.
Identify exactly what is missing or insufficient for each subject.

TEMPLATE REQUIRED SECTIONS (from label_dictionary + sections_order):
{sections}

TEMPLATE HAS THESE SECTIONS:
{has_sections}

CONTENT AVAILABLE:
{content_summary}

Return JSON — only gaps that genuinely need LLM generation:
{{
  "gaps": [
    {{
      "subject": "Exact Subject Name",
      "section": "objectives|outcomes|modules|references|textbooks|copo",
      "reason": "Brief reason why it's insufficient",
      "severity": "required|optional"
    }}
  ]
}}
Return empty gaps array if content is sufficient."""

_FILL_SYSTEM = """You are a University Curriculum & Academic Documentation Specialist.
Generate precise, accreditation-ready academic content. Return only valid JSON."""

_FILL_PROMPT = """Generate missing content for this section of a university syllabus.

SUBJECT: {subject_name}
SECTION TO FILL: {section}
REASON IT'S MISSING: {reason}
PROGRAM: {program} | SEMESTER: {semester}
UNIVERSITY TONE: {tone}
OBJECTIVE CODE LABEL: {obj_code} (use this prefix exactly, e.g. CLO1, CLO2 or CO1)

EXISTING CONTENT (for context, preserve this — only fill the gap):
Objectives: {existing_objectives}
Outcomes: {existing_outcomes}
Modules: {existing_modules}

INSTRUCTIONS:
- Bloom's Taxonomy verbs for objectives (Understand, Apply, Analyze, Evaluate, Create)
- Measurable, AICTE/NBA/NAAC-ready outcomes
- Professional academic language matching university tone
- 5-6 items for objectives/outcomes
- Match content to subject depth and program level

Return JSON:
{{
  "section": "{section}",
  "content": ["item1", "item2", "..."],
  "provenance": "generated",
  "generation_note": "Brief note on what was generated and why"
}}"""


def detect_gaps(blueprint: TemplateBlueprint, content: ContentModel) -> list[dict]:
    summary = [
        {
            "name": s.name,
            "objectives": len(s.objectives),
            "outcomes": len(s.outcomes),
            "modules": len(s.modules),
            "has_copo": bool(s.copo),
            "has_textbooks": bool(s.textbooks),
            "has_references": bool(s.references),
        }
        for s in content.subjects
    ]

    raw = complete(_DETECT_SYSTEM, _DETECT_PROMPT.format(
        sections=json.dumps(blueprint.sections_order + list(blueprint.label_dictionary.keys())),
        has_sections=json.dumps(blueprint.has_sections),
        content_summary=json.dumps(summary, indent=2),
    ), 2048)
    return json.loads(_clean(raw)).get("gaps", [])


def fill_gap(gap: dict, subject: SubjectContent, blueprint: TemplateBlueprint,
             program: str, semester: int) -> dict:
    raw = complete(_FILL_SYSTEM, _FILL_PROMPT.format(
        subject_name=subject.name,
        section=gap["section"],
        reason=gap["reason"],
        program=program,
        semester=semester,
        tone=blueprint.tone,
        obj_code=blueprint.label_dictionary.get("objective_code", "CLO"),
        existing_objectives="; ".join(subject.objectives[:3]) or "None",
        existing_outcomes="; ".join(subject.outcomes[:3]) or "None",
        existing_modules="; ".join(f"{m.label}: {m.title}" for m in subject.modules[:3]) or "None",
    ), MAX_TOKENS)
    result = json.loads(_clean(raw))
    result["subject"] = subject.name
    result["gap"] = gap
    return result


def fill_all_gaps(gaps: list[dict], content: ContentModel,
                  blueprint: TemplateBlueprint) -> list[dict]:
    subject_map = {s.name: s for s in content.subjects}
    return [
        fill_gap(gap, subj, blueprint, content.program, content.semester)
        for gap in gaps
        if (subj := subject_map.get(gap["subject"])) is not None
    ]


def apply_approved_content(content: ContentModel, approved_items: list[dict]) -> ContentModel:
    subject_map = {s.name: i for i, s in enumerate(content.subjects)}
    for item in approved_items:
        idx = subject_map.get(item.get("subject"))
        if idx is None:
            continue
        subj = content.subjects[idx]
        section = item.get("section", "")
        approved_content = item.get("approved_content", item.get("content", []))
        if section == "objectives":
            subj.generated_objectives = approved_content
        elif section == "outcomes":
            subj.generated_outcomes = approved_content
        elif section in ("references", "textbooks"):
            subj.generated_references = approved_content
        content.subjects[idx] = subj
    return content


def _clean(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return text.strip().rstrip("```")
