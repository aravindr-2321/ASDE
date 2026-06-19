"""ASDE — Academic Syllabus Document Engine · Streamlit UI"""
from pathlib import Path
import streamlit as st
from langgraph.types import Command

from ase.orchestrator.graph import get_graph
from ase.schemas.models import DocumentRecord, ContentModel
from ase.store import db
from ase.config import UPLOADS_DIR
from ase.ui.styles import (
    inject_css, page_header, badge, stat_row, steps_indicator,
    section_title, alert, empty_state, doc_card_html, review_card,
)

st.set_page_config(
    page_title="ASDE — Syllabus Engine",
    layout="wide",
    page_icon="📄",
    initial_sidebar_state="expanded",
)
inject_css()
graph = get_graph()

PAGES = ["Library", "New Document", "Process", "Inbox"]


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
    try:
        graph.invoke(Command(resume=payload), _cfg())
    except Exception as e:
        if "interrupt" not in str(e).lower():
            st.error(f"Error: {e}")

def _render_preview(content_dict: dict):
    if not content_dict:
        st.warning("No content to preview.")
        return
    try:
        content = ContentModel(**content_dict)
    except Exception:
        st.json(content_dict)
        return

    st.markdown(f"### 📋 {content.program}  ·  Semester {content.semester}")
    for subj in content.subjects:
        with st.expander(f"**{subj.name}**" + (f"  `{subj.code}`" if subj.code else ""), expanded=False):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Course Objectives (CLO/CO)**")
                for o in (subj.generated_objectives or subj.objectives):
                    st.markdown(f"- {o}")
            with c2:
                st.markdown("**Course Outcomes**")
                for o in (subj.generated_outcomes or subj.outcomes):
                    st.markdown(f"- {o}")
            st.markdown("**Modules**")
            for m in subj.modules:
                st.markdown(f"**{m.label}: {m.title}**")
                st.caption(m.topics[:140] + ("…" if len(m.topics) > 140 else ""))
            refs = subj.generated_references or subj.textbooks
            if refs:
                st.markdown("**References**")
                for r in refs[:3]:
                    st.caption(r[:120])
            if subj.copo:
                st.caption(f"CO-PO: {subj.copo.get('po_count', '?')} POs · Scale: {subj.copo.get('scale', [])}")


# ── Page: Library ─────────────────────────────────────────────────────────────

def page_library():
    page_header("Document Library", "All generated syllabus documents, approvals, and email threads.", "📚")
    docs = db.list_docs()

    # Stats
    approved  = sum(1 for d in docs if d.state == "approved")
    in_review = sum(1 for d in docs if d.state == "review")
    drafting  = sum(1 for d in docs if d.state in ("drafting", "analyzing", "clarifying"))
    stat_row(len(docs), approved, in_review, drafting)

    if not docs:
        empty_state("No documents yet", "Go to <b>New Document</b> to generate your first syllabus.")
        return

    section_title("Documents")
    for doc in docs:
        st.markdown(doc_card_html(
            doc.university_id, doc.program, doc.num_semesters,
            doc.current_version, doc.created_at, doc.state,
        ), unsafe_allow_html=True)

        with st.expander("View details & files"):
            col1, col2, col3 = st.columns([3, 1, 1])
            with col1:
                if doc.audit:
                    st.markdown("**Audit trail:**")
                    for e in doc.audit[-4:]:
                        st.caption(f"`{e.at[:19]}`  {e.from_state} → {e.to_state}  ({e.by})")
            with col2:
                for ver in reversed(doc.versions):
                    if ver.state == "approved":
                        # Multi-semester: show per-semester downloads if available
                        if ver.semester_paths:
                            for sem_str, paths in ver.semester_paths.items():
                                for ftype, label in [("docx", f"⬇ Sem{sem_str} DOCX"), ("pdf", f"⬇ Sem{sem_str} PDF")]:
                                    p = paths.get(ftype, "")
                                    if p and Path(p).exists():
                                        with open(p, "rb") as f:
                                            st.download_button(label, f, Path(p).name,
                                                               key=f"{ftype}_{doc.doc_id}_{ver.version}_{sem_str}")
                        else:
                            if ver.docx_path and Path(ver.docx_path).exists():
                                with open(ver.docx_path, "rb") as f:
                                    st.download_button("⬇ DOCX", f, Path(ver.docx_path).name,
                                                       key=f"dx_{doc.doc_id}_{ver.version}")
                            if ver.pdf_path and Path(ver.pdf_path).exists():
                                with open(ver.pdf_path, "rb") as f:
                                    st.download_button("⬇ PDF", f, Path(ver.pdf_path).name,
                                                       key=f"pdf_{doc.doc_id}_{ver.version}")
                        break
            with col3:
                if doc.state == "review":
                    if st.button("Open Review →", key=f"rv_{doc.doc_id}", type="primary"):
                        st.session_state["thread_id"] = doc.doc_id
                        st.session_state["page"] = "Process"
                        st.rerun()
                if doc.state == "approved":
                    if st.button("📬 Check Replies", key=f"inbox_{doc.doc_id}"):
                        st.session_state["inbox_doc_id"] = doc.doc_id
                        st.session_state["page"] = "Inbox"
                        st.rerun()

            if doc.state == "approved":
                _inline_inbox(doc)


def _inline_inbox(doc):
    from ase.store.db import list_email_records
    recs = list_email_records(doc.doc_id)
    if not recs:
        return
    section_title("Email Threads")
    for rec in recs:
        unread = sum(1 for r in rec.replies if not r.processed)
        lbl = f"📨  v{rec.version} → {', '.join(rec.to_emails[:2])}{'…' if len(rec.to_emails) > 2 else ''}"
        if unread:
            lbl += f"  🔴 {unread} unread"
        st.caption(lbl)


# ── Page: New Document ────────────────────────────────────────────────────────

def page_new_document():
    page_header("New Document", "Upload a university template and NIAT syllabus to begin.", "➕")

    alert(
        "The engine analyzes the <b>full template structure</b> (fonts, colors, layouts, tables), "
        "extracts the program name automatically from the syllabus, detects content gaps, and generates "
        "<b>one formatted document per semester</b> through human-approval gates.",
        "info",
    )

    with st.form("upload_form", border=False):
        section_title("Document Details")
        col1, col2 = st.columns(2)
        with col1:
            univ_id       = st.text_input("University ID (slug)", placeholder="adypu")
        with col2:
            num_semesters = st.number_input(
                "Number of Semesters to Generate", 1, 8, 1,
                help="Enter 5 → engine generates Semester 1 through Semester 5 documents",
            )

        section_title("Upload Files")
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**University Template** `.docx`")
            st.caption("Defines fonts, colors, layout, tables — analyzed in full")
            tmpl_file = st.file_uploader("", type=["docx"], key="tmpl")
            if tmpl_file:
                alert(f"✓ {tmpl_file.name}  ({round(tmpl_file.size/1024)}KB)", "success")
        with col_b:
            st.markdown("**NIAT Standard Syllabus** `.docx` or `.pdf`")
            st.caption("Program name and all semester content extracted automatically")
            syll_file = st.file_uploader("", type=["docx", "pdf"], key="syll")
            if syll_file:
                alert(f"✓ {syll_file.name}  ({round(syll_file.size/1024)}KB)", "success")

        submitted = st.form_submit_button("🚀  Analyze & Start Generation", type="primary", use_container_width=True)

    if submitted:
        if not all([univ_id, tmpl_file, syll_file]):
            alert("Please enter a University ID and upload both files.", "warn")
            return

        tmpl_path = _save_upload(tmpl_file, f"{univ_id}_template")
        syll_path = _save_upload(syll_file, f"{univ_id}_syllabus")

        doc = DocumentRecord(university_id=univ_id, num_semesters=int(num_semesters))
        db.save_doc(doc)

        initial = {
            "doc_id": doc.doc_id,
            "university_id": univ_id,
            "template_path": tmpl_path,
            "syllabus_path": syll_path,
            "num_semesters": int(num_semesters),
            "program": "",
            "blueprint": None,
            "semester_contents": {},
            "semester_gaps": {},
            "semester_fills": {},
            "semester_approved_fills": {},
            "semester_docx_paths": {},
            "semester_pdf_paths": {},
            "semester_qa_reports": {},
            "feedback": "",
            "version": 0,
            "final": False,
            "email_record_id": None,
        }
        st.session_state["thread_id"] = doc.doc_id
        st.session_state["page"] = "Process"

        with st.spinner(f"Analyzing template and extracting {num_semesters} semester(s)… (~30–60 s)"):
            try:
                graph.invoke(initial, {"configurable": {"thread_id": doc.doc_id}})
            except Exception as e:
                if "interrupt" not in str(e).lower():
                    alert(f"Error: {e}", "danger")
                    return

        st.success(f"Analysis complete — doc `{doc.doc_id}`")
        st.rerun()


# ── Page: Process ─────────────────────────────────────────────────────────────

def page_process():
    tid = ss("thread_id")
    if not tid:
        alert("No active document. Go to <b>New Document</b> to start.", "warn")
        return

    iv  = _interrupt()
    nxt = _next()

    # Step indicator
    current_step = iv.get("type") if iv else (nxt[0] if nxt else "done")
    steps_indicator(current_step)

    if not iv and not nxt:
        alert("✅ Document complete! Check the <b>Library</b> for your DOCX + PDF.", "success")
        return

    if iv:
        kind = iv.get("type")
        if kind == "content_review":   _gate_content_review(iv)
        elif kind == "preview":        _gate_preview(iv)
        elif kind == "email_gate":     _gate_email(iv)
        else:
            alert(f"Processing at: <code>{kind}</code>", "info")
    else:
        alert(f"⏳ Processing… next node: <code>{nxt[0] if nxt else '?'}</code>", "info")
        if st.button("🔄 Refresh"):
            st.rerun()


# ── Gate 1: Content Review ────────────────────────────────────────────────────

def _gate_content_review(iv: dict):
    page_header("Review Generated Content", "Approve or edit LLM-generated sections before assembly.", "✏️")

    semester_fills: dict = iv.get("semester_fills", {})
    num_semesters: int   = iv.get("num_semesters", len(semester_fills))
    total_fills = sum(len(v) for v in semester_fills.values())

    alert(
        f"<b>{total_fills} section(s)</b> across <b>{num_semesters} semester(s)</b> had missing content. "
        "The LLM has generated content for each. Review, edit, then confirm.",
        "info",
    )

    # Build semester tabs
    sem_keys = sorted(semester_fills.keys(), key=int)
    if not sem_keys:
        alert("No gaps detected — click Confirm to assemble all semester documents.", "success")
        if st.button("Confirm & Assemble All →", type="primary"):
            _invoke({str(s): [] for s in range(1, num_semesters + 1)})
            st.rerun()
        return

    tab_labels = [f"Semester {k}" for k in sem_keys]
    tabs = st.tabs(tab_labels)

    approved_by_sem: dict = {}

    for tab, sem_str in zip(tabs, sem_keys):
        fills = semester_fills[sem_str]
        approved_items = []

        with tab:
            if not fills:
                alert(f"No gaps for Semester {sem_str}.", "success")
                approved_by_sem[sem_str] = []
                continue

            for i, fill in enumerate(fills):
                subj    = fill.get("subject", "Unknown")
                section = fill.get("section", "")
                items   = fill.get("content", [])
                review_card(subj, section, fill.get("gap", {}).get("reason", ""), "\n".join(items[:3]))

                with st.expander(f"Edit  {subj} — {section}"):
                    edited = []
                    for j, item in enumerate(items):
                        val = st.text_area(
                            f"Item {j+1}", value=item,
                            key=f"fill_s{sem_str}_{i}_{j}", height=65,
                            label_visibility="collapsed",
                        )
                        edited.append(val.strip())

                    action = st.radio(
                        "", ["✅ Approve this section", "❌ Skip (leave blank)"],
                        key=f"act_s{sem_str}_{i}", horizontal=True,
                    )
                    if "Approve" in action:
                        approved_items.append({**fill, "approved_content": edited})

            approved_by_sem[sem_str] = approved_items

    st.divider()
    col1, col2 = st.columns([2, 1])
    with col1:
        alert(f"Reviewed {num_semesters} semester(s). Click Confirm to assemble all documents.", "info")
    with col2:
        if st.button("Confirm & Assemble All Semesters →", type="primary", use_container_width=True):
            _invoke(approved_by_sem)
            st.rerun()


# ── Gate 2: Preview + Feedback ────────────────────────────────────────────────

def _gate_preview(iv: dict):
    ver           = iv.get("version", 1)
    num_semesters = iv.get("num_semesters", 1)
    sem_docx      = iv.get("semester_docx_paths", {})
    sem_qa        = iv.get("semester_qa_reports", {})
    sem_contents  = iv.get("semester_contents", {})

    page_header(
        f"Document Preview  ·  v{ver}  ·  {num_semesters} Semester(s)",
        "Review all semester documents. Approve to export or send feedback to revise.",
        "🔍",
    )

    # Aggregate QA
    scores = [sem_qa.get(str(s), {}).get("score", 0) for s in range(1, num_semesters + 1)]
    avg_score = sum(scores) / len(scores) if scores else 0
    passed_all = all(sem_qa.get(str(s), {}).get("status") == "pass" for s in range(1, num_semesters + 1))

    col_m1, col_m2, col_m3, _ = st.columns([1, 1, 1, 3])
    col_m1.metric("Avg QA Score", f"{avg_score:.0%}")
    col_m2.metric("Semesters", num_semesters)
    col_m3.metric("QA Status", "✅ All Pass" if passed_all else "⚠️ Issues")

    st.divider()
    main_tab, approve_tab, feedback_tab = st.tabs(
        ["📋 Preview All Semesters", "✅ Approve & Export", "🔄 Request Changes"]
    )

    with main_tab:
        # One sub-tab per semester
        sem_keys = sorted(sem_docx.keys(), key=int)
        if sem_keys:
            sub_tabs = st.tabs([f"Semester {k}" for k in sem_keys])
            for sub_tab, sem_str in zip(sub_tabs, sem_keys):
                qa      = sem_qa.get(sem_str, {})
                content = sem_contents.get(sem_str, {})
                docx    = sem_docx.get(sem_str, "")

                with sub_tab:
                    score = qa.get("score", 0)
                    c1, c2 = st.columns([1, 1])
                    c1.metric("QA Score", f"{score:.0%}")
                    c2.metric("Status", "✅ Pass" if qa.get("status") == "pass" else "⚠️ Issues")

                    if qa.get("findings"):
                        with st.expander(f"⚠️ {len(qa['findings'])} issue(s)"):
                            for f in qa["findings"]:
                                st.caption(f"• `{f['check']}`:  {f['detail']}")

                    col_content, col_dl = st.columns([3, 1])
                    with col_content:
                        _render_preview(content)
                    with col_dl:
                        if docx and Path(docx).exists():
                            with open(docx, "rb") as f:
                                st.download_button(f"⬇ Sem {sem_str} DOCX", f, Path(docx).name,
                                                   use_container_width=True)
                            alert("Open in Word for pixel-perfect view.", "info")

    with approve_tab:
        alert(
            f"Approving will export all <b>{num_semesters} semester DOCX + PDF</b> files and save them to the library.",
            "success",
        )
        st.markdown("")
        if st.button("✅  Approve & Export All Semester Documents", type="primary", use_container_width=True):
            _invoke({"approved": True, "feedback": ""})
            st.rerun()

    with feedback_tab:
        alert(
            "Describe what needs changing across any semester. "
            "The engine will apply your feedback and rebuild all affected documents.",
            "warn",
        )
        feedback = st.text_area(
            "Your feedback",
            placeholder=(
                "e.g. The outcomes for Semester 2 Web Development are too generic — "
                "make them specific to React.js and Node.js. "
                "Also Semester 3 Data Science modules are missing deep learning topics."
            ),
            height=140,
        )
        if st.button("Submit Feedback & Revise →", type="secondary", use_container_width=True):
            if not feedback.strip():
                alert("Please enter feedback before submitting.", "warn")
            else:
                _invoke({"approved": False, "feedback": feedback})
                st.rerun()


# ── Gate 3: Email Recipients ──────────────────────────────────────────────────

def _gate_email(iv: dict):
    num_semesters = iv.get("num_semesters", 1)
    sem_docx      = iv.get("semester_docx_paths", {})
    sem_pdf       = iv.get("semester_pdf_paths", {})

    page_header("Send for External Review", f"All {num_semesters} semester documents exported! Send to reviewers.", "📧")
    alert(f"✅ <b>{num_semesters} semester document(s) exported.</b> You can skip emailing and go straight to Library.", "success")

    col1, col2 = st.columns([2, 1])
    with col1:
        section_title("Export Summary")
        st.markdown(f"""
| Field | Value |
|-------|-------|
| Program | {iv.get('program') or '(auto-detected)'} |
| Semesters | 1 – {num_semesters} |
| University | {iv.get('university', '').upper()} |
| Version | v{iv.get('version')} |
""")
        section_title("Download All Files")
        for sem_str in sorted(sem_docx.keys(), key=int):
            docx = sem_docx.get(sem_str, "")
            pdf  = sem_pdf.get(sem_str, "")
            c1, c2 = st.columns(2)
            if docx and Path(docx).exists():
                with open(docx, "rb") as f:
                    c1.download_button(f"⬇ Sem {sem_str} DOCX", f, Path(docx).name,
                                       key=f"eg_docx_{sem_str}", use_container_width=True)
            if pdf and Path(pdf).exists():
                with open(pdf, "rb") as f:
                    c2.download_button(f"⬇ Sem {sem_str} PDF", f, Path(pdf).name,
                                       key=f"eg_pdf_{sem_str}", use_container_width=True)

    with col2:
        import os
        sender = os.getenv("EMAIL_SENDER", "")
        section_title("Email Config")
        if sender:
            alert(f"Sender: <b>{sender}</b>", "success")
        else:
            alert("Set <code>EMAIL_SENDER</code> and <code>EMAIL_PASSWORD</code> in your <code>.env</code> file.", "warn")

        section_title("Recipients")
        raw_emails = st.text_area(
            "", placeholder="hod@university.ac.in\nbos@university.ac.in",
            height=120, label_visibility="collapsed",
        )

        if st.button("📤  Send Review Email", type="primary", use_container_width=True):
            emails = [e.strip() for e in raw_emails.replace(",", "\n").splitlines() if e.strip()]
            if not emails:
                alert("Enter at least one email address.", "warn")
            else:
                with st.spinner(f"Sending to {len(emails)} recipient(s)…"):
                    _invoke({"to_emails": emails})
                alert(f"✅ Email sent to: {', '.join(emails)}", "success")
                st.session_state["page"] = "Library"
                st.rerun()

        if st.button("Skip — Library Only", use_container_width=True):
            _invoke({"to_emails": []})
            st.session_state["page"] = "Library"
            st.rerun()


# ── Inbox Page ────────────────────────────────────────────────────────────────

def page_inbox_flow():
    flow = ss("inbox_flow", {})

    # Entry: pick a document if no flow is active
    if not flow:
        page_header("Inbox — Email Review Replies", "Check reviewer replies and manage revision cycles.", "📬")
        docs = [d for d in db.list_docs() if d.state == "approved"]
        if not docs:
            empty_state("No approved documents", "Approve a document first to enable email review.")
            return

        section_title("Select Document")
        for doc in docs:
            from ase.store.db import list_email_records
            recs = list_email_records(doc.doc_id)
            unread = sum(r2.processed == False for rec in recs for r2 in rec.replies)
            col1, col2, col3 = st.columns([4, 1, 1])
            with col1:
                st.markdown(f"**{doc.university_id.upper()}** — {doc.program}  ·  {doc.num_semesters} Sem(s)")
                st.caption(f"{len(recs)} email(s) sent  ·  {unread} unread replies")
            with col2:
                st.markdown(badge(doc.state), unsafe_allow_html=True)
            with col3:
                if st.button("Open Inbox", key=f"openinbox_{doc.doc_id}", type="primary"):
                    st.session_state["inbox_flow"] = {
                        "step": "check_replies",
                        "doc_id": doc.doc_id,
                    }
                    st.rerun()
        return

    step = flow.get("step")

    # Back button
    if st.button("← Back to Inbox"):
        del st.session_state["inbox_flow"]
        st.rerun()

    if step == "check_replies":      _inbox_check_replies(flow)
    elif step == "feedback_review":  _inbox_feedback_review(flow)
    elif step == "revision_preview": _inbox_revision_preview(flow)
    elif step == "email_draft":      _inbox_email_draft(flow)
    elif step == "done":
        alert("✅ Revision complete and reply sent to the reviewer in the same thread!", "success")
        if st.button("🏠 Back to Library"):
            del st.session_state["inbox_flow"]
            st.session_state["page"] = "Library"
            st.rerun()


def _inbox_check_replies(flow: dict):
    from ase.notify.inbox import check_replies
    from ase.store.db import list_email_records, save_email_record

    doc  = db.load_doc(flow["doc_id"])
    recs = list_email_records(doc.doc_id)

    page_header(
        f"Inbox — {doc.university_id.upper()} · {doc.program}",
        f"{doc.num_semesters} Semester(s)  ·  {len(recs)} email thread(s)",
        "📬",
    )

    if not recs:
        empty_state("No emails sent", "Use the email gate after approving a document to send to reviewers.")
        return

    for rec in recs:
        failed = rec.message_id.startswith("FAILED:")
        b_label = f"📨  v{rec.version}  ·  {rec.sent_at[:10]}  ·  {', '.join(rec.to_emails[:2])}"
        if not failed and rec.replies:
            unread = sum(1 for r in rec.replies if not r.processed)
            if unread:
                b_label += f"  🔴 {unread} new"

        with st.expander(b_label):
            if failed:
                alert(f"Send failed: {rec.message_id}", "danger")
            else:
                st.caption(f"Subject: {rec.subject}")
                col1, col2 = st.columns([3, 1])
                with col2:
                    if st.button("🔄 Check for Replies", key=f"chk_{rec.email_id}"):
                        with st.spinner("Checking inbox…"):
                            replies, err = check_replies(rec.message_id)
                        if err:
                            alert(f"Inbox error: {err}", "danger")
                        elif not replies:
                            alert("No replies found yet.", "info")
                        else:
                            existing = {r.body for r in rec.replies}
                            added = sum(1 for r in replies if r.body not in existing)
                            for r in replies:
                                if r.body not in existing:
                                    rec.replies.append(r)
                            save_email_record(rec)
                            if added:
                                alert(f"{added} new reply(ies) found!", "success")
                            else:
                                alert("No new replies.", "info")

            for i, reply in enumerate(rec.replies):
                with st.container(border=True):
                    c1, c2 = st.columns([4, 1])
                    with c1:
                        st.markdown(f"**From:** {reply.from_addr}  ·  {reply.date}")
                        st.caption(reply.body[:300] + ("…" if len(reply.body) > 300 else ""))
                    with c2:
                        if reply.processed:
                            alert("✓ Processed", "success")
                        else:
                            if st.button("🔁 Start Revision", key=f"start_{rec.email_id}_{i}", type="primary"):
                                flow.update({
                                    "step": "feedback_review",
                                    "email_record_id": rec.email_id,
                                    "reply_idx": i,
                                    "reply_body": reply.body,
                                    "reply_from": reply.from_addr,
                                    "original_subject": rec.subject,
                                    "original_message_id": rec.message_id,
                                    "prev_version": doc.current_version,
                                })
                                st.session_state["inbox_flow"] = flow
                                st.rerun()


def _inbox_feedback_review(flow: dict):
    from ase.notify.reply_composer import analyze_feedback

    doc = db.load_doc(flow["doc_id"])
    page_header("Reviewer Feedback Analysis", "Review the changes requested before approving revision.", "📋")

    col1, col2 = st.columns([3, 2])
    with col1:
        section_title("Reviewer's Reply")
        st.markdown(f"""
<div style="background:white;border-radius:12px;padding:20px;box-shadow:0 1px 4px rgba(0,0,0,0.07);
border-left:4px solid #4F46E5;">
  <p style="font-size:13px;color:#64748B;margin-bottom:8px;">From: <b>{flow.get('reply_from','')}</b></p>
  <p style="font-size:14px;color:#1E293B;line-height:1.7;">{flow.get('reply_body','')}</p>
</div>""", unsafe_allow_html=True)

    with col2:
        section_title("LLM Analysis")
        if "analysis" not in flow:
            with st.spinner("Analyzing feedback…"):
                analysis = analyze_feedback(flow["reply_body"], doc.program, doc.semester)
            flow["analysis"] = analysis
            st.session_state["inbox_flow"] = flow

        analysis = flow["analysis"]
        reviewer  = analysis.get("reviewer_name", "Reviewer")
        changes   = analysis.get("changes_requested", [])
        concern   = analysis.get("general_concerns", "")
        priority  = analysis.get("priority", "medium")

        st.markdown(f"**Reviewer:** {reviewer}")
        if concern:
            st.markdown(f"**Overall concern:** {concern}")
        st.markdown(f"**Priority:** `{priority}`  ·  Sentiment: `{analysis.get('sentiment','neutral')}`")

        if changes:
            st.markdown("**Specific changes requested:**")
            for i, c in enumerate(changes, 1):
                st.markdown(f"{i}. {c}")
        else:
            alert("No specific changes detected.", "warn")

    st.divider()
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("✅  Approve — Incorporate These Changes", type="primary", use_container_width=True):
            flow["step"] = "revising"
            st.session_state["inbox_flow"] = flow
            _run_revision(flow)
    with col_b:
        if st.button("❌  Skip — Don't Revise", use_container_width=True):
            _mark_reply_processed(flow)
            del st.session_state["inbox_flow"]
            st.session_state["page"] = "Library"
            st.rerun()


def _run_revision(flow: dict):
    from ase.notify.reply_composer import apply_feedback_to_content
    from ase.render.docx_builder import build_docx, export_pdf
    from ase.schemas.models import TemplateBlueprint, ContentModel
    import json

    doc    = db.load_doc(flow["doc_id"])
    latest = next((v for v in reversed(doc.versions) if v.state == "approved"), None)
    if not latest or not latest.content_model_path:
        alert("Cannot find saved content model for revision.", "danger")
        return

    content_dict = json.loads(Path(latest.content_model_path).read_text(encoding="utf-8"))
    profile      = db.load_profile(doc.university_id)
    bp_dict      = profile.blueprints[-1] if profile.blueprints else {}
    changes_req  = flow.get("analysis", {}).get("changes_requested", [])

    with st.spinner("Applying reviewer changes…"):
        updated_content, changes_made = apply_feedback_to_content(
            content_dict, changes_req, doc.program, doc.semester,
        )

    blueprint = TemplateBlueprint(**bp_dict)
    content   = ContentModel(**updated_content)
    new_ver   = doc.current_version + 1
    fname     = f"{doc.university_id}_{content.program.replace(' ','_')}_Sem{content.semester}_v{new_ver}.docx"
    docx_path = str(db.file_path(doc.doc_id, fname))

    with st.spinner("Building updated document…"):
        build_docx(blueprint, content, docx_path)
        pdf_path = export_pdf(docx_path)

    cjson = str(db.file_path(doc.doc_id, f"content_v{new_ver}.json"))
    Path(cjson).write_text(content.model_dump_json(indent=2), encoding="utf-8")

    flow.update({
        "step": "revision_preview",
        "new_version": new_ver,
        "new_docx": docx_path,
        "new_pdf": pdf_path,
        "new_content": updated_content,
        "changes_made": changes_made,
        "content_json_path": cjson,
    })
    st.session_state["inbox_flow"] = flow
    st.rerun()


def _inbox_revision_preview(flow: dict):
    page_header(f"Revised Document — v{flow.get('new_version')}", "Review what changed, then approve to generate the reply email.", "🔍")

    col1, col2 = st.columns([3, 1])
    with col1:
        section_title("Changes Made")
        for i, c in enumerate(flow.get("changes_made", []), 1):
            st.markdown(f"**{i}.** {c}")
        st.divider()
        _render_preview(flow.get("new_content", {}))

    with col2:
        section_title("Download")
        for pk, lbl in [("new_docx", "DOCX"), ("new_pdf", "PDF")]:
            p = flow.get(pk)
            if p and Path(p).exists():
                with open(p, "rb") as f:
                    st.download_button(f"⬇ {lbl}", f, Path(p).name, use_container_width=True)

        st.divider()
        if st.button("✅  Approve — Draft Reply Email", type="primary", use_container_width=True):
            flow["step"] = "email_draft"
            st.session_state["inbox_flow"] = flow
            _generate_email_draft(flow)

        if st.button("🔄  Revise Again", use_container_width=True):
            flow["step"] = "feedback_review"
            st.session_state["inbox_flow"] = flow
            st.rerun()


def _generate_email_draft(flow: dict):
    from ase.notify.reply_composer import generate_reply_body
    doc      = db.load_doc(flow["doc_id"])
    analysis = flow.get("analysis", {})

    docx_name = Path(flow.get("new_docx", "document.docx")).name
    pdf_name  = Path(flow.get("new_pdf", "document.pdf")).name if flow.get("new_pdf") else "N/A"

    with st.spinner("Drafting formal reply email…"):
        draft = generate_reply_body(
            reviewer_name=analysis.get("reviewer_name", "Reviewer"),
            feedback_summary=analysis.get("general_concerns", flow.get("reply_body", "")[:200]),
            changes_made=flow.get("changes_made", []),
            program=doc.program, semester=doc.semester,
            university=doc.university_id.upper(),
            prev_version=flow.get("prev_version", 1),
            new_version=flow.get("new_version", 2),
            docx_name=docx_name, pdf_name=pdf_name,
        )

    flow["email_draft"] = draft
    st.session_state["inbox_flow"] = flow
    st.rerun()


def _inbox_email_draft(flow: dict):
    from ase.notify.emailer import send_thread_reply
    from ase.store.db import load_email_record, save_email_record

    page_header("Approve Reply Email", "Review the LLM-generated reply. Edit if needed, then send.", "📧")

    alert(
        "This email will be sent <b>in the same thread</b> as the original review request. "
        "The updated DOCX and PDF will be attached automatically.",
        "info",
    )

    doc = db.load_doc(flow["doc_id"])
    rec = load_email_record(flow["email_record_id"])

    col1, col2 = st.columns([3, 2])
    with col1:
        section_title("Email Draft (editable)")
        subject = flow.get("original_subject", "")
        reply_subject = subject if subject.startswith("Re:") else f"Re: {subject}"
        st.markdown(f"**Subject:** `{reply_subject}`")
        st.markdown(f"**To:** {', '.join(rec.to_emails)}")
        st.markdown(f"**Thread:** replying to `{flow.get('original_message_id','')[:50]}…`")
        st.markdown("")
        edited_body = st.text_area(
            "Email body", value=flow.get("email_draft", ""),
            height=380, label_visibility="collapsed",
        )

    with col2:
        section_title("Attachments")
        for pk, lbl in [("new_docx", "DOCX"), ("new_pdf", "PDF")]:
            p = flow.get(pk)
            if p and Path(p).exists():
                with open(p, "rb") as f:
                    st.download_button(f"Preview {lbl}", f, Path(p).name, use_container_width=True)

        section_title("Changes Summary")
        for i, c in enumerate(flow.get("changes_made", [])[:5], 1):
            st.caption(f"{i}. {c}")

        st.divider()
        if st.button("✅  Approve & Send Reply", type="primary", use_container_width=True):
            attachments = [p for p in [flow.get("new_docx"), flow.get("new_pdf")]
                           if p and Path(p).exists()]
            failed = []
            with st.spinner("Sending reply…"):
                for addr in rec.to_emails:
                    ok, _, err = send_thread_reply(
                        to_email=addr,
                        original_subject=flow.get("original_subject", ""),
                        original_message_id=flow.get("original_message_id", ""),
                        body=edited_body,
                        attachments=attachments,
                    )
                    if not ok:
                        failed.append(f"{addr}: {err}")

            if failed:
                alert("Failed to send to: " + "; ".join(failed), "danger")
            else:
                _mark_reply_processed(flow)
                _save_new_version(flow, doc)
                alert(f"✅ Reply sent to {', '.join(rec.to_emails)} in the same thread!", "success")
                flow["step"] = "done"
                st.session_state["inbox_flow"] = flow
                st.rerun()

        if st.button("✏️  Regenerate Draft", use_container_width=True):
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

def _sidebar():
    with st.sidebar:
        st.markdown("""
<div style="padding:20px 8px 12px;">
  <div style="font-size:28px;font-weight:800;color:white;letter-spacing:-1px;">📄 ASDE</div>
  <div style="font-size:12px;color:#A5B4FC;margin-top:2px;font-weight:500;">
    Academic Syllabus Document Engine
  </div>
</div>""", unsafe_allow_html=True)

        page = st.radio("", PAGES,
                        index=PAGES.index(ss("page", "Library")),
                        label_visibility="collapsed")
        st.session_state["page"] = page

        st.markdown("<hr style='border-color:#4338CA;margin:12px 0;'>", unsafe_allow_html=True)

        # Active doc status
        if ss("thread_id"):
            iv  = _interrupt()
            nxt = _next()
            if iv:
                kind = iv.get("type", "")
                labels = {
                    "content_review": "✏️ Content review",
                    "preview":        "👁️ Preview approval",
                    "email_gate":     "📧 Email recipients",
                }
                st.markdown(f"""
<div style="background:rgba(245,158,11,0.15);border-radius:10px;padding:12px 14px;margin-bottom:8px;">
  <div style="font-size:11px;color:#FCD34D;text-transform:uppercase;font-weight:700;">Waiting for you</div>
  <div style="color:white;font-size:13px;margin-top:4px;">{labels.get(kind, kind)}</div>
</div>""", unsafe_allow_html=True)
            elif nxt:
                st.markdown("""
<div style="background:rgba(79,70,229,0.2);border-radius:10px;padding:12px 14px;margin-bottom:8px;">
  <div style="font-size:11px;color:#A5B4FC;text-transform:uppercase;font-weight:700;">Processing</div>
  <div style="color:white;font-size:13px;margin-top:4px;">⏳ Running…</div>
</div>""", unsafe_allow_html=True)

        # Inbox flow status
        if ss("inbox_flow"):
            step_labels = {
                "check_replies":    "📬 Checking replies",
                "feedback_review":  "📋 Feedback review",
                "revision_preview": "🔍 Preview revision",
                "email_draft":      "📧 Email approval",
                "done":             "✅ Reply sent",
            }
            step = ss("inbox_flow", {}).get("step", "")
            st.markdown(f"""
<div style="background:rgba(16,185,129,0.15);border-radius:10px;padding:12px 14px;margin-bottom:8px;">
  <div style="font-size:11px;color:#6EE7B7;text-transform:uppercase;font-weight:700;">Inbox Revision</div>
  <div style="color:white;font-size:13px;margin-top:4px;">{step_labels.get(step,'Active')}</div>
</div>""", unsafe_allow_html=True)

        # Quick stats
        docs = db.list_docs()
        if docs:
            approved = sum(1 for d in docs if d.state == "approved")
            st.markdown(f"""
<div style="margin-top:8px;padding:12px 14px;background:rgba(255,255,255,0.05);border-radius:10px;">
  <div style="font-size:11px;color:#A5B4FC;text-transform:uppercase;font-weight:700;margin-bottom:8px;">Quick Stats</div>
  <div style="display:flex;justify-content:space-between;color:white;font-size:13px;">
    <span>Total</span><span style="font-weight:700;">{len(docs)}</span>
  </div>
  <div style="display:flex;justify-content:space-between;color:#6EE7B7;font-size:13px;margin-top:4px;">
    <span>Approved</span><span style="font-weight:700;">{approved}</span>
  </div>
</div>""", unsafe_allow_html=True)

    return page


def main():
    page = _sidebar()
    if page == "Library":        page_library()
    elif page == "New Document": page_new_document()
    elif page == "Process":      page_process()
    elif page == "Inbox":        page_inbox_flow()


if __name__ == "__main__":
    main()
