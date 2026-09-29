# -*- coding: utf-8 -*-
"""The new-regime tax arithmetic, kept deliberately separate.

Every figure comes from Odoo's own ``hr.rule.parameter`` records -- the slab
chart, standard deduction, 87A rebate threshold, surcharge bands and the
marginal-relief table -- so nothing is hardcoded and a new financial year is a
data change, not a code change. The steps mirror l10n_in_hr_payroll's TDS
wizard exactly, so the two agree on any given taxable income.

What this does NOT do is the old regime: no 80C, no HRA exemption, no
declarations. Employees on the old regime should have automatic TDS switched
off on their record and their figure entered by hand.
"""


def annual_tax_on(env, taxable_income, date):
    """Slab tax, less 87A rebate, plus surcharge and 4% cess."""
    parameters = env['hr.rule.parameter']

    def parameter(code):
        return parameters._get_parameter_from_code(code, date=date)

    slabs = parameter('l10n_in_tds_rate_chart')
    surcharge_bands = parameter('l10n_in_surcharge_rate')
    min_income_surcharge = parameter('l10n_in_min_income_surcharge')
    min_income_rebate = parameter('l10n_in_min_income_tax_rebate')

    taxable_income = max(taxable_income, 0.0)

    slab_tax = 0
    for rate, (lower, upper) in slabs:
        if taxable_income <= lower:
            break
        slab_tax += round((min(taxable_income, float(upper)) - lower) * rate)

    # Section 87A, with marginal relief just above the threshold.
    if taxable_income >= min_income_rebate:
        marginal_income = taxable_income - min_income_rebate
        rebate = max(slab_tax - marginal_income, 0)
    else:
        rebate = slab_tax
    tax_after_rebate = slab_tax - rebate

    surcharge = 0.0
    if taxable_income > min_income_surcharge:
        for rate, band in surcharge_bands:
            if taxable_income <= float(band[1]):
                surcharge = tax_after_rebate * rate
                break
        # Marginal relief: the extra tax may not exceed the extra income.
        relief_table = parameter('l10n_in_max_surcharge_tax_rate')
        max_income, max_tax, max_surcharge = 0, 0, 0
        for income, tax, surcharge_rate in relief_table:
            if taxable_income <= income:
                break
            max_income, max_tax, max_surcharge = income, tax, surcharge_rate
        excess_income = taxable_income - max_income
        excess_tax = (tax_after_rebate + surcharge) - (max_tax + max_surcharge)
        if excess_tax - excess_income > 0:
            surcharge = (max_tax + max_surcharge + taxable_income
                         - max_income - tax_after_rebate)

    cess = (tax_after_rebate + surcharge) * 0.04
    return {
        'taxable_income': taxable_income,
        'slab_tax': slab_tax,
        'rebate': rebate,
        'tax_after_rebate': tax_after_rebate,
        'surcharge': surcharge,
        'cess': cess,
        'total_tax': tax_after_rebate + surcharge + cess,
    }


def standard_deduction(env, date):
    return env['hr.rule.parameter']._get_parameter_from_code(
        'l10n_in_standard_deduction', date=date) or 0.0
