"""Indian salary-income tax, worked out from a TDS slab set.

The rates live in ``ftp.tds.slab.set`` records (see tds_slab_set.py and
data/tds_slab_set_data.xml); this file holds only the formulas. Sources and
scope are documented in ../README.md. Special-rate income is not supported.
Surcharge relief is derived from the applicable slabs, never from Odoo's
outdated hard-coded threshold-tax table.
"""


def round_statutory_amount(amount):
    """Ignore paise, then round to the nearest Rs 10, with five upwards.

    Sections 288A/288B (1961 Act), continued in section 516 (2025 Act).
    Do not use Python's round(), which rounds exact ties to even.
    """
    return float(((int(max(amount, 0)) + 5) // 10) * 10)


def _slab_set(env, date, regime, company=None, slab_set=None):
    """The slab set to use: an explicit one, else the active set for the date."""
    return slab_set or env['ftp.tds.slab.set']._ftp_get(date, regime, company)


def annual_tax_on(env, taxable_income, date, regime='new', resident=True, age=0,
                  company=None, slab_set=None):
    """Normal salary income only; rebate, marginal relief, surcharge and cess."""
    slab_set = _slab_set(env, date, regime, company, slab_set)
    slabs = slab_set._ftp_brackets(resident, age)
    threshold, rebate_cap = slab_set.rebate_income_limit, slab_set.rebate_max
    taxable_income = round_statutory_amount(taxable_income)

    def slab_tax_at(income):
        total, lower = 0.0, 0.0
        for upper, rate in slabs:
            total += max(min(income, upper) - lower, 0) * rate
            lower = upper
        return total

    slab_tax = slab_tax_at(taxable_income)
    rebate = 0.0
    if resident or not slab_set.rebate_residents_only:
        if taxable_income <= threshold:
            rebate = min(slab_tax, rebate_cap)
        elif slab_set.rebate_marginal_relief:
            rebate = max(slab_tax - (taxable_income - threshold), 0)
    tax_after_rebate = slab_tax - rebate
    bands = slab_set._ftp_surcharge_bands()
    rate, boundary, previous_rate = 0, 0, 0
    for lower, next_rate in bands:
        if taxable_income > lower:
            boundary, previous_rate, rate = lower, rate, next_rate
    surcharge = tax_after_rebate * rate
    if rate:
        ceiling = slab_tax_at(boundary) * (1 + previous_rate) + taxable_income - boundary
        surcharge = max(min(surcharge, ceiling - tax_after_rebate), 0)
    cess = (tax_after_rebate + surcharge) * slab_set.cess_rate / 100
    unrounded_total_tax = tax_after_rebate + surcharge + cess
    return dict(taxable_income=taxable_income, slab_tax=slab_tax, rebate=rebate,
                tax_after_rebate=tax_after_rebate, surcharge=surcharge, cess=cess,
                unrounded_total_tax=unrounded_total_tax,
                total_tax=round_statutory_amount(unrounded_total_tax),
                slab_set_id=slab_set.id, slab_set_name=slab_set.name)


def standard_deduction(env, date, regime='new', company=None, slab_set=None):
    return _slab_set(env, date, regime, company, slab_set).standard_deduction
