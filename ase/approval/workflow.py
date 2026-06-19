"""Approval state machine: approve, request_changes, reject with full audit trail."""
from datetime import datetime
from ase.schemas.models import DocumentRecord, ApprovalRecord, AuditEntry, VersionRecord
from ase.store import db


def _now() -> str:
    return datetime.utcnow().isoformat()


def _transition(doc: DocumentRecord, from_: str, to_: str, by: str, note: str = "") -> DocumentRecord:
    doc.audit.append(AuditEntry(at=_now(), from_state=from_, to_state=to_, by=by, note=note))
    doc.state = to_  # type: ignore[assignment]
    db.save_doc(doc)
    return doc


def approve(doc_id: str, reviewer: str, notes: str = "") -> DocumentRecord:
    doc = db.load_doc(doc_id)
    ver = doc.current_version
    doc.approvals.append(ApprovalRecord(version=ver, decision="approve", reviewer=reviewer, notes=notes))
    # Mark the current version as approved
    for v in doc.versions:
        if v.version == ver:
            v.state = "approved"
    return _transition(doc, doc.state, "approved", reviewer, notes)


def request_changes(doc_id: str, reviewer: str, notes: str) -> DocumentRecord:
    doc = db.load_doc(doc_id)
    ver = doc.current_version
    doc.approvals.append(ApprovalRecord(version=ver, decision="request_changes", reviewer=reviewer, notes=notes))
    for v in doc.versions:
        if v.version == ver:
            v.state = "changes_requested"
    return _transition(doc, doc.state, "changes_requested", reviewer, notes)


def reject(doc_id: str, reviewer: str, notes: str = "") -> DocumentRecord:
    doc = db.load_doc(doc_id)
    ver = doc.current_version
    doc.approvals.append(ApprovalRecord(version=ver, decision="reject", reviewer=reviewer, notes=notes))
    for v in doc.versions:
        if v.version == ver:
            v.state = "rejected"
    return _transition(doc, doc.state, "rejected", reviewer, notes)


def add_version(doc: DocumentRecord, docx_path: str, qa_report: dict,
                generation_report: dict, blueprint_version: int = 1) -> DocumentRecord:
    """Register a new generated version on the document record."""
    ver_num = doc.current_version + 1
    doc.current_version = ver_num
    doc.versions.append(VersionRecord(
        version=ver_num,
        blueprint_version=blueprint_version,
        docx_path=docx_path,
        qa_score=qa_report.get("score", 0.0),
        qa_report=qa_report,
        generation_report=generation_report,
        state="draft",
    ))
    doc = _transition(doc, doc.state, "review", "system", f"Version {ver_num} ready for review")
    return doc
