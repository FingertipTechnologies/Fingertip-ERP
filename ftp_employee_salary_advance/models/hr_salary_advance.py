# -*- coding: utf-8 -*-
"""Salary advances, recovered a month at a time through the payslip.

The advance is agreed once and then clawed back in installments. Everything
that matters for payroll hangs off the installment schedule: the payslip
reserves the next due installment, and only a finalised payslip turns that
reservation into a recovery. Nothing here writes to a payslip -- see
hr_payslip.py for the one small extension that does.
"""
from math import ceil

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_round
from odoo.tools.date_utils import start_of

# States in which an advance may still take money off a payslip.
RECOVERABLE_STATES = ('approved', 'running')


class HrSalaryAdvance(models.Model):
    _name = 'hr.salary.advance'
    _description = 'Employee Salary Advance'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'advance_date desc, id desc'

    name = fields.Char(
        string='Reference', required=True, copy=False, readonly=True,
        index='trigram', default=lambda self: _('New'))
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, tracking=True,
        ondelete='restrict', index=True)
    # Odoo 19 has no hr.contract: the contract is the employee's hr.version.
    contract_id = fields.Many2one(
        'hr.version', string='Contract', compute='_compute_contract_id',
        store=True, readonly=False, ondelete='restrict',
        help="The employment version in force when the advance is granted.")
    department_id = fields.Many2one(
        related='employee_id.department_id', store=True, string='Department')
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        compute='_compute_company_id', store=True, readonly=False,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')

    request_date = fields.Date(
        string='Request Date', required=True, tracking=True,
        default=fields.Date.context_today)
    advance_date = fields.Date(
        string='Advance Date', required=True, tracking=True,
        default=fields.Date.context_today,
        help="Date the money is handed over. Recovery starts the month after.")
    advance_amount = fields.Monetary(string='Advance Amount', required=True, tracking=True)
    monthly_installment = fields.Monetary(
        string='Monthly Installment', required=True, tracking=True,
        help="Amount recovered from each payslip. The last installment is "
             "trimmed to whatever is left.")
    number_of_installments = fields.Integer(
        string='Number of Installments', compute='_compute_number_of_installments',
        inverse='_inverse_number_of_installments', store=True, readonly=False,
        help="Derived from the advance and the monthly installment. Type a "
             "number here instead and the monthly installment is worked out "
             "from it.")
    recovered_amount = fields.Monetary(
        string='Recovered Amount', compute='_compute_amounts', store=True, tracking=True)
    remaining_amount = fields.Monetary(
        string='Remaining Amount', compute='_compute_amounts', store=True, tracking=True)
    installment_ids = fields.One2many(
        'hr.salary.advance.installment', 'advance_id', string='Installment Schedule')
    remarks = fields.Text(string='Remarks')

    state = fields.Selection(
        [('draft', 'Draft'),
         ('submitted', 'Submitted'),
         ('approved', 'Approved'),
         ('running', 'Running'),
         ('completed', 'Completed'),
         ('rejected', 'Rejected'),
         ('cancelled', 'Cancelled')],
        string='Status', default='draft', required=True, tracking=True, copy=False)

    approved_by = fields.Many2one('res.users', string='Approved By', readonly=True, copy=False)
    approved_date = fields.Datetime(string='Approved Date', readonly=True, copy=False)
    rejected_by = fields.Many2one('res.users', string='Rejected By', readonly=True, copy=False)
    rejected_date = fields.Datetime(string='Rejected Date', readonly=True, copy=False)
    rejection_reason = fields.Text(string='Rejection Reason', readonly=True, copy=False)
    completion_date = fields.Date(string='Completion Date', readonly=True, copy=False)

    _check_advance_amount = models.Constraint(
        'CHECK(advance_amount > 0)',
        'The advance amount must be greater than zero.')
    _check_monthly_installment = models.Constraint(
        'CHECK(monthly_installment > 0)',
        'The monthly installment must be greater than zero.')

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends('employee_id')
    def _compute_contract_id(self):
        for advance in self:
            # sudo: hr.version is reserved to HR, and an officer raising an
            # advance need not be able to read the contract itself.
            advance.contract_id = advance.employee_id.sudo().version_id

    @api.depends('employee_id')
    def _compute_company_id(self):
        for advance in self:
            advance.company_id = advance.employee_id.company_id or self.env.company

    def _inverse_number_of_installments(self):
        """Typing a number of installments sets the monthly amount to match.

        Rounded *up* to the currency's smallest unit on purpose: rounding down
        would make ceil(advance / monthly) come back one higher than what was
        typed, and the number would flip back on the next recompute. The last
        installment absorbs the few paise this leaves over.
        """
        for advance in self:
            if advance.number_of_installments <= 0 or advance.advance_amount <= 0:
                continue
            rounding = advance.currency_id.rounding or 0.01
            advance.monthly_installment = float_round(
                advance.advance_amount / advance.number_of_installments,
                precision_rounding=rounding, rounding_method='UP')

    @api.depends('advance_amount', 'monthly_installment')
    def _compute_number_of_installments(self):
        for advance in self:
            if advance.advance_amount > 0 and advance.monthly_installment > 0:
                advance.number_of_installments = ceil(
                    advance.advance_amount / advance.monthly_installment)
            else:
                advance.number_of_installments = 0

    @api.depends('advance_amount', 'installment_ids.state', 'installment_ids.amount',
                 'installment_ids.already_paid')
    def _compute_amounts(self):
        for advance in self:
            # An installment counts once, whether payroll took it or somebody
            # ticked it off as settled outside the system.
            recovered = sum(advance.installment_ids.filtered(
                lambda i: i.state == 'deducted' or i.already_paid).mapped('amount'))
            advance.recovered_amount = recovered
            # Never let the display go negative, whatever the schedule says.
            advance.remaining_amount = max(advance.advance_amount - recovered, 0.0)

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------
    @api.constrains('advance_amount', 'monthly_installment')
    def _check_installment_not_larger_than_advance(self):
        for advance in self:
            if advance.currency_id.compare_amounts(
                    advance.monthly_installment, advance.advance_amount) > 0:
                raise ValidationError(_(
                    "The monthly installment (%(installment)s) cannot exceed the "
                    "advance amount (%(advance)s).",
                    installment=advance.monthly_installment,
                    advance=advance.advance_amount))

    @api.constrains('employee_id')
    def _check_employee_has_contract(self):
        for advance in self:
            version = advance.employee_id.sudo().version_id
            if not version or not version.contract_date_start:
                raise ValidationError(_(
                    "%(employee)s has no running contract. Create an employment "
                    "version with a start date before granting an advance.",
                    employee=advance.employee_id.display_name))

    @api.constrains('advance_amount', 'recovered_amount')
    def _check_recovered_not_over_advance(self):
        for advance in self:
            if advance.currency_id.compare_amounts(
                    advance.recovered_amount, advance.advance_amount) > 0:
                raise ValidationError(_(
                    "Recovered amount cannot exceed the advance amount on %s.",
                    advance.display_name))

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                company_id = vals.get('company_id') or self.env.company.id
                vals['name'] = self.env['ir.sequence'].with_company(
                    company_id).next_by_code('hr.salary.advance') or _('New')
        advances = super().create(vals_list)
        # The schedule is the whole point of the record: draw it up straight
        # away rather than making approval the first time anyone sees it.
        advances._generate_installments()
        return advances

    def write(self, vals):
        # The agreed numbers stop being negotiable once somebody approved them.
        locked = {'advance_amount', 'monthly_installment', 'employee_id', 'advance_date'}
        if locked.intersection(vals):
            frozen = self.filtered(lambda a: a.state not in ('draft', 'submitted'))
            if frozen:
                raise UserError(_(
                    "An approved advance cannot be re-priced. Cancel %s and "
                    "raise a new one instead.",
                    ', '.join(frozen.mapped('display_name'))))
        res = super().write(vals)
        if any(field in vals for field in self._SCHEDULE_DRIVERS):
            self._generate_installments()
        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_except_recovery_started(self):
        for advance in self:
            if advance.state not in ('draft', 'cancelled', 'rejected'):
                raise UserError(_(
                    "%s can no longer be deleted: it has been approved. Cancel "
                    "it instead so the history is kept.", advance.display_name))
            if advance.installment_ids.filtered(lambda i: i.state == 'deducted'):
                raise UserError(_(
                    "%s has already recovered money and cannot be deleted.",
                    advance.display_name))

    # ------------------------------------------------------------------
    # Schedule
    # ------------------------------------------------------------------
    # Lines nobody may rewrite: money already taken, or settled by hand.
    def _protected_installments(self):
        return self.installment_ids.filtered(
            lambda i: i.state == 'deducted' or i.already_paid or i.payslip_id)

    def _generate_installments(self):
        """Lay out the schedule, trimming the last line to the balance.

        Rebuilds only the untouched lines. Anything already deducted, reserved
        by a payslip or ticked as already paid is left exactly as it is, and the
        rest of the schedule is laid out after it -- so regenerating can never
        disturb money that has already moved.
        """
        Installment = self.env['hr.salary.advance.installment']
        for advance in self:
            if advance.state in ('completed', 'cancelled', 'rejected'):
                continue
            if advance.advance_amount <= 0 or advance.monthly_installment <= 0:
                continue
            keep = advance._protected_installments()
            # Anchor on the first line already scheduled, so a date somebody
            # moved by hand survives the schedule being redrawn. Read it before
            # the unlink, or there is nothing left to read.
            scheduled = advance.installment_ids.sorted('installment_no')
            first = scheduled[0].installment_date if scheduled else None
            (advance.installment_ids - keep).unlink()
            outstanding = advance.advance_amount - sum(keep.mapped('amount'))
            if advance.currency_id.compare_amounts(outstanding, 0) <= 0:
                continue
            if not first:
                # Recovery starts the month after the money was handed over.
                first = start_of(advance.advance_date + relativedelta(months=1), 'month')
            number = len(keep)
            values = []
            while advance.currency_id.compare_amounts(outstanding, 0) > 0:
                number += 1
                amount = min(advance.monthly_installment, outstanding)
                values.append({
                    'advance_id': advance.id,
                    'installment_no': number,
                    'installment_date': first + relativedelta(months=number - 1),
                    'amount': advance.currency_id.round(amount),
                })
                outstanding -= amount
            Installment.create(values)

    # Any of these changing means the schedule no longer matches the deal.
    _SCHEDULE_DRIVERS = ('advance_amount', 'monthly_installment',
                         'number_of_installments', 'advance_date')

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def action_submit(self):
        for advance in self:
            if advance.state != 'draft':
                raise UserError(_("Only a draft advance can be submitted."))
        self.write({'state': 'submitted'})
        for advance in self:
            advance.message_post(body=_("Advance submitted for approval."))

    def action_approve(self):
        if not self.env.user.has_group('hr.group_hr_manager'):
            raise UserError(_("Only an HR Manager can approve a salary advance."))
        for advance in self:
            if advance.state != 'submitted':
                raise UserError(_("Only a submitted advance can be approved."))
        self.write({
            'state': 'approved',
            'approved_by': self.env.user.id,
            'approved_date': fields.Datetime.now(),
        })
        self._generate_installments()
        for advance in self:
            advance.message_post(body=_(
                "Advance approved: %(count)s installments scheduled.",
                count=len(advance.installment_ids)))

    def action_start_recovery(self):
        for advance in self:
            if advance.state != 'approved':
                raise UserError(_("Only an approved advance can start recovery."))
        self.write({'state': 'running'})
        for advance in self:
            advance.message_post(body=_("Recovery started."))

    def action_reject(self):
        """Open the wizard-less reject dialog: the reason is caught on the form."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reject Salary Advance'),
            'res_model': 'hr.salary.advance.reject',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_advance_id': self.id},
        }

    def _do_reject(self, reason):
        if not self.env.user.has_group('hr.group_hr_manager'):
            raise UserError(_("Only an HR Manager can reject a salary advance."))
        for advance in self:
            if advance.state not in ('draft', 'submitted'):
                raise UserError(_(
                    "%s can no longer be rejected.", advance.display_name))
        self.write({
            'state': 'rejected',
            'rejected_by': self.env.user.id,
            'rejected_date': fields.Datetime.now(),
            'rejection_reason': reason,
        })
        for advance in self:
            advance.message_post(body=_("Advance rejected: %s", reason or _("no reason given")))

    def action_cancel(self):
        for advance in self:
            if advance.currency_id.compare_amounts(advance.recovered_amount, 0) > 0:
                raise UserError(_(
                    "%(advance)s has already recovered %(amount)s and cannot "
                    "be cancelled.",
                    advance=advance.display_name,
                    amount=advance.recovered_amount))
            if advance.state in ('completed', 'cancelled'):
                raise UserError(_("%s is already closed.", advance.display_name))
        self.installment_ids.filtered(lambda i: i.state == 'pending').write({
            'state': 'cancelled', 'payslip_id': False})
        self.write({'state': 'cancelled'})
        for advance in self:
            advance.message_post(body=_("Advance cancelled."))

    def action_reset_to_draft(self):
        for advance in self:
            if advance.state not in ('rejected', 'cancelled'):
                raise UserError(_("Only a rejected or cancelled advance can be reset."))
        self.write({
            'state': 'draft', 'rejected_by': False, 'rejected_date': False,
            'rejection_reason': False,
        })

    # ------------------------------------------------------------------
    # Completion
    # ------------------------------------------------------------------
    def _check_completion(self):
        """Close an advance the moment nothing is left to take."""
        for advance in self:
            if advance.state not in RECOVERABLE_STATES:
                continue
            if advance.currency_id.compare_amounts(advance.remaining_amount, 0) <= 0:
                advance.write({
                    'state': 'completed',
                    'completion_date': fields.Date.context_today(advance),
                })
                advance.installment_ids.filtered(
                    lambda i: i.state == 'pending').write({'state': 'cancelled'})
                advance.message_post(body=_(
                    "Advance fully recovered (%s). Marked completed.",
                    advance.recovered_amount))

    def _reopen_if_outstanding(self):
        """A completed advance that has money owing again goes back to running."""
        for advance in self:
            if advance.state != 'completed':
                continue
            if advance.currency_id.compare_amounts(advance.remaining_amount, 0) > 0:
                advance.write({'state': 'running', 'completion_date': False})
                advance.installment_ids.filtered(
                    lambda i: i.state == 'cancelled' and not i.already_paid
                ).write({'state': 'pending'})
                advance.message_post(body=_(
                    "Balance outstanding again: this advance is back in recovery."))

    def action_open_installments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Installments'),
            'res_model': 'hr.salary.advance.installment',
            'view_mode': 'list,form',
            'domain': [('advance_id', '=', self.id)],
        }


class HrSalaryAdvanceReject(models.TransientModel):
    _name = 'hr.salary.advance.reject'
    _description = 'Reject a Salary Advance'

    advance_id = fields.Many2one('hr.salary.advance', required=True, ondelete='cascade')
    reason = fields.Text(string='Rejection Reason', required=True)

    def action_confirm(self):
        self.ensure_one()
        self.advance_id._do_reject(self.reason)
        return {'type': 'ir.actions.act_window_close'}
