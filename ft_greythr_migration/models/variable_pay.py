from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

# Indian financial year: 1 April of the start year to 31 March of the next, so
# FY 2026 means 2026-04-01 .. 2027-03-31. The quarters follow the FY, not the
# calendar year - Q4 therefore lands in January-March of the FOLLOWING calendar
# year, which is why the offsets below are months from 1 April rather than a
# plain calendar-quarter lookup.
FY_START_MONTH = 4
QUARTER_MONTH_OFFSET = {'q1': 0, 'q2': 3, 'q3': 6, 'q4': 9}

# Other Input code carrying the approved amount onto the payslip. Kept as a
# module constant because the salary rule, the input type and the payslip
# integration all have to agree on it.
VARIABLE_PAY_INPUT_CODE = 'VAR_PAY'

# Fields an approved or paid record may still change. Everything else is frozen
# once approved so the figure a manager signed off cannot move underneath them;
# see _check_locked_fields.
UNLOCKED_AFTER_APPROVAL = {
    'state', 'payslip_id', 'approved_by_id', 'approval_date', 'remarks',
    'message_follower_ids', 'message_ids', 'activity_ids',
    'message_main_attachment_id', 'message_attachment_count',
    'activity_state', 'activity_user_id', 'activity_date_deadline',
    'activity_summary', 'activity_type_id', 'activity_type_icon',
    'activity_exception_decoration', 'activity_exception_icon',
    'write_date', 'write_uid',
}


class HrVariablePay(models.Model):
    """One quarter of performance-based variable pay for one employee.

    The annual target lives on the employment version (Odoo 19's replacement for
    hr.contract); this model turns a quarter of it into an amount somebody has
    approved, and hands that amount to exactly one payslip.
    """
    _name = 'hr.variable.pay'
    _description = 'Quarterly Variable Pay'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'financial_year desc, quarter desc, employee_id'
    _rec_name = 'name'

    name = fields.Char(copy=False, readonly=True, default=lambda self: self.env._('New'))
    employee_id = fields.Many2one(
        'hr.employee', required=True, index=True, ondelete='restrict',
        tracking=True, check_company=True)
    # The version the target was read from, kept so a later salary revision
    # cannot silently restate what a past quarter was measured against.
    version_id = fields.Many2one(
        'hr.version', string='Contract', ondelete='restrict',
        compute='_compute_version_id', store=True, readonly=False,
        check_company=True, help='Employment version supplying the quarterly target.')
    company_id = fields.Many2one(
        'res.company', required=True, index=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')

    financial_year = fields.Integer(
        required=True, index=True, tracking=True,
        default=lambda self: self._default_financial_year(),
        help='Starting calendar year of the Indian financial year: 2026 means FY 2026-27.')
    financial_year_label = fields.Char(
        'FY', compute='_compute_financial_year_label', store=True)
    quarter = fields.Selection(
        [('q1', 'Q1 (Apr-Jun)'), ('q2', 'Q2 (Jul-Sep)'),
         ('q3', 'Q3 (Oct-Dec)'), ('q4', 'Q4 (Jan-Mar)')],
        required=True, default='q1', index=True, tracking=True)
    date_start = fields.Date(
        'Quarter Start', compute='_compute_quarter_dates', store=True, readonly=False)
    date_end = fields.Date(
        'Quarter End', compute='_compute_quarter_dates', store=True, readonly=False)
    # Which payslip period should carry the payout. Defaults to the quarter end
    # but is editable: a quarter closing 30 June is usually paid with July's
    # payroll, and that decision belongs to HR rather than to this module.
    payout_date = fields.Date(
        compute='_compute_payout_date', store=True, readonly=False, tracking=True,
        help='The payslip whose period contains this date picks the amount up.')

    quarterly_target = fields.Monetary(
        compute='_compute_quarterly_target', store=True, readonly=False, tracking=True,
        help='Defaults to the annual variable pay on the contract, divided by four.')
    performance_percentage = fields.Float(
        'Performance %', default=100.0, tracking=True, digits='Payroll Rate')
    amount_computed = fields.Monetary(
        'Calculated Amount', compute='_compute_amount_computed', store=True,
        help='Quarterly target x performance percentage / 100.')
    # An override is a separate stored field rather than an editable computed
    # amount: a computed one is silently overwritten the next time the target or
    # the percentage changes, which on a figure somebody approved is a bug.
    use_override = fields.Boolean(
        'Override Amount', tracking=True,
        help='Pay a manually entered amount instead of the calculated one.')
    amount_override = fields.Monetary('Manual Amount', tracking=True)
    amount_payable = fields.Monetary(
        'Payable Amount', compute='_compute_amount_payable', store=True, tracking=True)

    remarks = fields.Text()
    approved_by_id = fields.Many2one('res.users', 'Approved By', readonly=True, copy=False)
    approval_date = fields.Datetime(readonly=True, copy=False)
    payslip_id = fields.Many2one(
        'hr.payslip', readonly=True, copy=False, ondelete='restrict', index=True,
        help='The payslip that carried this amount. Set when that payslip is validated.')
    payslip_state = fields.Selection(related='payslip_id.state', string='Payslip State')
    department_id = fields.Many2one(
        related='employee_id.department_id', store=True, index=True)
    state = fields.Selection(
        [('draft', 'Draft'), ('submitted', 'Submitted'),
         ('approved', 'Approved'), ('paid', 'Paid')],
        default='draft', required=True, copy=False, index=True, tracking=True)

    _unique_employee_quarter = models.Constraint(
        'unique(employee_id, financial_year, quarter)',
        'This employee already has a variable pay record for that financial year and quarter.')

    # ------------------------------------------------------------------
    # Defaults and computes
    # ------------------------------------------------------------------
    @api.model
    def _default_financial_year(self):
        today = fields.Date.context_today(self)
        return today.year if today.month >= FY_START_MONTH else today.year - 1

    @api.depends('financial_year')
    def _compute_financial_year_label(self):
        for record in self:
            year = record.financial_year
            record.financial_year_label = (
                'FY %s-%s' % (year, str(year + 1)[-2:]) if year else False)

    @api.depends('employee_id')
    def _compute_version_id(self):
        for record in self:
            record.version_id = record.employee_id.version_id

    @api.depends('financial_year', 'quarter')
    def _compute_quarter_dates(self):
        for record in self:
            if not record.financial_year or not record.quarter:
                record.date_start = record.date_end = False
                continue
            start = fields.Date.to_date('%s-%02d-01' % (record.financial_year, FY_START_MONTH))
            start += relativedelta(months=QUARTER_MONTH_OFFSET[record.quarter])
            record.date_start = start
            record.date_end = start + relativedelta(months=3, days=-1)

    @api.depends('date_end')
    def _compute_payout_date(self):
        for record in self:
            record.payout_date = record.date_end

    @api.depends('version_id', 'version_id.ft_quarterly_variable_pay')
    def _compute_quarterly_target(self):
        for record in self:
            record.quarterly_target = record.version_id.sudo().ft_quarterly_variable_pay

    @api.depends('quarterly_target', 'performance_percentage')
    def _compute_amount_computed(self):
        for record in self:
            record.amount_computed = record.currency_id.round(
                record.quarterly_target * record.performance_percentage / 100.0
            ) if record.currency_id else 0.0

    @api.depends('use_override', 'amount_override', 'amount_computed')
    def _compute_amount_payable(self):
        for record in self:
            record.amount_payable = (
                record.amount_override if record.use_override else record.amount_computed)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    @api.constrains('employee_id', 'version_id', 'company_id')
    def _check_employee_consistency(self):
        for record in self:
            if record.version_id and record.version_id.employee_id != record.employee_id:
                raise ValidationError(self.env._('The contract must belong to the same employee.'))
            if record.employee_id.company_id != record.company_id:
                raise ValidationError(self.env._('The employee belongs to another company.'))

    @api.constrains('quarterly_target', 'amount_override', 'amount_payable',
                    'performance_percentage')
    def _check_amounts_positive(self):
        """Python rather than a SQL CHECK deliberately.

        A CHECK constraint is evaluated by Postgres during the INSERT, which
        happens before @api.constrains runs, so it wins the race and surfaces a
        raw psycopg2 CheckViolation instead of a translatable message. Every
        write path goes through the ORM, so this covers the same ground.
        """
        for record in self:
            if record.performance_percentage < 0:
                raise ValidationError(self.env._('Performance percentage cannot be negative.'))
            if record.quarterly_target < 0 or record.amount_payable < 0:
                raise ValidationError(self.env._('Variable pay amounts cannot be negative.'))

    @api.constrains('date_start', 'date_end')
    def _check_quarter_dates(self):
        for record in self:
            if record.date_start and record.date_end and record.date_start > record.date_end:
                raise ValidationError(self.env._('The quarter end date precedes its start date.'))

    def _check_payroll_manager(self):
        if not self.env.su and not self.env.user.has_group('hr_payroll.group_hr_payroll_manager'):
            raise UserError(self.env._('Only Payroll administrators can approve variable pay.'))

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def action_submit(self):
        if any(record.state != 'draft' for record in self):
            raise UserError(self.env._('Only draft records can be submitted.'))
        self.write({'state': 'submitted'})

    def action_approve(self):
        self._check_payroll_manager()
        if any(record.state != 'submitted' for record in self):
            raise UserError(self.env._('Only submitted records can be approved.'))
        for record in self:
            if not record.version_id:
                raise UserError(self.env._(
                    'Set the contract on %s before approving it.', record.display_name))
        self.write({
            'state': 'approved',
            'approved_by_id': self.env.user.id,
            'approval_date': fields.Datetime.now(),
        })

    def action_reset_to_draft(self):
        self._check_payroll_manager()
        if any(record.state == 'paid' for record in self):
            raise UserError(self.env._(
                'A paid record cannot be reset. Cancel its payslip first.'))
        if any(record.payslip_id for record in self):
            raise UserError(self.env._(
                'This record is attached to a payslip. Cancel that payslip first.'))
        self.write({'state': 'draft', 'approved_by_id': False, 'approval_date': False})

    # ------------------------------------------------------------------
    # Payslip integration
    # ------------------------------------------------------------------
    @api.model
    def _eligible_domain(self, employee, date_from, date_to, payslip=None):
        """Approved records whose payout date falls inside a payslip period.

        ``payslip_id`` must be unset, or already this payslip: an amount that
        another payslip has claimed is never offered a second time, which is what
        stops the same quarter being paid twice.
        """
        claimed = ['|', ('payslip_id', '=', False)]
        claimed += [('payslip_id', '=', payslip.id)] if payslip else [('payslip_id', '=', False)]
        return [
            ('employee_id', '=', employee.id),
            ('state', '=', 'approved'),
            ('amount_payable', '!=', 0),
            ('payout_date', '>=', date_from),
            ('payout_date', '<=', date_to),
        ] + claimed

    def _claim_for_payslip(self, payslip):
        """Attach these records to ``payslip``, refusing anything already taken."""
        for record in self:
            if record.payslip_id and record.payslip_id != payslip:
                raise UserError(self.env._(
                    'Variable pay %(name)s is already on payslip %(slip)s. '
                    'Recompute this payslip before confirming it.',
                    name=record.display_name, slip=record.payslip_id.display_name))
        self.write({'payslip_id': payslip.id})

    # ------------------------------------------------------------------
    # Record protection
    # ------------------------------------------------------------------
    def write(self, vals):
        self._check_locked_fields(vals)
        return super().write(vals)

    def _check_locked_fields(self, vals):
        """Freeze approved records, and paid ones except for a payroll manager.

        Approval is a sign-off on an amount, so the amount and the quarter it
        belongs to stop being editable at that point. A payroll manager can still
        correct a paid record, because somebody has to be able to fix a genuine
        payroll error.
        """
        touched = set(vals) - UNLOCKED_AFTER_APPROVAL
        if not touched or self.env.su:
            return
        is_manager = self.env.user.has_group('hr_payroll.group_hr_payroll_manager')
        for record in self:
            if record.state == 'paid' and not is_manager:
                raise UserError(self.env._(
                    'A paid variable pay record is read-only. Ask a Payroll administrator.'))
            if record.state == 'approved' and not is_manager:
                raise UserError(self.env._(
                    'An approved variable pay record cannot be edited. Reset it to draft first.'))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_paid(self):
        if any(record.state == 'paid' or record.payslip_id for record in self):
            raise UserError(self.env._(
                'A variable pay record linked to a payslip cannot be deleted.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == self.env._('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('hr.variable.pay') or self.env._('New')
        return super().create(vals_list)

    @api.depends('employee_id', 'financial_year_label', 'quarter')
    def _compute_display_name(self):
        for record in self:
            record.display_name = '%s - %s %s' % (
                record.employee_id.name or '', record.financial_year_label or '',
                (record.quarter or '').upper())


class HrVersion(models.Model):
    """Annual variable pay target, held on the employment version.

    Odoo 19 has no hr.contract: hr.employee ``_inherits`` hr.version, so the
    version IS the contract and is where salary figures belong. The employee
    fields below are the delegated view of these two.
    """
    _inherit = 'hr.version'

    ft_annual_variable_pay = fields.Monetary(
        'Annual Variable Pay', tracking=True,
        groups='hr_payroll.group_hr_payroll_user',
        help='Full-year variable pay target. Paid quarterly against performance, '
             'never as a fixed monthly amount.')
    ft_quarterly_variable_pay = fields.Monetary(
        'Quarterly Variable Pay Target', compute='_compute_ft_quarterly_variable_pay',
        store=True, groups='hr_payroll.group_hr_payroll_user',
        help='Annual variable pay divided by the four quarterly payouts.')

    @api.depends('ft_annual_variable_pay')
    def _compute_ft_quarterly_variable_pay(self):
        for version in self:
            version.ft_quarterly_variable_pay = version.currency_id.round(
                version.ft_annual_variable_pay / 4.0
            ) if version.currency_id else version.ft_annual_variable_pay / 4.0

    @api.constrains('ft_annual_variable_pay')
    def _check_ft_annual_variable_pay(self):
        for version in self:
            if version.ft_annual_variable_pay < 0:
                raise ValidationError(self.env._('Annual variable pay cannot be negative.'))


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # inherited=True is required for a _inherits field carrying its own `groups`,
    # otherwise the delegation is not linked and the field is unreadable from the
    # employee (see the note above contract_date_start in hr/models/hr_employee.py).
    ft_annual_variable_pay = fields.Monetary(
        related='version_id.ft_annual_variable_pay', inherited=True, readonly=False,
        groups='hr_payroll.group_hr_payroll_user')
    ft_quarterly_variable_pay = fields.Monetary(
        related='version_id.ft_quarterly_variable_pay', inherited=True,
        groups='hr_payroll.group_hr_payroll_user')
    ft_variable_pay_ids = fields.One2many(
        'hr.variable.pay', 'employee_id', string='Variable Pay',
        groups='hr_payroll.group_hr_payroll_user')
    ft_variable_pay_count = fields.Integer(
        'Variable Pay Records', compute='_compute_ft_variable_pay_count',
        groups='hr_payroll.group_hr_payroll_user')

    @api.depends('ft_variable_pay_ids')
    def _compute_ft_variable_pay_count(self):
        grouped = dict(self.env['hr.variable.pay']._read_group(
            [('employee_id', 'in', self.ids)], ['employee_id'], ['__count']))
        for employee in self:
            employee.ft_variable_pay_count = grouped.get(employee, 0)

    def action_open_variable_pay(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Variable Pay'),
            'res_model': 'hr.variable.pay',
            'view_mode': 'list,form,pivot',
            'domain': [('employee_id', '=', self.id)],
            'context': {
                'default_employee_id': self.id,
                'default_company_id': self.company_id.id,
            },
        }


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    ft_variable_pay_ids = fields.One2many(
        'hr.variable.pay', 'payslip_id', string='Variable Pay', readonly=True)

    def _ft_variable_pay_input_amount(self):
        """Variable pay sitting on this payslip as an Other Input.

        Read from the input lines rather than from hr.variable.pay so a manually
        typed VAR_PAY input behaves exactly like a generated one, and so the
        salary rules and the gross reconciliation always see the same number.
        """
        self.ensure_one()
        return sum(self.input_line_ids.filtered(
            lambda line: line.code == VARIABLE_PAY_INPUT_CODE).mapped('amount'))

    @api.depends('employee_id', 'version_id', 'struct_id', 'date_from', 'date_to')
    def _compute_input_line_ids(self):
        """Add approved, unpaid variable pay for the period as an Other Input.

        Runs after super(), which owns the salary-adjustment input lines only, so
        the two do not fight over the same one2many.
        """
        super()._compute_input_line_ids()
        self._ft_sync_variable_pay_input()

    def _ft_sync_variable_pay_input(self):
        """Rebuild the VAR_PAY input line from the eligible approved records."""
        input_type = self.env.ref(
            'ft_greythr_migration.input_type_variable_pay', raise_if_not_found=False)
        if not input_type:
            return
        for slip in self:
            existing = slip.input_line_ids.filtered(
                lambda line: line.input_type_id == input_type)
            if not slip.employee_id or not slip.date_from or not slip.date_to \
                    or not slip.struct_id or input_type not in slip.struct_id.input_line_type_ids:
                if existing:
                    slip.input_line_ids = [fields.Command.unlink(line.id) for line in existing]
                continue
            records = self.env['hr.variable.pay'].sudo().search(
                self.env['hr.variable.pay']._eligible_domain(
                    slip.employee_id, slip.date_from, slip.date_to,
                    # _origin is empty for a payslip that has never been saved,
                    # whose NewId cannot go into a domain.
                    payslip=slip._origin if slip._origin.id else None))
            amount = sum(records.mapped('amount_payable'))
            commands = [fields.Command.unlink(line.id) for line in existing]
            if amount:
                commands.append(fields.Command.create({
                    'name': ', '.join(records.mapped('display_name')),
                    'amount': amount,
                    'input_type_id': input_type.id,
                }))
            if commands:
                slip.input_line_ids = commands

    def compute_sheet(self):
        # Refresh the input before computing. The compute above only re-runs when
        # the employee, structure or period changes, so an approval that lands
        # after the payslip was created would otherwise be missed - and approving
        # then recomputing is the order payroll actually works in.
        self.filtered(lambda slip: slip.state == 'draft')._ft_sync_variable_pay_input()
        return super().compute_sheet()

    def _ft_eligible_variable_pay(self):
        """The records behind this payslip's VAR_PAY input, for claiming."""
        self.ensure_one()
        return self.env['hr.variable.pay'].sudo().search(
            self.env['hr.variable.pay']._eligible_domain(
                self.employee_id, self.date_from, self.date_to, payslip=self))

    def action_payslip_done(self):
        result = super().action_payslip_done()
        for slip in self:
            if slip.currency_id.is_zero(slip._ft_variable_pay_input_amount()):
                continue
            slip._ft_eligible_variable_pay()._claim_for_payslip(slip)
        return result

    def action_payslip_paid(self):
        result = super().action_payslip_paid()
        paid = self.ft_variable_pay_ids.filtered(lambda record: record.state == 'approved')
        paid.sudo().write({'state': 'paid'})
        return result

    def action_payslip_cancel(self):
        # Release the quarter so it can be paid on a corrected payslip.
        released = self.ft_variable_pay_ids
        result = super().action_payslip_cancel()
        released.sudo().write({'state': 'approved', 'payslip_id': False})
        return result
