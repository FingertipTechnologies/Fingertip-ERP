from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    ft_resignation_date = fields.Date('Resignation Date', groups='hr.group_hr_user', tracking=True,
                                      help='The day the employee handed in the resignation; the notice period runs from it.')
    ft_fnf_settlement_ids = fields.One2many('ft.fnf.settlement', 'employee_id', groups='hr_payroll.group_hr_payroll_user')

    def action_ft_fnf_settlement(self):
        self.ensure_one()
        settlement = self.ft_fnf_settlement_ids.filtered(lambda fnf: fnf.state != 'cancel')[:1]
        action = {'type': 'ir.actions.act_window', 'res_model': 'ft.fnf.settlement', 'view_mode': 'form',
                  'name': self.env._('Full & Final Settlement')}
        if settlement:
            return dict(action, res_id=settlement.id)
        return dict(action, context={'default_employee_id': self.id, 'default_company_id': self.company_id.id,
                                     'default_resignation_date': self.ft_resignation_date,
                                     'default_last_working_date': self.departure_date})
