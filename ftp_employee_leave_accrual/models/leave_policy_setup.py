# -*- coding: utf-8 -*-
"""Build (or adopt) the time off types and accrual plans the policy needs.

Everything here is get-or-create: run it twice and nothing is duplicated. The
accrual itself is left entirely to Odoo -- this only writes the plan
configuration that makes Odoo accrue 1 day and 0.5 day a month and roll over
on 1 April. Nothing in this module ever adds days to an allocation by hand.
"""
import logging

from odoo import _

_logger = logging.getLogger(__name__)

CASUAL_LEAVE_NAME = 'Casual Leave'
SICK_LEAVE_NAME = 'Sick Leave'
CASUAL_PLAN_NAME = 'Casual Leave Monthly Accrual'
SICK_PLAN_NAME = 'Sick Leave Monthly Accrual'
MATERNITY_LEAVE_NAME = 'Maternity Leave'
PATERNITY_LEAVE_NAME = 'Paternity Leave'

# Financial year rollover.
CARRYOVER_MONTH = '4'
CARRYOVER_DAY = '1'


def _find_leave_type(env, name, company, company_only=False):
    """Match on name within the company, or a type shared by all companies.

    ``company_only`` skips the shared types. Maternity and Paternity need it:
    Odoo ships a dozen localisation types with those exact names and no
    company, and adopting a Belgian or Indonesian one would quietly attach
    this policy to someone else's rules.
    """
    companies = [company.id] if company_only else [company.id, False]
    return env['hr.leave.type'].with_context(active_test=False).search([
        ('name', '=ilike', name),
        ('company_id', 'in', companies),
    ], limit=1)


def _get_or_create_leave_type(env, name, company, company_only=False,
                              requires_allocation=True):
    existing = _find_leave_type(env, name, company, company_only=company_only)
    if existing:
        _logger.info("Leave policy: reusing existing time off type %r", name)
        return existing
    _logger.info("Leave policy: creating time off type %r for %s", name, company.name)
    return env['hr.leave.type'].create({
        'name': name,
        'company_id': company.id,
        'requires_allocation': requires_allocation,
        'allocation_validation_type': 'hr',
        'leave_validation_type': 'hr',
    })


def _get_or_create_plan(env, name, company, leave_type, added_value, carry_over,
                        max_carryover=0.0):
    """One monthly milestone, rolling over on 1 April.

    ``carry_over`` False means the balance is lost at rollover (sick leave);
    True carries it, capped at ``max_carryover`` when that is set.
    """
    Plan = env['hr.leave.accrual.plan']
    existing = Plan.with_context(active_test=False).search([
        ('name', '=ilike', name),
        ('company_id', 'in', [company.id, False]),
    ], limit=1)
    if existing:
        _logger.info("Leave policy: reusing existing accrual plan %r", name)
        return existing

    _logger.info("Leave policy: creating accrual plan %r for %s", name, company.name)
    plan = Plan.create({
        'name': name,
        'company_id': company.id,
        'time_off_type_id': leave_type.id,
        'transition_mode': 'immediately',
        'accrued_gain_time': 'end',
        # Roll over on the financial year boundary, not the calendar one.
        'can_be_carryover': carry_over,
        'carryover_date': 'other',
        'carryover_month': CARRYOVER_MONTH,
        'carryover_day': CARRYOVER_DAY,
    })
    level_vals = {
        'accrual_plan_id': plan.id,
        'start_count': 0,
        'start_type': 'day',
        'frequency': 'monthly',
        'first_day': '1',
        'added_value': added_value,
        'added_value_type': 'day',
        'action_with_unused_accruals': 'all' if carry_over else 'lost',
    }
    if carry_over and max_carryover:
        level_vals.update({
            'carryover_options': 'limited',
            'postpone_max_days': int(max_carryover),
        })
    env['hr.leave.accrual.level'].create(level_vals)
    return plan


def _sync_plan_with_settings(plan, added_value, carry_over, max_carryover=0.0):
    """Push the configured numbers onto a plan that already exists.

    Without this the settings would only bite on a fresh database: the days
    per month and the carry-forward cap are written when the plan is created,
    so an existing plan would keep whatever it was built with and the
    configuration would be decorative.
    """
    level = plan.level_ids[:1]
    if not level:
        return
    values = {'added_value': added_value}
    if carry_over and max_carryover:
        values.update({'carryover_options': 'limited',
                       'postpone_max_days': int(max_carryover)})
    elif carry_over:
        values['carryover_options'] = 'unlimited'
    level.write(values)
    plan.write({
        'can_be_carryover': carry_over,
        'carryover_date': 'other',
        'carryover_month': CARRYOVER_MONTH,
        'carryover_day': CARRYOVER_DAY,
    })


def setup_leave_policy(env, company):
    """Wire up one company's policy, reusing whatever is already there."""
    casual_type = _get_or_create_leave_type(env, CASUAL_LEAVE_NAME, company)
    sick_type = _get_or_create_leave_type(env, SICK_LEAVE_NAME, company)

    casual_days = company.ftp_casual_monthly_accrual or 1.0
    sick_days = company.ftp_sick_monthly_accrual or 0.5
    max_carry = company.ftp_casual_max_carryover or 0.0

    casual_plan = _get_or_create_plan(
        env, CASUAL_PLAN_NAME, company, casual_type, casual_days,
        carry_over=True, max_carryover=max_carry)
    sick_plan = _get_or_create_plan(
        env, SICK_PLAN_NAME, company, sick_type, sick_days, carry_over=False)

    # Re-apply the settings so an existing plan follows a changed policy.
    _sync_plan_with_settings(casual_plan, casual_days, True, max_carry)
    _sync_plan_with_settings(sick_plan, sick_days, False)

    # Granted on the event, not accrued, so no allocation is required. The
    # two-year service rule and the day limits are enforced on the request.
    maternity_type = _get_or_create_leave_type(
        env, MATERNITY_LEAVE_NAME, company, company_only=True,
        requires_allocation=False)
    paternity_type = _get_or_create_leave_type(
        env, PATERNITY_LEAVE_NAME, company, company_only=True,
        requires_allocation=False)

    values = {
        'ftp_casual_leave_type_id': casual_type.id,
        'ftp_sick_leave_type_id': sick_type.id,
        'ftp_maternity_leave_type_id': maternity_type.id,
        'ftp_paternity_leave_type_id': paternity_type.id,
        'ftp_casual_accrual_plan_id': casual_plan.id,
        'ftp_sick_accrual_plan_id': sick_plan.id,
    }
    if not company.ftp_eligible_contract_type_ids:
        # "Confirmed" is whatever this database calls a settled employee. Both
        # of the obvious candidates are ticked by default; Probation, Intern
        # and Consultant are deliberately left out.
        confirmed = env['hr.contract.type'].browse([
            ref for ref in (
                _safe_ref(env, 'hr.contract_type_permanent'),
                _safe_ref(env, 'hr.contract_type_full_time'),
            ) if ref
        ])
        if confirmed:
            values['ftp_eligible_contract_type_ids'] = [(6, 0, confirmed.ids)]
    company.write(values)
    return casual_plan, sick_plan


def _safe_ref(env, xmlid):
    record = env.ref(xmlid, raise_if_not_found=False)
    return record.id if record else None
