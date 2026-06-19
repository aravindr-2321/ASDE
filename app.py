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


# ── Inbox: Full Multi-Gate Revision Flow ─────────────────────────────────────
#
#  Step 1  check_replies   — show replies, check inbox
#  Step 2  feedback_review — show reviewer's changes (LLM analyzed), operator approves
#  Step 3  revising        — LLM revises doc, show new preview, operator approves
#  Step 4  email_draft     — LLM drafts formal reply, operator edits & approves
#  Step 5  done            — reply sent in thread

def page_inbox(doc):
    """Inbox panel shown inside Library for each approved document."""
    from ase.notify.inbox import check_replies
    from ase.store.db import list_email_records, save_email_record

    recs = list_email_records(doc.doc_id)
    if not recs:
        st.info("No emails sent for this document.")
        return

    for rec in recs:
        label = f"📨  v{rec.version} → {', '.join(rec.to_emails)}  ·  {rec.sent_at[:10]}"
        with st.expander(label):
            failed = rec.message_id.startswith("FAILED:")
            if failed:
                st.error(f"Send failed: {rec.message_id}")
            else:
                st.caption(f"Subject: {rec.subject}")

            if not failed:
                if st.button("🔄 Check for New Replies", key=f"chk_{rec.email_id}"):
                    with st.spinner("Checking inbox…"):
                        replies, err = check_replies(rec.message_id)
                    if err:
                        st.error(f"Inbox error: {err}")
                    elif not replies:
                        st.info("No replies found yet.")
                    else:
                        existing = {r.body for r in rec.replies}
                        added = 0
                        for r in replies:
                            if r.body not in existing:
                                rec.replies.append(r)
                                added += 1
                        save_email_record(rec)
                        if added:
                            st.success(f"{added} new reply(ies) found!")
                        else:
                            st.info("No new replies since last check.")

            for i, reply in enumerate(rec.replies):
                with st.container(border=True):
                    st.write(f"**From:** {reply.from_addr}  |  **{reply.date}**")
                    st.text_area("Reply", reply.body, height=100,
                                 key=f"rbody_{rec.email_id}_{i}", disabled=True)

                    badge = "✅ Processed" if reply.processed else "🔵 Pending"
                    st.caption(badge)

                    if not reply.processed:
                        if st.button("🔁 Start Revision from this Reply",
                                     key=f"start_{rec.email_id}_{i}", type="primary"):
                            st.session_state["inbox_flow"] = {
                                "step": "feedback_review",
                                "doc_id": doc.doc_id,
                                "email_record_id": rec.email_id,
                                "reply_idx": i,
                                "reply_body": reply.body,
                                "reply_from": reply.from_addr,
                                "original_subject": rec.subject,
                                "original_message_id": rec.message_id,
                                "prev_version": doc.current_version,
                            }
                            st.session_state["page"] = "Inbox"
                            st.rerun()


def page_inbox_flow():
    """Dedicated page that runs the multi-step revision-from-email flow."""
    flow = ss("inbox_flow", {})
    if not flow:
        st.info("No active inbox revision. Start one from the Library.")
        return

    step = flow.get("step")

    # ── Step 2: Show LLM analysis of reviewer feedback, ask operator to approve ──
    if step == "feedback_review":
        _inbox_step_feedback_review(flow)

    # ── Step 3: Show revised document preview, ask operator to approve ────────
    elif step == "revision_preview":
        _inbox_step_revision_preview(flow)

    # ── Step 4: Show LLM email draft, ask operator to approve before sending ──
    elif step == "email_draft":
        _inbox_step_email_draft(flow)

    elif step == "done":
        st.success("✅ Revision complete and reply sent to reviewer!")
        if st.button("Back to Library"):
            del st.session_state["inbox_flow"]
            st.session_state["page"] = "Library"
            st.rerun()


def _inbox_step_feedback_review(flow: dict):
    from ase.notify.reply_composer import analyze_feedback

    st.header("📋 Reviewer Feedback Analysis")
    st.caption(f"Document: `{flow['doc_id']}`  |  From: {flow['reply_from']}")

    st.subheader("Reviewer's Reply")
    st.info(flow["reply_body"])

    # Run LLM analysis once and cache in flow
    if "analysis" not in flow:
        doc = db.load_doc(flow["doc_id"])
        with st.spinner("Analyzing reviewer feedback…"):
            analysis = analyze_feedback(flow["reply_body"], doc.program, doc.semester)
        flow["analysis"] = analysis
        st.session_state["inbox_flow"] = flow

    analysis = flow["analysis"]
    reviewer_name = analysis.get("reviewer_name", "Reviewer")
    changes = analysis.get("changes_requested", [])
    concern = analysis.get("general_concerns", "")

    st.subheader(f"Changes Requested by {reviewer_name}")
    if concern:
        st.write(f"**Overall concern:** {concern}")
    if changes:
        for i, c in enumerate(changes, 1):
            st.write(f"**{i}.** {c}")
    else:
        st.warning("No specific changes detected. The reply may be a general comment.")

    priority = analysis.get("priority", "medium")
    st.caption(f"Priority: `{priority}`  |  Sentiment: `{analysis.get('sentiment','neutral')}`")

    st.divider()
    st.subheader("Your Decision")
    col1, col2 = st.columns(2)

    with col1:
        if st.button("✅ Approve — Work on These Changes", type="primary"):
            flow["step"] = "revising"
            st.session_state["inbox_flow"] = flow
            _run_revision(flow)

    with col2:
        if st.button("❌ Skip — Don't Incorporate These Changes"):
            _mark_reply_processed(flow)
            del st.session_state["inbox_flow"]
            st.session_state["page"] = "Library"
            st.rerun()


def _run_revision(flow: dict):
    """Apply LLM revision and move to preview step."""
    from ase.notify.reply_composer import apply_feedback_to_content
    from ase.render.docx_builder import build_docx, export_pdf
    from ase.schemas.models import TemplateBlueprint, ContentModel

    doc = db.load_doc(flow["doc_id"])
    latest = next((v for v in reversed(doc.versions) if v.state == "approved"), None)
    if not latest or not latest.content_model_path:
        st.error("Cannot find saved content model for revision.")
        return

    # Load persisted content model and blueprint
    content_dict = __import__("json").loads(
        Path(latest.content_model_path).read_text(encoding="utf-8")
    )
    profile = db.load_profile(doc.university_id)
    blueprint_dict = profile.blueprints[-1] if profile.blueprints else {}

    analysis = flow.get("analysis", {})
    changes_requested = analysis.get("changes_requested", [])

    with st.spinner("Applying reviewer changes to document…"):
        updated_content, changes_made = apply_feedback_to_content(
            content_dict, changes_requested, doc.program, doc.semester
        )

    # Build new DOCX + PDF
    blueprint = TemplateBlueprint(**blueprint_dict)
    content = ContentModel(**updated_content)
    new_ver = doc.current_version + 1
    fname = f"{doc.university_id}_{content.program.replace(' ','_')}_Sem{content.semester}_v{new_ver}.docx"
    docx_path = str(db.file_path(doc.doc_id, fname))

    with st.spinner("Building updated document…"):
        build_docx(blueprint, content, docx_path)
        pdf_path = export_pdf(docx_path)

    # Save new content model
    content_json_path = str(db.file_path(doc.doc_id, f"content_v{new_ver}.json"))
    Path(content_json_path).write_text(content.model_dump_json(indent=2), encoding="utf-8")

    flow.update({
        "step": "revision_preview",
        "new_version": new_ver,
        "new_docx": docx_path,
        "new_pdf": pdf_path,
        "new_content": updated_content,
        "changes_made": changes_made,
        "content_json_path": content_json_path,
    })
    st.session_state["inbox_flow"] = flow
    st.rerun()


def _inbox_step_revision_preview(flow: dict):
    st.header(f"🔍 Preview — Updated Version {flow.get('new_version')}")
    st.caption(f"Document: `{flow['doc_id']}`")

    c1, c2 = st.columns([3, 1])
    with c1:
        st.subheader("Changes Made")
        for i, c in enumerate(flow.get("changes_made", []), 1):
            st.write(f"**{i}.** {c}")
        st.divider()
        _render_preview(flow.get("new_content", {}))

    with c2:
        for path_key, label in [("new_docx", "DOCX"), ("new_pdf", "PDF")]:
            p = flow.get(path_key)
            if p and Path(p).exists():
                with open(p, "rb") as f:
                    st.download_button(f"⬇ {label}", f, Path(p).name)

        st.divider()
        if st.button("✅ Approve — Generate Reply Email", type="primary"):
            flow["step"] = "email_draft"
            st.session_state["inbox_flow"] = flow
            _generate_email_draft(flow)

        if st.button("🔄 Revise Again"):
            flow["step"] = "feedback_review"
            st.session_state["inbox_flow"] = flow
            st.rerun()


def _generate_email_draft(flow: dict):
    from ase.notify.reply_composer import generate_reply_body

    doc = db.load_doc(flow["doc_id"])
    analysis = flow.get("analysis", {})
    reviewer_name = analysis.get("reviewer_name", "Reviewer")
    feedback_summary = analysis.get("general_concerns", flow.get("reply_body", "")[:200])

    docx_name = Path(flow.get("new_docx", "document.docx")).name
    pdf_name = Path(flow.get("new_pdf", "document.pdf")).name if flow.get("new_pdf") else "N/A"

    with st.spinner("Drafting formal reply email…"):
        draft = generate_reply_body(
            reviewer_name=reviewer_name,
            feedback_summary=feedback_summary,
            changes_made=flow.get("changes_made", []),
            program=doc.program,
            semester=doc.semester,
            university=doc.university_id.upper(),
            prev_version=flow.get("prev_version", 1),
            new_version=flow.get("new_version", 2),
            docx_name=docx_name,
            pdf_name=pdf_name,
        )

    flow["email_draft"] = draft
    flow["reviewer_name"] = reviewer_name
    st.session_state["inbox_flow"] = flow
    st.rerun()


def _inbox_step_email_draft(flow: dict):
    from ase.notify.emailer import send_thread_reply
    from ase.store.db import load_email_record, save_email_record

    st.header("📧 Approve Reply Email Before Sending")
    st.caption(
        "The email below was drafted by the LLM based on the reviewer's feedback "
        "and the changes incorporated. Review and edit before approving."
    )

    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("Email Draft")
        edited_body = st.text_area(
            "Email body (edit if needed)",
            value=flow.get("email_draft", ""),
            height=400,
            key="final_email_body",
        )
        doc = db.load_doc(flow["doc_id"])
        subject = flow.get("original_subject", "")
        reply_subject = subject if subject.startswith("Re:") else f"Re: {subject}"
        st.info(f"**Subject:** {reply_subject}")

    with col2:
        st.subheader("Send Details")
        rec = load_email_record(flow["email_record_id"])
        to_email = rec.to_emails[0] if rec.to_emails else ""
        st.write(f"**To:** {', '.join(rec.to_emails)}")
        st.write(f"**In reply to:** `{flow.get('original_message_id', '')[:40]}…`")

        for path_key, label in [("new_docx", "DOCX"), ("new_pdf", "PDF")]:
            p = flow.get(path_key)
            if p and Path(p).exists():
                with open(p, "rb") as f:
                    st.download_button(f"Preview {label}", f, Path(p).name)

        st.divider()
        if st.button("✅ Approve & Send Reply", type="primary"):
            attachments = [p for p in [flow.get("new_docx"), flow.get("new_pdf")] if p and Path(p).exists()]
            with st.spinner("Sending reply…"):
                for email_addr in rec.to_emails:
                    ok, new_mid, err = send_thread_reply(
                        to_email=email_addr,
                        original_subject=flow.get("original_subject", ""),
                        original_message_id=flow.get("original_message_id", ""),
                        body=edited_body,
                        attachments=attachments,
                    )
                    if not ok:
                        st.error(f"Failed to send to {email_addr}: {err}")
                        return

            # Mark reply as processed + update doc version
            _mark_reply_processed(flow)
            _save_new_version(flow, doc)

            st.success(f"✅ Reply sent to {', '.join(rec.to_emails)} in the same thread!")
            flow["step"] = "done"
            st.session_state["inbox_flow"] = flow
            st.rerun()

        if st.button("✏️ Regenerate Email Draft"):
            del flow["email_draft"]
            st.session_state["inbox_flow"] = flow
            _generate_email_draft(flow)


def _mark_reply_processed(flow: dict):
    from ase.store.db import load_email_record, save_email_record
    try:
        rec = load_email_record(flow["email_record_id"])
        idx = flow.get("reply_idx", 0)
        if idx < len(rec.replies):
            rec.replies[idx].processed = True
        save_email_record(rec)
    except Exception:
        pass


def _save_new_version(flow: dict, doc):
    from ase.schemas.models import VersionRecord, AuditEntry
    doc.versions.append(VersionRecord(
        version=flow["new_version"],
        docx_path=flow.get("new_docx", ""),
        pdf_path=flow.get("new_pdf", ""),
        content_model_path=flow.get("content_json_path", ""),
        state="approved",
    ))
    doc.current_version = flow["new_version"]
    doc.audit.append(AuditEntry(
        from_state="approved", to_state="approved",
        by="email-revision",
        note=f"Revised to v{flow['new_version']} from reviewer feedback",
    ))
    db.save_doc(doc)


# ── Navigation ────────────────────────────────────────────────────────────────

def main():
    PAGES = ["Library", "New Document", "Process", "Inbox"]
    with st.sidebar:
        st.title("📄 ASDE")
        st.caption("Academic Syllabus Document Engine")
        page = st.radio("", PAGES,
                        index=PAGES.index(ss("page", "Library")))
        st.session_state["page"] = page

        if ss("inbox_flow"):
            st.divider()
            step_labels = {
                "feedback_review": "📋 Reviewer feedback",
                "revision_preview": "🔍 Preview revision",
                "email_draft":     "📧 Approve email",
                "done":            "✅ Reply sent",
            }
            st.info(step_labels.get(ss("inbox_flow", {}).get("step", ""), "📬 Inbox revision active"))

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
    elif page == "Inbox":
        page_inbox_flow()


if __name__ == "__main__":
    main()
