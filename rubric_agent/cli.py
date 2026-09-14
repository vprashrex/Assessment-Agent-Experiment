"""CLI: strip | run | continue | resume | answer | trend | gt.

  python -m rubric_agent.cli strip --prompt mature.md --out v0.md            # under-specified starting rubric
  python -m rubric_agent.cli run --sheet data.xlsx --context context.md --prompt v0.md \
      --schema score_schema.md --run runs/main --rounds 30 [--k-full]
  python -m rubric_agent.cli continue --run runs/main --comments comments.md --rounds 5   # after human review
  python -m rubric_agent.cli resume --run runs/main          # continue after a crash
  python -m rubric_agent.cli answer --run runs/main "text"   # reply to a parser question
  python -m rubric_agent.cli trend --run runs/main           # trend.png
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from langgraph.types import Command


def _drive(app, payload, run_dir: Path) -> None:
    config = {"configurable": {"thread_id": run_dir.name}, "recursion_limit": 2000}
    for update in app.stream(payload, config=config, stream_mode="updates"):
        for node, out in update.items():
            if node == "__interrupt__":
                print("\nPAUSED — the parser needs an answer:")
                for it in out:
                    print(" ", it.value)
                print(f'\nReply with: python -m rubric_agent.cli answer --run {run_dir} "your answer"')
                return
            tail = out.get("ledger", [])[-1] if isinstance(out, dict) and out.get("ledger") else ""
            print(f"[{node}]" + (f"\n  {tail}" if tail else "") + (f"\n  decision: {out['decision']}" if isinstance(out, dict) and out.get("decision") else ""), flush=True)
    ledger = run_dir / "ledger.md"
    if ledger.exists():
        print("\nLEDGER\n" + ledger.read_text())
    if (run_dir / "HANDOFF.md").exists():
        print(f"handoff -> {run_dir / 'HANDOFF.md'}   best rubric -> {run_dir / 'rubric' / 'best.md'}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="rubric_agent")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("strip", help="make an under-specified starting rubric from a mature one")
    s.add_argument("--prompt", required=True)
    s.add_argument("--out", required=True)

    r = sub.add_parser("run")
    for flag in ("--sheet", "--context", "--prompt", "--schema", "--run"):
        r.add_argument(flag, required=True)
    r.add_argument("--constitution", default=None, help="rubric setup.md is written from (default: --prompt). Pass the mature rubric for a guided run")
    r.add_argument("--rounds", type=int, default=30, help="hard ceiling; the Judge decides success/fail before that")
    r.add_argument("--n", type=int, default=60, help="train rows in the baseline round")
    r.add_argument("--k-full", action="store_true", help="baseline with RUBRIC_K_FULL repeats instead of RUBRIC_K")
    r.add_argument("--max-attachments", type=int, default=None)
    r.add_argument("--review", action="store_true", help="pause for setup.md review")

    c = sub.add_parser("continue", help="feed human review comments and run more rounds from the best version")
    c.add_argument("--run", required=True)
    c.add_argument("--comments", required=True)
    c.add_argument("--rounds", type=int, default=5, help="additional rounds ceiling")

    for name in ("resume", "answer", "trend"):
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
    if a.cmd == "strip":
        from .parser.strip import strip
        out = strip(Path(a.prompt), Path(a.out))
        print("\n".join(f"- removed: {x}" for x in out.removed) + f"\n-> {a.out} ({len(out.rubric_md)} chars)")
        return
    run_dir = Path(a.run)
    if a.cmd == "trend":
        from .loop.plot import plot_trend
        print(f"-> {plot_trend(run_dir)}")
        return
    if a.cmd == "gt":
        from . import gt_check
        gt_check.main(a.mode, run_dir, Path(a.gt), a.score_pattern, a.label_pattern)
        return
    from . import graph
    app = graph.build(run_dir / "checkpoints.sqlite")
    if a.cmd == "run":
        payload = {"run_dir": str(run_dir), "context": Path(a.context).read_text(), "sheet_path": a.sheet, "prompt_path": a.prompt,
                   "schema_path": a.schema, "constitution_path": a.constitution or a.prompt, "max_rounds": a.rounds, "n_random": a.n, "max_attachments": a.max_attachments, "k_full": a.k_full,
                   "review": a.review, "operator_answers": [], "ledger": [], "resume_loop": False, "comments": ""}
    elif a.cmd == "continue":
        versions = json.loads((run_dir / "versions.json").read_text())
        done = max(v["round"] for v in versions.values())
        payload = {"comments": Path(a.comments).read_text(), "resume_loop": True, "max_rounds": done + a.rounds,
                   "stop": False, "stop_reason": "", "consecutive_fail": 0, "needs_input": []}
        (run_dir / "ledger.md").open("a").write(f"HUMAN: comments received, continuing from best for up to {a.rounds} more rounds\n")
    elif a.cmd == "resume":
        payload = None
    else:
        payload = Command(resume=a.text)
    _drive(app, payload, run_dir)


if __name__ == "__main__":
    main(sys.argv[1:])
