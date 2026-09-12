"""Deals branch: apply the rebate rules to real prices for every listed vehicle.

A "deal" is one TC-listed trim priced at its published MSRP with no dealer fees or
add-ons (the cleanest possible transaction). It records the incentive for purchase and
each standard lease term, net price, headroom under the cap, and NRCan range/efficiency
so the UI can filter, sort and compare.
"""
from __future__ import annotations

from datetime import date

from .calc import Transaction, compute
from .rules import full_amount

LEASE_TERMS = (48, 36, 24, 12)


def build_deal(vehicle: dict, price: dict | None, spec: dict | None, rules: dict, today: date) -> dict:
    d = {
        "id": vehicle["id"],
        "model_year": vehicle["model_year"], "make": vehicle["make"], "model": vehicle["model"],
        "trim": vehicle["trim"], "fuel_type": vehicle["fuel_type"], "canadian_made": vehicle["canadian_made"],
        "price": None, "rebate": None, "spec": None,
    }
    if spec:
        d["spec"] = {k: spec.get(k) for k in ("vehicle_class", "range_km", "total_range_km", "combined_kwh_100km",
                                                "combined_le_100km", "gas_combined_l_100km", "motor_kw",
                                                "recharge_h", "match_confidence")}
        d["spec"]["nrcan_model"] = spec.get("model")
        d["spec"]["nrcan_model_year"] = spec.get("model_year")
    if not price or price["msrp_cad"] is None:
        d["price"] = None if not price else {k: price[k] for k in ("source_url", "as_of", "confidence", "notes")} | {"msrp_cad": None}
        return d
    msrp, freight = price["msrp_cad"], price["freight_pdi_cad"]
    t = Transaction(fuel_type=vehicle["fuel_type"], canadian_made=vehicle["canadian_made"], msrp=msrp,
                    freight_pdi=freight or 0, submission_date=today)
    r = compute(t, rules)
    leases = {}
    for m in LEASE_TERMS:
        lr = compute(Transaction(**{**t.__dict__, "transaction_type": "lease", "lease_term_months": m}), rules)
        leases[str(m)] = lr.incentive_cad
    full = full_amount(rules, vehicle["fuel_type"], today.year) or 0
    d["price"] = {
        "msrp_cad": msrp, "freight_pdi_cad": freight, "all_in_cad": msrp + (freight or 0),
        "source_url": price["source_url"], "as_of": price["as_of"], "age_days": price["age_days"],
        "confidence": price["confidence"], "stale": price["stale"], "notes": price["notes"],
    }
    d["rebate"] = {
        "eligible": r.eligible, "purchase_cad": r.incentive_cad, "lease_cad": leases,
        "full_cad": full, "final_transaction_value": r.final_transaction_value,
        "cap_cad": r.price_cap_cad, "headroom_cad": r.cap_headroom_cad,
        "net_msrp_cad": msrp - r.incentive_cad, "net_all_in_cad": msrp + (freight or 0) - r.incentive_cad,
        "rebate_pct_of_msrp": round(100 * r.incentive_cad / msrp, 2) if msrp else None,
        "reasons": r.reasons, "next_step_down": r.next_step_down,
    }
    rng = (d["spec"] or {}).get("range_km")
    if rng and r.eligible:
        d["rebate"]["net_cad_per_km_range"] = round(d["rebate"]["net_msrp_cad"] / rng, 2)
    return d


def summarize(deals: list[dict]) -> dict:
    priced = [d for d in deals if d["price"] and d["price"]["msrp_cad"]]
    elig = [d for d in priced if d["rebate"]["eligible"]]
    return {
        "vehicles": len(deals), "priced": len(priced), "eligible_at_msrp": len(elig),
        "unpriced": sorted(d["id"] for d in deals if not (d["price"] and d["price"]["msrp_cad"])),
        "stale_prices": sorted(d["id"] for d in priced if d["price"]["stale"]),
        "with_spec": sum(1 for d in deals if d["spec"]),
        "cheapest_net": min((d["rebate"]["net_msrp_cad"], d["id"]) for d in elig) if elig else None,
    }
