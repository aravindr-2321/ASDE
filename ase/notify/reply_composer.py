"""LLM-powered: analyze reviewer feedback → extract changes → draft formal reply email."""
import json
import anthropic
from ase.config import MODEL, MAX_TOKENS

_client = anthropic.Anthropic()

# ── Analyze reviewer feedback ─────────────────────────────────────────────────

_ANALYZE_SYSTEM = "You are an academic document reviewer. Extract specific change requests from reviewer feedback. Return only valid JSON."

_ANALYZE_PROMPT = """A reviewer replied to a university syllabus review email with the following feedback.
Analyze it carefully and extract every specific, actionable change they are requesting.

PROGRAM: {program} | SEMESTER: {semester}
REVIEWER FEEDBACK:
{feedback}

Return JSON:
{{
  "reviewer_name": "Reviewer's name if mentioned, else 'Reviewer'",
  "changes_requested": [
    "Specific change 1: which subject / section + what exactly to change",
    "Specific change 2: ...",
    "..."
  ],
  "general_concerns": "One-line summary of overall concern",
  "priority": "high|medium|low",
  "sentiment": "positive|neutral|critical"
}}"""


def analyze_feedback(feedback_text: str, program: str, semester: int) -> dict:
    """Extract structured change requests from a reviewer's email reply."""
    resp = _client.messages.create(
        model=MODEL, max_tokens=1024, system=_ANALYZE_SYSTEM,
        messages=[{"role": "user", "content": _ANALYZE_PROMPT.format(
            program=program, semester=semester, feedback=feedback_text,
        )}],
    )
    raw = _clean(resp.content[0].text)
    return json.loads(raw)


# ── Generate formal reply email ───────────────────────────────────────────────

_REPLY_SYSTEM = (
    "You are an academic correspondence specialist at NxtWave / NIAT. "
    "Write formal, warm, professional academic reply emails. "
    "Return only the email body text — no subject line, no markdown."
)

_REPLY_PROMPT = """Write a formal reply email to a university syllabus reviewer.

CONTEXT:
  Program   : {program}
  Semester  : {semester}
  University: {university}
  Previous version reviewed: v{prev_version}
  Updated version being sent: v{new_version}
  Reviewer name: {reviewer_name}

REVIEWER'S ORIGINAL CONCERNS:
{feedback_summary}

CHANGES INCORPORATED IN v{new_version}:
{changes_list}

ATTACHED FILES:
  • {docx_name}
  • {pdf_name}

INSTRUCTIONS FOR THE EMAIL:
1. Open with a warm but formal salutation addressing {reviewer_name} by name
2. Thank them sincerely for their time and valuable feedback
3. Acknowledge their specific concerns in one sentence
4. State clearly that the document has been revised based on their inputs
5. List every change made (numbered), mapped to their suggestions
6. Mention the version number of the updated document explicitly
7. Invite further feedback or clarification if needed
8. Close with a professional sign-off

Tone: formal, respectful, concise. Do NOT be verbose or repeat the same point twice."""


def generate_reply_body(
    reviewer_name: str,
    feedback_summary: str,
    changes_made: list[str],
    program: str,
    semester: int,
    university: str,
    prev_version: int,
    new_version: int,
    docx_name: str,
    pdf_name: str,
) -> str:
    """Generate a formal reply email body using LLM."""
    changes_list = "\n".join(f"  {i+1}. {c}" for i, c in enumerate(changes_made))

    resp = _client.messages.create(
        model=MODEL, max_tokens=MAX_TOKENS, system=_REPLY_SYSTEM,
        messages=[{"role": "user", "content": _REPLY_PROMPT.format(
            program=program, semester=semester, university=university,
            prev_version=prev_version, new_version=new_version,
            reviewer_name=reviewer_name,
            feedback_summary=feedback_summary,
            changes_list=changes_list,
            docx_name=docx_name,
            pdf_name=pdf_name,
        )}],
    )
    return resp.content[0].text.strip()


# ── Apply feedback to content model ──────────────────────────────────────────

_REVISE_SYSTEM = "You are a University Curriculum Specialist. Revise syllabus content based on reviewer feedback. Return only valid JSON."

_REVISE_PROMPT = """Revise this syllabus content to incorporate the reviewer's requested changes.

PROGRAM: {program} | SEMESTER: {semester}
CURRENT CONTENT:
{content_summary}

REVIEWER REQUESTED CHANGES:
{changes}

For each subject that needs updating, return revised objectives and/or outcomes.
Return JSON:
{{
  "updates": [
    {{
      "subject": "Exact Subject Name",
      "objectives": ["Revised CLO1...", "CLO2..."],
      "outcomes":   ["Revised CO1...", "CO2..."],
      "change_notes": ["What specifically changed and why"]
    }}
  ],
  "changes_made": [
    "Human-readable description of each change for the reply email"
  ]
}}
Return empty updates array for subjects that need no changes."""


def apply_feedback_to_content(
    content_dict: dict,
    changes_requested: list[str],
    program: str,
    semester: int,
) -> tuple[dict, list[str]]:
    """Use LLM to revise content model based on reviewer's change requests.
    Returns (updated_content_dict, changes_made_list)."""
    from ase.schemas.models import ContentModel
    content = ContentModel(**content_dict)

    summary = [
        {
            "name": s.name,
            "objectives": (s.generated_objectives or s.objectives)[:3],
            "outcomes":   (s.generated_outcomes or s.outcomes)[:3],
            "modules":    [m.label + ": " + m.title for m in s.modules[:3]],
        }
        for s in content.subjects
    ]

    resp = _client.messages.create(
        model=MODEL, max_tokens=MAX_TOKENS, system=_REVISE_SYSTEM,
        messages=[{"role": "user", "content": _REVISE_PROMPT.format(
            program=program, semester=semester,
            content_summary=json.dumps(summary, indent=2),
            changes="\n".join(f"- {c}" for c in changes_requested),
        )}],
    )

    raw = _clean(resp.content[0].text)
    data = json.loads(raw)
    changes_made: list[str] = data.get("changes_made", [])

    subj_map = {s.name: i for i, s in enumerate(content.subjects)}
    for upd in data.get("updates", []):
        idx = subj_map.get(upd.get("subject"))
        if idx is not None:
            if upd.get("objectives"):
                content.subjects[idx].generated_objectives = upd["objectives"]
            if upd.get("outcomes"):
                content.subjects[idx].generated_outcomes = upd["outcomes"]

    return content.model_dump(), changes_made


def _clean(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return text.strip()
