"""A leaver's full and final settlement.

The figures fill themselves in from the employee, the salary in force on the
last working day, the leave balances and the salary advances, using the rules
in Payroll settings (res_company.py). HR can correct the worked-out amounts
and types the rest. Approving creates a payslip on the Full & Final
structure, which is validated, posted and paid like any other payslip and is
held with the leaver's last salary until both are released.
"""
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import Command, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_round

# Settlement amount field -> payslip input code on the Full & Final structure.
DUES = {
    'encash_amount': 'FNF_LEAVE_ENC',
    'gratuity_amount': 'FNF_GRATUITY',
    'variable_pay_due': 'FNF_VAR_PAY',
    'other_dues': 'FNF_OTHER_DUE',
}
RECOVERIES = {
    'notice_recovery': 'FNF_NOTICE',
    'other_recoveries': 'FNF_OTHER_REC',
    'tds_amount': 'FNF_TDS',
}


def _rupees(amount):
    return float_round(amount, precision_digits=0, rounding_method='HALF-UP')


class FtFnfSettlement(models.Model):
    _name = 'ft.fnf.settlement'
    _description = 'Full & Final Settlement'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'last_working_date desc, id desc'

    name = fields.Char('Reference', default='New', readonly=True, copy=False)
    employee_id = fields.Many2one('hr.employee', required=True, tracking=True, index=True,
                                  domain="[('company_id', '=', company_id)]")
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    state = fields.Selection([('draft', 'Draft'), ('approved', 'Approved'), ('paid', 'Paid'),
                              ('cancel', 'Cancelled')], default='draft', required=True, tracking=True, copy=False)

    resignation_date = fields.Date(tracking=True, help='Empty when the employee did not resign: no notice is recovered.')
    last_working_date = fields.Date('Last Working Day', required=True, tracking=True)
    joining_date = fields.Date(tracking=True)
    version_id = fields.Many2one('hr.version', 'Salary Used', readonly=True)
    monthly_gross = fields.Monetary(readonly=True)
    monthly_basic = fields.Monetary(readonly=True)

    service_text = fields.Char('Service', readonly=True)
    service_years = fields.Float('Service (Years)', readonly=True, digits=(16, 2))
    gratuity_years = fields.Integer('Years Counted', readonly=True)
    gratuity_note = fields.Char(readonly=True)
    gratuity_confirmed = fields.Boolean(
        'Gratuity Confirmed', tracking=True,
        help='Asked for when Payroll settings say HR confirms the gratuity on each settlement.')
    gratuity_rule = fields.Selection(related='company_id.ft_fnf_gratuity_rule')
    gratuity_amount = fields.Monetary('Gratuity', tracking=True)

    encash_days = fields.Float('Leave Balance (Days)', tracking=True)
    encash_rate = fields.Monetary('Rate per Day', readonly=True)
    encash_amount = fields.Monetary('Leave Encashment', compute='_compute_amounts', store=True)

    notice_days = fields.Integer('Notice Period (Days)', readonly=True)
    notice_served = fields.Integer('Notice Served (Days)', readonly=True)
    notice_shortfall = fields.Integer('Notice Short (Days)', tracking=True)
    notice_rate = fields.Monetary('Recovery per Day', readonly=True)
    notice_recovery = fields.Monetary('Notice Recovery', compute='_compute_amounts', store=True)

    variable_pay_due = fields.Monetary('Variable Pay / Bonus Due', tracking=True)
    other_dues = fields.Monetary('Other Dues', tracking=True)
    other_dues_note = fields.Char('Other Dues For')
    advance_recovery = fields.Monetary('Salary Advance Balance', readonly=True)
    other_recoveries = fields.Monetary('Other Recoveries', tracking=True)
    other_recoveries_note = fields.Char('Other Recoveries For')
    tds_amount = fields.Monetary('TDS', tracking=True)

    total_dues = fields.Monetary(compute='_compute_amounts', store=True)
    total_recoveries = fields.Monetary(compute='_compute_amounts', store=True)
    net_amount = fields.Monetary('Net Payable', compute='_compute_amounts', store=True,
                                 help='Negative when the employee owes the company.')
    notes = fields.Text()

    payslip_id = fields.Many2one('hr.payslip', 'Settlement Payslip', readonly=True, copy=False)
    payslip_state = fields.Selection(related='payslip_id.state', string='Payslip Status')
    final_payslip_id = fields.Many2one('hr.payslip', 'Last Monthly Payslip', compute='_compute_final_payslip')

    _unique_open_settlement = models.UniqueIndex(
        '(employee_id) WHERE state != \'cancel\'',
        'This employee already has a full and final settlement.')

    @api.depends('encash_days', 'encash_rate', 'notice_shortfall', 'notice_rate', 'gratuity_amount',
                 'variable_pay_due', 'other_dues', 'advance_recovery', 'other_recoveries', 'tds_amount')
    def _compute_amounts(self):
        for fnf in self:
            fnf.encash_amount = _rupees(max(fnf.encash_days, 0) * fnf.encash_rate)
            fnf.notice_recovery = _rupees(max(fnf.notice_shortfall, 0) * fnf.notice_rate)
            fnf.total_dues = fnf.encash_amount + fnf.gratuity_amount + fnf.variable_pay_due + fnf.other_dues
            fnf.total_recoveries = (fnf.notice_recovery + fnf.advance_recovery + fnf.other_recoveries
                                    + fnf.tds_amount)
            fnf.net_amount = fnf.total_dues - fnf.total_recoveries

    def _compute_final_payslip(self):
        for fnf in self:
            fnf.final_payslip_id = self.env['hr.payslip'].search([
                ('employee_id', '=', fnf.employee_id.id), ('state', '!=', 'cancel'),
                ('date_from', '<=', fnf.last_working_date), ('date_to', '>=', fnf.last_working_date),
                ('id', '!=', fnf.payslip_id.id),
                ('struct_id', '!=', self.env.ref('ft_full_final_settlement.fnf_structure').id),
            ], limit=1) if fnf.employee_id and fnf.last_working_date else False

    # --- filling in --------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('ft.fnf.settlement') or 'New'
        settlements = super().create(vals_list)
        settlements._ft_fill()
        return settlements

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        employee = self.employee_id
        if employee:
            self.resignation_date = employee.ft_resignation_date
            self.last_working_date = employee.departure_date
            self.joining_date = employee._get_first_contract_date(no_gap=False)
        if self.employee_id and self.last_working_date:
            self._ft_fill()

    @api.onchange('resignation_date', 'last_working_date', 'joining_date')
    def _onchange_dates(self):
        if self.employee_id and self.last_working_date:
            self._ft_fill()

    def action_refresh(self):
        self._check_draft()
        self._ft_fill()

    def _check_draft(self):
        if any(fnf.state != 'draft' for fnf in self):
            raise UserError(self.env._('Only a draft settlement can be changed. Reset it to draft first.'))

    def _ft_fill(self):
        """Work the settlement out again from the rules in Payroll settings.
        Amounts HR types (variable pay, other dues/recoveries, TDS) are kept."""
        for fnf in self:
            if not fnf.employee_id or not fnf.last_working_date:
                continue
            company = fnf.company_id
            employee = fnf.employee_id
            if not fnf.joining_date:
                fnf.joining_date = employee._get_first_contract_date(no_gap=False)
            version = employee._get_version(fnf.last_working_date)
            gross = version.l10n_in_gross_salary or version.wage
            basic = version.l10n_in_basic_salary_amount
            vals = {'version_id': version.id, 'monthly_gross': gross, 'monthly_basic': basic}
            vals.update(fnf._ft_service_values(company, version, basic))
            vals.update(fnf._ft_encashment_values(company, gross, basic))
            vals.update(fnf._ft_notice_values(company, gross, basic))
            vals['advance_recovery'] = sum(fnf._ft_outstanding_installments().mapped('amount'))
            fnf.update(vals)

    @staticmethod
    def _ft_rate(basis, divisor, gross, basic):
        return (gross if basis == 'gross' else basic) / divisor if divisor else 0.0

    def _ft_service_values(self, company, version, basic):
        if not self.joining_date or self.joining_date > self.last_working_date:
            return {'service_text': False, 'service_years': 0, 'gratuity_years': 0, 'gratuity_amount': 0,
                    'gratuity_note': self.env._('Joining date missing.')}
        service = relativedelta(self.last_working_date + timedelta(days=1), self.joining_date)
        years = service.years + service.months / 12 + service.days / 365
        counted = service.years + (1 if service.months >= company.ft_fnf_gratuity_part_year_months else 0)
        text = self.env._('%(y)s years %(m)s months %(d)s days', y=service.years, m=service.months, d=service.days)
        if years + 1e-9 < company.ft_fnf_gratuity_min_years:
            return {'service_text': text, 'service_years': years, 'gratuity_years': counted, 'gratuity_amount': 0,
                    'gratuity_note': self.env._('Less than %s years of service: no gratuity.',
                                                f'{company.ft_fnf_gratuity_min_years:g}')}
        if company.ft_fnf_gratuity_rule == 'ticked' and not version.ft_gratuity_eligible:
            return {'service_text': text, 'service_years': years, 'gratuity_years': counted, 'gratuity_amount': 0,
                    'gratuity_note': self.env._('Gratuity Eligible is not ticked on the Payroll tab.')}
        amount = (company.ft_fnf_gratuity_days / company.ft_fnf_gratuity_month_days * basic * counted
                  if company.ft_fnf_gratuity_month_days else 0.0)
        note = self.env._('%(days)s/%(month)s x Basic %(basic)s x %(years)s years',
                          days=f'{company.ft_fnf_gratuity_days:g}', month=f'{company.ft_fnf_gratuity_month_days:g}',
                          basic=f'{basic:,.2f}', years=counted)
        if company.ft_fnf_gratuity_cap and amount > company.ft_fnf_gratuity_cap:
            amount = company.ft_fnf_gratuity_cap
            note += self.env._(' (capped)')
        return {'service_text': text, 'service_years': years, 'gratuity_years': counted,
                'gratuity_amount': _rupees(amount), 'gratuity_note': note}

    def _ft_encashment_values(self, company, gross, basic):
        leave_types = company.ft_fnf_encash_leave_type_ids
        days = 0.0
        if leave_types:
            data = leave_types.get_allocation_data(self.employee_id, self.last_working_date)[self.employee_id]
            days = sum(max(item[1].get('virtual_remaining_leaves', 0), 0) for item in data
                       if item[3] in leave_types.ids)
        return {'encash_days': days,
                'encash_rate': self._ft_rate(company.ft_fnf_encash_basis, company.ft_fnf_encash_divisor, gross, basic)}

    def _ft_notice_values(self, company, gross, basic):
        required = company.ft_fnf_notice_days
        served = ((self.last_working_date - self.resignation_date).days + 1
                  if self.resignation_date and self.resignation_date <= self.last_working_date else 0)
        return {'notice_days': required, 'notice_served': served,
                'notice_shortfall': max(required - served, 0) if self.resignation_date else 0,
                'notice_rate': self._ft_rate(company.ft_fnf_notice_basis, company.ft_fnf_notice_divisor, gross, basic)}

    def _ft_outstanding_installments(self):
        """Advance installments no monthly payslip has taken yet."""
        self.ensure_one()
        return self.env['hr.salary.advance.installment'].search([
            ('employee_id', '=', self.employee_id.id), ('state', '=', 'pending'),
            ('already_paid', '=', False), ('advance_id.state', 'in', ('approved', 'running')),
            '|', ('payslip_id', '=', False), ('payslip_id', '=', self.payslip_id.id or 0),
        ])

    # --- workflow ----------------------------------------------------------

    def _check_payroll_manager(self):
        if not self.env.user.has_group('hr_payroll.group_hr_payroll_manager'):
            raise UserError(self.env._('Only Payroll administrators can approve or cancel a settlement.'))

    def action_approve(self):
        self._check_payroll_manager()
        self._check_draft()
        structure = self.env.ref('ft_full_final_settlement.fnf_structure')
        for fnf in self:
            if not fnf.employee_id.departure_date:
                raise UserError(self.env._('Register the departure of %s first.', fnf.employee_id.name))
            if fnf.gratuity_rule == 'manual' and fnf.gratuity_amount and not fnf.gratuity_confirmed:
                raise UserError(self.env._('Confirm the gratuity amount first (Gratuity Confirmed).'))
            fnf._ft_fill_keep_hr_amounts()
            inputs = [Command.create({'input_type_id': self.env.ref(f'ft_full_final_settlement.input_{code.lower()}').id,
                                      'amount': fnf[field]})
                      for field, code in {**DUES, **RECOVERIES}.items() if fnf[field]]
            payslip = self.env['hr.payslip'].create({
                'name': self.env._('Full & Final Settlement - %s', fnf.employee_id.name),
                'employee_id': fnf.employee_id.id, 'version_id': fnf.version_id.id,
                'struct_id': structure.id, 'company_id': fnf.company_id.id,
                'date_from': fnf.last_working_date, 'date_to': fnf.last_working_date,
                'input_line_ids': inputs, 'ft_fnf_settlement_id': fnf.id,
            })
            fnf.payslip_id = payslip
            payslip.compute_sheet()
            net = sum(payslip.line_ids.filtered(lambda line: line.code == 'NET').mapped('total'))
            if fnf.currency_id.compare_amounts(net, fnf.net_amount):
                raise UserError(self.env._('The settlement payslip came to %(slip)s, not %(fnf)s. '
                                           'Check the salary rules of the Full & Final structure.',
                                           slip=net, fnf=fnf.net_amount))
            fnf.state = 'approved'
            fnf.message_post(body=self.env._('Approved; settlement payslip %s created.', payslip.name))

    def _ft_fill_keep_hr_amounts(self):
        """The advance balance is re-read at approval: it is recovered in full."""
        for fnf in self:
            fnf.advance_recovery = sum(fnf._ft_outstanding_installments().mapped('amount'))

    def action_reset_to_draft(self):
        self._check_payroll_manager()
        for fnf in self:
            slip = fnf.payslip_id
            if slip and slip.state not in ('draft', 'cancel'):
                raise UserError(self.env._('The settlement payslip is already %s. Reset it to draft '
                                           'from the payslip first.', dict(slip._fields['state']._description_selection(self.env))[slip.state]))
            if slip:
                slip.unlink()
            fnf.write({'state': 'draft', 'payslip_id': False})

    def action_cancel(self):
        self._check_payroll_manager()
        self.filtered(lambda fnf: fnf.state != 'draft').action_reset_to_draft()
        self.write({'state': 'cancel'})

    def action_open_payslip(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'hr.payslip', 'res_id': self.payslip_id.id,
                'view_mode': 'form'}

    def action_print_statement(self):
        return self.env.ref('ft_full_final_settlement.action_report_fnf_statement').report_action(self)

    def _ft_sync_state_from_payslip(self):
        for fnf in self.filtered(lambda f: f.state in ('approved', 'paid')):
            fnf.state = 'paid' if fnf.payslip_id.state == 'paid' else 'approved'
