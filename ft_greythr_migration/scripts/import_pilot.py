"""Run with Odoo shell; source paths via GREYTHR_BASIC and GREYTHR_CTC.
Restricted to the reviewed single-row export format. No mail or payslips created.
"""
import os
from datetime import datetime
from decimal import Decimal
import openpyxl
import xlrd

assert env.cr.dbname == 'erp19_sep9', 'This pilot is restricted to erp19_sep9'
basic_path = os.environ['GREYTHR_BASIC']
ctc_path = os.environ['GREYTHR_CTC']
wb = openpyxl.load_workbook(basic_path, data_only=True)
rows = list(wb.active.values)
assert len(rows) == 2 and len(rows[0]) == 24, 'Expected one basic-information row'
b = dict(zip(rows[0], rows[1]))
xls = xlrd.open_workbook(ctc_path)
sheet = xls.sheet_by_index(0)
assert sheet.nrows == 2 and sheet.ncols == 30, 'Expected one CTC row'
c = dict(zip(sheet.row_values(0), sheet.row_values(1)))
assert b['Employee Number'] == c['Employee No'] and b['Employee Name'] == c['Name']
assert rows[1][3] == 'Active' and rows[1][11] == 'No'
assert b['Gender'] == 'M' and b['Is PF Eligible'] == 'Yes' and b['Is ESI Eligible'] == 'No'
assert Decimal(c['ELIGIBLE FOR PF']) == 1

def date(v):
    if not v:
        return False
    if isinstance(v, (float, int)):
        return xlrd.xldate_as_datetime(v, xls.datemode).date()
    return datetime.strptime(v, '%d %b %Y').date()

assert date(b['Joined On']) == date(c['Joined On'])
company = env['res.company'].search([])
assert len(company) == 1 and company.currency_id.name == 'INR'
Employee = env['hr.employee'].with_company(company).with_context(active_test=False, tracking_disable=True, mail_create_nosubscribe=True, mail_create_nolog=True)
emp = Employee.search([('registration_number', '=', b['Employee Number']), ('company_id', '=', company.id)])
assert len(emp) <= 1
if not emp:
    assert not Employee.search_count([('work_email', '=', b['Email'])]), 'Resolve existing email before import'
values = dict(name=b['Employee Name'], registration_number=b['Employee Number'], company_id=company.id,
    active=True, marital='not_provided', country_id=False, spouse_complete_name=False, sex='male', birthday=date(b['Date Of Birth']), work_email=b['Email'],
    private_phone=str(b['Phone']), emergency_phone=str(b['Emergency Contact Number']),
    l10n_in_pan=b['PAN Number'], greythr_father_name=b["Father's Name"], greythr_role=b['Employee Role'],
    greythr_pf_eligible=True, greythr_esi_eligible=False,
    greythr_pf_number=b['PF Number'] or False, greythr_pf_join_date=date(b['PF Join Date']),
    l10n_in_uan=b['UAN'] or False, l10n_in_esic_number=b['ESI Number'] or False,
    greythr_source_basic={'headers': list(rows[0]), 'values': list(rows[1])})
manager = Employee.search([('name', '=ilike', b['Reporting To']), ('company_id', '=', company.id)])
assert len(manager) <= 1, 'Resolve ambiguous manager name before import'
if not manager:
    manager = Employee.create({'name': b['Reporting To']})
values['parent_id'] = manager.id
if emp:
    emp.write(values)
else:
    emp = Employee.create(values)
# Odoo 19 stores employment terms on hr.version. Gross is explicitly identified
# in this report; CTC is NOT used as gross wage. Keep component reconciliation separate.
emp.version_id.with_context(tracking_disable=True).write({
    'date_version': date(c['Effective Date']), 'contract_date_start': date(b['Joined On']),
    'wage': float(c['MONTHLY GROSS']),
    'contract_type_id': env.ref('l10n_in_hr_payroll.l10n_in_contract_type_probation').id,
})
vals = dict(employee_id=emp.id, effective_date=date(c['Effective Date']), payout_month=date(c['Payout Month']),
    joined_on=date(c['Joined On']), leaving_date=date(c['Leaving Date']), employee_status=c['Employee  Status'],
    eligible_for_pf=True, remarks=c['Employee Remarks'], source_data=c)
for label, value in c.items():
    key = label.lower().replace(' ', '_')
    if key in env['ft.greythr.ctc']._fields and key not in vals and key not in ['name']:
        vals[key] = float(Decimal(str(value)))
earnings = sum(Decimal(c[k]) for k in c if k.startswith('FULL ') and k not in ('FULL GRATUITY', 'FULL EMPLOYER ESIC'))
notes = [f'Source earnings sum {earnings}; reported gross {c["MONTHLY GROSS"]}; difference {earnings - Decimal(c["MONTHLY GROSS"])}.',
    'Reported CTC less gross and gratuity: ' + str(Decimal(c['MONTHLY CTC']) - Decimal(c['MONTHLY GROSS']) - Decimal(c['FULL GRATUITY'])) + '; employer PF is not explicitly supplied.',
    'Company PF and ESIC settings are off. Source eligibility is retained without changing company settings.',
    'Use Apply to Payroll on this CTC, then review a draft payslip and statutory deductions before confirming payroll.',
    'Marital status is Not Provided; nationality is empty, not inferred.',
    'Years In Service is retained in original source only; its unit/reference date is unclear.']
vals['review_notes'] = '\n'.join(notes)
Snapshot = env['ft.greythr.ctc']
snap = Snapshot.search([('employee_id', '=', emp.id), ('effective_date', '=', vals['effective_date'])])
if snap:
    snap.write(vals)
else:
    snap = Snapshot.create(vals)
env.flush_all()
assert emp.registration_number == b['Employee Number'] and emp.wage == float(c['MONTHLY GROSS'])
assert snap.annual_ctc == float(c['ANNUAL CTC'])
assert len(emp.greythr_ctc_ids) == 1
for label, value in c.items():
    key = label.lower().replace(' ', '_')
    if key in Snapshot._fields and Snapshot._fields[key].type == 'monetary':
        assert abs(snap[key] - float(value)) < 0.001, label
# An external ID makes subsequent standard Odoo imports straightforward.
xid = env['ir.model.data'].search([('module', '=', 'ft_greythr_migration'), ('name', '=', 'employee_' + b['Employee Number'].lower())])
if not xid:
    env['ir.model.data'].create({'module': 'ft_greythr_migration', 'name': 'employee_' + b['Employee Number'].lower(), 'model': 'hr.employee', 'res_id': emp.id, 'noupdate': True})
env.cr.commit()
print('IMPORT_VERIFIED', {'employee_id': emp.id, 'ctc_id': snap.id, 'ctc_components_verified': 21, 'employee_count': Employee.search_count([])})
print('REVIEW', vals['review_notes'])
