"""Read-only post-import checks; run with Odoo shell in the pilot database."""
from odoo.exceptions import AccessError
assert env.cr.dbname == 'erp19_sep9'
e = env['hr.employee'].search([('registration_number', '=', 'FT0174')])
assert len(e) == 1 and len(e.greythr_ctc_ids) == 1
assert str(e.contract_date_start) == '2026-05-04' and e.wage == 59274.46
assert e.marital == 'not_provided' and not e.country_id and e.parent_id.name == 'ASHITHA NAIR E'
assert len(e.greythr_source_basic['headers']) == 24
assert e.greythr_ctc_ids.annual_ctc == 750000
assert len(e.greythr_ctc_ids.source_data) == 30
view = env['hr.employee'].get_view(env.ref('hr.view_employee_form').id, 'form')
assert 'greythr_ctc_ids' in view['arch']
assert 'greythr_reporting_to' not in env['hr.employee']._fields
assert 'greythr_reporting_to' not in view['arch']
assert not e.parent_id.user_id and not e.parent_id.work_email
assert env['hr.employee'].with_context(active_test=False).search_count([('name', '=', 'ASHITHA NAIR E'), ('company_id', '=', e.company_id.id)]) == 1
public = env.ref('base.public_user')
try:
    e.greythr_ctc_ids.with_user(public).read(['annual_ctc'])
    raise AssertionError('Public user must not read CTC')
except AccessError:
    pass
assert 'greythr_source_basic' not in env['hr.employee'].with_user(public).fields_get()
assert not env['hr.payslip'].search_count([('employee_id', '=', e.id), ('state', 'not in', ['draft', 'cancel'])])
print('VERIFIED: persisted employee, dates, wage, original columns, no duplicate, merged form, restricted access, no confirmed payslips')
