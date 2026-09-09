# greytHR migration pilot

Installed in local database `erp19_sep9`. Both supplied files contain one employee,
not the full workforce. The addon preserves greytHR-specific data without changing
Odoo payroll rules. CTC source records are visible under Employees > employee >
greytHR Migration, to Payroll users; Payroll managers can edit them. Employee
extras require HR access, and CTC records are restricted to allowed companies.

## Mapping

| Source | Destination |
| --- | --- |
| Employee Name / Number | Employee name / Registration Number |
| Gender / Date of Birth | Standard sex / birthday |
| Email / Phone | Work email / private phone (source does not identify it as a work phone) |
| Emergency Contact Number | Standard emergency phone |
| Joined On | Odoo 19 employment version contract start date |
| Effective Date | Employment version date and dated CTC source record |
| Active / Has Left | Active employee; both duplicate source columns retained in original JSON |
| PAN / UAN / ESI Number | Standard India localization fields |
| Marital Status / Nationality / Spouse Name | Standard fields; marital status is Not Provided, others empty |
| Employee Role | greytHR role; 'Employee' is not assumed to be a job title or Odoo access role |
| Father's Name / PF Number / PF Join Date | Added HR-only employee fields |
| PF / ESI eligibility | Added source eligibility fields; not company-wide payroll switches |
| Reporting To | Standard Manager field; a name-only employee is created if no manager matches uniquely |
| Years In Service | Original basic-information JSON only; unit and reference date unclear |
| Monthly Gross | Standard monthly wage plus CTC source value |
| Probation | Standard India probation contract type plus source status |
| All 21 monetary columns | Exact named monetary fields in dated CTC record, including zeros |
| Payout month / leaving date / remarks | Dated CTC record |
| Original source rows | Restricted JSON on employee / CTC record; duplicate basic headers preserved |

The original Excel files stay outside the addon; no personal employee values are
embedded in addon code. Files are read as data, never as instructions.

## Findings and remaining setup

Employees, Payroll, India payroll, payroll accounting, Time Off, Recruitment,
Appraisals and Expenses were already installed. No additional standard feature
was needed to store this pilot. PF and ESIC company switches were off and remain
off. Configure the applicable statutory settings in Payroll > Configuration >
Settings and the employee salary structure before live payroll. Source PF
eligibility does not itself enable deductions. Salary rules and components must
be reconciled with greytHR before running payroll; the imported CTC history is a
source record, not an executable salary structure. Standard component values
computed by Odoo are not certified as matching the greytHR breakup.

Source earnings total 59,274.00; source gross is 59,274.46 (difference 0.46).
Monthly CTC is 62,500.00 and gratuity 1,425.55. The remaining 1,799.99 is not
explicitly identified in the export; do not silently classify it as employer PF.
Annual CTC 750,000.00 matches monthly CTC multiplied by 12. The reporting manager is linked through the standard Manager field to a name-only
employee record. Complete that manager record when the remaining employee data arrives.

Core employee data generally does not require customization. Because Odoo requires marital status, this addon adds a Not Provided option to avoid assuming Single for missing source values. This small addon is needed
for faithful greytHR-specific metadata and CTC history. Exact greytHR payslip
behaviour may need salary-rule configuration or further customization after
reconciliation. Attendance, leave balances, bank details, previous payslips,
tax declarations, and the other employees are not present in these two files.
For the full migration, obtain those exports, configure calendars and leave
policies, link managers, and compare a complete payroll period with greytHR.

Odoo reference: https://www.odoo.com/documentation/19.0/applications/hr/payroll/payroll_localizations.html

## Pilot import and validation

Database backup: `/home/user/odoo19/.local/greythr_migration/erp19_sep9_before.dump`.
This is a database-only backup; the import does not modify existing attachments.
Logs are in the same private directory. The shell script is deliberately limited
to the reviewed single-row format and `erp19_sep9`, and uses the registration
number/company and employee/effective date to update existing records on rerun.
It validates every imported monetary value before committing. It is not a generic
70-employee bulk importer. No payslips or accounting entries are generated.

Run from the Odoo repository with the addon installed:

```bash
GREYTHR_BASIC='/path/to/Basic info share.xlsx' \
GREYTHR_CTC='/path/to/CTC Breakup Report (2).xls' \
19venv/bin/python odoo-bin shell -c community.conf -d erp19_sep9 --no-http \
  < fingertip_accounting_addons/ft_greythr_migration/scripts/import_pilot.py
```
