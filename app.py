"""ASDE — Academic Syllabus Document Engine · Streamlit UI"""
import shutil
import json
from pathlib import Path
import streamlit as st
from langgraph.types import Command

from ase.orchestrator.graph import get_graph
from ase.schemas.models import DocumentRecord
from ase.store import db
from ase.config import UPLOADS_DIR

st.set_page_config(page_title="ASDE — Syllabus Engine", layout="wide", page_icon="📄")

graph = get_graph()

# ── Session helpers ───────────────────────────────────────────────────────────

def ss(key, default=None):
    return st.session_state.get(key, default)

def _config():
    return {"configurable": {"thread_id": ss("thread_id")}}

def _graph_state():
    if not ss("thread_id"):
        return None
    try:
        return graph.get_state(_config())
    except Exception:
        return None

def _next_nodes():
    s = _graph_state()
    return list(s.next) if s else []

def _interrupt_value():
    """Return the interrupt payload from current graph state."""
    s = _graph_state()
    if not s:
        return None
    for task in s.tasks:
        if hasattr(task, "interrupts") and task.interrupts:
            return task.interrupts[0].value
    return None

def _save_upload(file, prefix: str) -> str:
    dest = UPLOADS_DIR / f"{prefix}_{file.name}"
    dest.write_bytes(file.read())
    return str(dest)


# ── Pages ─────────────────────────────────────────────────────────────────────

def page_library():
    st.header("📚 Document Library")
    docs = db.list_docs()
    if not docs:
        st.info("No documents yet. Start with **New Document**.")
        return

    STATUS_COLOR = {
        "approved": "🟢", "review": "🟡", "drafting": "🔵",
        "clarifying": "🟠", "rejected": "🔴", "intake": "⚪",
    }
    for doc in docs:
        icon = STATUS_COLOR.get(doc.state, "⚪")
        with st.expander(f"{icon} {doc.university_id.upper()} — {doc.program} | Sem {doc.semester}  ·  `{doc.doc_id}`"):
            col1, col2 = st.columns([2, 1])
            with col1:
                st.write(f"**State:** {doc.state}  |  **Version:** {doc.current_version}  |  **Created:** {doc.created_at[:10]}")
                if doc.approvals:
                    last = doc.approvals[-1]
                    st.write(f"**Last approval action:** {last.decision} by {last.reviewer} — *{last.notes or 'no notes'}*")
            with col2:
                if doc.state == "review":
                    if st.button(f"Open Review", key=f"open_{doc.doc_id}"):
                        st.session_state["thread_id"] = doc.doc_id
                        st.session_state["page"] = "Review"
                        st.rerun()
                # Download approved docx
                ver = next((v for v in reversed(doc.versions) if v.state == "approved"), None)
                if ver and Path(ver.docx_path).exists():
                    with open(ver.docx_path, "rb") as f:
                        st.download_button("⬇ Download DOCX", f, file_name=Path(ver.docx_path).name)

            if doc.audit:
                st.write("**Audit Trail:**")
                for entry in doc.audit:
                    st.write(f"  `{entry.at[:19]}` {entry.from_state} → {entry.to_state} ({entry.by})")


def page_new_document():
    st.header("➕ New Document")

    with st.form("new_doc_form"):
        col1, col2 = st.columns(2)
        with col1:
            university_id = st.text_input("University ID (slug)", placeholder="adypu")
            program = st.text_input("Program Name", placeholder="B.Tech CSE Data Science")
            semester = st.number_input("Semester", min_value=1, max_value=8, value=1)
        with col2:
            template_file = st.file_uploader("University Template (.docx)", type=["docx"])
            syllabus_file = st.file_uploader("NIAT Syllabus (.docx or .pdf)", type=["docx", "pdf"])

        instructions = st.text_area(
            "Custom Instructions / Context (optional)",
            placeholder="e.g. Use CLO prefix, include CO-PO for 12 POs, subject level is UG...",
            height=80,
        )
        submitted = st.form_submit_button("🚀 Start Generation")

    if submitted:
        if not all([university_id, program, template_file, syllabus_file]):
            st.error("Please fill all required fields and upload both files.")
            return

        # Save uploaded files
        template_path = _save_upload(template_file, f"{university_id}_template")
        syllabus_path = _save_upload(syllabus_file, f"{university_id}_syllabus")

        # Create document record
        doc = DocumentRecord(university_id=university_id, program=program, semester=int(semester))
        db.save_doc(doc)

        initial_state = {
            "doc_id": doc.doc_id,
            "university_id": university_id,
            "template_path": template_path,
            "syllabus_path": syllabus_path,
            "custom_instructions": instructions,
            "program": program,
            "semester": int(semester),
            "blueprint": None,
            "content_model": None,
            "clarification_answers": {},
            "ref_decision": None,
            "generated": False,
            "docx_path": None,
            "qa_report": None,
            "generation_report": {},
            "error": None,
        }

        st.session_state["thread_id"] = doc.doc_id
        config = {"configurable": {"thread_id": doc.doc_id}}

        with st.spinner("Analyzing template and parsing syllabus…"):
            try:
                graph.invoke(initial_state, config)
            except Exception as e:
                if "interrupt" not in str(e).lower():
                    st.error(f"Error: {e}")
                    return

        st.session_state["page"] = "Process"
        st.success(f"Document `{doc.doc_id}` created! Moving to processing…")
        st.rerun()


def page_process():
    thread_id = ss("thread_id")
    if not thread_id:
        st.warning("No active document. Go to **New Document**.")
        return

    next_nodes = _next_nodes()
    interrupt_val = _interrupt_value()

    if not next_nodes:
        st.success("✅ Generation complete! Check the Library.")
        return

    # ── Clarification gate ────────────────────────────────────────────────────
    if interrupt_val and interrupt_val.get("type") == "questions":
        st.header("❓ Clarification Required")
        st.caption(f"Document: `{thread_id}`")
        questions = interrupt_val.get("questions", [])

        with st.form("clarify_form"):
            answers = {}
            for q in questions:
                opts = q.get("options", [])
                ans = st.radio(q["question"], opts, key=q["id"])
                answers[q["question"]] = ans
            submitted = st.form_submit_button("Submit Answers")

        if submitted:
            config = _config()
            with st.spinner("Generating academic content…"):
                try:
                    graph.invoke(Command(resume=answers), config)
                except Exception as e:
                    if "interrupt" not in str(e).lower():
                        st.error(f"Error: {e}")
                        return
            st.rerun()

    # ── Approval gate ─────────────────────────────────────────────────────────
    elif interrupt_val and interrupt_val.get("type") == "approval":
        page_review_gate(interrupt_val)

    else:
        st.info(f"⏳ Processing… next: `{next_nodes}`")
        if st.button("Refresh"):
            st.rerun()


def page_review_gate(interrupt_val: dict):
    st.header("🔍 Review & Approve")
    doc_id = interrupt_val.get("doc_id", ss("thread_id"))
    version = interrupt_val.get("version", "?")
    docx_path = interrupt_val.get("docx_path", "")
    qa = interrupt_val.get("qa_report", {})
    gen = interrupt_val.get("generation_report", {})

    col1, col2 = st.columns([3, 1])
    with col1:
        st.subheader(f"Version {version}")
        st.metric("QA Score", f"{qa.get('score', 0):.0%}")
        if qa.get("findings"):
            st.warning("QA Issues:")
            for f in qa["findings"]:
                st.write(f"  ⚠️ {f['check']}: {f['detail']}")

        st.subheader("Generation Report")
        for s in gen.get("subjects", []):
            st.write(f"**{s['name']}** — {s['objectives_generated']} objectives, {s['outcomes_generated']} outcomes, {s['modules_refined']} modules refined")

    with col2:
        if docx_path and Path(docx_path).exists():
            with open(docx_path, "rb") as f:
                st.download_button("⬇ Preview DOCX", f, file_name=Path(docx_path).name, type="primary")

        reviewer = st.text_input("Your name / email", key="reviewer_id")

        if st.button("✅ Approve", type="primary"):
            if not reviewer:
                st.error("Enter your name before approving.")
            else:
                from ase.approval.workflow import approve as do_approve
                do_approve(doc_id, reviewer)
                config = _config()
                graph.invoke(Command(resume={"decision": "approve", "reviewer": reviewer, "notes": ""}), config)
                st.success("Document approved and stored!")
                st.rerun()

        notes = st.text_area("Change request notes", key="change_notes", height=80)
        if st.button("🔄 Request Changes"):
            if not reviewer:
                st.error("Enter your name.")
            elif not notes:
                st.error("Provide change notes.")
            else:
                from ase.approval.workflow import request_changes as do_req
                do_req(doc_id, reviewer, notes)
                config = _config()
                graph.invoke(Command(resume={"decision": "request_changes", "reviewer": reviewer, "notes": notes}), config)
                st.info("Changes requested. Re-generation will start.")
                st.rerun()

        if st.button("❌ Reject"):
            if reviewer:
                from ase.approval.workflow import reject as do_reject
                do_reject(doc_id, reviewer, notes or "Rejected")
                config = _config()
                graph.invoke(Command(resume={"decision": "reject", "reviewer": reviewer, "notes": notes}), config)
                st.error("Document rejected.")
                st.rerun()


# ── Navigation ────────────────────────────────────────────────────────────────

def main():
    with st.sidebar:
        st.title("📄 ASDE")
        st.caption("Academic Syllabus Document Engine")
        page = st.radio(
            "Navigation",
            ["Library", "New Document", "Process"],
            index=["Library", "New Document", "Process"].index(ss("page", "Library")),
        )
        st.session_state["page"] = page
        st.divider()
        if ss("thread_id"):
            st.caption(f"Active doc: `{ss('thread_id')[:12]}…`")
            next_n = _next_nodes()
            interrupt_v = _interrupt_value()
            if interrupt_v:
                kind = interrupt_v.get("type", "")
                label = "❓ Awaiting Answers" if kind == "questions" else "🔍 Awaiting Approval"
                st.warning(label)
            elif next_n:
                st.info(f"⏳ Next: {next_n[0]}")
            else:
                st.success("✅ Done")

    if page == "Library":
        page_library()
    elif page == "New Document":
        page_new_document()
    elif page == "Process":
        page_process()


if __name__ == "__main__":
    main()
