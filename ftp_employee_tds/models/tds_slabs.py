"""Indian salary-income tax, FY 2023-24 through FY 2026-27.

Sources and scope are documented in ../README.md. Special-rate income is
not supported. Surcharge relief is derived from the applicable slabs, never
from Odoo's outdated hard-coded threshold-tax table.
"""
from odoo.exceptions import ValidationError


def round_statutory_amount(amount):
    """Ignore paise, then round to the nearest Rs 10, with five upwards.

    Sections 288A/288B (1961 Act), continued in section 516 (2025 Act).
    Do not use Python's round(), which rounds exact ties to even.
    """
    return float(((int(max(amount, 0)) + 5) // 10) * 10)


def _rules(date, regime, resident=True, age=0):
    year = date.year - (date.month < 4)
    if year not in (2023, 2024, 2025, 2026):
        raise ValidationError('Automatic TDS supports FY 2023-24 through FY 2026-27. '
                              'Update the tax rules or switch to manual TDS for this year.')
    if regime == 'old':
        exemption = 500000 if resident and age >= 80 else 300000 if resident and age >= 60 else 250000
        return [(exemption, 0), (500000, .05), (1000000, .20), (float('inf'), .30)], 50000, 500000, 12500
    if year >= 2025:
        return [(400000, 0), (800000, .05), (1200000, .10), (1600000, .15),
                (2000000, .20), (2400000, .25), (float('inf'), .30)], 75000, 1200000, 60000
    if year == 2024:
        return [(300000, 0), (700000, .05), (1000000, .10), (1200000, .15),
                (1500000, .20), (float('inf'), .30)], 75000, 700000, 25000
    return [(300000, 0), (600000, .05), (900000, .10), (1200000, .15),
            (1500000, .20), (float('inf'), .30)], 50000, 700000, 25000


def annual_tax_on(env, taxable_income, date, regime='new', resident=True, age=0):
    """Normal salary income only; rebate, marginal relief, surcharge and cess."""
    slabs, _, threshold, rebate_cap = _rules(date, regime, resident, age)
    taxable_income = round_statutory_amount(taxable_income)

    def slab_tax_at(income):
        total, lower = 0.0, 0.0
        for upper, rate in slabs:
            total += max(min(income, upper) - lower, 0) * rate
            lower = upper
        return total

    slab_tax = slab_tax_at(taxable_income)
    rebate = 0.0
    if resident:
        if taxable_income <= threshold:
            rebate = min(slab_tax, rebate_cap)
        elif regime == 'new':
            rebate = max(slab_tax - (taxable_income - threshold), 0)
    tax_after_rebate = slab_tax - rebate
    bands = [(5000000, .10), (10000000, .15), (20000000, .25)]
    if regime == 'old':
        bands.append((50000000, .37))
    rate, boundary, previous_rate = 0, 0, 0
    for lower, next_rate in bands:
        if taxable_income > lower:
            boundary, previous_rate, rate = lower, rate, next_rate
    surcharge = tax_after_rebate * rate
    if rate:
        ceiling = slab_tax_at(boundary) * (1 + previous_rate) + taxable_income - boundary
        surcharge = max(min(surcharge, ceiling - tax_after_rebate), 0)
    cess = (tax_after_rebate + surcharge) * .04
    unrounded_total_tax = tax_after_rebate + surcharge + cess
    return dict(taxable_income=taxable_income, slab_tax=slab_tax, rebate=rebate,
                tax_after_rebate=tax_after_rebate, surcharge=surcharge, cess=cess,
                unrounded_total_tax=unrounded_total_tax,
                total_tax=round_statutory_amount(unrounded_total_tax))


def standard_deduction(env, date, regime='new'):
    return _rules(date, regime)[1]
