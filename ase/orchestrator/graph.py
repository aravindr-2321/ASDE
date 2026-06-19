"""
LangGraph orchestration — 3-gate flow:

  ingest → analyze_template → parse_content → detect_gaps
       → generate_fills → [GATE 1: content approval per section]
       → assemble → [GATE 2: preview + feedback loop]
       → export (DOCX + PDF) → [GATE 3: email recipients]
       → send_email → END
"""
from __future__ import annotations
import json
from typing import Optional, TypedDict
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt, Command

from ase.ingestion.parser import ingest
from ase.analysis.blueprint import extract_blueprint
from ase.analysis.content import extract_content
from ase.analysis.gap_detector import detect_gaps, fill_all_gaps, apply_approved_content
from ase.render.docx_builder import build_docx, export_pdf
from ase.qa.validator import validate
from ase.notify.emailer import send_review_email
from ase.schemas.models import (
    DocumentRecord, TemplateBlueprint, ContentModel, AuditEntry, EmailRecord,
)
from ase.store import db


# ── State ─────────────────────────────────────────────────────────────────────

class ASEState(TypedDict):
    doc_id: str
    university_id: str
    template_path: str
    syllabus_path: str
    program: str
    semester: int
    blueprint: Optional[dict]
    content_model: Optional[dict]
    detected_gaps: list[dict]
    generated_fills: list[dict]       # LLM-generated content pending human review
    approved_fills: list[dict]        # human-approved content
    docx_path: Optional[str]
    pdf_path: Optional[str]
    qa_report: Optional[dict]
    feedback: str                     # human feedback from preview gate
    version: int
    final: bool
    email_record_id: Optional[str]    # stored after email is sent


# ── Utilities ─────────────────────────────────────────────────────────────────

def _log(doc_id: str, from_: str, to_: str, note: str = "system"):
    doc = db.load_doc(doc_id)
    doc.audit.append(AuditEntry(from_state=from_, to_state=to_, by=note))
    doc.state = to_  # type: ignore[assignment]
    db.save_doc(doc)


# ── Nodes ─────────────────────────────────────────────────────────────────────

def node_ingest(state: ASEState) -> dict:
    """Parse both files and store raw data on the doc record."""
    _log(state["doc_id"], "intake", "analyzing")
    t_data = ingest(state["template_path"])
    s_data = ingest(state["syllabus_path"])
    doc = db.load_doc(state["doc_id"])
    doc.inputs.update({
        "template_hash": t_data.get("hash", ""),
        "syllabus_hash": s_data.get("hash", ""),
        "template_raw": json.dumps(t_data),
        "syllabus_raw": json.dumps(s_data),
    })
    db.save_doc(doc)
    return {}


def node_analyze_template(state: ASEState) -> dict:
    """Extract the full Template Blueprint — structure, fonts, colors, layout, margins."""
    doc = db.load_doc(state["doc_id"])
    t_data = json.loads(doc.inputs["template_raw"])
    bp = extract_blueprint(t_data, state["university_id"])

    # Persist blueprint to university profile
    profile = db.load_profile(state["university_id"])
    profile.blueprints = [bp.model_dump()]
    profile.display_name = profile.display_name or state["university_id"].upper()
    db.save_profile(profile)

    return {"blueprint": bp.model_dump()}


def node_parse_content(state: ASEState) -> dict:
    """Extract the ContentModel from the NIAT syllabus."""
    doc = db.load_doc(state["doc_id"])
    s_data = json.loads(doc.inputs["syllabus_raw"])
    content = extract_content(s_data, state["program"], state["semester"])

    doc.program = content.program
    doc.semester = content.semester
    db.save_doc(doc)
    return {"content_model": content.model_dump()}


def node_detect_gaps(state: ASEState) -> dict:
    """Compare template sections with content model — find what's missing."""
    _log(state["doc_id"], "analyzing", "drafting")
    blueprint = TemplateBlueprint(**state["blueprint"])
    content = ContentModel(**state["content_model"])
    gaps = detect_gaps(blueprint, content)
    return {"detected_gaps": gaps}


def node_generate_fills(state: ASEState) -> dict:
    """LLM generates content for every detected gap."""
    if not state["detected_gaps"]:
        return {"generated_fills": []}
    blueprint = TemplateBlueprint(**state["blueprint"])
    content = ContentModel(**state["content_model"])
    fills = fill_all_gaps(state["detected_gaps"], content, blueprint)
    return {"generated_fills": fills}


def node_review_content(state: ASEState) -> dict:
    """
    GATE 1 — Human approves LLM-generated content section by section.
    If no gaps were detected, this gate is skipped automatically.
    """
    fills = state.get("generated_fills", [])
    if not fills:
        return {"approved_fills": [], "content_model": state["content_model"]}

    # Interrupt — UI presents each generated fill for approval/edit
    approved: list[dict] = interrupt({
        "type": "content_review",
        "fills": fills,
        "instruction": "Review each LLM-generated section. Approve, edit, or reject before assembly.",
    })

    # Apply approved content back into the content model
    content = ContentModel(**state["content_model"])
    content = apply_approved_content(content, approved)
    return {"approved_fills": approved, "content_model": content.model_dump()}


def node_assemble(state: ASEState) -> dict:
    """Build the DOCX from blueprint + enriched content model."""
    blueprint = TemplateBlueprint(**state["blueprint"])
    content = ContentModel(**state["content_model"])
    doc = db.load_doc(state["doc_id"])

    ver = state.get("version", 0) + 1
    fname = f"{state['university_id']}_{content.program.replace(' ','_')}_Sem{content.semester}_v{ver}.docx"
    out = str(db.file_path(state["doc_id"], fname))
    build_docx(blueprint, content, out)

    qa = validate(out, content, blueprint)
    return {"docx_path": out, "qa_report": qa, "version": ver}


def node_preview(state: ASEState) -> dict:
    """
    GATE 2 — Show full document preview to human.
    Human can approve (→ export) or give feedback (→ re-assemble).
    """
    _log(state["doc_id"], "drafting", "review")
    decision: dict = interrupt({
        "type": "preview",
        "docx_path": state["docx_path"],
        "qa_report": state["qa_report"],
        "version": state["version"],
        "content_model": state["content_model"],
    })
    feedback = decision.get("feedback", "").strip()
    approved = decision.get("approved", False)

    if approved:
        return {"final": True, "feedback": ""}

    # Store feedback so next assemble pass can use it
    return {"final": False, "feedback": feedback}


def node_apply_feedback(state: ASEState) -> dict:
    """Re-generate content incorporating the human's feedback, then re-assemble."""
    import anthropic
    from ase.config import MODEL, MAX_TOKENS

    client = anthropic.Anthropic()
    content = ContentModel(**state["content_model"])
    blueprint = TemplateBlueprint(**state["blueprint"])
    feedback = state.get("feedback", "")

    prompt = f"""The human reviewer gave this feedback on the assembled syllabus:

FEEDBACK: {feedback}

CURRENT CONTENT SUMMARY:
Program: {content.program}, Semester: {content.semester}
Subjects: {[s.name for s in content.subjects]}

Apply the feedback. For each subject, return updated objectives and outcomes if they need changing.
Return JSON:
{{
  "updates": [
    {{
      "subject": "Subject Name",
      "objectives": ["updated CLO1...", "CLO2..."],
      "outcomes": ["updated CO1...", "CO2..."]
    }}
  ]
}}
Return empty updates array if no changes are needed for a subject."""

    resp = client.messages.create(
        model=MODEL, max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    data = json.loads(raw)
    subj_map = {s.name: i for i, s in enumerate(content.subjects)}
    for upd in data.get("updates", []):
        idx = subj_map.get(upd["subject"])
        if idx is not None:
            if upd.get("objectives"):
                content.subjects[idx].generated_objectives = upd["objectives"]
            if upd.get("outcomes"):
                content.subjects[idx].generated_outcomes = upd["outcomes"]

    return {"content_model": content.model_dump()}


def node_export(state: ASEState) -> dict:
    """Export DOCX + PDF and store as the authoritative approved file."""
    _log(state["doc_id"], "review", "approved")
    doc = db.load_doc(state["doc_id"])
    ver_num = state["version"]

    from ase.schemas.models import VersionRecord
    doc.versions.append(VersionRecord(
        version=ver_num,
        docx_path=state["docx_path"],
        qa_score=state["qa_report"].get("score", 0.0) if state["qa_report"] else 0.0,
        qa_report=state["qa_report"] or {},
        state="approved",
    ))
    doc.current_version = ver_num

    pdf_path = export_pdf(state["docx_path"])
    if pdf_path:
        doc.versions[-1].pdf_path = pdf_path

    db.save_doc(doc)
    return {"pdf_path": pdf_path}


def node_email_gate(state: ASEState) -> dict:
    """
    GATE 3 — Ask for reviewer email IDs after the document is finalized.
    Human provides email addresses; system sends the email.
    """
    decision: dict = interrupt({
        "type": "email_gate",
        "docx_path": state["docx_path"],
        "pdf_path": state.get("pdf_path"),
        "program": state["program"],
        "semester": state["semester"],
        "university": state["university_id"],
        "version": state["version"],
    })
    return {"_email_decision": decision}


def node_send_email(state: ASEState) -> dict:
    """Send the review email with DOCX + PDF attached to all provided email IDs."""
    decision = state.get("_email_decision", {})
    to_emails: list[str] = decision.get("to_emails", [])

    if not to_emails:
        return {"email_record_id": None}

    content = ContentModel(**state["content_model"])
    ok, message_id, err = send_review_email(
        to_emails=to_emails,
        program=content.program,
        semester=content.semester,
        university=state["university_id"].upper(),
        version=state["version"],
        docx_path=state["docx_path"],
        pdf_path=state.get("pdf_path"),
    )

    rec = EmailRecord(
        doc_id=state["doc_id"],
        version=state["version"],
        message_id=message_id,
        to_emails=to_emails,
        subject=f"[Review Request] {state['university_id'].upper()} — {content.program} | Semester {content.semester} Syllabus (v{state['version']})",
    )
    db.save_email_record(rec)

    if not ok:
        # Store the error but don't fail the graph
        rec.message_id = f"FAILED: {err}"
        db.save_email_record(rec)

    return {"email_record_id": rec.email_id}


# ── Routing ───────────────────────────────────────────────────────────────────

def route_preview(state: ASEState) -> str:
    return "export" if state.get("final") else "apply_feedback"


# ── Graph ─────────────────────────────────────────────────────────────────────

def build_graph():
    g = StateGraph(ASEState)

    for name, fn in [
        ("ingest",           node_ingest),
        ("analyze_template", node_analyze_template),
        ("parse_content",    node_parse_content),
        ("detect_gaps",      node_detect_gaps),
        ("generate_fills",   node_generate_fills),
        ("review_content",   node_review_content),   # GATE 1 — content approval
        ("assemble",         node_assemble),
        ("preview",          node_preview),          # GATE 2 — preview + feedback
        ("apply_feedback",   node_apply_feedback),
        ("export",           node_export),
        ("email_gate",       node_email_gate),       # GATE 3 — collect email IDs
        ("send_email",       node_send_email),
    ]:
        g.add_node(name, fn)

    g.set_entry_point("ingest")
    g.add_edge("ingest", "analyze_template")
    g.add_edge("analyze_template", "parse_content")
    g.add_edge("parse_content", "detect_gaps")
    g.add_edge("detect_gaps", "generate_fills")
    g.add_edge("generate_fills", "review_content")
    g.add_edge("review_content", "assemble")
    g.add_edge("assemble", "preview")
    g.add_conditional_edges("preview", route_preview, {"export": "export", "apply_feedback": "apply_feedback"})
    g.add_edge("apply_feedback", "assemble")
    g.add_edge("export", "email_gate")
    g.add_edge("email_gate", "send_email")
    g.add_edge("send_email", END)

    return g.compile(checkpointer=MemorySaver())


_graph = None

def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph
