"""Send formal review emails with DOCX + PDF attachments via SMTP."""
import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from email.utils import make_msgid, formatdate
from pathlib import Path


EMAIL_BODY_TEMPLATE = """\
Dear Reviewer,

Greetings from the Content Development Team, NxtWave / NIAT.

We are pleased to share the draft syllabus document for your kind review and \
feedback. Please find the details below:

    Program   : {program}
    Semester  : {semester}
    University: {university}
    Version   : {version}

Kindly find attached the following documents for your reference:

    1. {docx_name}  —  Editable version (Microsoft Word)
    2. {pdf_name}   —  Print-ready version (PDF)

We request you to review the attached syllabus at your earliest convenience \
and share your observations, suggestions, or concerns by replying directly \
to this email.

Your valuable inputs will be carefully reviewed and incorporated. An updated \
version of the document will be shared with you thereafter for your \
confirmation.

Should you require any clarifications or additional information, please do \
not hesitate to reach out to us.

Thanking you for your time and continued support.

Warm regards,
Content Development Team
NxtWave Technology Solutions Pvt. Ltd. / NIAT
"""

SUBJECT_TEMPLATE = (
    "[Review Request] {university} — {program} | Semester {semester} Syllabus (v{version})"
)


def _smtp_config() -> dict:
    return {
        "sender":    os.getenv("EMAIL_SENDER", ""),
        "password":  os.getenv("EMAIL_PASSWORD", ""),
        "smtp_host": os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com"),
        "smtp_port": int(os.getenv("EMAIL_SMTP_PORT", "587")),
    }


def send_review_email(
    to_emails: list[str],
    program: str,
    semester: int,
    university: str,
    version: int,
    docx_path: str,
    pdf_path: str | None,
) -> tuple[bool, str, str]:
    """
    Send the review email with DOCX + PDF attached.
    Returns (success, message_id, error_message).
    """
    cfg = _smtp_config()
    if not cfg["sender"] or not cfg["password"]:
        return False, "", "EMAIL_SENDER or EMAIL_PASSWORD not set in environment."

    msg = MIMEMultipart()
    msg["From"]    = cfg["sender"]
    msg["To"]      = ", ".join(to_emails)
    msg["Date"]    = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=cfg["sender"].split("@")[-1])

    docx_name = Path(docx_path).name
    pdf_name  = Path(pdf_path).name if pdf_path else "N/A (PDF not generated)"

    msg["Subject"] = SUBJECT_TEMPLATE.format(
        university=university, program=program,
        semester=semester, version=version,
    )

    body = EMAIL_BODY_TEMPLATE.format(
        program=program, semester=semester,
        university=university, version=version,
        docx_name=docx_name, pdf_name=pdf_name,
    )
    msg.attach(MIMEText(body, "plain"))

    # Attach DOCX
    _attach_file(msg, docx_path)

    # Attach PDF if available
    if pdf_path and Path(pdf_path).exists():
        _attach_file(msg, pdf_path)

    try:
        with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"]) as server:
            server.ehlo()
            server.starttls()
            server.login(cfg["sender"], cfg["password"])
            server.sendmail(cfg["sender"], to_emails, msg.as_string())
        return True, msg["Message-ID"], ""
    except Exception as e:
        return False, "", str(e)


def _attach_file(msg: MIMEMultipart, path: str):
    with open(path, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header(
        "Content-Disposition",
        f'attachment; filename="{Path(path).name}"',
    )
    msg.attach(part)
