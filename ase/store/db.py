"""JSON file-based storage for documents, versions, profiles, and email records."""
from pathlib import Path
from ase.schemas.models import DocumentRecord, UniversityProfile, EmailRecord
from ase.config import STORE_DIR

_docs = STORE_DIR / "documents"
_profiles = STORE_DIR / "profiles"
_files = STORE_DIR / "files"

for _d in (_docs, _profiles, _files):
    _d.mkdir(parents=True, exist_ok=True)


# ── Documents ─────────────────────────────────────────────────────────────────

def save_doc(doc: DocumentRecord) -> None:
    p = _docs / doc.doc_id
    p.mkdir(exist_ok=True)
    (p / "record.json").write_text(doc.model_dump_json(indent=2), encoding="utf-8")


def load_doc(doc_id: str) -> DocumentRecord:
    return DocumentRecord.model_validate_json(
        (_docs / doc_id / "record.json").read_text(encoding="utf-8")
    )


def list_docs() -> list[DocumentRecord]:
    if not _docs.exists():
        return []
    docs = []
    for p in _docs.iterdir():
        if p.is_dir() and (p / "record.json").exists():
            try:
                docs.append(load_doc(p.name))
            except Exception:
                pass
    return sorted(docs, key=lambda d: d.created_at, reverse=True)


# ── University Profiles ───────────────────────────────────────────────────────

def load_profile(university_id: str) -> UniversityProfile:
    f = _profiles / f"{university_id}.json"
    if not f.exists():
        return UniversityProfile(university_id=university_id)
    return UniversityProfile.model_validate_json(f.read_text(encoding="utf-8"))


def save_profile(profile: UniversityProfile) -> None:
    f = _profiles / f"{profile.university_id}.json"
    f.write_text(profile.model_dump_json(indent=2), encoding="utf-8")


def list_universities() -> list[str]:
    return [f.stem for f in _profiles.glob("*.json")]


# ── Email Records ─────────────────────────────────────────────────────────────

_emails = STORE_DIR / "emails"
_emails.mkdir(parents=True, exist_ok=True)

def save_email_record(rec: EmailRecord) -> None:
    f = _emails / f"{rec.email_id}.json"
    f.write_text(rec.model_dump_json(indent=2), encoding="utf-8")

def load_email_record(email_id: str) -> EmailRecord:
    f = _emails / f"{email_id}.json"
    return EmailRecord.model_validate_json(f.read_text(encoding="utf-8"))

def list_email_records(doc_id: str) -> list[EmailRecord]:
    recs = []
    for f in _emails.glob("*.json"):
        try:
            r = EmailRecord.model_validate_json(f.read_text(encoding="utf-8"))
            if r.doc_id == doc_id:
                recs.append(r)
        except Exception:
            pass
    return sorted(recs, key=lambda r: r.sent_at, reverse=True)


# ── File storage ──────────────────────────────────────────────────────────────

def file_path(doc_id: str, filename: str) -> Path:
    p = _files / doc_id
    p.mkdir(parents=True, exist_ok=True)
    return p / filename
