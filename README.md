# ASDE — Academic Syllabus Document Engine

> **Codename Morph** · Automatically convert any university template + NIAT standard syllabus into a pixel-perfect, AI-enriched academic document, approved by humans every step of the way.

---

## Overview

ASDE is a human-in-the-loop document generation engine built on **Claude AI + LangGraph + Streamlit**.

Upload a university template DOCX (any format) and a standard NIAT syllabus — the engine:

1. **Analyzes** the full template structure (fonts, colors, margins, tables, layouts) and extracts a reusable **Blueprint**
2. **Parses** the syllabus into a structured content model
3. **Detects gaps** — sections in the template that the syllabus doesn't cover — and uses the LLM to generate content for them
4. **Asks you to approve** every AI-generated section before assembling the document
5. **Assembles** a fully formatted DOCX, renders a **live preview**, and loops on your feedback until you're satisfied
6. **Exports** the final document as DOCX + PDF, saves to the library
7. **Emails** it to external reviewers (HoD, BoS, etc.), monitors for replies, and manages the entire revision + threaded reply cycle through additional human-approval gates

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          LangGraph Pipeline                             │
│                                                                         │
│  ingest → analyze_template → parse_content → detect_gaps               │
│        → generate_fills                                                 │
│        → [GATE 1] review_content  (human approves each AI-filled gap)  │
│        → assemble                                                       │
│        → [GATE 2] preview         (human approves or gives feedback)   │
│           ↑________________ apply_feedback (on feedback, loop back)     │
│        → export                                                         │
│        → [GATE 3] email_gate      (human enters reviewer email IDs)    │
│        → send_email → END                                               │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                       Email Revision Flow (Inbox)                       │
│                                                                         │
│  check_replies → [GATE A] feedback_review (operator approves changes)  │
│               → apply_feedback_to_content → build_docx → export_pdf   │
│               → [GATE B] revision_preview (preview + approve/revise)   │
│               → generate_reply_body (LLM drafts formal reply)          │
│               → [GATE C] email_draft (operator approves email text)    │
│               → send_thread_reply (same email thread) → done           │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| **AI / LLM** | Anthropic Claude (`claude-sonnet-4-6`) |
| **Workflow** | LangGraph `StateGraph` with `interrupt()` for human gates |
| **DOCX generation** | `python-docx` — blueprint-driven, zero hard-coded styles |
| **PDF export** | `docx2pdf` → Microsoft Word COM (Windows) |
| **DOCX / PDF parsing** | `python-docx`, `pdfplumber` |
| **Data models** | Pydantic v2 |
| **Storage** | JSON file store (no external DB) |
| **Email** | `smtplib` (SMTP) + `imaplib` (IMAP) with thread headers |
| **UI** | Streamlit 1.57 + custom CSS (Inter font, indigo design system) |
| **Checkpointing** | LangGraph `MemorySaver` |

---

## Folder Structure

```
syllabus-format-engine/
├── app.py                         # Streamlit UI — all 4 pages
├── requirements.txt
├── .env.example
├── .streamlit/
│   └── config.toml                # Theme (indigo color scheme)
│
└── ase/
    ├── config.py                  # Env vars, paths, constants
    ├── schemas/
    │   └── models.py              # All Pydantic v2 models
    ├── store/
    │   └── db.py                  # JSON file store (docs, profiles, emails)
    ├── ingestion/
    │   └── parser.py              # DOCX + PDF ingestion
    ├── analysis/
    │   ├── blueprint.py           # Template → Blueprint (Claude)
    │   ├── content.py             # Syllabus → ContentModel (Claude)
    │   └── gap_detector.py        # Gap detection + LLM fill
    ├── generate/
    │   └── academic.py            # CO/CLO generation (Bloom's Taxonomy)
    ├── references/
    │   └── engine.py              # IEEE textbook + reference generation
    ├── render/
    │   └── docx_builder.py        # Blueprint-driven DOCX assembly
    ├── qa/
    │   └── validator.py           # QA checks (8 dimensions, ≥85% pass)
    ├── approval/
    │   └── workflow.py            # State machine helpers
    ├── notify/
    │   ├── emailer.py             # Send review email + thread reply
    │   ├── inbox.py               # IMAP reply checker
    │   └── reply_composer.py      # LLM feedback analysis + reply draft
    ├── orchestrator/
    │   └── graph.py               # LangGraph pipeline
    └── ui/
        └── styles.py              # CSS injection + HTML component helpers
```

---

## Setup

### Prerequisites

- Python 3.11+
- Microsoft Word (for PDF export on Windows via `docx2pdf`)
- Gmail account with [App Password](https://myaccount.google.com/apppasswords) enabled (for email features)

### Install

```bash
git clone https://github.com/aravindr-2321/ASDE
cd ASDE
pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
```

Edit `.env`:

```env
ANTHROPIC_API_KEY=your_anthropic_key_here

# Gmail (for email send/receive)
EMAIL_SENDER=yourname@gmail.com
EMAIL_PASSWORD=xxxx xxxx xxxx xxxx   # 16-char App Password
EMAIL_SMTP_HOST=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_IMAP_HOST=imap.gmail.com
```

### Run

```bash
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501)

---

## Usage Guide

### 1 · New Document

- Go to **New Document** in the sidebar
- Enter the University ID (e.g. `adypu`), Program name, and Semester
- Upload the **University Template** (`.docx`) and the **NIAT Syllabus** (`.docx` or `.pdf`)
- Click **Analyze & Start Generation** — the engine runs the full pipeline automatically

### 2 · Content Review Gate (Gate 1)

When gaps are found between the template and syllabus, the LLM generates content for them. You see each generated section and can:
- Edit the text inline
- Approve or skip each section

Click **Confirm & Assemble** to build the document.

### 3 · Preview Gate (Gate 2)

The assembled DOCX is shown with:
- **QA score** (≥85% to pass)
- **Content preview** (all subjects, CLOs, COs, modules, references)
- **Download DOCX** for a pixel-perfect view in Word

Choose:
- **Approve & Export** → produces final DOCX + PDF, saves to Library
- **Submit Feedback** → LLM revises the document and loops back to preview

### 4 · Email Gate (Gate 3)

After export, enter reviewer email addresses (one per line) and click **Send Review Email**. A formal email with DOCX + PDF attached is sent via your configured Gmail account.

### 5 · Inbox — Reviewer Reply Cycle

Go to **Inbox**, select the document, and click **Check for Replies**.

When a reply is found:

| Gate | What you do |
|---|---|
| **A — Feedback Review** | LLM extracts all change requests; you approve or skip |
| **B — Revision Preview** | See every change made; approve or revise again |
| **C — Email Draft** | LLM writes a formal reply email; edit if needed; send in the same thread |

The reply arrives in the original email thread with the updated DOCX + PDF attached.

---

## Data Storage

All data is stored locally as JSON files under `store/`:

```
store/
├── documents/
│   └── {doc_id}/
│       ├── record.json              # DocumentRecord (state machine)
│       ├── content_v1.json          # ContentModel snapshot (per version)
│       ├── {university}_v1.docx
│       └── {university}_v1.pdf
├── profiles/
│   └── {university_id}.json         # UniversityProfile + blueprints
└── emails/
    └── {email_id}.json              # EmailRecord (sent emails + replies)
```

---

## Key Design Decisions

**Blueprint-driven rendering** — every color, font, label, and layout value comes from the extracted template blueprint. No university-specific values are hard-coded in the renderer. Supports any university template.

**LangGraph `interrupt()` for human gates** — the graph pauses execution mid-run, persists state to `MemorySaver`, and waits for a `Command(resume=payload)` from the UI. This means the Streamlit UI can reload freely between gate approvals without losing graph state.

**Content model saved to disk** — since the LangGraph pipeline is complete by the time email replies arrive, the `ContentModel` is serialized to `content_v{N}.json` at assembly time. The email revision flow loads this file directly, bypassing the graph entirely.

**Email threading** — replies use `In-Reply-To` and `References` MIME headers so they appear in the same Gmail thread. IMAP search uses these headers to find replies.

---

## Environment Variables

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `EMAIL_SENDER` | Gmail address used to send/receive |
| `EMAIL_PASSWORD` | 16-character Gmail App Password |
| `EMAIL_SMTP_HOST` | SMTP host (default: `smtp.gmail.com`) |
| `EMAIL_SMTP_PORT` | SMTP port (default: `587`) |
| `EMAIL_IMAP_HOST` | IMAP host (default: `imap.gmail.com`) |

---

## Contributing

Issues and PRs welcome at [github.com/aravindr-2321/ASDE](https://github.com/aravindr-2321/ASDE).

---

## License

MIT
