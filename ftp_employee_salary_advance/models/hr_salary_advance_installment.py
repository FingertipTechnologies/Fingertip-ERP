# -*- coding: utf-8 -*-
"""One scheduled recovery.

An installment carries its own state so a payslip can *reserve* it while still
in draft without that counting as money recovered. Only ``deducted`` counts
towards the advance's recovered amount, which is what makes a payslip reset
safe: releasing a reservation cannot un-recover something that was never
recovered in the first place.
"""
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class HrSalaryAdvanceInstallment(models.Model):
    _name = 'hr.salary.advance.installment'
    _description = 'Salary Advance Installment'
    _order = 'advance_id, installment_no'

    advance_id = fields.Many2one(
        'hr.salary.advance', string='Salary Advance', required=True,
        ondelete='cascade', index=True)
    employee_id = fields.Many2one(
        related='advance_id.employee_id', store=True, string='Employee', index=True)
    company_id = fields.Many2one(related='advance_id.company_id', store=True)
    currency_id = fields.Many2one(related='advance_id.currency_id')
    installment_no = fields.Integer(string='Installment', required=True)
    installment_date = fields.Date(string='Date', required=True, index=True)
    amount = fields.Monetary(string='Amount', required=True)
    payslip_id = fields.Many2one(
        'hr.payslip', string='Payslip', readonly=True, copy=False,
        ondelete='set null', index=True,
        help="The payslip this installment is reserved on, or was taken by.")
    state = fields.Selection(
        [('pending', 'Pending'),
         ('deducted', 'Deducted'),
         ('paid', 'Paid'),
         ('cancelled', 'Cancelled')],
        string='Status', default='pending', required=True, index=True,
        help="Deducted means payroll took it on a payslip. Paid means it was "
             "settled outside payroll and ticked off by hand.")
    already_paid = fields.Boolean(
        string='Already Paid', default=False, index=True,
        help="Tick when this installment was settled outside payroll -- an "
             "advance part-recovered before it was entered here, or repaid in "
             "cash. It counts towards the recovered amount and payroll will "
             "not deduct it again.")

    _check_amount = models.Constraint(
        'CHECK(amount > 0)', 'An installment amount must be greater than zero.')
    _unique_number = models.Constraint(
        'unique(advance_id, installment_no)',
        'Installment numbers must be unique within one advance.')

    def _display_name_compute(self):
        for line in self:
            line.display_name = '%s / %s' % (line.advance_id.name, line.installment_no)

    @api.depends('advance_id.name', 'installment_no')
    def _compute_display_name(self):
        self._display_name_compute()

    @api.constrains('already_paid', 'state')
    def _check_already_paid(self):
        for line in self:
            if line.already_paid and line.state == 'deducted':
                raise ValidationError(_(
                    "Installment %(no)s was recovered on payslip %(slip)s, so "
                    "it cannot also be marked as already paid.",
                    no=line.installment_no,
                    slip=line.payslip_id.display_name or '-'))

    def _cascade_dates(self):
        """Re-anchor the later installments to a monthly cadence from this one.

        Moving installment 3 to 1 September puts 4 on 1 October, 5 on
        1 November and so on -- the gap is taken from each line's number, not
        from the number of days, so the schedule stays monthly whatever date
        is typed. Earlier lines are left alone, and so is anything already
        deducted, settled by hand or held by a payslip: those dates are facts,
        not plans.
        """
        self.ensure_one()
        if not self.installment_date:
            return
        later = self.advance_id.installment_ids.filtered(
            lambda i: i.installment_no > self.installment_no
            and i.state != 'deducted' and not i.already_paid and not i.payslip_id)
        for line in later:
            shifted = self.installment_date + relativedelta(
                months=line.installment_no - self.installment_no)
            if line.installment_date != shifted:
                line.with_context(ftp_skip_date_cascade=True).installment_date = shifted

    def write(self, vals):
        res = super().write(vals)
        if 'installment_date' in vals and not self.env.context.get('ftp_skip_date_cascade'):
            for line in self:
                line._cascade_dates()
        if 'already_paid' in vals:
            # The Status column has to agree with the toggle, or a settled
            # installment still reads "Pending" and looks unpaid.
            for line in self:
                if line.already_paid and line.state == 'pending':
                    line.state = 'paid'
                elif not line.already_paid and line.state == 'paid':
                    line.state = 'pending'
            for line in self:
                line.advance_id.message_post(body=(
                    _("Installment %(no)s marked as already paid (%(amount)s).",
                      no=line.installment_no, amount=line.amount)
                    if line.already_paid else
                    _("Installment %(no)s is no longer marked as already paid.",
                      no=line.installment_no)))
            # Settling a line by hand can finish the advance, and un-ticking it
            # can bring a finished one back.
            self.advance_id._check_completion()
            self.advance_id._reopen_if_outstanding()
        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_except_deducted(self):
        if self.filtered(lambda i: i.state == 'deducted' or i.already_paid):
            raise UserError(_(
                "An installment that has already been recovered cannot be "
                "deleted. Untick Already Paid first if it was a mistake."))

    # ------------------------------------------------------------------
    # Reservation lifecycle, driven from hr_payslip.py
    # ------------------------------------------------------------------
    def _reserve(self, payslip):
        """Hold these installments for a draft payslip without recovering yet."""
        self.write({'payslip_id': payslip.id})
        for advance in self.advance_id:
            if advance.state == 'approved':
                advance.write({'state': 'running'})
                advance.message_post(body=_(
                    "Recovery started automatically on payslip %s.",
                    payslip.display_name))

    def _release(self):
        """Give the installments back: the payslip was reset or cancelled."""
        released = self.filtered(lambda i: i.state in ('pending', 'deducted'))
        advances = released.advance_id
        released.write({'state': 'pending', 'payslip_id': False})
        # A completed advance that loses a recovery is running again.
        for advance in advances:
            if advance.state == 'completed' and advance.currency_id.compare_amounts(
                    advance.remaining_amount, 0) > 0:
                advance.write({'state': 'running', 'completion_date': False})
                advance.message_post(body=_(
                    "A payslip was reset, so this advance is back in recovery."))

    def _mark_deducted(self):
        """The payslip is finalised: the reservation becomes a real recovery."""
        pending = self.filtered(lambda i: i.state == 'pending' and i.payslip_id)
        if not pending:
            return
        pending.write({'state': 'deducted'})
        for line in pending:
            line.advance_id.message_post(body=_(
                "Installment %(no)s of %(amount)s recovered on payslip %(slip)s.",
                no=line.installment_no, amount=line.amount,
                slip=line.payslip_id.display_name))
        pending.advance_id._check_completion()
