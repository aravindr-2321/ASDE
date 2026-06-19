"""LangGraph orchestration: intake → analyze → clarify (gate) → generate → assemble → QA → review (gate) → export."""
from __future__ import annotations
import json
from typing import Any, Optional, TypedDict
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt, Command

from ase import config  # noqa — loads env
from ase.ingestion.parser import ingest
from ase.analysis.blueprint import extract_blueprint
from ase.analysis.content import extract_content
from ase.clarify.gate import generate_questions, apply_memory, get_ref_decision
from ase.generate.academic import generate_objectives_outcomes, refine_module_topics
from ase.references.engine import generate_references, has_ref_sections
from ase.render.docx_builder import build_docx
from ase.qa.validator import validate
from ase.approval.workflow import add_version
from ase.schemas.models import (
    DocumentRecord, TemplateBlueprint, ContentModel,
    ClarificationRecord, AuditEntry,
)
from ase.store import db


# ── State ─────────────────────────────────────────────────────────────────────

class ASEState(TypedDict):
    doc_id: str
    university_id: str
    template_path: str
    syllabus_path: str
    custom_instructions: str
    program: str
    semester: int
    blueprint: Optional[dict]
    content_model: Optional[dict]
    clarification_answers: dict        # question → answer
    ref_decision: Optional[str]        # "yes" | "no"
    generated: bool
    docx_path: Optional[str]
    qa_report: Optional[dict]
    generation_report: dict
    error: Optional[str]


# ── Helper ────────────────────────────────────────────────────────────────────

def _update_doc_state(doc_id: str, state: str, by: str = "system"):
    doc = db.load_doc(doc_id)
    doc.audit.append(AuditEntry(from_state=doc.state, to_state=state, by=by))  # type: ignore
    doc.state = state  # type: ignore
    db.save_doc(doc)


# ── Nodes ─────────────────────────────────────────────────────────────────────

def node_ingest(state: ASEState) -> dict:
    _update_doc_state(state["doc_id"], "analyzing")
    template_data = ingest(state["template_path"])
    syllabus_data = ingest(state["syllabus_path"])
    # Store raw data in doc inputs
    doc = db.load_doc(state["doc_id"])
    doc.inputs["template_hash"] = template_data.get("hash", "")
    doc.inputs["syllabus_hash"] = syllabus_data.get("hash", "")
    doc.inputs["template_raw"] = json.dumps(template_data)
    doc.inputs["syllabus_raw"] = json.dumps(syllabus_data)
    db.save_doc(doc)
    return {}


def node_analyze(state: ASEState) -> dict:
    doc = db.load_doc(state["doc_id"])
    template_data = json.loads(doc.inputs["template_raw"])
    bp = extract_blueprint(template_data, state["university_id"])
    blueprint_dict = bp.model_dump()
    # Save blueprint to university profile
    profile = db.load_profile(state["university_id"])
    profile.blueprints = [blueprint_dict]  # latest blueprint
    db.save_profile(profile)
    return {"blueprint": blueprint_dict}


def node_parse_content(state: ASEState) -> dict:
    doc = db.load_doc(state["doc_id"])
    syllabus_data = json.loads(doc.inputs["syllabus_raw"])
    content = extract_content(syllabus_data, state["program"], state["semester"])
    content_dict = content.model_dump()
    doc.program = content.program
    doc.semester = content.semester
    db.save_doc(doc)
    return {"content_model": content_dict}


def node_clarify(state: ASEState) -> dict:
    """Human interrupt gate: ask pending questions, wait for answers."""
    blueprint = TemplateBlueprint(**state["blueprint"])
    content = ContentModel(**state["content_model"])
    profile = db.load_profile(state["university_id"])

    questions = generate_questions(
        blueprint, content, profile.clarification_memory, state["custom_instructions"]
    )
    _, pending = apply_memory(questions, profile.clarification_memory)

    if not pending:
        return {"clarification_answers": state.get("clarification_answers", {})}

    _update_doc_state(state["doc_id"], "clarifying")
    # Interrupt — pause until UI provides answers
    answers: dict = interrupt({
        "type": "questions",
        "questions": [q.model_dump() for q in pending],
    })

    # Persist answers to university profile
    for q in pending:
        if q.question in answers:
            q.answer = answers[q.question]
            profile.clarification_memory.append(q)
    db.save_profile(profile)

    merged = {**state.get("clarification_answers", {}), **answers}

    # Extract ref_decision from answers
    ref_q_key = next(
        (k for k in answers if "textbook" in k.lower() or "isbn" in k.lower()), None
    )
    ref_decision = answers.get(ref_q_key) if ref_q_key else None

    return {"clarification_answers": merged, "ref_decision": ref_decision}


def node_generate(state: ASEState) -> dict:
    """Generate academic content (CO/CLO, refined modules)."""
    _update_doc_state(state["doc_id"], "drafting")
    blueprint = TemplateBlueprint(**state["blueprint"])
    content = ContentModel(**state["content_model"])
    gen_report: dict = {"subjects": []}

    for i, subj in enumerate(content.subjects):
        objs, outs = generate_objectives_outcomes(subj, blueprint, content.program, content.semester)
        subj.generated_objectives = objs
        subj.generated_outcomes = outs
        subj = refine_module_topics(subj, blueprint)
        content.subjects[i] = subj
        gen_report["subjects"].append({
            "name": subj.name,
            "objectives_generated": len(objs),
            "outcomes_generated": len(outs),
            "modules_refined": len(subj.modules),
        })

    return {"content_model": content.model_dump(), "generation_report": gen_report, "generated": True}


def node_build_refs(state: ASEState) -> dict:
    """Generate IEEE references if user confirmed."""
    blueprint = TemplateBlueprint(**state["blueprint"])
    content = ContentModel(**state["content_model"])

    # Check ref decision from clarification answers or stored profile
    ref_dec = state.get("ref_decision")
    if not ref_dec:
        profile = db.load_profile(state["university_id"])
        ref_dec = get_ref_decision(profile.clarification_memory)

    if ref_dec and "yes" in ref_dec.lower():
        for i, subj in enumerate(content.subjects):
            tb, refs = generate_references(subj, blueprint, content.program, content.semester)
            subj.generated_references = tb
            subj.references = refs
            content.subjects[i] = subj

    return {"content_model": content.model_dump()}


def node_assemble(state: ASEState) -> dict:
    """Build the DOCX from blueprint + content model."""
    blueprint = TemplateBlueprint(**state["blueprint"])
    content = ContentModel(**state["content_model"])
    doc = db.load_doc(state["doc_id"])

    ver = doc.current_version + 1
    filename = f"{state['university_id']}_{content.program}_Sem{content.semester}_v{ver}.docx"
    output_path = str(db.file_path(state["doc_id"], filename))

    build_docx(blueprint, content, output_path)
    return {"docx_path": output_path}


def node_qa(state: ASEState) -> dict:
    blueprint = TemplateBlueprint(**state["blueprint"])
    content = ContentModel(**state["content_model"])
    report = validate(state["docx_path"], content, blueprint)
    return {"qa_report": report}


def node_review(state: ASEState) -> dict:
    """Human interrupt gate: approval decision."""
    doc = db.load_doc(state["doc_id"])
    ver_doc = add_version(
        doc,
        docx_path=state["docx_path"],
        qa_report=state["qa_report"],
        generation_report=state["generation_report"],
        blueprint_version=state["blueprint"].get("version", 1),
    )
    db.save_doc(ver_doc)

    # Interrupt — wait for approver action
    decision: dict = interrupt({
        "type": "approval",
        "doc_id": state["doc_id"],
        "version": ver_doc.current_version,
        "docx_path": state["docx_path"],
        "qa_report": state["qa_report"],
        "generation_report": state["generation_report"],
    })
    return {"_approval_decision": decision}


def node_export(state: ASEState) -> dict:
    """Store the final approved document."""
    doc = db.load_doc(state["doc_id"])
    doc.audit.append(AuditEntry(from_state="review", to_state="approved", by="system"))
    doc.state = "approved"
    db.save_doc(doc)
    return {}


# ── Routing ───────────────────────────────────────────────────────────────────

def route_after_refs(state: ASEState) -> str:
    blueprint = TemplateBlueprint(**state["blueprint"])
    if has_ref_sections(blueprint):
        return "build_refs"
    return "assemble"


def route_qa(state: ASEState) -> str:
    report = state.get("qa_report", {})
    return "review" if report.get("status") == "pass" else "assemble"  # retry once on fail


# ── Graph construction ────────────────────────────────────────────────────────

def build_graph():
    g = StateGraph(ASEState)

    g.add_node("ingest", node_ingest)
    g.add_node("analyze", node_analyze)
    g.add_node("parse_content", node_parse_content)
    g.add_node("clarify", node_clarify)
    g.add_node("generate", node_generate)
    g.add_node("build_refs", node_build_refs)
    g.add_node("assemble", node_assemble)
    g.add_node("qa", node_qa)
    g.add_node("review", node_review)
    g.add_node("export", node_export)

    g.set_entry_point("ingest")
    g.add_edge("ingest", "analyze")
    g.add_edge("analyze", "parse_content")
    g.add_edge("parse_content", "clarify")
    g.add_edge("clarify", "generate")
    g.add_edge("generate", "build_refs")
    g.add_edge("build_refs", "assemble")
    g.add_edge("assemble", "qa")
    g.add_conditional_edges("qa", route_qa, {"review": "review", "assemble": "assemble"})
    g.add_edge("review", "export")
    g.add_edge("export", END)

    return g.compile(checkpointer=MemorySaver())


# Singleton graph instance
_graph = None

def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph
