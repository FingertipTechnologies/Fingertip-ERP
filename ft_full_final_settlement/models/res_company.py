"""Full & final settlement rules, all changeable in Payroll settings.

Starting values agreed with HR (26-Nov-2026): casual leave is paid out at
gross / 30 a day; the notice period is 90 days and a shortfall is recovered
at gross / 30 a day; gratuity is 15/26 x last Basic x years of service, for
anyone with at least 5 years, capped at 20,00,000, a part year of 6 months
or more counting as a full year.
"""
from odoo import fields, models

RATE_BASIS = [('gross', 'Monthly Gross'), ('basic', 'Monthly Basic')]
GRATUITY_RULE = [
    ('service', 'Anyone with the minimum service'),
    ('ticked', 'Minimum service and Gratuity Eligible ticked'),
    ('manual', 'HR confirms the amount on each settlement'),
]


class ResCompany(models.Model):
    _inherit = 'res.company'

    ft_fnf_encash_leave_type_ids = fields.Many2many(
        'hr.leave.type', 'ft_fnf_company_encash_leave_type_rel', 'company_id', 'leave_type_id',
        string='Leave Paid Out at Exit')
    ft_fnf_encash_basis = fields.Selection(RATE_BASIS, 'Leave Encashment Based On', default='gross', required=True)
    ft_fnf_encash_divisor = fields.Float('Leave Encashment Days per Month', default=30)
    ft_fnf_notice_days = fields.Integer('Notice Period (Days)', default=90)
    ft_fnf_notice_basis = fields.Selection(RATE_BASIS, 'Notice Recovery Based On', default='gross', required=True)
    ft_fnf_notice_divisor = fields.Float('Notice Recovery Days per Month', default=30)
    ft_fnf_gratuity_rule = fields.Selection(GRATUITY_RULE, 'Gratuity at Exit', default='service', required=True)
    ft_fnf_gratuity_min_years = fields.Float('Gratuity Minimum Service (Years)', default=5)
    ft_fnf_gratuity_days = fields.Float('Gratuity Days per Year', default=15)
    ft_fnf_gratuity_month_days = fields.Float('Gratuity Days per Month', default=26)
    ft_fnf_gratuity_part_year_months = fields.Integer('Part Year Counted From (Months)', default=6)
    ft_fnf_gratuity_cap = fields.Float('Gratuity Cap (Rs)', default=2000000)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    ft_fnf_encash_leave_type_ids = fields.Many2many(related='company_id.ft_fnf_encash_leave_type_ids', readonly=False)
    ft_fnf_encash_basis = fields.Selection(related='company_id.ft_fnf_encash_basis', readonly=False)
    ft_fnf_encash_divisor = fields.Float(related='company_id.ft_fnf_encash_divisor', readonly=False)
    ft_fnf_notice_days = fields.Integer(related='company_id.ft_fnf_notice_days', readonly=False)
    ft_fnf_notice_basis = fields.Selection(related='company_id.ft_fnf_notice_basis', readonly=False)
    ft_fnf_notice_divisor = fields.Float(related='company_id.ft_fnf_notice_divisor', readonly=False)
    ft_fnf_gratuity_rule = fields.Selection(related='company_id.ft_fnf_gratuity_rule', readonly=False)
    ft_fnf_gratuity_min_years = fields.Float(related='company_id.ft_fnf_gratuity_min_years', readonly=False)
    ft_fnf_gratuity_days = fields.Float(related='company_id.ft_fnf_gratuity_days', readonly=False)
    ft_fnf_gratuity_month_days = fields.Float(related='company_id.ft_fnf_gratuity_month_days', readonly=False)
    ft_fnf_gratuity_part_year_months = fields.Integer(related='company_id.ft_fnf_gratuity_part_year_months', readonly=False)
    ft_fnf_gratuity_cap = fields.Float(related='company_id.ft_fnf_gratuity_cap', readonly=False)
