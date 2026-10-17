"""Compare a run's outputs with the numbers README.md cites (analysis/expected.json).

Usage: python -I scripts/check_numbers.py [repo root] [full|quick]   (quick: historical rows are reported as not run)   -> prints a markdown table, exit 1 if any row mismatches.
A row MATCHES when the reproduced value, rounded the way the README rounds it, equals the README text.
Rows listed under "platform_tolerance" in expected.json (urgent ER head, proxy-label run: they differ between macOS arm64,
where the README was made, and Linux x86_64) also pass as "match (platform tolerance)" when within the stated tolerance.
"""
import json
from decimal import ROUND_HALF_UP, Decimal
import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
MODE = sys.argv[2] if len(sys.argv) > 2 else "full"
EXP = json.loads((ROOT / "analysis" / "expected.json").read_text())
rows = EXP["rows"]
TOL = EXP.get("platform_tolerance", {}).get("rows", {})
cache = {}


def load(f):
    if f not in cache:
        p = ROOT / f
        cache[f] = json.loads(p.read_text()) if p.exists() else None
    return cache[f]


def resolve(doc, key):
    if key.startswith("#"):  # roster counts: #status.alert, #urgent
        parts = key[1:].split(".")
        r = doc["roster"]
        return sum(1 for x in r if (x.get(parts[0]) is True if len(parts) == 1 else x.get(parts[0]) == parts[1]))
    if key.startswith("@c3-"):  # roster tile field
        sid, field = key[1:].split(".", 1)
        return next(x for x in doc["roster"] if x["survivorId"] == sid)[field]
    if key.startswith("fairness.@"):  # fairness.@dimension.group.field[.i]
        dim, rest = key[len("fairness.@"):].split(".", 1)
        rows_ = next(x for x in doc["fairness"]["dimensions"] if x["dimension"] == dim)["rows"]
        row = next(r for r in rows_ if rest.startswith(r["group"] + "."))
        doc, key = row, rest[len(row["group"]) + 1:]
    cur = doc
    for part in key.split(".") if not isinstance(doc, dict) or key not in doc else [key]:
        if isinstance(cur, list):
            cur = cur[int(part)]
        elif part in cur:
            cur = cur[part]
        else:  # keys that contain dots or spaces: greedy match
            raise KeyError(part)
    return cur


def resolve_greedy(doc, key):
    try:
        return resolve(doc, key)
    except (KeyError, StopIteration):
        pass
    cur, rest = doc, key
    while rest:
        if isinstance(cur, list):
            head, _, rest = rest.partition(".")
            cur = cur[int(head)]
            continue
        for k in sorted(cur, key=len, reverse=True):
            if rest == k or rest.startswith(k + "."):
                cur, rest = cur[k], rest[len(k) + 1:]
                break
        else:
            raise KeyError(rest)
    return cur


def r(x, nd=0):
    """Round half up, the way the README rounds (0.085 -> +9 points), not Python's round-half-even."""
    q = Decimal(1).scaleb(-nd)
    return float(Decimal(repr(float(x))).quantize(q, rounding=ROUND_HALF_UP))


def fmt(v, f):
    v = float(v)
    if f == "int": return str(int(r(v)))
    if f == "pct0": return f"{int(r(v * 100))}%"
    if f == "pct1": return f"{r(v * 100, 1)}%"
    if f == "pp0": return f"{'+' if v >= 0 else '-'}{int(abs(r(v * 100)))}"
    if f == "round50": return str(int(r(v / 50) * 50))
    if f == "round10": return str(int(r(v / 10) * 10))
    if f.startswith("f"):
        return f"{r(v, int(f[1:])):.{int(f[1:])}f}"
    raise ValueError(f)


def parse(text, f):
    """README text back to the raw scale (inverse of fmt)."""
    t = text.rstrip("%").lstrip("+")
    v = float(t)
    return v / 100 if f in ("pct0", "pct1", "pp0") else v


def within(label, v, readme, f, doc):
    """Cross-platform tolerance. abs: |raw - README| <= amount. pts: the printed values differ by at most 2 points,
    or (small groups) the implied ER-event counts differ by at most 2 events."""
    t = TOL.get(label)
    if t is None:
        return None
    want = parse(readme, f)
    if t["kind"] == "abs":
        gap = abs(float(v) - want)
        return gap <= t["amount"] + 1e-9, f"{gap:.3g} vs allowed {t['amount']:g}"
    pts = abs(parse(fmt(v, f), f) - want) * 100
    if pts <= 2 + 1e-9:
        return True, f"{pts:g} points"
    if t.get("events_key"):
        n = resolve_greedy(doc, t["events_key"])
        ev = abs(round(float(v) * n) - round(want * n))
        return ev <= 2, f"{pts:g} points = {ev} of {n} ER events"
    return False, f"{pts:g} points > 2"


out, bad, missing = [], 0, 0
tolerated = 0
skipped = 0
for label, f, key, readme, how, scope in rows:
    if scope == "historical" and MODE == "quick":
        out.append((label, f, key, readme, "(quick mode)", "not run")); skipped += 1; continue
    doc = load(f)
    if doc is None:
        out.append((label, f, key, readme, "(file not produced)", "MISSING")); missing += 1; continue
    try:
        v = resolve_greedy(doc, key)
    except Exception as e:  # noqa: BLE001
        out.append((label, f, key, readme, f"(key not found: {e})", "MISSING")); missing += 1; continue
    got = fmt(v, how)
    ok = got == readme
    res = "match" if ok else "MISMATCH"
    if not ok and (w := within(label, v, readme, how, doc)) is not None:
        ok, note = w
        res = f"match (platform tolerance, {note})" if ok else f"MISMATCH ({note})"
        tolerated += ok
    bad += not ok
    out.append((label, f, key, readme, f"{got}  (raw {v})", res))

print("| README number | File | Key | README | Reproduced | Result |\n|---|---|---|---|---|---|")
for r in out:
    print("| " + " | ".join(str(x) for x in r) + " |")
n = len(out)
print(f"\n**{n - bad - missing - skipped}/{n - skipped} match**, {bad} mismatch, {missing} missing" + (f", {skipped} not run (quick)" if skipped else "")
      + (f"; {tolerated} of the matches are within the cross-platform tolerance." if tolerated else "."))
sys.exit(0 if bad == 0 and missing == 0 else 1)
