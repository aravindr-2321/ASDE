"""Monitor IMAP inbox for replies to sent review emails."""
import imaplib
import email
import os
import re
from email.header import decode_header
from ase.schemas.models import EmailReply


def _imap_config() -> dict:
    return {
        "sender":    os.getenv("EMAIL_SENDER", ""),
        "password":  os.getenv("EMAIL_PASSWORD", ""),
        "imap_host": os.getenv("EMAIL_IMAP_HOST", "imap.gmail.com"),
    }


def check_replies(sent_message_id: str) -> tuple[list[EmailReply], str]:
    """
    Search INBOX for replies to the given Message-ID.
    Returns (list of EmailReply, error_string).
    """
    cfg = _imap_config()
    if not cfg["sender"] or not cfg["password"]:
        return [], "EMAIL_SENDER or EMAIL_PASSWORD not set."

    try:
        imap = imaplib.IMAP4_SSL(cfg["imap_host"])
        imap.login(cfg["sender"], cfg["password"])
        imap.select("INBOX")

        # Search by In-Reply-To header
        clean_id = sent_message_id.strip("<>")
        _, data = imap.search(None, f'HEADER In-Reply-To "<{clean_id}>"')
        nums = data[0].split() if data[0] else []

        # Also search by References header (some clients use this)
        _, data2 = imap.search(None, f'HEADER References "<{clean_id}>"')
        nums2 = data2[0].split() if data2[0] else []

        all_nums = list(set(nums + nums2))
        replies: list[EmailReply] = []

        for num in all_nums:
            _, raw = imap.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(raw[0][1])
            body = _extract_body(msg)
            # Strip quoted original email (lines starting with >)
            clean_body = _strip_quoted(body)
            if clean_body.strip():
                replies.append(EmailReply(
                    from_addr=_decode_header(msg.get("From", "")),
                    date=msg.get("Date", ""),
                    subject=_decode_header(msg.get("Subject", "")),
                    body=clean_body.strip(),
                ))

        imap.logout()
        return replies, ""

    except Exception as e:
        return [], str(e)


def extract_feedback_text(replies: list[EmailReply]) -> str:
    """Combine all reply bodies into a single feedback string for the LLM."""
    if not replies:
        return ""
    parts = []
    for r in replies:
        parts.append(
            f"From: {r.from_addr}\nDate: {r.date}\nFeedback:\n{r.body}"
        )
    return "\n\n---\n\n".join(parts)


def _extract_body(msg) -> str:
    """Extract plain text body from an email message."""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in disp:
                charset = part.get_content_charset() or "utf-8"
                try:
                    return part.get_payload(decode=True).decode(charset, errors="replace")
                except Exception:
                    return part.get_payload(decode=True).decode("utf-8", errors="replace")
    else:
        charset = msg.get_content_charset() or "utf-8"
        return msg.get_payload(decode=True).decode(charset, errors="replace")
    return ""


def _decode_header(value: str) -> str:
    parts = decode_header(value)
    decoded = []
    for part, enc in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return " ".join(decoded)


def _strip_quoted(text: str) -> str:
    """Remove quoted original email lines (lines starting with > or On ... wrote:)."""
    lines = text.splitlines()
    clean = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(">"):
            continue
        if re.match(r"^On .+ wrote:$", stripped):
            break  # everything after is quoted
        clean.append(line)
    return "\n".join(clean)
