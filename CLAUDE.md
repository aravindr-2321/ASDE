# ASDE — Academic Syllabus Document Engine

## Project layout

```
ase/
  config.py            — env, paths, model constants
  schemas/models.py    — all Pydantic v2 models
  store/db.py          — JSON file storage (documents + profiles)
  ingestion/parser.py  — DOCX / PDF → raw dict
  analysis/
    blueprint.py       — Claude: extract TemplateBlueprint from template DOCX
    content.py         — Claude: extract ContentModel from NIAT syllabus
  clarify/gate.py      — Claude: generate questions; scoped memory; interrupt gate
  generate/academic.py — Claude: Bloom-aligned CO/CLO + module refinement
  references/engine.py — Claude: IEEE references with ISBN
  render/docx_builder.py — python-docx: assemble final DOCX from blueprint+content
  qa/validator.py      — structural + content-preservation validation
  approval/workflow.py — state transitions: approve / request_changes / reject
  orchestrator/graph.py — LangGraph StateGraph with two human interrupt gates
app.py                 — Streamlit UI (Library / New Document / Process / Review)
main.py                — CLI interface
```

## Running

```bash
# Install
pip install -r requirements.txt

# Set API key
copy .env.example .env   # then fill ANTHROPIC_API_KEY

# Streamlit UI
streamlit run app.py

# CLI
python main.py --template path/to/template.docx --syllabus path/to/syllabus.pdf \
               --university adypu --program "B.Tech CSE" --semester 1
```

## Key design choices

- **Claude drives all AI tasks**: blueprint extraction, content parsing, CO/CLO generation, references.
- **LangGraph interrupts**: two durable human gates — clarification (questions) and approval (review).
- **Blueprint-driven renderer**: `docx_builder.py` reads blueprint colors/fonts/labels; no hard-coded university values.
- **JSON file store**: `store/documents/{doc_id}/record.json` + `store/profiles/{uid}.json` — no external DB needed.
- **Anti-hallucination**: source text preserved verbatim; generated content tagged and shown in generation report; approval gate is the final guardrail.

## Environment

`ANTHROPIC_API_KEY` — required. Model: `claude-sonnet-4-6`.
