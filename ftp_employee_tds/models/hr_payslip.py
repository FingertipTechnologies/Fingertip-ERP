from odoo import fields, models


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    ftp_tds_slab_set_id = fields.Many2one('ftp.tds.slab.set', string='TDS Slab Set',
        readonly=True, copy=False, index='btree_not_null',
        groups='hr_payroll.group_hr_payroll_user',
        help="The slab set automatic TDS used for this payslip. Once the payslip is "
             "validated, that set's rates can no longer be changed.")

    def _get_payslip_lines(self):
        # Work one slip at a time: historical slips can share a version but
        # require different tax dates. Never rewrite validated payroll lines.
        result = []
        regular = self.env.ref('l10n_in_hr_payroll.hr_payroll_structure_in_employee_salary')
        for slip in self:
            if slip.state == 'draft' and slip.struct_id == regular:
                version = slip.version_id
                version._ftp_apply_tds(slip.date_from)
                slip.ftp_tds_slab_set_id = (version._ftp_tds_slab_set(slip.date_from)
                                            if version._ftp_eligible_for_auto_tds() else False)
            result.extend(super(HrPayslip, slip)._get_payslip_lines())
        return result
