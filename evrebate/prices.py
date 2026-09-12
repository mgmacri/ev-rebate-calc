"""Curated Canadian MSRP table: prices/msrp_ca.csv.

There is no open MSRP dataset for Canada, so prices are transcribed from manufacturer
Canadian pricing pages (or dated OEM press releases) with a source URL, as-of date and
confidence on every row. The pipeline flags stale rows so they get re-verified.
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

PRICES_FILE = Path(__file__).resolve().parent.parent / "prices" / "msrp_ca.csv"
STALE_AFTER_DAYS = 90
COLUMNS = ["id", "msrp_cad", "freight_pdi_cad", "source_url", "as_of", "confidence", "notes"]


def load_prices(path: Path | None = None, today: date | None = None) -> dict[str, dict]:
    path = path or PRICES_FILE
    today = today or date.today()
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    with open(path, newline="") as f:
        rdr = csv.DictReader(f)
        missing = [c for c in COLUMNS if c not in (rdr.fieldnames or [])]
        if missing:
            raise ValueError(f"{path} missing columns {missing}")
        for r in rdr:
            r = {k: (v or "").strip() for k, v in r.items()}
            if not r["id"]:
                continue
            msrp = int(float(r["msrp_cad"])) if r["msrp_cad"] else None
            freight = int(float(r["freight_pdi_cad"])) if r["freight_pdi_cad"] else None
            as_of = date.fromisoformat(r["as_of"]) if r["as_of"] else None
            age = (today - as_of).days if as_of else None
            out[r["id"]] = {
                "msrp_cad": msrp, "freight_pdi_cad": freight, "source_url": r["source_url"] or None,
                "as_of": as_of.isoformat() if as_of else None, "age_days": age,
                "confidence": r["confidence"] or ("low" if msrp else None),
                "stale": (age is None or age > STALE_AFTER_DAYS) if msrp else False,
                "notes": r["notes"] or None,
            }
    return out
