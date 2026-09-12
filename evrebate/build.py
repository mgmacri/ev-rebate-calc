"""Build the published dataset from raw snapshots + rules, and track changes."""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

from . import __version__
from .normalize import consistency_issues, normalize
from .rules import load_rules
from .sources import tc_evap

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw" / "tc_evap_vehicle_list"
OUT_DIR = ROOT / "data" / "dataset"


def fetch_snapshot(today: date | None = None) -> Path:
    today = today or date.today()
    pages = tc_evap.fetch_all_pages()
    d = RAW_DIR / tc_evap.snapshot_name(today)
    d.mkdir(parents=True, exist_ok=True)
    for i, body in enumerate(pages):
        (d / f"page{i}.html").write_text(body, encoding="utf-8")
    meta = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "url": tc_evap.LIST_URL,
        "pages": len(pages),
        "source_date_modified": tc_evap.parse_date_modified(pages[0]),
        "sha256": hashlib.sha256("".join(pages).encode()).hexdigest(),
    }
    (d / "meta.json").write_text(json.dumps(meta, indent=2))
    return d


def latest_snapshot() -> Path:
    dirs = sorted(p for p in RAW_DIR.iterdir() if p.is_dir()) if RAW_DIR.exists() else []
    if not dirs:
        raise FileNotFoundError("no raw snapshots; run `evrebate fetch` first")
    return dirs[-1]


def load_snapshot(d: Path) -> tuple[list[tc_evap.RawVehicle], dict]:
    pages = [p.read_text(encoding="utf-8") for p in sorted(d.glob("page*.html"))]
    meta = json.loads((d / "meta.json").read_text())
    return tc_evap.parse_all(pages), meta


def _load_previous() -> dict[str, dict]:
    f = OUT_DIR / "vehicles.json"
    if not f.exists():
        return {}
    return {v["id"]: v for v in json.loads(f.read_text())["vehicles"]}


def _diff(prev: dict[str, dict], cur: dict[str, dict]) -> dict:
    added = sorted(set(cur) - set(prev))
    removed = sorted(set(prev) - set(cur))
    changed = []
    for k in sorted(set(cur) & set(prev)):
        a, b = prev[k], cur[k]
        fields = [f for f in ("fuel_type", "canadian_made", "published") if a.get(f) != b.get(f)]
        if fields:
            changed.append({"id": k, "fields": fields, "before": {f: a.get(f) for f in fields},
                            "after": {f: b.get(f) for f in fields}})
    return {"added": added, "removed": removed, "changed": changed}


def build(snapshot: Path | None = None, today: date | None = None) -> dict:
    today = today or date.today()
    rules = load_rules()
    snap = snapshot or latest_snapshot()
    raw, meta = load_snapshot(snap)
    snap_date = date.fromisoformat(snap.name)

    vehicles = [normalize(v, rules, snap_date) for v in raw]
    vehicles.sort(key=lambda v: (v["make"], v["model"], -v["model_year"], v["trim"] or ""))
    ids = [v["id"] for v in vehicles]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise RuntimeError(f"duplicate vehicle ids (trim collision?): {dupes}")

    issues = {v["id"]: iss for v in vehicles if (iss := consistency_issues(v, rules))}

    prev = _load_previous()
    cur = {v["id"]: v for v in vehicles}
    diff = _diff(prev, cur)

    # first_seen / last_seen lineage
    for v in vehicles:
        p = prev.get(v["id"])
        v["first_seen"] = p["first_seen"] if p else snap_date.isoformat()
        v["last_seen"] = snap_date.isoformat()

    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    dataset_meta = {
        "dataset_version": snap_date.isoformat(),
        "generated_at": generated,
        "pipeline_version": __version__,
        "rules_version": rules["rules_version"],
        "source": {"name": "tc_evap_vehicle_list", "url": meta["url"], "fetched_at": meta["fetched_at"],
                   "date_modified": meta.get("source_date_modified"), "sha256": meta["sha256"]},
        "counts": {
            "vehicles": len(vehicles),
            "by_fuel_type": _count(vehicles, "fuel_type"),
            "canadian_made": sum(v["canadian_made"] for v in vehicles),
            "makes": len({v["make"] for v in vehicles}),
        },
        "consistency_issues": issues,
        "changes_since_previous": diff,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "vehicles.json").write_text(json.dumps({"meta": dataset_meta, "vehicles": vehicles}, indent=2))
    (OUT_DIR / "rules.json").write_text(json.dumps(rules, indent=2, default=str))
    (OUT_DIR / "dataset.json").write_text(json.dumps(
        {"meta": dataset_meta, "rules": rules, "vehicles": vehicles}, indent=2, default=str))
    _write_csv(vehicles, OUT_DIR / "vehicles.csv")
    site = ROOT / "site"
    if site.is_dir():  # static calculator reads ./dataset.json
        (site / "dataset.json").write_text((OUT_DIR / "dataset.json").read_text())
    _append_changelog(snap_date, diff, issues, dataset_meta["counts"])
    return dataset_meta


def _count(vs: list[dict], key: str) -> dict:
    out: dict[str, int] = {}
    for v in vs:
        out[v[key]] = out.get(v[key], 0) + 1
    return dict(sorted(out.items()))


def _write_csv(vehicles: list[dict], path: Path) -> None:
    cols = ["id", "model_year", "make", "model", "trim", "fuel_type", "canadian_made", "price_cap_cad",
            "published_year", "incentive_purchase_or_48mo", "incentive_36mo", "incentive_24mo", "incentive_12mo",
            "first_seen", "last_seen", "source_row_hash"]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for v in vehicles:
            p = v["published"]
            w.writerow([v["id"], v["model_year"], v["make"], v["model"], v["trim"] or "", v["fuel_type"],
                        int(v["canadian_made"]), v["price_cap_cad"] if v["price_cap_cad"] is not None else "",
                        p["year"], p["purchase_or_48mo"], p["lease_36mo"], p["lease_24mo"], p["lease_12mo"],
                        v["first_seen"], v["last_seen"], v["source"]["row_hash"]])


def _append_changelog(snap_date: date, diff: dict, issues: dict, counts: dict) -> None:
    f = OUT_DIR / "changelog.json"
    log = json.loads(f.read_text()) if f.exists() else []
    entry = {"dataset_version": snap_date.isoformat(), "counts": counts, **diff,
             "consistency_issues": sorted(issues)}
    log = [e for e in log if e["dataset_version"] != entry["dataset_version"]] + [entry]
    f.write_text(json.dumps(log, indent=2))
