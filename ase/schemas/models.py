from __future__ import annotations
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field
from datetime import datetime
import uuid

# ── Template Blueprint ────────────────────────────────────────────────────────

class TemplateBlueprint(BaseModel):
    university_id: str
    version: int = 1
    source_doc_hash: str = ""
    page: dict = Field(default_factory=lambda: {"size": "A4", "margins_dxa": {}})
    assets: dict = Field(default_factory=dict)
    color_tokens: dict = Field(default_factory=dict)
    typography: dict = Field(default_factory=lambda: {"default_font": "Calibri", "body_font": "Times New Roman"})
    footer_template: str = ""
    sections_order: list[str] = Field(default_factory=list)
    table_templates: dict[str, Any] = Field(default_factory=dict)
    label_dictionary: dict[str, str] = Field(default_factory=dict)
    has_sections: dict[str, bool] = Field(default_factory=dict)
    tone: str = "formal-academic"
    defaults: dict = Field(default_factory=dict)
    confidence: dict[str, float] = Field(default_factory=dict)
    raw_analysis: str = ""

# ── Content Model ─────────────────────────────────────────────────────────────

class Module(BaseModel):
    label: str
    title: str
    topics: str

class SubjectContent(BaseModel):
    name: str
    code: Optional[str] = None
    credits: Optional[str] = None
    ltp: Optional[str] = None
    marks: Optional[str] = None
    objectives: list[str] = Field(default_factory=list)
    outcomes: list[str] = Field(default_factory=list)
    modules: list[Module] = Field(default_factory=list)
    copo: dict = Field(default_factory=dict)
    textbooks: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    generated_objectives: list[str] = Field(default_factory=list)
    generated_outcomes: list[str] = Field(default_factory=list)
    generated_references: list[str] = Field(default_factory=list)

class ContentModel(BaseModel):
    program: str
    semester: int
    subjects: list[SubjectContent] = Field(default_factory=list)

# ── Clarification ─────────────────────────────────────────────────────────────

class ClarificationRecord(BaseModel):
    id: str = Field(default_factory=lambda: f"clr_{uuid.uuid4().hex[:8]}")
    trigger: str
    question: str
    options: list[str] = Field(default_factory=list)
    answer: Optional[str] = None
    scope: Literal["this_doc", "this_university", "global"] = "this_university"
    applied_on: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

# ── Document Record ───────────────────────────────────────────────────────────

DocState = Literal[
    "intake", "analyzing", "clarifying", "drafting",
    "review", "approved", "changes_requested", "rejected"
]

class VersionRecord(BaseModel):
    version: int
    blueprint_version: int = 1
    docx_path: str = ""
    pdf_path: str = ""
    content_model_path: str = ""   # persisted JSON for revision access
    qa_score: float = 0.0
    qa_report: dict = Field(default_factory=dict)
    generation_report: dict = Field(default_factory=dict)
    state: str = "draft"
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

class ApprovalRecord(BaseModel):
    version: int
    decision: Literal["approve", "request_changes", "reject"]
    reviewer: str
    notes: str = ""
    at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

class AuditEntry(BaseModel):
    at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    from_state: str
    to_state: str
    by: str
    note: str = ""

class DocumentRecord(BaseModel):
    doc_id: str = Field(default_factory=lambda: f"doc_{uuid.uuid4().hex[:8]}")
    university_id: str
    program: str = ""
    semester: int = 1
    inputs: dict = Field(default_factory=dict)
    state: DocState = "intake"
    current_version: int = 0
    versions: list[VersionRecord] = Field(default_factory=list)
    approvals: list[ApprovalRecord] = Field(default_factory=list)
    audit: list[AuditEntry] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

# ── Email Record ─────────────────────────────────────────────────────────────

class EmailReply(BaseModel):
    from_addr: str
    date: str
    subject: str
    body: str
    processed: bool = False

class EmailRecord(BaseModel):
    email_id: str = Field(default_factory=lambda: f"email_{uuid.uuid4().hex[:8]}")
    doc_id: str
    version: int = 1
    message_id: str = ""
    to_emails: list[str] = Field(default_factory=list)
    subject: str = ""
    sent_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    replies: list[EmailReply] = Field(default_factory=list)

# ── University Profile ────────────────────────────────────────────────────────

class UniversityProfile(BaseModel):
    university_id: str
    display_name: str = ""
    blueprints: list[dict] = Field(default_factory=list)
    clarification_memory: list[ClarificationRecord] = Field(default_factory=list)
    defaults: dict = Field(default_factory=dict)
    runs: list[dict] = Field(default_factory=list)
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
