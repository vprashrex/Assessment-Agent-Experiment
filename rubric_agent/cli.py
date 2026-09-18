"""strip | run | continue | resume | answer | trend | contrib | gt

  python -m rubric_agent.cli run --sheet data.xlsx --context context.md --run runs/main [--prompt v0.md] [--schema schema.md]
      [--scorer openai:gpt-4o-mini] [--scorer-params '{"temperature":1}'] [--k 4] [--n 60] [--rounds 30]
  python -m rubric_agent.cli continue --run runs/main --comments comments.md --rounds 5
  python -m rubric_agent.cli resume --run runs/main
  python -m rubric_agent.cli trend --run runs/main
  python -m rubric_agent.cli contrib --run runs/main     # per-metric contribution to the overall std move
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _drive(app, payload, run_dir: Path) -> None:
    from langgraph.types import Command  # noqa: F401

    config = {"configurable": {"thread_id": run_dir.name}, "recursion_limit": 3000}
    for update in app.stream(payload, config=config, stream_mode="updates"):
        for node, out in update.items():
            if node == "__interrupt__":
                print("\nPAUSED — the parser needs an answer:")
                for it in out:
                    print(" ", it.value)
                print(f'\nReply with: python -m rubric_agent.cli answer --run {run_dir} "your answer"')
                return
            tail = out.get("ledger", [])[-1] if isinstance(out, dict) and out.get("ledger") else ""
            print(f"[{node}]" + (f"\n  {tail}" if tail else ""), flush=True)
    if (run_dir / "ledger.md").exists():
        print("\nLEDGER\n" + (run_dir / "ledger.md").read_text())
    if (run_dir / "HANDOFF.md").exists():
        print(f"handoff -> {run_dir / 'HANDOFF.md'}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="rubric_agent")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("strip")
    s.add_argument("--prompt", required=True)
    s.add_argument("--out", required=True)

    r = sub.add_parser("run")
    for flag in ("--sheet", "--context", "--run"):
        r.add_argument(flag, required=True)
    r.add_argument("--prompt", default=None, help="starting rubric; else the Generator drafts v0")
    r.add_argument("--schema", default=None, help="output schema (json or md fence); else the parser proposes one")
    r.add_argument("--scorer", default=None, help="provider:model for the scorer sub-agents")
    r.add_argument("--scorer-params", default=None, help="JSON kwargs for the scorer model")
    r.add_argument("--k", type=int, default=None, help="runs per submission")
    r.add_argument("--n", type=int, default=None, help="subsample size; default whole dataset")
    r.add_argument("--rounds", type=int, default=30, help="hard ceiling")
    r.add_argument("--max-attachments", type=int, default=None)
    r.add_argument("--review", action="store_true")

    c = sub.add_parser("continue")
    c.add_argument("--run", required=True)
    c.add_argument("--comments", required=True)
    c.add_argument("--rounds", type=int, default=5)

    for name in ("resume", "answer", "trend", "contrib"):
        p = sub.add_parser(name)
        p.add_argument("--run", required=True)
        if name == "answer":
            p.add_argument("text")

    g = sub.add_parser("gt")
    g.add_argument("--run", required=True)
    g.add_argument("--gt", required=True)
    g.add_argument("--score-pattern", default="{metric}_score")
    g.add_argument("--label-pattern", default="{metric}")

    a = ap.parse_args(argv)
    for env, val in (("RUBRIC_SCORER", getattr(a, "scorer", None)), ("RUBRIC_SCORER_PARAMS", getattr(a, "scorer_params", None)),
                     ("RUBRIC_K", getattr(a, "k", None))):
        if val is not None:
            os.environ[env] = str(val)

    if a.cmd == "strip":
        from .parser.strip import strip
        out = strip(Path(a.prompt), Path(a.out))
        print("\n".join(f"- removed: {x}" for x in out.removed) + f"\n-> {a.out} ({len(out.rubric_md)} chars)")
        return
    run_dir = Path(a.run)
    if a.cmd == "trend":
        from .loop.plot import plot_all
        print("->", *plot_all(run_dir))
        return
    if a.cmd == "contrib":
        from .core.runio import Run
        from .loop.contrib import report
        run = Run(str(run_dir))
        stats = sorted((run_dir / "stats").glob("round_*.json"))
        n = len(next(iter(run.json(f"stats/{stats[-1].name}", {}).values()))["rows"]) if stats else 0
        md = report(run.json("trend.json", []), run.json("versions.json", {}), run.metrics, n)
        run.write("contributions.md", md)
        print(md + f"\n-> {run_dir / 'contributions.md'}")
        return
    if a.cmd == "gt":
        from . import gt_check
        gt_check.main(run_dir, Path(a.gt), a.score_pattern, a.label_pattern)
        return
    from langgraph.types import Command

    from . import graph
    app = graph.build(run_dir / "checkpoints.sqlite")
    if a.cmd == "run":
        payload = {"run_dir": str(run_dir), "context": Path(a.context).read_text(), "sheet_path": a.sheet, "prompt_path": a.prompt or "",
                   "schema_path": a.schema or "", "max_rounds": a.rounds, "n": a.n, "max_attachments": a.max_attachments, "review": a.review,
                   "operator_answers": [], "ledger": [], "resume_loop": False, "comments": ""}
    elif a.cmd == "continue":
        done = max(v["round"] for v in json.loads((run_dir / "versions.json").read_text()).values())
        payload = {"comments": Path(a.comments).read_text(), "resume_loop": True, "max_rounds": done + a.rounds, "stop": False,
                   "stop_reason": "", "consecutive_fail": 0, "mode": "revise", "needs_input": []}
        (run_dir / "ledger.md").open("a").write(f"HUMAN: comments received, continuing from best for up to {a.rounds} more rounds\n")
    elif a.cmd == "resume":
        payload = None
    else:
        payload = Command(resume=a.text)
    _drive(app, payload, run_dir)


if __name__ == "__main__":
    main(sys.argv[1:])
