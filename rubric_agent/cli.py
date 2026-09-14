"""CLI: run | resume | answer | gt.

  python -m rubric_agent.cli run --sheet data.xlsx --context context.md --prompt prompt.md \
      --schema score_schema.md --run runs/main --rounds 8 --budget 40
  python -m rubric_agent.cli resume --run runs/main          # continue after a crash
  python -m rubric_agent.cli answer --run runs/main "text"   # reply to a parser question
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from langgraph.types import Command

from . import graph


def _drive(app, payload, run_dir: Path) -> None:
    config = {"configurable": {"thread_id": run_dir.name}, "recursion_limit": 1000}
    for update in app.stream(payload, config=config, stream_mode="updates"):
        for node, out in update.items():
            if node == "__interrupt__":
                print("\nPAUSED — the parser needs an answer:")
                for it in out:
                    print(" ", it.value)
                print(f'\nReply with: python -m rubric_agent.cli answer --run {run_dir} "your answer"')
                return
            tail = out.get("ledger", [])[-1] if isinstance(out, dict) and out.get("ledger") else ""
            print(f"[{node}]" + (f"\n  {tail}" if tail else ""))
    ledger = run_dir / "ledger.md"
    if ledger.exists():
        print("\nLEDGER\n" + ledger.read_text())
    stop = [l for l in ledger.read_text().splitlines() if l.startswith("STOP:")] if ledger.exists() else []
    if stop:
        print(stop[-1])
    best = run_dir / "rubric" / "best.md"
    if best.exists():
        print(f"best rubric -> {best}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="rubric_agent")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run")
    r.add_argument("--sheet", required=True)
    r.add_argument("--context", required=True)
    r.add_argument("--prompt", required=True)
    r.add_argument("--schema", required=True)
    r.add_argument("--run", required=True)
    r.add_argument("--rounds", type=int, default=30, help="safety ceiling only; the loop stops on plateau, convergence or target")
    r.add_argument("--n", type=int, default=60, help="random rows in the baseline round")
    r.add_argument("--target", type=float, default=0.0, help="success break: stop when best disagree%% <= target; 0 = judge noise floor + margin")
    r.add_argument("--margin", type=float, default=5.0, help="points above the judge noise floor for the derived target")
    r.add_argument("--max-attachments", type=int, default=None)
    r.add_argument("--review", action="store_true", help="pause for setup.md review")

    for name in ("resume", "answer"):
        p = sub.add_parser(name)
        p.add_argument("--run", required=True)
        if name == "answer":
            p.add_argument("text")

    g = sub.add_parser("gt", help="offline ground-truth diagnostics")
    g.add_argument("mode", choices=["preflight", "report"])
    g.add_argument("--run", required=True)
    g.add_argument("--gt", required=True)
    g.add_argument("--score-pattern", default="{metric}_score", help="GT column holding the production score per metric")
    g.add_argument("--label-pattern", default="{metric}", help="GT column holding the human Agree/Disagree per metric")

    a = ap.parse_args(argv)
    run_dir = Path(a.run)
    if a.cmd == "gt":
        from . import gt_check
        gt_check.main(a.mode, run_dir, Path(a.gt), a.score_pattern, a.label_pattern)
        return
    app = graph.build(run_dir / "checkpoints.sqlite")
    if a.cmd == "run":
        payload = {"run_dir": str(run_dir), "context": Path(a.context).read_text(), "sheet_path": a.sheet, "prompt_path": a.prompt,
                   "schema_path": a.schema, "max_rounds": a.rounds, "n_random": a.n, "target": a.target, "margin": a.margin,
                   "max_attachments": a.max_attachments, "review": a.review, "operator_answers": [], "ledger": []}
    elif a.cmd == "resume":
        payload = None
    else:
        payload = Command(resume=a.text)
    _drive(app, payload, run_dir)


if __name__ == "__main__":
    main(sys.argv[1:])
