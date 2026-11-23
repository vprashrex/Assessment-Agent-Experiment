"""python -m refiner --sheet S.xlsx --context C.md --prompt v0.md --run runs/name [options]

Refines an assessment prompt until a scoring model's outputs agree with reference judgements in the sheet.
Rerun the same command to resume. --prepare stops after the setup (columns, layers, attachments) so it can be reviewed.
Every option comes from config.RunConfig: one flag per field, with its default and help text from there."""

from __future__ import annotations

import argparse
import json
from dataclasses import fields
from pathlib import Path

from . import api
from .engine import events
from .config import DEFAULTS, EFFORTS, HELP, REQUIRED, RunConfig
from .engine.loop import NeedsAnswers

_TYPES = {"str": str, "int": int, "float": float}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="refiner", description=__doc__.split("\n\n")[1])
    for f in fields(RunConfig):
        kw: dict = {"help": HELP.get(f.name, "")}
        kw.update({"required": True} if f.name in REQUIRED else {"default": DEFAULTS[f.name]})
        base = str(f.type).replace(" | None", "")
        kw["type"] = _TYPES.get(base, str)
        if f.name in ("effort", "scorer_effort"):
            kw["choices"] = EFFORTS
        p.add_argument(f"--{f.name.replace('_', '-')}", **kw)
    p.add_argument("--prepare", action="store_true", help="only set up the run (parser, layers, attachments) and print it")
    return p


def main() -> None:
    a = vars(parser().parse_args())
    only_prepare = a.pop("prepare")
    cfg = RunConfig(**a)
    task = "prepare" if only_prepare else "refine"
    run_dir = Path(cfg.run)
    events.emit(run_dir, "run.started", task=task, effort=cfg.effort, scorer_effort=cfg.scorer_effort,
                models={"parser": cfg.parser_model, "judge": cfg.judge_model, "generator": cfg.generator_model, "scorer": cfg.scorer})
    try:
        if only_prepare:
            res = api.prepare(cfg)  # emits setup.ready or setup.questions
            print(json.dumps(res, indent=1, ensure_ascii=False))
            events.emit(run_dir, "run.done", task=task, ready=res["ready"])
            return
        best = api.refine(cfg)  # locks the models, then runs the loop
        events.emit(run_dir, "run.done", task=task, best=best)
    except NeedsAnswers as e:
        events.emit(run_dir, "setup.questions", questions=e.questions)
        events.emit(run_dir, "run.done", task=task, ready=False)
        raise SystemExit(str(e))
    except BaseException as e:
        events.emit(run_dir, "run.failed", task=task, error=f"{type(e).__name__}: {e}"[:500])
        raise


if __name__ == "__main__":
    main()
