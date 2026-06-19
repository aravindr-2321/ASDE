"""
LangGraph orchestration — multi-semester, 3-gate flow:

  ingest → analyze_template → parse_content (all N semesters)
        → detect_gaps → generate_fills
        → [GATE 1: content approval for all semesters]
        → assemble (builds N DOCX files)
        → [GATE 2: preview all semesters + feedback loop]
        → export (N DOCX + N PDF)
        → [GATE 3: email recipients]
        → send_email → END
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional, TypedDict
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt

from ase.ingestion.parser import ingest
from ase.analysis.blueprint import extract_blueprint
from ase.analysis.content import extract_all_semesters
from ase.analysis.gap_detector import detect_gaps, fill_all_gaps, apply_approved_content
from ase.render.docx_builder import build_docx, export_pdf
from ase.qa.validator import validate
from ase.notify.emailer import send_review_email
from ase.schemas.models import (
    DocumentRecord, TemplateBlueprint, ContentModel,
    AuditEntry, EmailRecord, VersionRecord,
)
from ase.store import db


# ── State ─────────────────────────────────────────────────────────────────────

class ASEState(TypedDict):
    doc_id: str
    university_id: str
    template_path: str
    syllabus_path: str
    num_semesters: int                  # how many semester documents to produce
    program: str                        # auto-extracted from syllabus
    blueprint: Optional[dict]
    # Multi-semester content — keys are string ints ("1", "2", …)
    semester_contents: dict             # {"1": ContentModel.dict, "2": ...}
    semester_gaps: dict                 # {"1": [gap,...], ...}
    semester_fills: dict                # {"1": [fill,...], ...}
    semester_approved_fills: dict       # {"1": [fill,...], ...}
    semester_docx_paths: dict           # {"1": "path/to/sem1.docx", ...}
    semester_pdf_paths: dict            # {"1": "path/to/sem1.pdf", ...}
    semester_qa_reports: dict           # {"1": {score:…}, ...}
    feedback: str
    version: int
    final: bool
    email_record_id: Optional[str]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _log(doc_id: str, from_: str, to_: str, note: str = "system"):
    doc = db.load_doc(doc_id)
    doc.audit.append(AuditEntry(from_state=from_, to_state=to_, by=note))
    doc.state = to_  # type: ignore[assignment]
    db.save_doc(doc)


def _sems(state: ASEState) -> range:
    return range(1, state["num_semesters"] + 1)


# ── Nodes ─────────────────────────────────────────────────────────────────────

def node_ingest(state: ASEState) -> dict:
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
    doc = db.load_doc(state["doc_id"])
    t_data = json.loads(doc.inputs["template_raw"])
    bp = extract_blueprint(t_data, state["university_id"])

    profile = db.load_profile(state["university_id"])
    profile.blueprints = [bp.model_dump()]
    profile.display_name = profile.display_name or state["university_id"].upper()
    db.save_profile(profile)

    return {"blueprint": bp.model_dump()}


def node_parse_content(state: ASEState) -> dict:
    """Extract content for ALL semesters from the NIAT syllabus in one LLM call."""
    doc = db.load_doc(state["doc_id"])
    s_data = json.loads(doc.inputs["syllabus_raw"])

    program, sem_map = extract_all_semesters(s_data, state["num_semesters"])

    semester_contents = {
        str(sem): content.model_dump()
        for sem, content in sem_map.items()
    }

    doc.program = program
    doc.num_semesters = state["num_semesters"]
    db.save_doc(doc)

    return {"program": program, "semester_contents": semester_contents}


def node_detect_gaps(state: ASEState) -> dict:
    """Detect content gaps for every semester."""
    _log(state["doc_id"], "analyzing", "drafting")
    blueprint = TemplateBlueprint(**state["blueprint"])
    semester_gaps: dict = {}

    for sem in _sems(state):
        content = ContentModel(**state["semester_contents"][str(sem)])
        semester_gaps[str(sem)] = detect_gaps(blueprint, content)

    return {"semester_gaps": semester_gaps}


def node_generate_fills(state: ASEState) -> dict:
    """LLM generates fill content for every gap in every semester."""
    blueprint = TemplateBlueprint(**state["blueprint"])
    semester_fills: dict = {}

    for sem in _sems(state):
        gaps = state["semester_gaps"].get(str(sem), [])
        if not gaps:
            semester_fills[str(sem)] = []
            continue
        content = ContentModel(**state["semester_contents"][str(sem)])
        semester_fills[str(sem)] = fill_all_gaps(gaps, content, blueprint)

    return {"semester_fills": semester_fills}


def node_review_content(state: ASEState) -> dict:
    """
    GATE 1 — Human reviews LLM-generated content for ALL semesters.
    Skipped automatically if no gaps were found across any semester.
    """
    all_fills = {
        k: v for k, v in state["semester_fills"].items() if v
    }

    if not all_fills:
        return {
            "semester_approved_fills": {str(s): [] for s in _sems(state)},
            "semester_contents": state["semester_contents"],
        }

    # Interrupt — UI shows fills grouped by semester
    approved_by_sem: dict = interrupt({
        "type": "content_review",
        "semester_fills": all_fills,
        "num_semesters": state["num_semesters"],
        "instruction": "Review LLM-generated content for each semester. Approve, edit, or skip.",
    })

    # Apply approved fills back into each semester's content model
    updated_contents = dict(state["semester_contents"])
    for sem_str, approved_list in approved_by_sem.items():
        if not approved_list:
            continue
        content = ContentModel(**updated_contents[sem_str])
        content = apply_approved_content(content, approved_list)
        updated_contents[sem_str] = content.model_dump()

    return {
        "semester_approved_fills": approved_by_sem,
        "semester_contents": updated_contents,
    }


def node_assemble(state: ASEState) -> dict:
    """Build one DOCX per semester using the shared blueprint."""
    blueprint = TemplateBlueprint(**state["blueprint"])
    ver = state.get("version", 0) + 1

    docx_paths: dict = {}
    qa_reports: dict = {}

    for sem in _sems(state):
        content = ContentModel(**state["semester_contents"][str(sem)])
        fname = (
            f"{state['university_id']}_"
            f"{content.program.replace(' ','_')}_"
            f"Sem{sem}_v{ver}.docx"
        )
        out = str(db.file_path(state["doc_id"], fname))
        build_docx(blueprint, content, out)

        # Persist content JSON for revision access
        cjson = str(db.file_path(state["doc_id"], f"content_sem{sem}_v{ver}.json"))
        Path(cjson).write_text(content.model_dump_json(indent=2), encoding="utf-8")

        qa = validate(out, content, blueprint)
        docx_paths[str(sem)] = out
        qa_reports[str(sem)] = qa

    return {
        "semester_docx_paths": docx_paths,
        "semester_qa_reports": qa_reports,
        "version": ver,
    }


def node_preview(state: ASEState) -> dict:
    """GATE 2 — Show all semester documents for human approval or feedback."""
    _log(state["doc_id"], "drafting", "review")

    decision: dict = interrupt({
        "type": "preview",
        "num_semesters": state["num_semesters"],
        "semester_docx_paths": state["semester_docx_paths"],
        "semester_qa_reports": state["semester_qa_reports"],
        "semester_contents": state["semester_contents"],
        "version": state["version"],
    })

    feedback = decision.get("feedback", "").strip()
    approved = decision.get("approved", False)

    if approved:
        return {"final": True, "feedback": ""}
    return {"final": False, "feedback": feedback}


def node_apply_feedback(state: ASEState) -> dict:
    """Apply human feedback to the appropriate semester content model(s)."""
    import anthropic
    from ase.config import MODEL, MAX_TOKENS

    client = anthropic.Anthropic()
    feedback = state.get("feedback", "")
    updated_contents = dict(state["semester_contents"])

    for sem in _sems(state):
        content = ContentModel(**updated_contents[str(sem)])
        prompt = f"""The reviewer gave this feedback on a {state['num_semesters']}-semester syllabus:

FEEDBACK: {feedback}

CURRENT SEMESTER {sem} CONTENT:
Program: {content.program}, Semester: {sem}
Subjects: {[s.name for s in content.subjects]}

If this feedback applies to Semester {sem}, return updated objectives and outcomes.
Return JSON:
{{
  "applies": true,
  "updates": [
    {{
      "subject": "Subject Name",
      "objectives": ["updated CLO1...", "CLO2..."],
      "outcomes": ["updated CO1...", "CO2..."]
    }}
  ]
}}
If feedback does not apply to Semester {sem}, return: {{"applies": false, "updates": []}}"""

        resp = client.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        data = json.loads(raw.strip().rstrip("```"))
        if not data.get("applies"):
            continue

        subj_map = {s.name: i for i, s in enumerate(content.subjects)}
        for upd in data.get("updates", []):
            idx = subj_map.get(upd.get("subject"))
            if idx is not None:
                if upd.get("objectives"):
                    content.subjects[idx].generated_objectives = upd["objectives"]
                if upd.get("outcomes"):
                    content.subjects[idx].generated_outcomes = upd["outcomes"]

        updated_contents[str(sem)] = content.model_dump()

    return {"semester_contents": updated_contents}


def node_export(state: ASEState) -> dict:
    """Export all semester DOCX → PDF and record approved versions."""
    _log(state["doc_id"], "review", "approved")
    doc = db.load_doc(state["doc_id"])
    ver_num = state["version"]

    pdf_paths: dict = {}
    semester_paths: dict = {}

    for sem in _sems(state):
        docx = state["semester_docx_paths"].get(str(sem), "")
        pdf = export_pdf(docx) if docx else None
        if pdf:
            pdf_paths[str(sem)] = pdf

        cjson = str(db.file_path(state["doc_id"], f"content_sem{sem}_v{ver_num}.json"))
        semester_paths[str(sem)] = {
            "docx": docx,
            "pdf": pdf or "",
            "content": cjson,
            "qa": state["semester_qa_reports"].get(str(sem), {}),
        }

    # One VersionRecord covering all semesters
    first_sem = str(next(iter(semester_paths)))
    avg_score = (
        sum(d["qa"].get("score", 0) for d in semester_paths.values())
        / len(semester_paths)
    )
    doc.versions.append(VersionRecord(
        version=ver_num,
        docx_path=semester_paths[first_sem]["docx"],
        pdf_path=semester_paths[first_sem]["pdf"],
        content_model_path=semester_paths[first_sem]["content"],
        semester_paths=semester_paths,
        qa_score=avg_score,
        qa_report=state["semester_qa_reports"],
        state="approved",
    ))
    doc.current_version = ver_num
    db.save_doc(doc)

    return {"semester_pdf_paths": pdf_paths}


def node_email_gate(state: ASEState) -> dict:
    """GATE 3 — Collect reviewer email IDs before sending."""
    decision: dict = interrupt({
        "type": "email_gate",
        "num_semesters": state["num_semesters"],
        "semester_docx_paths": state["semester_docx_paths"],
        "semester_pdf_paths": state.get("semester_pdf_paths", {}),
        "program": state["program"],
        "university": state["university_id"],
        "version": state["version"],
    })
    return {"_email_decision": decision}


def node_send_email(state: ASEState) -> dict:
    """Send one review email with ALL semester documents attached."""
    decision = state.get("_email_decision", {})
    to_emails: list[str] = decision.get("to_emails", [])

    if not to_emails:
        return {"email_record_id": None}

    # Collect all DOCX and PDF files
    all_docx = list(state["semester_docx_paths"].values())
    all_pdf = list(state.get("semester_pdf_paths", {}).values())
    primary_docx = all_docx[0] if all_docx else ""
    primary_pdf = all_pdf[0] if all_pdf else None

    ok, message_id, err = send_review_email(
        to_emails=to_emails,
        program=state["program"],
        semester=state["num_semesters"],  # total semesters count
        university=state["university_id"].upper(),
        version=state["version"],
        docx_path=primary_docx,
        pdf_path=primary_pdf,
    )

    subject = (
        f"[Review Request] {state['university_id'].upper()} — "
        f"{state['program']} | Semesters 1–{state['num_semesters']} (v{state['version']})"
    )
    rec = EmailRecord(
        doc_id=state["doc_id"],
        version=state["version"],
        message_id=message_id if ok else f"FAILED: {err}",
        to_emails=to_emails,
        subject=subject,
    )
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
        ("review_content",   node_review_content),
        ("assemble",         node_assemble),
        ("preview",          node_preview),
        ("apply_feedback",   node_apply_feedback),
        ("export",           node_export),
        ("email_gate",       node_email_gate),
        ("send_email",       node_send_email),
    ]:
        g.add_node(name, fn)

    g.set_entry_point("ingest")
    g.add_edge("ingest",           "analyze_template")
    g.add_edge("analyze_template", "parse_content")
    g.add_edge("parse_content",    "detect_gaps")
    g.add_edge("detect_gaps",      "generate_fills")
    g.add_edge("generate_fills",   "review_content")
    g.add_edge("review_content",   "assemble")
    g.add_edge("assemble",         "preview")
    g.add_conditional_edges(
        "preview", route_preview,
        {"export": "export", "apply_feedback": "apply_feedback"},
    )
    g.add_edge("apply_feedback", "assemble")
    g.add_edge("export",         "email_gate")
    g.add_edge("email_gate",     "send_email")
    g.add_edge("send_email",     END)

    return g.compile(checkpointer=MemorySaver())


_graph = None

def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph
