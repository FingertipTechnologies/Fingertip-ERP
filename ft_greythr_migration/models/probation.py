# -*- coding: utf-8 -*-
"""Probation that ends by itself.

A new joiner starts on the Probation contract type and is confirmed six
months later. The confirmation date lives in Odoo's own ``trial_date_end``
field -- it already exists on hr.version and is tracked, it simply is not
shown anywhere -- so this module puts it on the Payroll tab and lets a
nightly cron move anyone whose date has arrived onto Full-Time.
"""
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.tools import format_date

PROBATION_MONTHS = 6

PROBATION_TYPE = 'l10n_in_hr_payroll.l10n_in_contract_type_probation'
CONFIRMED_TYPE = 'hr.contract_type_full_time'


class HrVersion(models.Model):
    _inherit = 'hr.version'

    trial_date_end = fields.Date(
        compute='_compute_trial_date_end', store=True, readonly=False)

    @api.depends('contract_date_start', 'contract_type_id')
    def _compute_trial_date_end(self):
        """Fill the confirmation date for probationers only, and never
        overwrite a date that is already there: HR extends or shortens a
        probation by editing it, and that edit has to survive a later change
        to the contract start date."""
        probation = self.env.ref(PROBATION_TYPE, raise_if_not_found=False)
        for version in self:
            if (probation and version.contract_type_id == probation
                    and version.contract_date_start
                    and not version.trial_date_end):
                version.trial_date_end = (
                    version.contract_date_start
                    + relativedelta(months=PROBATION_MONTHS))
            else:
                # Keep what is on the record. A stored compute has to assign
                # every record, and assigning the current value is how you
                # say "leave this one alone".
                version.trial_date_end = version.trial_date_end


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    @api.model
    def _cron_confirm_probation(self):
        """Move everyone whose probation has run its course onto Full-Time.

        Goes through the employee rather than hr.version so that only the
        current version is touched -- earlier versions keep their history --
        and leaves a chatter note so the change is never a surprise.
        """
        probation = self.env.ref(PROBATION_TYPE, raise_if_not_found=False)
        confirmed = self.env.ref(CONFIRMED_TYPE, raise_if_not_found=False)
        if not probation or not confirmed:
            return 0
        # sudo: contract_type_id and trial_date_end are delegated to hr.version
        # and reserved to HR managers, which the scheduler user need not be.
        employees = self.sudo().search([
            ('contract_type_id', '=', probation.id),
            ('trial_date_end', '!=', False),
            ('trial_date_end', '<=', fields.Date.context_today(self)),
        ])
        for employee in employees:
            ended_on = employee.trial_date_end
            employee.contract_type_id = confirmed
            employee.message_post(body=_(
                "Probation completed on %(date)s. Contract type changed "
                "from %(was)s to %(now)s automatically.",
                date=format_date(self.env, ended_on),
                was=probation.name, now=confirmed.name))
        return len(employees)
