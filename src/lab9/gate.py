"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    rows, base_rows = pr.get("rows") or [], base.get("rows") or []
    graded = _graded_metrics(spec, base_rows or rows)

    # 1. Metric values must be real numbers: NaN compares False with every threshold.
    for k, v in (pr.get("metrics") or {}).items():
        if isinstance(v, float) and not math.isfinite(v):
            problems.append(f"metric {k} is {v}: a crashed grader must not look like a pass")

    # 2. Graders must have run cleanly on every row.
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s) in the PR run")
    for r in rows:
        for m in graded:
            v = r.get(m)
            if v is None or not isinstance(v, bool):
                problems.append(f"row {r.get('item_id')}@{r.get('seed')}: {m} is {v!r}, not a graded True/False")
                break

    # 3. Coverage: every (item, seed) exactly once, same set as the baseline, same manifest.
    man, bman = pr.get("manifest") or {}, base.get("manifest") or {}
    want_n = (man.get("items") or 0) * len(man.get("seeds") or [])
    if len(rows) != want_n:
        problems.append(f"{len(rows)} rows, manifest says {man.get('items')} items x {len(man.get('seeds') or [])} seeds = {want_n}")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    dupes = len(keys) - len(set(keys))
    if dupes:
        problems.append(f"{dupes} duplicated (item, seed) row(s)")
    for f in ("items", "seeds"):
        if man.get(f) != bman.get(f):
            problems.append(f"manifest {f} {man.get(f)} differs from the baseline's {bman.get(f)}")
    base_keys = {(r.get("item_id"), r.get("seed")) for r in base_rows}
    if set(keys) != base_keys:
        miss, extra = len(base_keys - set(keys)), len(set(keys) - base_keys)
        problems.append(f"(item, seed) set differs from the baseline: {miss} missing, {extra} extra")

    # 4. Reported metrics must be what the rows say (a hand-edited summary).
    for m, want in _recount(rows, spec, graded).items():
        got = (pr.get("metrics") or {}).get(m)
        if isinstance(got, (int, float)) and not isinstance(got, bool) and math.isfinite(got) \
                and abs(got - want) > 1e-3:
            problems.append(f"metric {m} reported {got} but its rows give {round(want, 4)}")

    # 5. Slice tags come from labels and may not move between runs.
    base_tags = {r.get("item_id"): sorted(r.get("slices") or []) for r in base_rows}
    for r in rows:
        iid = r.get("item_id")
        if iid in base_tags and sorted(r.get("slices") or []) != base_tags[iid]:
            problems.append(f"item {iid} slice tags {r.get('slices')} differ from the baseline's {base_tags[iid]}")
            break

    # 6. Ratchet: on the same eval set a spec may only get stricter.
    if base_spec is not None:
        problems += ratchet_problems(spec, base_spec)
    return problems


def _graded_metrics(spec: dict, rows: list[dict]) -> list[str]:
    """Spec metrics that are scored per row (present in the rows), e.g. pass_rate, secret_leak."""
    present = set().union(*(r.keys() for r in rows)) if rows else set()
    return [m["id"] for m in spec.get("metrics", []) if m["id"] in present]


def _recount(rows: list[dict], spec: dict, graded: list[str]) -> dict[str, float]:
    kinds = {m["id"]: m.get("kind") for m in spec.get("metrics", [])}
    out = {}
    for m in graded:
        vals = [r[m] for r in rows if isinstance(r.get(m), bool)]
        if vals:
            out[m] = float(sum(vals)) if kinds.get(m) == "safety" else sum(vals) / len(vals)
    return out


def _looser(old: dict, new: dict, where: str) -> list[str]:
    """Compare one metric/slice entry: thresholds may only tighten."""
    out = []
    th_o = old.get("threshold", old)
    th_n = new.get("threshold", new)
    for k in ("max", "max_increase"):
        if k in th_o and (k not in th_n or th_n[k] > th_o[k]):
            out.append(f"{where}: {k} loosened {th_o[k]} -> {th_n.get(k)}")
    if "min" in th_o and ("min" not in th_n or th_n["min"] < th_o["min"]):
        out.append(f"{where}: min loosened {th_o['min']} -> {th_n.get('min')}")
    if th_o.get("no_significant_drop") and not th_n.get("no_significant_drop"):
        out.append(f"{where}: no_significant_drop removed")
    if old.get("blocking") and not new.get("blocking"):
        out.append(f"{where}: blocking -> non-blocking")
    return out


def ratchet_problems(spec: dict, base_spec: dict) -> list[str]:
    same_set = (spec.get("eval_set_version") == base_spec.get("eval_set_version")
                or spec.get("eval_set") == base_spec.get("eval_set"))
    if not same_set:
        return []
    out = []
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        out.append("RATCHET eval_set_version renamed without changing the eval set")
    new_m = {m["id"]: m for m in spec.get("metrics", [])}
    for m in base_spec.get("metrics", []):
        if m["id"] not in new_m:
            out.append(f"RATCHET metric {m['id']} removed")
        else:
            out += [f"RATCHET {p}" for p in _looser(m, new_m[m["id"]], f"metric {m['id']}")]
    new_s = {(s["name"], s["metric"]): s for s in spec.get("slices") or []}
    for s in base_spec.get("slices") or []:
        key = (s["name"], s["metric"])
        if key not in new_s:
            out.append(f"RATCHET slice {key[0]}/{key[1]} removed")
        else:
            out += [f"RATCHET {p}" for p in _looser(s, new_s[key], f"slice {key[0]}/{key[1]}")]
    if spec.get("seeds") != base_spec.get("seeds"):
        out.append(f"RATCHET seeds changed {base_spec.get('seeds')} -> {spec.get('seeds')}")
    bo, bn = base_spec.get("bootstrap") or {}, spec.get("bootstrap") or {}
    if bn.get("confidence", 0.95) < bo.get("confidence", 0.95) or bn.get("n_resamples", 1000) < bo.get("n_resamples", 1000):
        out.append("RATCHET bootstrap weakened (confidence / n_resamples)")
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for s in spec.get("slices") or []:
        name, metric = s["name"], s["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note = "ok", ""
        if not a:
            # A slice with no rows cannot vouch for anything: treat as a failure, never as a pass.
            verdict, val = "fail", None
            note = "no rows in slice"
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in s and val < s["min"]:
                verdict = "fail"
            keys = sorted(set(a) & set(b))
            if s.get("no_significant_drop") and keys:
                d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                   n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
        if verdict != "ok" and s.get("blocking"):
            blocked.append(sid)
        label = "ok" if verdict == "ok" else ("BLOCK" if s.get("blocking") else "warn")
        th = {k: s[k] for k in ("min", "no_significant_drop") if k in s}
        lines.append(f"  {sid:<34} {val!s:<8} n={len(a):<3} {json.dumps(th):<36} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
