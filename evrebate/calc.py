"""Reference calculator for the federal EVAP incentive.

This is the executable specification of the rules file. The consumer/sales/pricing
calculators should reproduce these results; `tests/test_calc.py` pins them.

All money in CAD. The result includes *why* so sales staff can explain the outcome
and pricers can see how much headroom a configuration has under the cap.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date

from .rules import full_amount


@dataclass
class Transaction:
    fuel_type: str                       # BEV | FCEV | PHEV
    canadian_made: bool
    on_tc_list: bool = True
    is_new: bool = True
    odometer_km: int = 0                 # demonstrators must be < 10,000 km
    transaction_type: str = "purchase"   # purchase | lease
    lease_term_months: int | None = None
    submission_date: date = field(default_factory=date.today)
    # Final-transaction-value components (pre-tax). Excluded items are accepted so the
    # calculator can show the user what did NOT count.
    msrp: float = 0.0                    # after manufacturer/dealer discounts
    options_and_packages: float = 0.0
    accessories: float = 0.0
    dealer_fees: float = 0.0             # doc/admin/market-adjustment fees
    freight_pdi: float = 0.0             # excluded
    extended_warranty: float = 0.0       # excluded
    winter_tires: float = 0.0            # excluded (one set)
    charger: float = 0.0                 # excluded (Level 2 + adapters)
    trade_in: float = 0.0                # excluded
    provincial_incentive: float = 0.0    # excluded from FTV, stacks on top
    recipient_type: str = "individual"   # individual | organization | government | carsharing
    prior_incentives_received: int = 0


@dataclass
class Result:
    eligible: bool
    incentive_cad: float
    full_incentive_cad: float | None
    final_transaction_value: float
    price_cap_cad: float | None
    cap_headroom_cad: float | None       # cap - FTV (negative = over cap); None if exempt
    lease_factor: float
    schedule_year: int
    reasons: list[str]
    warnings: list[str]
    excluded_from_ftv: dict[str, float]
    next_step_down: dict | None          # {"date": ..., "full_incentive_cad": ...}

    def to_dict(self) -> dict:
        return asdict(self)


def final_transaction_value(t: Transaction) -> float:
    return round(t.msrp + t.options_and_packages + t.accessories + t.dealer_fees, 2)


def lease_factor(rules: dict, term_months: int | None) -> tuple[float, str | None]:
    L = rules["lease"]
    if term_months is None:
        return 0.0, "lease term is required for a lease"
    if term_months < L["minimum_term_months"]:
        return 0.0, f"lease term {term_months} mo is below the {L['minimum_term_months']}-month minimum"
    full = L["full_incentive_term_months"]
    return (1.0 if term_months >= full else term_months / full), None


def next_step_down(rules: dict, fuel_type: str, year: int) -> dict | None:
    cur = full_amount(rules, fuel_type, year)
    nxt = full_amount(rules, fuel_type, year + 1)
    if cur is None:
        return None
    if nxt is None:
        return {"date": rules["program"]["program_end"], "full_incentive_cad": 0, "note": "program ends"}
    if nxt < cur:
        return {"date": f"{year + 1}-01-01", "full_incentive_cad": nxt}
    return next_step_down(rules, fuel_type, year + 1)


def compute(t: Transaction, rules: dict) -> Result:
    reasons: list[str] = []
    warnings: list[str] = []
    P = rules["program"]
    year = t.submission_date.year
    full = full_amount(rules, t.fuel_type, year)
    ftv = final_transaction_value(t)
    cap = None if (t.canadian_made and rules["price_cap"]["exempt_if_canadian_made"]) else rules["price_cap"]["max_cad"]
    headroom = None if cap is None else round(cap - ftv, 2)

    excluded = {k: getattr(t, k) for k in
                ("freight_pdi", "extended_warranty", "winter_tires", "charger", "trade_in", "provincial_incentive")
                if getattr(t, k)}

    # --- hard eligibility gates ---
    start = date.fromisoformat(str(P["transactions_eligible_from"]))
    end = date.fromisoformat(str(P["program_end"]))
    if t.submission_date < start:
        reasons.append(f"transaction before program start {start}")
    if t.submission_date > end:
        reasons.append(f"transaction after program end {end}")
    if t.fuel_type not in rules["vehicle_eligibility"]["fuel_types"]:
        reasons.append(f"fuel type {t.fuel_type} not eligible")
    if not t.on_tc_list:
        reasons.append("vehicle/trim is not on the Transport Canada eligible list")
    if not t.is_new:
        reasons.append("only new vehicles are eligible")
    if t.odometer_km >= rules["vehicle_eligibility"]["demonstrator_max_odometer_km"]:
        reasons.append(f"odometer {t.odometer_km} km exceeds demonstrator limit")
    if cap is not None and ftv > cap:
        reasons.append(f"final transaction value ${ftv:,.0f} exceeds ${cap:,.0f} cap (no partial incentive)")
    if full is None:
        reasons.append(f"no incentive schedule for {year}")

    limits = rules["recipient_limits"]
    limit = {"individual": limits["individual_total_over_program"],
             "organization": limits["organization_total_over_program"],
             "government": limits["government_total_over_program"],
             "carsharing": limits["carsharing_per_calendar_year"]}.get(t.recipient_type)
    if limit is not None and t.prior_incentives_received >= limit:
        reasons.append(f"{t.recipient_type} has reached the limit of {limit} incentive(s)")

    factor = 1.0
    if t.transaction_type == "lease":
        factor, err = lease_factor(rules, t.lease_term_months)
        if err:
            reasons.append(err)
    elif t.transaction_type != "purchase":
        reasons.append(f"unknown transaction type {t.transaction_type!r}")

    eligible = not reasons
    amount = round((full or 0) * factor, 2) if eligible else 0.0

    if eligible:
        if cap is None:
            reasons.append("Canadian-made: exempt from the final transaction value cap")
        else:
            reasons.append(f"final transaction value ${ftv:,.0f} is within the ${cap:,.0f} cap")
        if factor < 1.0:
            reasons.append(f"lease of {t.lease_term_months} months prorated at {factor:.4f} of the full amount")
        if t.odometer_km:
            reasons.append(f"demonstrator with {t.odometer_km} km accepted (< 10,000 km)")
    if headroom is not None and 0 <= headroom < 1000:
        warnings.append(f"only ${headroom:,.0f} of headroom under the cap; any added fee or accessory could disqualify")
    if excluded:
        warnings.append("items listed in excluded_from_ftv do not count toward the cap")

    return Result(
        eligible=eligible, incentive_cad=amount, full_incentive_cad=full,
        final_transaction_value=ftv, price_cap_cad=cap, cap_headroom_cad=headroom,
        lease_factor=factor if eligible else 0.0, schedule_year=year,
        reasons=reasons, warnings=warnings, excluded_from_ftv=excluded,
        next_step_down=next_step_down(rules, t.fuel_type, year) if full is not None else None,
    )


def max_eligible_addons(t: Transaction, rules: dict) -> float | None:
    """For pricers/sales: how much can still be added (fees, accessories, options) to this
    configuration before the incentive is lost. None if cap-exempt."""
    r = compute(t, rules)
    return None if r.cap_headroom_cad is None else max(r.cap_headroom_cad, 0.0)
