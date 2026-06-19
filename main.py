"""CLI entry point for ASDE — run a full generation pipeline headlessly."""
import argparse
import json
import sys
from pathlib import Path
from langgraph.types import Command

from ase.orchestrator.graph import get_graph
from ase.schemas.models import DocumentRecord
from ase.store import db
from ase.config import UPLOADS_DIR


def run(args):
    graph = get_graph()

    doc = DocumentRecord(
        university_id=args.university,
        program=args.program,
        semester=args.semester,
    )
    db.save_doc(doc)

    initial = {
        "doc_id": doc.doc_id,
        "university_id": args.university,
        "template_path": args.template,
        "syllabus_path": args.syllabus,
        "custom_instructions": args.instructions or "",
        "program": args.program,
        "semester": args.semester,
        "blueprint": None, "content_model": None,
        "clarification_answers": {}, "ref_decision": None,
        "generated": False, "docx_path": None,
        "qa_report": None, "generation_report": {},
        "error": None,
    }

    config = {"configurable": {"thread_id": doc.doc_id}}
    print(f"[ASDE] Starting — doc_id: {doc.doc_id}")

    # Run until first interrupt or completion
    graph.invoke(initial, config)

    # Interactive clarification loop
    while True:
        state = graph.get_state(config)
        if not state.next:
            break

        interrupt_val = None
        for task in state.tasks:
            if hasattr(task, "interrupts") and task.interrupts:
                interrupt_val = task.interrupts[0].value
                break

        if not interrupt_val:
            break

        if interrupt_val.get("type") == "questions":
            print("\n[ASDE] Clarification required:")
            answers = {}
            for q in interrupt_val["questions"]:
                print(f"\n  {q['question']}")
                for i, opt in enumerate(q["options"], 1):
                    print(f"    {i}. {opt}")
                choice = input("  Your choice (number): ").strip()
                try:
                    answers[q["question"]] = q["options"][int(choice) - 1]
                except (ValueError, IndexError):
                    answers[q["question"]] = q["options"][0]
            graph.invoke(Command(resume=answers), config)

        elif interrupt_val.get("type") == "approval":
            print("\n[ASDE] Document ready for review.")
            print(f"  DOCX: {interrupt_val.get('docx_path')}")
            qa = interrupt_val.get("qa_report", {})
            print(f"  QA Score: {qa.get('score', 0):.0%} ({qa.get('status')})")
            decision = input("  Decision (approve/reject/changes): ").strip().lower()
            notes = input("  Notes (optional): ").strip()
            reviewer = input("  Your name: ").strip() or "cli-user"

            if decision == "approve":
                from ase.approval.workflow import approve as do_approve
                do_approve(doc.doc_id, reviewer, notes)
            elif decision == "changes":
                from ase.approval.workflow import request_changes as do_req
                do_req(doc.doc_id, reviewer, notes)
            else:
                from ase.approval.workflow import reject as do_reject
                do_reject(doc.doc_id, reviewer, notes)

            graph.invoke(Command(resume={"decision": decision, "reviewer": reviewer, "notes": notes}), config)
        else:
            break

    final = db.load_doc(doc.doc_id)
    print(f"\n[ASDE] Done — State: {final.state}")
    ver = next((v for v in reversed(final.versions) if v.docx_path), None)
    if ver:
        print(f"[ASDE] Output: {ver.docx_path}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="ASDE — Academic Syllabus Document Engine")
    parser.add_argument("--template", required=True, help="Path to university template DOCX")
    parser.add_argument("--syllabus", required=True, help="Path to NIAT syllabus DOCX/PDF")
    parser.add_argument("--university", required=True, help="University ID slug (e.g. adypu)")
    parser.add_argument("--program", default="B.Tech", help="Program name")
    parser.add_argument("--semester", type=int, default=1, help="Semester number")
    parser.add_argument("--instructions", default="", help="Custom instructions/context")
    args = parser.parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
