# -*- coding: utf-8 -*-
from . import models

SALARY_ADVANCE_CODE = 'SALARY_ADVANCE'


def post_init_hook(env):
    """Attach the recovery rule to the salary structures that already exist.

    A salary rule in Odoo belongs to exactly one structure -- hr.payslip reads
    ``struct_id.rule_ids`` and nothing is inherited between structures -- so a
    single record cannot serve them all. The rule shipped in data sits on the
    default rule set, which only covers structures created afterwards, so it is
    copied onto every structure already in the database. The rule is inert
    unless an input is present, so adding it everywhere is harmless.
    """
    template = env.ref('ftp_employee_salary_advance.salary_rule_salary_advance',
                       raise_if_not_found=False)
    input_type = env.ref('ftp_employee_salary_advance.input_type_salary_advance',
                         raise_if_not_found=False)
    if not template or not input_type:
        return
    structures = env['hr.payroll.structure'].search([('id', '!=', template.struct_id.id)])
    for structure in structures:
        if SALARY_ADVANCE_CODE in structure.rule_ids.mapped('code'):
            continue
        template.copy({'struct_id': structure.id, 'name': template.name})
    # Make the input selectable by hand on those structures as well.
    for structure in structures | template.struct_id:
        if input_type not in structure.input_line_type_ids:
            structure.input_line_type_ids = [(4, input_type.id)]
