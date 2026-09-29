# -*- coding: utf-8 -*-
"""Project the year's pay, work out the tax, spread what is left.

Two things are done differently from l10n_in_hr_payroll's TDS wizard, both
deliberate:

* **Gross, not net.** The wizard projects annual income as net wage x 12. Net
  is already after PF, PT and TDS itself, so it understates taxable pay and
  gets worse every time it is re-run. Tax is charged on gross salary, so gross
  is what is projected here.

* **Remaining months, not twelve.** The wizard always divides the year's tax
  by 12. Run it in September and the employee under-pays for the rest of the
  year. Here the tax already deducted this financial year is netted off and
  the balance is spread over the months that are left, so starting late, a
  pay rise or a missed month all self-correct on the next run.
"""
import logging

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models

from .tds_slabs import annual_tax_on, standard_deduction

_logger = logging.getLogger(__name__)

# Indian financial year: 1 April to 31 March.
FY_START_MONTH = 4


class HrVersion(models.Model):
    _inherit = 'hr.version'

    ftp_tds_auto = fields.Boolean(
        string='Automatic TDS', default=True,
        groups='hr_payroll.group_hr_payroll_user', tracking=True,
        help="Work out TDS every month and write it to the TDS Deduction "
             "field. Switch off for anyone on the old regime or with a figure "
             "agreed outside Odoo, and their TDS is left exactly as typed.")

    # ------------------------------------------------------------------
    # Financial year helpers
    # ------------------------------------------------------------------
    @api.model
    def _ftp_financial_year(self, on_date):
        """(start, end) of the Indian financial year containing on_date."""
        year = on_date.year if on_date.month >= FY_START_MONTH else on_date.year - 1
        start = fields.Date.to_date('%s-04-01' % year)
        return start, start + relativedelta(years=1, days=-1)

    @api.model
    def _ftp_months_remaining(self, on_date):
        """Months left in the financial year, counting the current one."""
        start, _end = self._ftp_financial_year(on_date)
        elapsed = (on_date.year - start.year) * 12 + (on_date.month - start.month)
        return max(12 - elapsed, 1)

    # ------------------------------------------------------------------
    # Projection
    # ------------------------------------------------------------------
    def _ftp_payslips_this_year(self, on_date):
        self.ensure_one()
        start, end = self._ftp_financial_year(on_date)
        return self.env['hr.payslip'].sudo().search([
            ('employee_id', '=', self.employee_id.id),
            ('state', 'in', ('validated', 'paid')),
            ('date_from', '>=', start),
            ('date_to', '<=', end),
        ])

    def _ftp_months_employed(self, on_date):
        """Months of this financial year the employee is on the payroll for."""
        self.ensure_one()
        start, end = self._ftp_financial_year(on_date)
        joined = self.contract_date_start or start
        first = max(joined, start)
        if first > end:
            return 0
        return (end.year - first.year) * 12 + (end.month - first.month) + 1

    def _ftp_tds_breakdown(self, on_date=None):
        """Everything behind the number, so it can be explained and tested."""
        self.ensure_one()
        on_date = on_date or fields.Date.context_today(self)
        slips = self._ftp_payslips_this_year(on_date)
        lines = slips.mapped('line_ids')
        gross_so_far = sum(lines.filtered(lambda l: l.code == 'GROSS').mapped('total'))
        # TDS lines are negative; what matters is how much has been taken.
        tds_so_far = abs(sum(lines.filtered(lambda l: l.code == 'TDS').mapped('total')))

        months_left = self._ftp_months_remaining(on_date)
        monthly_gross = self.l10n_in_gross_salary or 0.0

        # Project the months Odoo has no payslip for, not merely the months
        # still to come. Mid-year, and especially just after a migration, the
        # earlier months may have been paid outside Odoo -- ignoring them would
        # understate the year's income and under-deduct for everybody.
        months_employed = self._ftp_months_employed(on_date)
        months_covered = len({(s.date_from.year, s.date_from.month) for s in slips})
        months_estimated = max(months_employed - months_covered, 0)
        projected_gross = gross_so_far + monthly_gross * months_estimated

        deduction = standard_deduction(self.env, on_date)
        tax = annual_tax_on(self.env, projected_gross - deduction, on_date)
        outstanding = max(tax['total_tax'] - tds_so_far, 0.0)
        monthly = self.currency_id.round(outstanding / months_left) if months_left else 0.0
        return {
            **tax,
            'gross_so_far': gross_so_far,
            'monthly_gross': monthly_gross,
            'months_remaining': months_left,
            'months_employed': months_employed,
            'months_covered_by_payslips': months_covered,
            'months_estimated': months_estimated,
            'projected_gross': projected_gross,
            'standard_deduction': deduction,
            'tds_already_deducted': tds_so_far,
            'outstanding_tax': outstanding,
            'monthly_tds': monthly,
        }

    # ------------------------------------------------------------------
    # Applying it
    # ------------------------------------------------------------------
    def _ftp_eligible_for_auto_tds(self):
        return self.filtered(
            lambda v: v.ftp_tds_auto
            and v.employee_id
            and v.company_id.ftp_tds_auto_enabled
            and v.company_id.country_id.code == 'IN'
            and v.l10n_in_gross_salary > 0
        )

    def _ftp_apply_tds(self, on_date=None):
        """Write the computed figure onto the field the salary rule reads."""
        updated = self.browse()
        for version in self._ftp_eligible_for_auto_tds():
            figures = version._ftp_tds_breakdown(on_date)
            new_value = figures['monthly_tds']
            if version.currency_id.compare_amounts(new_value, version.l10n_in_tds) == 0:
                continue
            version.l10n_in_tds = new_value
            updated |= version
            _logger.info(
                "TDS: %s set to %s/month (projected gross %s, annual tax %s, "
                "%s already deducted, %s months left)",
                version.employee_id.display_name, new_value,
                figures['projected_gross'], figures['total_tax'],
                figures['tds_already_deducted'], figures['months_remaining'])
        return updated

    @api.model
    def _cron_update_tds(self):
        """Monthly sweep over the employment versions currently in force."""
        versions = self.env['hr.employee'].sudo().search([]).version_id
        updated = versions._ftp_apply_tds()
        _logger.info("TDS: updated %s of %s employees", len(updated), len(versions))
        return len(updated)

    def action_ftp_recompute_tds(self):
        """Button: recompute now and say what happened."""
        updated = self._ftp_apply_tds()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success' if updated else 'warning',
                'message': (_("TDS updated for %(count)s employee(s).",
                              count=len(updated)) if updated else
                            _("No change: TDS is already up to date, or "
                              "automatic TDS is switched off.")),
                'sticky': False,
            },
        }


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    ftp_tds_auto = fields.Boolean(
        related='version_id.ftp_tds_auto', readonly=False, inherited=True,
        groups='hr_payroll.group_hr_payroll_user')

    def action_ftp_recompute_tds(self):
        return self.version_id.action_ftp_recompute_tds()
