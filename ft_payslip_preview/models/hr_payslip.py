from odoo import _, models
from odoo.exceptions import ValidationError


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    def action_ft_preview_pdf(self):
        """Show this payslip's PDF in a dialog instead of downloading it."""
        self.ensure_one()
        if self.error_count:
            raise ValidationError(self._get_error_message())
        return {
            'type': 'ir.actions.client',
            'tag': 'ft_payslip_preview',
            'name': _('Preview: %s', self.name),
            'params': {'url': '/ft_payslip_preview/%s' % self.id},
        }
