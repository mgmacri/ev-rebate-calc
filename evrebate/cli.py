from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from . import build as B
from .calc import Transaction, compute
from .rules import load_rules


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="evrebate", description="Federal EV rebate dataset pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("fetch", help="download a dated raw snapshot of the Transport Canada list")
    b = sub.add_parser("build", help="build data/dataset from the latest (or given) snapshot")
    b.add_argument("--snapshot", type=Path)
    sub.add_parser("refresh", help="fetch + build; exit 3 if consistency issues were found")
    sub.add_parser("status", help="print dataset meta")

    c = sub.add_parser("calc", help="compute the incentive for one transaction")
    c.add_argument("--fuel", required=True, choices=["BEV", "FCEV", "PHEV"])
    c.add_argument("--msrp", type=float, required=True)
    c.add_argument("--options", type=float, default=0)
    c.add_argument("--accessories", type=float, default=0)
    c.add_argument("--fees", type=float, default=0)
    c.add_argument("--freight-pdi", type=float, default=0)
    c.add_argument("--canadian-made", action="store_true")
    c.add_argument("--lease", type=int, metavar="MONTHS")
    c.add_argument("--date", type=date.fromisoformat, default=date.today())
    c.add_argument("--odometer", type=int, default=0)

    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        d = B.fetch_snapshot()
        print(f"snapshot saved: {d}")
    elif a.cmd == "build":
        meta = B.build(a.snapshot)
        _report(meta)
    elif a.cmd == "refresh":
        B.fetch_snapshot()
        meta = B.build()
        _report(meta)
        if meta["consistency_issues"]:
            return 3
    elif a.cmd == "status":
        f = B.OUT_DIR / "vehicles.json"
        if not f.exists():
            print("no dataset built"); return 1
        _report(json.loads(f.read_text())["meta"])
    elif a.cmd == "calc":
        rules = load_rules()
        t = Transaction(fuel_type=a.fuel, canadian_made=a.canadian_made, msrp=a.msrp,
                        options_and_packages=a.options, accessories=a.accessories, dealer_fees=a.fees,
                        freight_pdi=a.freight_pdi, odometer_km=a.odometer, submission_date=a.date,
                        transaction_type="lease" if a.lease else "purchase", lease_term_months=a.lease)
        print(json.dumps(compute(t, rules).to_dict(), indent=2, default=str))
    return 0


def _report(meta: dict) -> None:
    c = meta["counts"]; ch = meta["changes_since_previous"]
    print(f"dataset {meta['dataset_version']} rules {meta['rules_version']} "
          f"source-modified {meta['source']['date_modified']}")
    print(f"vehicles={c['vehicles']} {c['by_fuel_type']} canadian_made={c['canadian_made']} makes={c['makes']}")
    print(f"changes: +{len(ch['added'])} -{len(ch['removed'])} ~{len(ch['changed'])}")
    for k in ("added", "removed"):
        for i in ch[k]:
            print(f"  {'+' if k == 'added' else '-'} {i}")
    for i in ch["changed"]:
        print(f"  ~ {i['id']}: {i['fields']}")
    if meta["consistency_issues"]:
        print("CONSISTENCY ISSUES (rules file may be stale):", file=sys.stderr)
        for k, v in meta["consistency_issues"].items():
            print(f"  {k}: {v}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
