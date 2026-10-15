"""python -m refiner --sheet S.xlsx --context C.md --prompt v0.md --run runs/name [options]

Refines an assessment prompt until a scoring model's outputs agree with reference judgements in the sheet.
Rerun the same command to resume. --prepare stops after the setup (columns, layers, attachments) so it can be reviewed.
"""

from __future__ import annotations

import argparse
import json

from . import api, tracing
from .config import DEFAULT_MODEL, RunConfig
from .loop import NeedsAnswers


def main() -> None:
    p = argparse.ArgumentParser(prog="refiner")
    p.add_argument("--sheet", required=True)
    p.add_argument("--sheet-name", default=None)
    p.add_argument("--context", required=True, help="operator notes: which columns are input, which is the reference")
    p.add_argument("--prompt", required=True, help="the prompt in use today (v0)")
    p.add_argument("--schema", default=None, help="optional output schema (JSON)")
    p.add_argument("--run", required=True)
    p.add_argument("--docs-dir", default=None, help="folder of downloaded files for links that cannot be fetched (matched by name)")
    p.add_argument("--model", default=DEFAULT_MODEL, help="parser, judge and generator")
    p.add_argument("--effort", default="high")
    p.add_argument("--mode", default="standard", help="OpenAI reasoning mode (standard | pro)")
    p.add_argument("--scorer", default=None, help="scoring model; defaults to --model")
    p.add_argument("--rounds", type=int, default=8)
    p.add_argument("--patience", type=int, default=4, help="stop after this many rejected rounds in a row")
    p.add_argument("--target", type=float, default=None, help="stop when MAE (or miss rate) reaches this")
    p.add_argument("--n", type=int, default=None, help="use only the first N items")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--prepare", action="store_true", help="only set up the run (parser, layers, attachments) and print it")
    a = vars(p.parse_args())
    only_prepare = a.pop("prepare")
    cfg = RunConfig(**a)
    try:
        if only_prepare:
            print(json.dumps(api.prepare(cfg), indent=1, ensure_ascii=False))
            return
        api.refine(cfg)
    except NeedsAnswers as e:
        raise SystemExit(str(e))
    finally:
        tracing.flush()  # send the last observations before the process exits


if __name__ == "__main__":
    main()
