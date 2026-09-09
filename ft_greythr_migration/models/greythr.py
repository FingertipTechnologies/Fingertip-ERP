from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    greythr_father_name = fields.Char("Father's Name", groups='hr.group_hr_user')
    greythr_role = fields.Char('greytHR Role', groups='hr.group_hr_user')
    greythr_pf_number = fields.Char('PF Number', groups='hr.group_hr_user')
    greythr_pf_join_date = fields.Date('PF Join Date', groups='hr.group_hr_user')
    greythr_pf_eligible = fields.Boolean('PF Eligible (Source)', groups='hr.group_hr_user')
    greythr_esi_eligible = fields.Boolean('ESI Eligible (Source)', groups='hr.group_hr_user')
    greythr_source_basic = fields.Json('Original Basic Information', groups='hr.group_hr_user', copy=False)
    greythr_ctc_ids = fields.One2many('ft.greythr.ctc', 'employee_id', string='greytHR CTC History', groups='hr_payroll.group_hr_payroll_user')


class GreythrCTC(models.Model):
    _name = 'ft.greythr.ctc'
    _description = 'greytHR CTC Source Record'
    _rec_name = 'employee_id'
    _order = 'effective_date desc, id desc'

    employee_id = fields.Many2one('hr.employee', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='employee_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    effective_date = fields.Date(required=True)
    payout_month = fields.Date()
    joined_on = fields.Date()
    leaving_date = fields.Date()
    employee_status = fields.Char()
    eligible_for_pf = fields.Boolean()
    remarks = fields.Text()
    source_data = fields.Json('Original CTC Row', copy=False)
    review_notes = fields.Text()
    _unique_employee_date = models.Constraint('unique(employee_id, effective_date)', 'A CTC source record already exists for this employee and date.')
    full_basic = fields.Monetary('Full Basic')
    full_hra = fields.Monetary('Full Hra')
    full_conveyance = fields.Monetary('Full Conveyance')
    full_special_allowance = fields.Monetary('Full Special Allowance')
    full_medical_allowance = fields.Monetary('Full Medical Allowance')
    full_consultancy_fees = fields.Monetary('Full Consultancy Fees')
    full_employer_esic = fields.Monetary('Full Employer Esic')
    full_meal_allowance = fields.Monetary('Full Meal Allowance')
    full_leave_travel_allowance = fields.Monetary('Full Leave Travel Allowance')
    full_children_education_allowance = fields.Monetary('Full Children Education Allowance')
    full_attire_allowance = fields.Monetary('Full Attire Allowance')
    full_book_and_periodicals = fields.Monetary('Full Book And Periodicals')
    full_telephone_charges = fields.Monetary('Full Telephone Charges')
    full_gratuity = fields.Monetary('Full Gratuity')
    annual_ctc = fields.Monetary('Annual Ctc')
    monthly_ctc = fields.Monetary('Monthly Ctc')
    annual_variable_pay = fields.Monetary('Annual Variable Pay')
    monthly_gross = fields.Monetary('Monthly Gross')
    epf_excess_contribution = fields.Monetary('Epf Excess Contribution')
    pf_base_limit = fields.Monetary('Pf Base Limit')
    master_pf_basic = fields.Monetary('Master Pf Basic')


class HrVersion(models.Model):
    _inherit = 'hr.version'

    @api.model
    def _get_marital_status_selection(self):
        return super()._get_marital_status_selection() + [('not_provided', self.env._('Not Provided'))]
