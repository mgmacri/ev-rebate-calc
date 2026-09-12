from datetime import date
import pytest
from evrebate.calc import Transaction, compute, max_eligible_addons
from evrebate.rules import load_rules

R = load_rules()
D = date(2026, 9, 12)


def tx(**kw):
    base = dict(fuel_type="BEV", canadian_made=False, msrp=45000, submission_date=D)
    base.update(kw)
    return Transaction(**base)


def test_bev_purchase_under_cap():
    r = compute(tx(), R)
    assert r.eligible and r.incentive_cad == 5000 and r.cap_headroom_cad == 5000


def test_phev_purchase():
    assert compute(tx(fuel_type="PHEV"), R).incentive_cad == 2500


def test_cap_is_inclusive_and_has_no_partial():
    assert compute(tx(msrp=50000), R).eligible
    r = compute(tx(msrp=50000.01), R)
    assert not r.eligible and r.incentive_cad == 0


def test_fees_and_options_count_toward_cap_but_excluded_items_do_not():
    r = compute(tx(msrp=48000, dealer_fees=1500, accessories=600), R)
    assert not r.eligible  # 50,100
    r = compute(tx(msrp=48000, freight_pdi=2200, extended_warranty=3000, charger=900, trade_in=10000), R)
    assert r.eligible and r.final_transaction_value == 48000


def test_canadian_made_has_no_cap():
    r = compute(tx(canadian_made=True, msrp=77790), R)
    assert r.eligible and r.incentive_cad == 5000 and r.price_cap_cad is None


@pytest.mark.parametrize("months,expected", [(48, 5000), (60, 5000), (36, 3750), (24, 2500), (12, 1250), (39, 4062.5)])
def test_lease_proration(months, expected):
    r = compute(tx(transaction_type="lease", lease_term_months=months), R)
    assert r.eligible and r.incentive_cad == expected


def test_lease_below_minimum():
    assert not compute(tx(transaction_type="lease", lease_term_months=11), R).eligible


def test_schedule_steps_down_on_jan_1():
    assert compute(tx(submission_date=date(2026, 12, 31)), R).incentive_cad == 5000
    assert compute(tx(submission_date=date(2027, 1, 1)), R).incentive_cad == 4000
    assert compute(tx(submission_date=date(2030, 6, 1)), R).incentive_cad == 2000
    assert compute(tx(fuel_type="PHEV", submission_date=date(2028, 6, 1)), R).incentive_cad == 1500


def test_next_step_down_hint():
    r = compute(tx(), R)
    assert r.next_step_down == {"date": "2027-01-01", "full_incentive_cad": 4000}


def test_program_window():
    assert not compute(tx(submission_date=date(2026, 2, 15)), R).eligible
    assert compute(tx(submission_date=date(2026, 2, 16)), R).eligible
    assert not compute(tx(submission_date=date(2031, 4, 1)), R).eligible


def test_demonstrator_odometer():
    assert compute(tx(odometer_km=9999), R).eligible
    assert not compute(tx(odometer_km=10000), R).eligible


def test_used_and_off_list():
    assert not compute(tx(is_new=False), R).eligible
    assert not compute(tx(on_tc_list=False), R).eligible


def test_recipient_limits():
    assert not compute(tx(prior_incentives_received=1), R).eligible
    assert compute(tx(recipient_type="organization", prior_incentives_received=9), R).eligible
    assert not compute(tx(recipient_type="organization", prior_incentives_received=10), R).eligible


def test_headroom_for_pricers():
    assert max_eligible_addons(tx(msrp=47250, dealer_fees=750), R) == 2000
    assert max_eligible_addons(tx(canadian_made=True, msrp=90000), R) is None
    assert max_eligible_addons(tx(msrp=51000), R) == 0
