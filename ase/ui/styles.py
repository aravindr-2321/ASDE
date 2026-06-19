"""CSS injection and reusable HTML component helpers."""
import streamlit as st

# ── Color tokens ──────────────────────────────────────────────────────────────
BADGE = {
    "approved":          ("#D1FAE5", "#065F46", "✅"),
    "review":            ("#FEF3C7", "#92400E", "🔍"),
    "drafting":          ("#DBEAFE", "#1E40AF", "⚙️"),
    "clarifying":        ("#FDE8D8", "#9A3412", "❓"),
    "analyzing":         ("#EDE9FE", "#5B21B6", "🔬"),
    "approved_email":    ("#D1FAE5", "#065F46", "📧"),
    "changes_requested": ("#FEF3C7", "#92400E", "🔄"),
    "rejected":          ("#FEE2E2", "#991B1B", "❌"),
    "intake":            ("#F1F5F9", "#475569", "📥"),
}

PRIORITY_COLOR = {"high": "#EF4444", "medium": "#F59E0B", "low": "#10B981"}


def inject_css():
    st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

/* ── Global ── */
html, body, [class*="css"] { font-family: 'Inter', sans-serif !important; }
.main .block-container { padding: 2rem 2.5rem 4rem; max-width: 1280px; }
#MainMenu, footer, header { visibility: hidden; }

/* ── Sidebar ── */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #1E1B4B 0%, #312E81 60%, #3730A3 100%);
    border-right: none;
}
section[data-testid="stSidebar"] * { color: #E0E7FF !important; }
section[data-testid="stSidebar"] .stRadio label {
    color: #C7D2FE !important; font-size: 14px; padding: 4px 0;
}
section[data-testid="stSidebar"] .stRadio [data-testid="stMarkdownContainer"] p {
    font-size: 15px; font-weight: 500;
}
section[data-testid="stSidebar"] hr { border-color: #4338CA !important; }

/* ── Page header card ── */
.page-header {
    background: linear-gradient(135deg, #4F46E5 0%, #7C3AED 100%);
    color: white; padding: 28px 36px; border-radius: 16px;
    margin-bottom: 28px; box-shadow: 0 4px 20px rgba(79,70,229,0.3);
}
.page-header h1 { margin: 0; font-size: 26px; font-weight: 800; letter-spacing: -0.5px; }
.page-header p  { margin: 6px 0 0; font-size: 14px; opacity: 0.85; }

/* ── Stat cards row ── */
.stat-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 28px; }
.stat-card {
    background: white; border-radius: 12px; padding: 20px 24px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.07); text-align: center;
    border-top: 3px solid #4F46E5;
}
.stat-number { font-size: 30px; font-weight: 800; color: #4F46E5; line-height: 1; }
.stat-label  { font-size: 12px; color: #64748B; margin-top: 6px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.5px; }

/* ── Document card ── */
.doc-card {
    background: white; border-radius: 12px; padding: 20px 24px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.07); margin-bottom: 14px;
    border-left: 4px solid #4F46E5; transition: box-shadow 0.2s;
}
.doc-card:hover { box-shadow: 0 4px 16px rgba(0,0,0,0.12); }
.doc-card h3 { margin: 0 0 4px; font-size: 16px; font-weight: 700; color: #1E293B; }
.doc-card p  { margin: 0; font-size: 13px; color: #64748B; }
.doc-card-footer { margin-top: 14px; padding-top: 12px; border-top: 1px solid #F1F5F9; display: flex; gap: 8px; align-items: center; }

/* ── Status badge ── */
.badge {
    display: inline-flex; align-items: center; gap: 5px;
    padding: 4px 12px; border-radius: 20px;
    font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;
}

/* ── Step progress indicator ── */
.steps-wrap { display: flex; align-items: center; margin-bottom: 32px; }
.step-item  { display: flex; flex-direction: column; align-items: center; flex: 1; }
.step-circle {
    width: 38px; height: 38px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 15px; font-weight: 700; border: 2px solid transparent;
}
.step-circle.done    { background: #4F46E5; color: white; }
.step-circle.active  { background: #F59E0B; color: white; box-shadow: 0 0 0 4px rgba(245,158,11,0.2); }
.step-circle.pending { background: #F1F5F9; color: #94A3B8; border-color: #E2E8F0; }
.step-lbl { font-size: 11px; margin-top: 6px; color: #64748B; font-weight: 500; text-align: center; white-space: nowrap; }
.step-lbl.active { color: #F59E0B; font-weight: 700; }
.step-lbl.done   { color: #4F46E5; }
.step-line { flex: 1; height: 2px; background: #E2E8F0; margin-bottom: 24px; }
.step-line.done { background: #4F46E5; }

/* ── Section heading ── */
.section-title {
    font-size: 13px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 1px; color: #64748B; margin: 24px 0 12px;
    padding-bottom: 8px; border-bottom: 2px solid #EEF2FF;
}

/* ── Content review card ── */
.review-card {
    background: white; border-radius: 12px; padding: 20px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.07); margin-bottom: 16px;
    border-left: 4px solid #F59E0B;
}
.review-card h4 { margin: 0 0 4px; font-size: 15px; font-weight: 700; color: #1E293B; }
.review-card .reason { font-size: 12px; color: #64748B; margin-bottom: 12px; }

/* ── Alert boxes ── */
.alert { padding: 14px 18px; border-radius: 10px; font-size: 14px; margin-bottom: 16px; }
.alert-info    { background: #EEF2FF; border-left: 4px solid #4F46E5; color: #3730A3; }
.alert-success { background: #D1FAE5; border-left: 4px solid #10B981; color: #065F46; }
.alert-warn    { background: #FEF3C7; border-left: 4px solid #F59E0B; color: #92400E; }
.alert-danger  { background: #FEE2E2; border-left: 4px solid #EF4444; color: #991B1B; }

/* ── Email draft box ── */
.email-preview {
    background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 12px;
    padding: 20px; font-family: 'Courier New', monospace; font-size: 13px;
    color: #334155; white-space: pre-wrap; line-height: 1.7;
}

/* ── Empty state ── */
.empty-state { text-align: center; padding: 60px 20px; color: #94A3B8; }
.empty-state h3 { font-size: 20px; color: #CBD5E1; margin-bottom: 8px; }
.empty-state p  { font-size: 14px; }

/* ── Override Streamlit button ── */
div[data-testid="stButton"] > button[kind="primary"] {
    background: linear-gradient(135deg, #4F46E5, #7C3AED);
    border: none; border-radius: 10px; font-weight: 600;
    padding: 10px 24px; box-shadow: 0 4px 12px rgba(79,70,229,0.35);
}
div[data-testid="stButton"] > button[kind="primary"]:hover {
    box-shadow: 0 6px 18px rgba(79,70,229,0.45);
    transform: translateY(-1px);
}
div[data-testid="stButton"] > button[kind="secondary"] {
    border-radius: 10px; font-weight: 500;
}

/* ── Form ── */
div[data-testid="stForm"] {
    background: white; border-radius: 16px; padding: 28px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.07); border: none;
}
div[data-testid="stTextInput"] input,
div[data-testid="stTextArea"] textarea,
div[data-testid="stNumberInput"] input {
    border-radius: 8px; border: 1.5px solid #E2E8F0;
    font-size: 14px; padding: 10px 14px;
}
div[data-testid="stTextInput"] input:focus,
div[data-testid="stTextArea"] textarea:focus {
    border-color: #4F46E5; box-shadow: 0 0 0 3px rgba(79,70,229,0.1);
}

/* ── Download button ── */
div[data-testid="stDownloadButton"] > button {
    border-radius: 10px; font-weight: 600; width: 100%;
    border: 1.5px solid #4F46E5; color: #4F46E5;
}
div[data-testid="stDownloadButton"] > button:hover {
    background: #EEF2FF;
}

/* ── Metrics ── */
div[data-testid="metric-container"] {
    background: white; border-radius: 12px; padding: 16px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.07);
}

/* ── Expander ── */
details { border-radius: 12px !important; border: 1px solid #E2E8F0 !important; }
details summary { font-weight: 600; font-size: 14px; padding: 14px 18px !important; }
</style>
""", unsafe_allow_html=True)


# ── HTML helpers ──────────────────────────────────────────────────────────────

def page_header(title: str, subtitle: str = "", icon: str = ""):
    icon_html = f'<span style="font-size:28px;margin-right:12px;">{icon}</span>' if icon else ""
    sub_html  = f'<p>{subtitle}</p>' if subtitle else ""
    st.markdown(f"""
<div class="page-header">
  <h1>{icon_html}{title}</h1>
  {sub_html}
</div>""", unsafe_allow_html=True)


def badge(status: str) -> str:
    bg, color, icon = BADGE.get(status, ("#F1F5F9", "#475569", "⚪"))
    label = status.replace("_", " ").upper()
    return f'<span class="badge" style="background:{bg};color:{color};">{icon} {label}</span>'


def stat_row(total: int, approved: int, in_review: int, drafting: int):
    st.markdown(f"""
<div class="stat-row">
  <div class="stat-card">
    <div class="stat-number">{total}</div>
    <div class="stat-label">Total Documents</div>
  </div>
  <div class="stat-card" style="border-top-color:#10B981;">
    <div class="stat-number" style="color:#10B981;">{approved}</div>
    <div class="stat-label">Approved</div>
  </div>
  <div class="stat-card" style="border-top-color:#F59E0B;">
    <div class="stat-number" style="color:#F59E0B;">{in_review}</div>
    <div class="stat-label">In Review</div>
  </div>
  <div class="stat-card" style="border-top-color:#94A3B8;">
    <div class="stat-number" style="color:#94A3B8;">{drafting}</div>
    <div class="stat-label">Drafting</div>
  </div>
</div>""", unsafe_allow_html=True)


def steps_indicator(current: str):
    """Horizontal step progress bar for the Process page."""
    steps = [
        ("📥", "Ingest",    ["ingest", "analyzing"]),
        ("🔍", "Analyze",   ["detect_gaps", "generate_fills"]),
        ("✏️", "Content",  ["content_review"]),
        ("🏗️", "Assemble", ["assemble"]),
        ("👁️", "Preview",  ["preview"]),
        ("📧", "Email",    ["email_gate", "send_email", "done"]),
    ]

    def _state(tags):
        idx_cur = next((i for i, (_, _, t) in enumerate(steps) if current in t), -1)
        idx_this = next((i for i, (_, _, t) in enumerate(steps) if tags == t), -1)
        if idx_this < idx_cur:   return "done"
        if idx_this == idx_cur:  return "active"
        return "pending"

    parts = ['<div class="steps-wrap">']
    for i, (icon, label, tags) in enumerate(steps):
        st = _state(tags)
        parts.append(f'''
<div class="step-item">
  <div class="step-circle {st}">{icon if st != "done" else "✓"}</div>
  <div class="step-lbl {st}">{label}</div>
</div>''')
        if i < len(steps) - 1:
            line_cls = "done" if _state(tags) == "done" else ""
            parts.append(f'<div class="step-line {line_cls}"></div>')
    parts.append('</div>')
    import streamlit as _st
    _st.markdown("".join(parts), unsafe_allow_html=True)


def section_title(text: str):
    st.markdown(f'<div class="section-title">{text}</div>', unsafe_allow_html=True)


def alert(text: str, kind: str = "info"):
    st.markdown(f'<div class="alert alert-{kind}">{text}</div>', unsafe_allow_html=True)


def empty_state(title: str, body: str = ""):
    st.markdown(f"""
<div class="empty-state">
  <h3>{title}</h3>
  {"<p>" + body + "</p>" if body else ""}
</div>""", unsafe_allow_html=True)


def doc_card_html(university: str, program: str, num_semesters: int, version: int,
                  created: str, state: str) -> str:
    b = badge(state)
    sem_label = f"{num_semesters} Semester(s)" if num_semesters > 1 else "1 Semester"
    return f"""
<div class="doc-card">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;">
    <div>
      <h3>{university.upper()} &nbsp;·&nbsp; {program or "(program auto-detected)"}</h3>
      <p>{sem_label} &nbsp;·&nbsp; Version {version} &nbsp;·&nbsp; {created[:10]}</p>
    </div>
    <div style="margin-top:2px;">{b}</div>
  </div>
</div>"""


def review_card(subject: str, section: str, reason: str, content_preview: str):
    st.markdown(f"""
<div class="review-card">
  <h4>📌 {subject} &nbsp;—&nbsp; <code>{section}</code></h4>
  <div class="reason">Gap reason: {reason}</div>
  <div style="font-size:13px;color:#334155;background:#FFFBEB;border-radius:8px;padding:10px 14px;">
    {content_preview[:300]}{"…" if len(content_preview) > 300 else ""}
  </div>
</div>""", unsafe_allow_html=True)
