# -*- coding: utf-8 -*-
from odoo import api, models

SALARY_ADVANCE_CODE = 'SALARY_ADVANCE'


class HrPayrollStructure(models.Model):
    _inherit = 'hr.payroll.structure'

    @api.model_create_multi
    def create(self, vals_list):
        # A structure gets Odoo's built-in default rules, not the rules of
        # hr_payroll.default_structure, so the recovery rule is copied here.
        # Structures created by other modules after this one (e.g. the greytHR
        # structure) would otherwise never deduct an advance.
        structures = super().create(vals_list)
        structures._ftp_add_salary_advance_rule()
        return structures

    def _ftp_add_salary_advance_rule(self):
        """Copy the recovery rule onto these structures, where missing.

        A salary rule belongs to exactly one structure and hr.payslip only reads
        struct_id.rule_ids. The rule is inert unless the input is present, so
        adding it everywhere is harmless.
        """
        template = self.env.ref('ftp_employee_salary_advance.salary_rule_salary_advance',
                                raise_if_not_found=False)
        input_type = self.env.ref('ftp_employee_salary_advance.input_type_salary_advance',
                                  raise_if_not_found=False)
        if not template or not input_type:
            return
        for structure in self:
            if structure != template.struct_id and \
                    SALARY_ADVANCE_CODE not in structure.rule_ids.mapped('code'):
                template.copy({'struct_id': structure.id, 'name': template.name})
            # Make the input selectable by hand as well.
            if input_type not in structure.input_line_type_ids:
                structure.input_line_type_ids = [(4, input_type.id)]
