"""The data split: train / test item ids, seeded and stratified by reference scores, made once per run
(setup/split.json). Items are sorted by their references and cut into consecutive blocks; each block deals its items
to train and test in shuffled order (80/20 → blocks of 5: 4 train, 1 test), so both parts span the score range.

The rubric is tuned on train only: scoring, judge notes, the checklist and the gate never see a test item. Test is
scored once, when the run has stopped, so its numbers are out of sample. "100/0" means no holdout."""

from __future__ import annotations

import random
from math import gcd

PARTS = ("train", "test")
FILE = "setup/split.json"


def shares(spec: str) -> tuple[int, int]:
    """"80/20" -> (80, 20). Train must be positive; test may be 0."""
    try:
        a = tuple(int(x) for x in spec.split("/"))
    except ValueError:
        a = ()
    if len(a) != 2 or a[0] <= 0 or a[1] < 0:
        raise ValueError(f"split must be train/test, like 80/20 (got {spec!r})")
    return a  # type: ignore[return-value]


def _ref(it: dict, keys: list[str]) -> tuple[float, ...]:
    out = []
    for k in keys:
        v = (it.get("truths") or {}).get(k, it.get("truth"))
        try:
            out.append(float(v.get("old") if isinstance(v, dict) else v))
        except (TypeError, ValueError, AttributeError):
            out.append(-1.0)
    return tuple(out)


def make(items: list[dict], spec: str, seed: int) -> dict[str, list[str]]:
    """{"train": [ids], "test": [ids]}: deterministic for the same items, spec and seed."""
    s = shares(spec)
    if s[1] == 0:
        return {"train": [it["id"] for it in items], "test": []}
    g = gcd(*s)
    deck = [p for p, k in zip(PARTS, s) for _ in range(k // g)]
    keys = sorted({k for it in items for k in (it.get("truths") or {})}) or ["truth"]
    ordered = sorted(items, key=lambda it: (_ref(it, keys), it["id"]))
    rng, out = random.Random(seed), {p: [] for p in PARTS}
    for i in range(0, len(ordered), len(deck)):
        d = deck[:]
        rng.shuffle(d)
        for it, p in zip(ordered[i:i + len(deck)], d):
            out[p].append(it["id"])
    return out


def part(items: list[dict], ids) -> list[dict]:
    """The items whose id is in `ids`, in their original order."""
    ids = set(ids)
    return [it for it in items if it["id"] in ids]


def filter_refs(refs: dict, ids) -> dict:
    """A references dict (item id -> value) restricted to `ids`."""
    ids = set(ids)
    return {i: v for i, v in refs.items() if i in ids}


def guard(items: list[dict], test_ids) -> None:
    """Refuse to score a test item while refining. The only scoring of test items is the final pass."""
    leaked = sorted({it["id"] for it in items} & set(test_ids))
    if leaked:
        raise AssertionError(f"test items must not be scored during refinement: {leaked[:5]}{'…' if len(leaked) > 5 else ''}")


def read(run) -> dict[str, list[str]]:
    """The run's split, or everything as train when the run predates splits."""
    sp = run.read(FILE)
    if sp is None:
        return {"train": [it["id"] for it in run.read("setup/items.json") or []], "test": []}
    return {"train": list(sp["train"]), "test": list(sp.get("test", []))}
