# -*- coding: utf-8 -*-
"""The small extension that puts an advance recovery on a payslip.

Two touch points only, both deliberately narrow:

* ``compute_sheet`` reserves the installments due for the period and writes a
  single SALARY_ADVANCE input line. Reserving is not recovering -- the
  installments stay Pending, so a draft payslip never moves a balance.
* ``write`` watches the state. Finalised (validated/paid) turns reservations
  into recoveries; reset to draft or cancelled hands them back.

Odoo's own hr.salary.attachment records its payment on ``paid`` and never
reverses it. Recovering on validation and reversing on reset is what the spec
asks for, and is why this does not simply reuse that model.
"""
from odoo import Command, _, api, fields, models

SALARY_ADVANCE_CODE = 'SALARY_ADVANCE'
# States in which the money is considered actually taken from the employee.
FINALISED_STATES = ('validated', 'paid')


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    salary_advance_installment_ids = fields.One2many(
        'hr.salary.advance.installment', 'payslip_id',
        string='Salary Advance Installments', readonly=True)
    salary_advance_amount = fields.Monetary(
        string='Salary Advance Recovery', compute='_compute_salary_advance_amount')

    @api.depends('salary_advance_installment_ids.amount',
                 'salary_advance_installment_ids.state')
    def _compute_salary_advance_amount(self):
        for slip in self:
            slip.salary_advance_amount = sum(
                slip.salary_advance_installment_ids.filtered(
                    lambda i: i.state in ('pending', 'deducted')).mapped('amount'))

    # ------------------------------------------------------------------
    # Reservation
    # ------------------------------------------------------------------
    def _salary_advance_due_installments(self):
        """The installments this payslip should take, at most one per advance.

        Guards against the same month being recovered twice: if any other live
        payslip overlapping this period already holds an installment of the
        same advance, that advance is skipped here.
        """
        self.ensure_one()
        Installment = self.env['hr.salary.advance.installment']
        if not self.employee_id or not self.date_to:
            return Installment
        candidates = Installment.search([
            ('employee_id', '=', self.employee_id.id),
            ('state', '=', 'pending'),
            ('already_paid', '=', False),
            ('payslip_id', '=', False),
            ('installment_date', '<=', self.date_to),
            ('advance_id.state', 'in', ('approved', 'running')),
        ], order='advance_id, installment_no')

        due = Installment
        for advance, lines in candidates.grouped('advance_id').items():
            clash = Installment.search_count([
                ('advance_id', '=', advance.id),
                ('payslip_id', '!=', False),
                ('payslip_id', '!=', self.id),
                ('payslip_id.state', '!=', 'cancel'),
                ('payslip_id.date_from', '<=', self.date_to),
                ('payslip_id.date_to', '>=', self.date_from),
                ('state', '!=', 'cancelled'),
            ])
            if clash:
                continue
            # Oldest outstanding installment only: one month, one deduction.
            due |= lines[0]
        return due

    def _salary_advance_sync_inputs(self):
        """Refresh the reservation and the input line on draft payslips."""
        input_type = self.env.ref(
            'ftp_employee_salary_advance.input_type_salary_advance',
            raise_if_not_found=False)
        if not input_type:
            return
        for slip in self.filtered(lambda s: s.state == 'draft'):
            # Start from a clean slate so recomputing cannot stack deductions.
            slip.salary_advance_installment_ids.filtered(
                lambda i: i.state == 'pending')._release()
            due = slip._salary_advance_due_installments()
            if due:
                due._reserve(slip)
            total = sum(due.mapped('amount'))
            existing = slip.input_line_ids.filtered(
                lambda l: l.input_type_id == input_type)
            if total:
                if existing:
                    existing[0].amount = total
                    (existing - existing[0]).unlink()
                else:
                    slip.write({'input_line_ids': [Command.create({
                        'input_type_id': input_type.id,
                        'name': _('Salary Advance Recovery'),
                        'amount': total,
                    })]})
            elif existing:
                slip.write({'input_line_ids': [Command.unlink(i) for i in existing.ids]})

    def compute_sheet(self):
        self._salary_advance_sync_inputs()
        return super().compute_sheet()

    # ------------------------------------------------------------------
    # Finalisation and reversal
    # ------------------------------------------------------------------
    def write(self, vals):
        state = vals.get('state')
        # compute_sheet() re-writes state='draft' on an already-draft payslip,
        # so a write to 'draft' is only a reset when the slip was NOT draft
        # before. Without this, recomputing would release its own reservation.
        previous = {slip.id: slip.state for slip in self} if state else {}
        res = super().write(vals)
        if state in FINALISED_STATES:
            for slip in self:
                slip.salary_advance_installment_ids._mark_deducted()
        elif state == 'cancel':
            for slip in self:
                slip.salary_advance_installment_ids._release()
        elif state == 'draft':
            for slip in self:
                if previous.get(slip.id) != 'draft':
                    slip.salary_advance_installment_ids._release()
        return res

    def action_open_salary_advances(self):
        self.ensure_one()
        advances = self.salary_advance_installment_ids.advance_id
        return {
            'type': 'ir.actions.act_window',
            'name': _('Salary Advances'),
            'res_model': 'hr.salary.advance',
            'view_mode': 'list,form',
            'domain': [('id', 'in', advances.ids)],
        }
