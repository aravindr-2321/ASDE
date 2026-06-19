"""ASDE — Academic Syllabus Document Engine · Streamlit UI"""
from pathlib import Path
import streamlit as st
from langgraph.types import Command

from ase.orchestrator.graph import get_graph
from ase.schemas.models import DocumentRecord, ContentModel
from ase.store import db
from ase.config import UPLOADS_DIR

st.set_page_config(page_title="ASDE — Syllabus Engine", layout="wide", page_icon="📄")
graph = get_graph()


# ── Helpers ───────────────────────────────────────────────────────────────────

def ss(k, d=None):
    return st.session_state.get(k, d)

def _cfg():
    return {"configurable": {"thread_id": ss("thread_id")}}

def _graph_state():
    if not ss("thread_id"):
        return None
    try:
        return graph.get_state(_cfg())
    except Exception:
        return None

def _interrupt():
    s = _graph_state()
    if not s:
        return None
    for task in s.tasks:
        if getattr(task, "interrupts", None):
            return task.interrupts[0].value
    return None

def _next():
    s = _graph_state()
    return list(s.next) if s else []

def _save_upload(file, tag: str) -> str:
    dest = UPLOADS_DIR / f"{tag}_{file.name}"
    dest.write_bytes(file.read())
    return str(dest)

def _invoke(payload):
    """Resume the graph with payload, ignore interrupt exceptions."""
    try:
        graph.invoke(Command(resume=payload), _cfg())
    except Exception as e:
        if "interrupt" not in str(e).lower():
            st.error(f"Error: {e}")


# ── Page: Library ─────────────────────────────────────────────────────────────

def page_library():
    st.header("📚 Document Library")
    docs = db.list_docs()
    if not docs:
        st.info("No documents yet. Go to **New Document** to start.")
        return

    state_icon = {"approved": "🟢", "review": "🟡", "drafting": "🔵",
                  "clarifying": "🟠", "rejected": "🔴", "intake": "⚪", "analyzing": "🔵"}

    for doc in docs:
        icon = state_icon.get(doc.state, "⚪")
        label = f"{icon}  **{doc.university_id.upper()}** — {doc.program} | Sem {doc.semester}"
        with st.expander(label):
            c1, c2 = st.columns([3, 1])
            with c1:
                st.write(f"**State:** `{doc.state}`  |  **Version:** {doc.current_version}  |  **Created:** {doc.created_at[:10]}")
                if doc.audit:
                    st.write("**Audit trail:**")
                    for e in doc.audit[-5:]:
                        st.caption(f"`{e.at[:19]}`  {e.from_state} → {e.to_state}  ({e.by})")
            with c2:
                # Download approved DOCX + PDF
                for ver in reversed(doc.versions):
                    if ver.state == "approved":
                        if ver.docx_path and Path(ver.docx_path).exists():
                            with open(ver.docx_path, "rb") as f:
                                st.download_button("⬇ DOCX", f, Path(ver.docx_path).name, key=f"dx_{doc.doc_id}_{ver.version}")
                        if ver.pdf_path and Path(ver.pdf_path).exists():
                            with open(ver.pdf_path, "rb") as f:
                                st.download_button("⬇ PDF", f, Path(ver.pdf_path).name, key=f"pdf_{doc.doc_id}_{ver.version}")
                        break

                if doc.state == "review":
                    if st.button("Open Review", key=f"rv_{doc.doc_id}"):
                        st.session_state["thread_id"] = doc.doc_id
                        st.session_state["page"] = "Process"
                        st.rerun()

            # Inbox checker for approved docs
            if doc.state == "approved":
                with st.expander("📬 Email Replies & Revision"):
                    page_inbox(doc)


# ── Page: New Document ────────────────────────────────────────────────────────

def page_new_document():
    st.header("➕ New Document")
    st.caption("Upload the university template and the NIAT syllabus. The engine will handle the rest.")

    with st.form("upload_form"):
        c1, c2 = st.columns(2)
        with c1:
            univ_id  = st.text_input("University ID (short slug)", placeholder="adypu")
            program  = st.text_input("Program Name", placeholder="B.Tech CSE Data Science")
            semester = st.number_input("Semester", 1, 8, 1)
        with c2:
            tmpl_file  = st.file_uploader("University Template (.docx)", type=["docx"])
            syll_file  = st.file_uploader("NIAT Standard Syllabus (.docx or .pdf)", type=["docx", "pdf"])

        submitted = st.form_submit_button("🚀 Analyze & Start", type="primary")

    if submitted:
        if not all([univ_id, program, tmpl_file, syll_file]):
            st.error("Fill all fields and upload both files.")
            return

        tmpl_path = _save_upload(tmpl_file, f"{univ_id}_template")
        syll_path = _save_upload(syll_file, f"{univ_id}_syllabus")

        doc = DocumentRecord(university_id=univ_id, program=program, semester=int(semester))
        db.save_doc(doc)

        initial = {
            "doc_id": doc.doc_id, "university_id": univ_id,
            "template_path": tmpl_path, "syllabus_path": syll_path,
            "program": program, "semester": int(semester),
            "blueprint": None, "content_model": None,
            "detected_gaps": [], "generated_fills": [], "approved_fills": [],
            "docx_path": None, "pdf_path": None,
            "qa_report": None, "feedback": "", "version": 0, "final": False,
            "email_record_id": None,
        }

        st.session_state["thread_id"] = doc.doc_id
        st.session_state["page"] = "Process"

        with st.spinner("Analyzing template structure and parsing syllabus… this takes ~30 seconds."):
            try:
                graph.invoke(initial, {"configurable": {"thread_id": doc.doc_id}})
            except Exception as e:
                if "interrupt" not in str(e).lower():
                    st.error(f"Error during analysis: {e}")
                    return

        st.success(f"Analysis complete! Document `{doc.doc_id}` ready.")
        st.rerun()


# ── Page: Process (interrupt dispatcher) ─────────────────────────────────────

def page_process():
    tid = ss("thread_id")
    if not tid:
        st.warning("No active document. Go to **New Document**.")
        return

    iv = _interrupt()
    nxt = _next()

    if not iv and not nxt:
        st.success("✅ Document complete! Check the **Library** for your DOCX + PDF.")
        return

    if iv:
        kind = iv.get("type")
        if kind == "content_review":
            page_content_review(iv)
        elif kind == "preview":
            page_preview(iv)
        elif kind == "email_gate":
            page_email_gate(iv)
        else:
            st.info(f"Waiting at: `{kind}`")
    else:
        st.info(f"⏳ Processing… (`{nxt[0] if nxt else '?'}`)")
        if st.button("Refresh"):
            st.rerun()


# ── Gate 1: Content Review ────────────────────────────────────────────────────

def page_content_review(iv: dict):
    fills: list[dict] = iv.get("fills", [])

    st.header("✏️ Review LLM-Generated Content")
    st.info(
        "The syllabus didn't have enough content for some sections. "
        "The LLM has generated the missing content below. "
        "**Review each section, edit if needed, then approve.**"
    )

    approved_items = []
    all_ok = True

    for i, fill in enumerate(fills):
        subj   = fill.get("subject", "Unknown Subject")
        section = fill.get("section", "")
        note   = fill.get("generation_note", "")
        items  = fill.get("content", [])

        with st.expander(f"📌 **{subj}** — `{section}`  ·  *{note}*", expanded=True):
            st.caption(f"Gap reason: {fill.get('gap', {}).get('reason', '')}")

            edited = []
            for j, item in enumerate(items):
                val = st.text_area(
                    f"Item {j+1}", value=item,
                    key=f"fill_{i}_{j}", height=60,
                )
                edited.append(val.strip())

            action = st.radio(
                "Action", ["✅ Approve", "❌ Skip (leave blank)"],
                key=f"action_{i}", horizontal=True,
            )

            if "Approve" in action:
                approved_items.append({**fill, "approved_content": edited})
            else:
                all_ok = False  # at least one skipped

    st.divider()
    if st.button("Confirm and Assemble Document →", type="primary"):
        _invoke(approved_items)
        st.session_state["page"] = "Process"
        st.rerun()


# ── Gate 2: Preview + Feedback ────────────────────────────────────────────────

def page_preview(iv: dict):
    docx_path = iv.get("docx_path", "")
    qa        = iv.get("qa_report", {})
    version   = iv.get("version", 1)
    content   = iv.get("content_model", {})

    st.header(f"🔍 Document Preview — Version {version}")
    c1, c2 = st.columns([2, 1])

    with c1:
        _render_preview(content)

    with c2:
        # QA badge
        score = qa.get("score", 0)
        color = "normal" if score >= 0.9 else "inverse"
        st.metric("QA Score", f"{score:.0%}", help="Checks: content preservation, structure, completeness")
        if qa.get("findings"):
            with st.expander("QA Issues"):
                for f in qa["findings"]:
                    st.write(f"⚠️ `{f['check']}`: {f['detail']}")

        # Download for detailed review in Word
        if docx_path and Path(docx_path).exists():
            with open(docx_path, "rb") as f:
                st.download_button("⬇ Download DOCX to review in Word", f,
                                   Path(docx_path).name, type="secondary")

        st.divider()
        st.subheader("Your Decision")
        tab_approve, tab_feedback = st.tabs(["✅ Approve & Export", "🔄 Request Changes"])

        with tab_approve:
            st.write("Approve this version. It will be exported as **DOCX + PDF** and stored.")
            if st.button("Approve & Export Final Document", type="primary"):
                _invoke({"approved": True, "feedback": ""})
                st.rerun()

        with tab_feedback:
            st.write("Describe what needs to change. The engine will re-generate and rebuild.")
            feedback = st.text_area(
                "Feedback / Change Request",
                placeholder="e.g. The objectives for Web Development are too generic. Make them more specific to React and Node.js. Also add more practical outcomes.",
                height=120,
            )
            if st.button("Submit Feedback →", type="secondary"):
                if not feedback.strip():
                    st.error("Please enter feedback before submitting.")
                else:
                    _invoke({"approved": False, "feedback": feedback})
                    st.rerun()


def _render_preview(content_dict: dict):
    """Render a structured in-browser preview of the document content."""
    if not content_dict:
        st.warning("No content to preview.")
        return

    try:
        content = ContentModel(**content_dict)
    except Exception:
        st.json(content_dict)
        return

    st.subheader(f"📋 {content.program}  |  Semester {content.semester}")

    for subj in content.subjects:
        with st.expander(f"**{subj.name}**" + (f"  `{subj.code}`" if subj.code else ""), expanded=False):
            # Objectives
            st.markdown("**Course Objectives (CLO/CO):**")
            objs = subj.generated_objectives or subj.objectives
            for o in objs:
                st.write(f"  • {o}")

            # Outcomes
            st.markdown("**Course Outcomes:**")
            outs = subj.generated_outcomes or subj.outcomes
            for o in outs:
                st.write(f"  • {o}")

            # Modules
            st.markdown("**Modules:**")
            for m in subj.modules:
                st.write(f"  **{m.label}: {m.title}**")
                st.caption(f"  {m.topics[:120]}{'…' if len(m.topics) > 120 else ''}")

            # References
            refs = subj.generated_references or subj.textbooks
            if refs:
                st.markdown("**Textbooks / References:**")
                for r in refs[:3]:
                    st.caption(f"  {r[:100]}…")

            # CO-PO
            if subj.copo:
                po_count = subj.copo.get("po_count", 12)
                st.caption(f"CO-PO Matrix: {po_count} POs, scale: {subj.copo.get('scale', [])}")


# ── Gate 3: Email Recipients ──────────────────────────────────────────────────

def page_email_gate(iv: dict):
    st.header("📧 Send for External Review")
    st.success("✅ Document approved and exported! Now send it to reviewers.")

    col1, col2 = st.columns([3, 1])
    with col1:
        st.subheader("Document Ready")
        st.write(f"**Program:** {iv.get('program')}  |  **Semester:** {iv.get('semester')}  |  **Version:** {iv.get('version')}")

        for path_key, label in [("docx_path", "DOCX"), ("pdf_path", "PDF")]:
            p = iv.get(path_key)
            if p and Path(p).exists():
                with open(p, "rb") as f:
                    st.download_button(f"⬇ {label}", f, Path(p).name)

    with col2:
        st.subheader("Email Configuration")
        import os
        sender = os.getenv("EMAIL_SENDER", "")
        if sender:
            st.success(f"Sender: {sender}")
        else:
            st.warning("EMAIL_SENDER not set in .env")

    st.divider()
    st.subheader("Recipient Email IDs")
    st.caption("Enter the email addresses of reviewers (HODs, BOS coordinators, subject experts).")

    raw_emails = st.text_area(
        "Email addresses (one per line or comma-separated)",
        placeholder="hod@university.ac.in\nbos.coordinator@university.ac.in\nsubject.expert@gmail.com",
        height=120,
    )

    col_send, col_skip = st.columns(2)
    with col_send:
        if st.button("📤 Send Review Email", type="primary"):
            emails = [e.strip() for e in raw_emails.replace(",", "\n").splitlines() if e.strip()]
            if not emails:
                st.error("Please enter at least one email address.")
            else:
                with st.spinner(f"Sending email to {len(emails)} recipient(s)…"):
                    _invoke({"to_emails": emails})
                st.success(f"Email sent to: {', '.join(emails)}")
                st.session_state["page"] = "Library"
                st.rerun()

    with col_skip:
        if st.button("Skip — Save to Library Only"):
            _invoke({"to_emails": []})
            st.session_state["page"] = "Library"
            st.rerun()


# ── Inbox: Check Replies ───────────────────────────────────────────────────────

def page_inbox(doc: "DocumentRecord"):
    """Show email records and check for replies for a given document."""
    from ase.notify.inbox import check_replies, extract_feedback_text
    from ase.store.db import list_email_records, save_email_record, load_doc
    from ase.schemas.models import EmailReply

    email_records = list_email_records(doc.doc_id)
    if not email_records:
        st.info("No emails sent for this document yet.")
        return

    for rec in email_records:
        with st.expander(f"📨 Sent v{rec.version} → {', '.join(rec.to_emails)}  ·  `{rec.sent_at[:10]}`"):
            failed = rec.message_id.startswith("FAILED:")
            if failed:
                st.error(f"Send failed: {rec.message_id}")
            else:
                st.write(f"**Subject:** {rec.subject}")
                st.write(f"**Message-ID:** `{rec.message_id}`")

            if not failed:
                if st.button("🔄 Check for Replies", key=f"check_{rec.email_id}"):
                    with st.spinner("Checking inbox…"):
                        replies, err = check_replies(rec.message_id)
                    if err:
                        st.error(f"Inbox error: {err}")
                    elif not replies:
                        st.info("No replies found yet.")
                    else:
                        new_replies = []
                        existing_bodies = {r.body for r in rec.replies}
                        for r in replies:
                            if r.body not in existing_bodies:
                                new_replies.append(r)
                                rec.replies.append(r)
                        save_email_record(rec)
                        if new_replies:
                            st.success(f"{len(new_replies)} new reply(ies) found!")
                        else:
                            st.info("No new replies since last check.")

            # Show stored replies
            if rec.replies:
                st.subheader(f"{len(rec.replies)} Reply(ies)")
                for i, reply in enumerate(rec.replies):
                    with st.container(border=True):
                        st.write(f"**From:** {reply.from_addr}  |  **Date:** {reply.date}")
                        st.text_area("Reply content", reply.body, height=120, key=f"reply_{rec.email_id}_{i}", disabled=True)

                        if not reply.processed:
                            if st.button("🔁 Use this reply as revision input", key=f"use_{rec.email_id}_{i}"):
                                _start_email_revision(doc, rec, reply, extract_feedback_text([reply]))
                                reply.processed = True
                                save_email_record(rec)
                                st.success("Revision started! Go to **Process** tab.")
                                st.rerun()


def _start_email_revision(doc, rec, reply, feedback_text: str):
    """Start a new graph run for a revision based on an email reply."""
    from ase.store.db import load_doc
    full_doc = load_doc(doc.doc_id)
    # Find the latest approved version for its files
    latest = next((v for v in reversed(full_doc.versions) if v.state == "approved"), None)
    if not latest:
        st.error("No approved version found to revise.")
        return

    # Resume from assemble with feedback
    config = {"configurable": {"thread_id": doc.doc_id}}
    st.session_state["thread_id"] = doc.doc_id
    _invoke({"approved": False, "feedback": f"Email reviewer feedback:\n\n{feedback_text}"})


# ── Navigation ────────────────────────────────────────────────────────────────

def main():
    with st.sidebar:
        st.title("📄 ASDE")
        st.caption("Academic Syllabus Document Engine")
        page = st.radio("", ["Library", "New Document", "Process"],
                        index=["Library", "New Document", "Process"].index(ss("page", "Library")))
        st.session_state["page"] = page

        if ss("thread_id"):
            st.divider()
            st.caption(f"Active: `{ss('thread_id')[:14]}…`")
            iv = _interrupt()
            if iv:
                kind = iv.get("type", "")
                labels = {
                    "content_review": "✏️ Awaiting content review",
                    "preview":        "🔍 Awaiting preview approval",
                    "email_gate":     "📧 Awaiting email recipients",
                }
                st.info(labels.get(kind, f"⏸ {kind}"))
            elif _next():
                st.info("⏳ Processing…")
            else:
                st.success("✅ Complete")

    if page == "Library":
        page_library()
    elif page == "New Document":
        page_new_document()
    elif page == "Process":
        page_process()


if __name__ == "__main__":
    main()
