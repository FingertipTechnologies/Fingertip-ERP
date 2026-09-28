# -*- coding: utf-8 -*-
"""Eligibility and allocation creation.

This module never adds a day of leave to anybody. It creates the accrual
allocation and lets Odoo's own accrual plan do the monthly arithmetic, which
keeps standard Time Off behaviour -- carry-over, caps, reporting -- intact.

Eligibility reuses the employee's Contract Type, which is the field that
already carries Probation and Intern in this database, rather than adding a
second status field that would immediately disagree with it.
"""
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # ------------------------------------------------------------------
    # Eligibility
    # ------------------------------------------------------------------
    def _leave_accrual_is_eligible(self):
        """True when this employee's status is one the company allocates to."""
        self.ensure_one()
        company = self.company_id or self.env.company
        if not company.ftp_leave_accrual_enabled:
            return False
        eligible = company.ftp_eligible_contract_type_ids
        if not eligible:
            return False
        # sudo: contract_type_id is delegated to hr.version and reserved to HR.
        return self.sudo().contract_type_id in eligible

    def _leave_allocation_start_date(self):
        """Confirmation date, then joining date, then today.

        trial_date_end is Odoo's own end-of-trial date, which is the day the
        employee is confirmed -- so leave never starts accruing for a period
        the employee was not yet eligible for.
        """
        self.ensure_one()
        version = self.sudo().version_id
        return (version.trial_date_end
                or version.contract_date_start
                or fields.Date.context_today(self))

    # ------------------------------------------------------------------
    # Allocation
    # ------------------------------------------------------------------
    def _leave_policy_pairs(self, company):
        """The (time off type, accrual plan) pairs this company allocates."""
        return [
            (company.ftp_casual_leave_type_id, company.ftp_casual_accrual_plan_id),
            (company.ftp_sick_leave_type_id, company.ftp_sick_accrual_plan_id),
        ]

    def _ensure_leave_allocations(self):
        """Create whatever accrual allocation is missing. Safe to re-run.

        Returns the allocations created, so callers can report a count.
        """
        Allocation = self.env['hr.leave.allocation'].sudo()
        created = Allocation.browse()
        for employee in self:
            company = employee.company_id or self.env.company
            if not employee._leave_accrual_is_eligible():
                _logger.debug(
                    "Leave accrual: skipping %s, status %r is not eligible",
                    employee.display_name,
                    employee.sudo().contract_type_id.display_name or 'unset')
                continue
            pairs = employee._leave_policy_pairs(company)
            if not all(leave_type and plan for leave_type, plan in pairs):
                _logger.warning(
                    "Leave accrual: %s has no leave policy configured; "
                    "set it under Time Off > Configuration.", company.name)
                continue
            date_from = employee._leave_allocation_start_date()
            for leave_type, plan in pairs:
                existing = Allocation.search([
                    ('employee_id', '=', employee.id),
                    ('holiday_status_id', '=', leave_type.id),
                    ('accrual_plan_id', '=', plan.id),
                    ('state', '!=', 'refuse'),
                ], limit=1)
                if existing:
                    _logger.debug(
                        "Leave accrual: %s already has %s (%s)",
                        employee.display_name, leave_type.name, existing.name)
                    continue
                allocation = Allocation.create({
                    'name': _('%(leave_type)s - %(employee)s',
                              leave_type=leave_type.name,
                              employee=employee.display_name),
                    'employee_id': employee.id,
                    'holiday_status_id': leave_type.id,
                    'accrual_plan_id': plan.id,
                    # Set explicitly: the field defaults to 'regular', and the
                    # duration check rejects a regular allocation of zero days.
                    'allocation_type': 'accrual',
                    'date_from': date_from,
                    'number_of_days': 0.0,
                })
                # Odoo only accrues against approved allocations.
                allocation.action_approve()
                created |= allocation
                _logger.info(
                    "Leave accrual: created %s allocation for %s from %s",
                    leave_type.name, employee.display_name, date_from)
        return created

    @api.model
    def _cron_ensure_leave_allocations(self):
        """Daily sweep: every active eligible employee has both allocations.

        Deliberately does not add leave days -- the accrual plan does that.
        This only makes sure the allocation exists to accrue against.
        """
        employees = self.search([])
        created = employees._ensure_leave_allocations()
        if created:
            _logger.info(
                "Leave accrual: created %s missing allocation(s) across %s employees",
                len(created), len(employees))
        return len(created)

    def action_generate_leave_allocations(self):
        """Server action target: process the selected employees."""
        created = self._ensure_leave_allocations()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success' if created else 'warning',
                'message': (
                    _("%(count)s leave allocation(s) created.", count=len(created))
                    if created else
                    _("Nothing to do: no eligible employee was missing an allocation.")),
                'sticky': False,
            },
        }

    # ------------------------------------------------------------------
    # Triggers
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        employees._ensure_leave_allocations()
        return employees

    def write(self, vals):
        res = super().write(vals)
        # Becoming eligible is what grants the allocation. Losing eligibility
        # deliberately does nothing: history and used leave are preserved, and
        # Odoo's own accrual handles a stopped allocation.
        if 'contract_type_id' in vals:
            self._ensure_leave_allocations()
        return res


class HrVersion(models.Model):
    _inherit = 'hr.version'

    def write(self, vals):
        res = super().write(vals)
        # The status really lives here -- a probation ending writes the
        # version, not the employee -- so catch it on this side too.
        if 'contract_type_id' in vals:
            self.employee_id._ensure_leave_allocations()
        return res
