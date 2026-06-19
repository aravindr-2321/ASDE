"""Generate Bloom-aligned CO/CLO and refined modules via Claude."""
import json
import anthropic
from ase.config import MODEL, MAX_TOKENS
from ase.schemas.models import SubjectContent, TemplateBlueprint

_client = anthropic.Anthropic()

_SYSTEM = """You are a University Curriculum & Academic Documentation Specialist.
Generate accreditation-ready academic content aligned to Bloom's Taxonomy.
Return only valid JSON."""

_OBJ_PROMPT = """Generate Course {code_label}s (Course {label_type}s) for this subject.

SUBJECT: {name}
PROGRAM: {program} | SEMESTER: {semester}
EXISTING OBJECTIVES (source-preserved, use as context):
{existing}

TEMPLATE TONE: {tone}
UNIVERSITY LABEL: {code_label} (use this exact code, e.g. CLO1, CLO2 or CO1, CO2)

Requirements:
- Bloom's Taxonomy verbs (Remember→Create levels)
- Measurable, specific, accreditation-ready (AICTE/NBA/NAAC/NEP 2020)
- Match subject depth and university level
- 5-6 objectives if none exist, else refine existing
- Professional academic language

Return JSON:
{{
  "objectives": [
    "{code_label}1: <Bloom verb> <specific measurable statement>",
    "{code_label}2: ..."
  ],
  "outcomes": [
    "CO1: Upon completing this course, students will be able to <verb> ...",
    "CO2: ..."
  ]
}}"""


def generate_objectives_outcomes(
    subject: SubjectContent,
    blueprint: TemplateBlueprint,
    program: str,
    semester: int,
) -> tuple[list[str], list[str]]:
    """Generate Bloom-aligned objectives and outcomes for a subject."""
    code_label = blueprint.label_dictionary.get("objective_code", "CLO")
    tone = blueprint.tone or "formal-academic"

    existing_obj = "\n".join(f"- {o}" for o in subject.objectives) or "None provided"

    resp = _client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=_SYSTEM,
        messages=[{"role": "user", "content": _OBJ_PROMPT.format(
            name=subject.name,
            program=program,
            semester=semester,
            existing=existing_obj,
            tone=tone,
            code_label=code_label,
            label_type="Learning Objective" if code_label == "CLO" else "Objective",
        )}],
    )

    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    data = json.loads(raw)
    return data.get("objectives", []), data.get("outcomes", [])


_MODULE_PROMPT = """Refine these module topics into professional academic language for a university syllabus.

SUBJECT: {name}
MODULE: {label} — {title}
TOPICS (preserve all verbatim, only improve language/formatting):
{topics}

TONE: {tone}

Return JSON: {{"refined_topics": "Topic 1: description; Topic 2: description; ..."}}
Preserve ALL original topics — never remove or invent content."""


def refine_module_topics(subject: SubjectContent, blueprint: TemplateBlueprint) -> SubjectContent:
    """Return subject with academically refined module descriptions."""
    tone = blueprint.tone or "formal-academic"
    refined_modules = []

    for mod in subject.modules:
        try:
            resp = _client.messages.create(
                model=MODEL,
                max_tokens=1024,
                system=_SYSTEM,
                messages=[{"role": "user", "content": _MODULE_PROMPT.format(
                    name=subject.name,
                    label=mod.label,
                    title=mod.title,
                    topics=mod.topics,
                    tone=tone,
                )}],
            )
            raw = resp.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw)
            refined_modules.append(mod.model_copy(update={"topics": data.get("refined_topics", mod.topics)}))
        except Exception:
            refined_modules.append(mod)

    return subject.model_copy(update={"modules": refined_modules})
