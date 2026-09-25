from odoo import api, fields, models

# Annual field -> the monthly field it is twelve times.
#
# Odoo 19 holds every salary figure on hr.version as a MONTHLY amount; there is
# no annual field anywhere in hr_payroll or l10n_in_hr_payroll. This section is
# read-only and derived, so nothing here is stored: it is a presentation of the
# monthly figures in the shape of the CTC sheet people already read.
#
# The earning list is deliberately identical to what l10n_in_hr_payroll sums into
# l10n_in_gross_salary. If the two ever drift, Gross Total stops reconciling with
# the lines printed above it, which is worse than not showing it at all.
ANNUAL_EARNINGS = {
    'ft_annual_basic': 'l10n_in_basic_salary_amount',
    'ft_annual_hra': 'l10n_in_hra',
    'ft_annual_standard_allowance': 'l10n_in_standard_allowance',
    'ft_annual_performance_bonus': 'l10n_in_performance_bonus',
    'ft_annual_lta': 'l10n_in_leave_travel_allowance',
    'ft_annual_fixed_allowance': 'l10n_in_fixed_allowance',
    'ft_annual_meal': 'l10n_in_meal_voucher_amount',
    'ft_annual_phone': 'l10n_in_phone_subscription',
    'ft_annual_internet': 'l10n_in_internet_subscription',
    'ft_annual_transport': 'l10n_in_company_transport',
}

# Employer costs: part of CTC, never deducted from the employee.
ANNUAL_EMPLOYER = {
    'ft_annual_pf_employer': 'l10n_in_pf_employer_amount',
    'ft_annual_esic_employer': 'l10n_in_esic_employer_amount',
    'ft_annual_gratuity': 'l10n_in_gratuity',
    'ft_annual_lwf_employer': 'l10n_in_lwf_employer_contribution',
}

# Employee deductions.
ANNUAL_DEDUCTIONS = {
    'ft_annual_pf_employee': 'l10n_in_pf_employee_amount',
    'ft_annual_esic_employee': 'l10n_in_esic_employee_amount',
    'ft_annual_lwf_employee': 'l10n_in_lwf_employee_contribution',
    'ft_annual_medical_insurance': 'l10n_in_medical_insurance_total',
}

ANNUAL_FROM_MONTHLY = {**ANNUAL_EARNINGS, **ANNUAL_EMPLOYER, **ANNUAL_DEDUCTIONS}

PAYROLL_GROUP = 'hr_payroll.group_hr_payroll_user'


def _annual(string, help=None):
    return fields.Monetary(
        string=string, compute='_compute_ft_annual_components',
        groups=PAYROLL_GROUP, help=help)


class HrVersion(models.Model):
    """Annual CTC breakup, derived from the monthly salary fields.

    Read-only throughout. Nothing is stored and nothing is written back: editing
    salary stays in the fields above this section, exactly as before.
    """
    _inherit = 'hr.version'

    # --- Fixed salary break up (annual) ---
    ft_annual_basic = _annual('Basic Salary (Yearly)')
    ft_annual_hra = _annual('House Rent Allowance (Yearly)')
    ft_annual_standard_allowance = _annual('Standard Allowance (Yearly)')
    ft_annual_performance_bonus = _annual('Performance Bonus (Yearly)')
    ft_annual_lta = _annual('Leave Travel Allowance (Yearly)')
    ft_annual_fixed_allowance = _annual('Fixed Allowance (Yearly)')
    ft_annual_meal = _annual('Meal Allowance (Yearly)')
    ft_annual_phone = _annual('Phone Subscription (Yearly)')
    ft_annual_internet = _annual('Internet Subscription (Yearly)')
    ft_annual_transport = _annual('Company Transport (Yearly)')

    # --- Employer cost (annual) ---
    ft_annual_pf_employer = _annual('PF Employer (Yearly)')
    ft_annual_esic_employer = _annual('ESI Employer (Yearly)')
    ft_annual_gratuity = _annual('Gratuity (Yearly)')
    ft_annual_lwf_employer = _annual('LWF Employer (Yearly)')

    # --- Deductions (annual) ---
    ft_annual_pf_employee = _annual('PF Employee (Yearly)')
    ft_annual_esic_employee = _annual('ESI Employee (Yearly)')
    ft_annual_lwf_employee = _annual('LWF Employee (Yearly)')
    ft_annual_medical_insurance = _annual('Medical Insurance (Yearly)')

    # --- Professional tax: no field holds it, it comes from the state slab ---
    ft_monthly_professional_tax = fields.Monetary(
        'Professional Tax', compute='_compute_ft_professional_tax', groups=PAYROLL_GROUP)
    ft_annual_professional_tax = fields.Monetary(
        'Professional Tax (Yearly)', compute='_compute_ft_professional_tax',
        groups=PAYROLL_GROUP)

    # --- Totals ---
    ft_annual_gross = fields.Monetary(
        'Gross Total (Yearly)', compute='_compute_ft_ctc_totals', groups=PAYROLL_GROUP,
        help='Monthly gross salary x 12. Also shown as Fixed Pay, which it equals.')
    ft_monthly_ctc = fields.Monetary(
        'Total CTC (Monthly)', compute='_compute_ft_ctc_totals', groups=PAYROLL_GROUP)
    ft_annual_ctc = fields.Monetary(
        'Total CTC (Yearly)', compute='_compute_ft_ctc_totals', groups=PAYROLL_GROUP,
        help='Gross salary plus employer costs plus the annual variable pay target.')
    ft_monthly_total_deductions = fields.Monetary(
        'Total Deductions (Monthly)', compute='_compute_ft_ctc_totals', groups=PAYROLL_GROUP)
    ft_annual_total_deductions = fields.Monetary(
        'Total Deductions (Yearly)', compute='_compute_ft_ctc_totals', groups=PAYROLL_GROUP)
    ft_monthly_net_payable = fields.Monetary(
        'Net Payable (Monthly)', compute='_compute_ft_ctc_totals', groups=PAYROLL_GROUP)
    ft_annual_net_payable = fields.Monetary(
        'Net Payable (Yearly)', compute='_compute_ft_ctc_totals', groups=PAYROLL_GROUP,
        help='Gross salary less employee deductions. Excludes TDS, which is not '
             'held as a fixed monthly figure.')

    @api.depends(*ANNUAL_FROM_MONTHLY.values())
    def _compute_ft_annual_components(self):
        for version in self:
            for annual, monthly in ANNUAL_FROM_MONTHLY.items():
                version[annual] = (version[monthly] or 0.0) * 12

    @api.depends('l10n_in_pt', 'pt_rule_parameter_id', 'l10n_in_gross_salary',
                 'sex', 'date_version')
    def _compute_ft_professional_tax(self):
        """Resolve the state PT slab for the current gross.

        Mirrors the PT salary rule rather than inventing a second set of rules,
        so the figure shown here is the one a payslip would deduct. Returns 0
        where PT is off, no state parameter is set, or the gross falls outside
        every slab.
        """
        for version in self:
            monthly = 0.0
            parameter = version.pt_rule_parameter_id
            if version.l10n_in_pt and parameter:
                slabs = self.env['hr.rule.parameter']._get_parameter_from_code(
                    parameter.code, version.date_version or fields.Date.context_today(self),
                    raise_if_not_found=False)
                if isinstance(slabs, dict):
                    gender = version.sex if version.sex in ('male', 'female') else 'male'
                    slabs = slabs.get(gender, [])
                for amount, (lower, upper) in (slabs or []):
                    if float(lower) <= version.l10n_in_gross_salary <= float(upper):
                        monthly = amount
                        break
            version.ft_monthly_professional_tax = monthly
            version.ft_annual_professional_tax = monthly * 12

    @api.depends('l10n_in_gross_salary', 'ft_annual_variable_pay',
                 'ft_monthly_professional_tax',
                 *(ANNUAL_EMPLOYER.values()), *(ANNUAL_DEDUCTIONS.values()))
    def _compute_ft_ctc_totals(self):
        for version in self:
            gross = version.l10n_in_gross_salary or 0.0
            employer = sum((version[f] or 0.0) for f in ANNUAL_EMPLOYER.values())
            deductions = sum((version[f] or 0.0) for f in ANNUAL_DEDUCTIONS.values())
            deductions += version.ft_monthly_professional_tax

            version.ft_annual_gross = gross * 12
            # Variable pay is already an annual figure and is deliberately NOT
            # divided into the monthly CTC: it is paid quarterly on performance,
            # which is the whole point of hr.variable.pay.
            version.ft_annual_ctc = (gross + employer) * 12 + version.ft_annual_variable_pay
            version.ft_monthly_ctc = gross + employer
            version.ft_monthly_total_deductions = deductions
            version.ft_annual_total_deductions = deductions * 12
            version.ft_monthly_net_payable = gross - deductions
            version.ft_annual_net_payable = (gross - deductions) * 12


def _related(name):
    """Delegated, read-only view of a hr.version breakup field.

    A hr.version field carrying its own `groups` needs an explicit related with
    inherited=True or it is not reachable from the employee - see the note above
    contract_date_start in hr/models/hr_employee.py. Declared in the class body
    rather than set afterwards, because Odoo's metaclass only collects fields
    present when the class is created.
    """
    return fields.Monetary(
        related='version_id.%s' % name, inherited=True, groups=PAYROLL_GROUP)


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    ft_annual_basic = _related('ft_annual_basic')
    ft_annual_hra = _related('ft_annual_hra')
    ft_annual_standard_allowance = _related('ft_annual_standard_allowance')
    ft_annual_performance_bonus = _related('ft_annual_performance_bonus')
    ft_annual_lta = _related('ft_annual_lta')
    ft_annual_fixed_allowance = _related('ft_annual_fixed_allowance')
    ft_annual_meal = _related('ft_annual_meal')
    ft_annual_phone = _related('ft_annual_phone')
    ft_annual_internet = _related('ft_annual_internet')
    ft_annual_transport = _related('ft_annual_transport')
    ft_annual_pf_employer = _related('ft_annual_pf_employer')
    ft_annual_esic_employer = _related('ft_annual_esic_employer')
    ft_annual_gratuity = _related('ft_annual_gratuity')
    ft_annual_lwf_employer = _related('ft_annual_lwf_employer')
    ft_annual_pf_employee = _related('ft_annual_pf_employee')
    ft_annual_esic_employee = _related('ft_annual_esic_employee')
    ft_annual_lwf_employee = _related('ft_annual_lwf_employee')
    ft_annual_medical_insurance = _related('ft_annual_medical_insurance')
    ft_monthly_professional_tax = _related('ft_monthly_professional_tax')
    ft_annual_professional_tax = _related('ft_annual_professional_tax')
    ft_annual_gross = _related('ft_annual_gross')
    ft_monthly_ctc = _related('ft_monthly_ctc')
    ft_annual_ctc = _related('ft_annual_ctc')
    ft_monthly_total_deductions = _related('ft_monthly_total_deductions')
    ft_annual_total_deductions = _related('ft_annual_total_deductions')
    ft_monthly_net_payable = _related('ft_monthly_net_payable')
    ft_annual_net_payable = _related('ft_annual_net_payable')
