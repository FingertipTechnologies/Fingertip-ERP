# Fingertip greytHR migration and payroll

This addon imports greytHR-specific employee metadata and dated CTC history and
provides an opt-in **Fingertip: greytHR Monthly** salary structure. Installing it
creates fields, views and reusable salary rules, not employee or salary data.
The supplied spreadsheets contain one employee, not the full workforce.

## Use in staging

1. Install/upgrade `ft_greythr_migration` version `19.0.1.3.0`.
2. With Employees and Payroll administrator access, select the correct India
   company (INR), then import the manager file first and the employee/CTC file
   second through Employees > Import records. Keep external IDs unchanged.
3. Open the employee > greytHR Migration > CTC row. Select the appropriate PF
   Treatment and click **Apply to Payroll**. This populates standard salary
   fields and assigns the new pay category to the employment version matching
   the source effective date; it creates a version if needed.
4. Generate a draft payslip. Review calendar/worked days, source differences,
   statutory settings, tax deductions and the salary components. Only then mark
   **Payroll Setup Reviewed** on the CTC. Pending PF or unreviewed CTC records
   prevent payslip confirmation. Applying CTC alone does not confirm anything.

CTC records can be read by Payroll users and edited by Payroll administrators,
restricted to allowed companies. Other added employee details require HR access.
Manager uses Odoo's standard Manager relation. A missing manager is created with
name only. No login user is created.

## Mapping

| Source | Destination |
| --- | --- |
| Name / number | Standard employee name / Registration Number |
| Gender / DOB / contact details | Standard employee fields; Phone uses private phone |
| PAN / UAN / ESIC Number | Standard India localization fields |
| Joined On / Effective Date / Probation | Employment version start/date/contract type |
| Reporting To | Standard Manager linked to a name-only employee if missing |
| Marital / nationality / spouse | Standard fields; Not Provided for missing marital status |
| Father's name, greytHR role, PF number/join date, eligibility | Added HR fields |
| Basic / HRA | Native basic salary / HRA |
| Special allowance | Native fixed allowance, preserving the supplied amount |
| Leave travel / meal / telephone / conveyance | Native LTA / meal voucher / phone / transport amounts |
| Gratuity | Native gratuity amount; employer provision in this structure |
| Medical allowance, consultancy, education, attire, books | Named earnings rules reading the applied CTC |
| Gross | Native monthly wage; source reconciliation is an explicit salary line |
| PF | Source PF eligibility/base/limit and chosen treatment; dated Odoo PF rate |
| Employer ESIC | Source employer amount as a separate employer cost |
| Annual/monthly CTC and all 21 monetary columns | Named fields in dated CTC history |
| Source dates/status/remarks | Dated CTC history |
| Original raw rows / Years In Service | Source JSON retained by local shell import; raw JSON is not in UI import files |

## Calculation behavior

The new structure is separate from **India: Regular Pay**. It does not change
standard rules for other employees. Most native localization fields are reused.
For versions linked to a CTC, fixed allowance does not include meal/phone/
conveyance a second time. Native gross also includes the additional CTC earnings
and explicit gross reconciliation.

Earnings use Odoo's paid-amount ratio, so unpaid time prorates monthly components.
The current PF calculation also prorates the selected monthly PF base/limit;
confirm that this matches company policy for partial months. Employer PF,
gratuity and employer ESIC/LWF are separate employer costs; they do not reduce
employee net pay. Both the computation tab and the India PDF separate employer
costs from employee earnings/deductions. Reconciliation totals are informational.

PF eligibility and treatment are per applied CTC; this structure does not require
turning on the company-wide PF flag and does not change it. PT, TDS, medical
insurance, employee ESIC and LWF retain the native configured rules. Employee
ESIC additionally checks the employee's source eligibility. Company ESIC/other
settings and the appropriate employee rates/slabs must be configured separately.
The source employer ESIC amount is not a substitute for statutory recalculation.
Excess PF is rejected by Apply to Payroll until an explicit payout policy is
implemented. Annual variable pay is accepted from 19.0.1.3.0 and is carried to the
employment version as a target only; see Quarterly variable pay below. Hourly and
nonmonthly pay are unsupported.
This is a pilot mapping, not certification of all Indian statutory reporting.

A source change clears Payroll Setup Reviewed. Reapply the CTC before computing
if mapped salary fields are stale. CTC records used by confirmed payslips cannot
be rewritten; use a new effective date. A payslip spanning a version change must
be split, so historical periods do not accidentally use the latest CTC.

## Local pilot result

Local database: `erp19_sep9`. Employee: FT0174. Review payslip: June 2026,
using the existing 40-hour calendar and a full scheduled month with no recorded
unpaid leave. These work assumptions are not attendance imported from greytHR.

- Basic 29,637.00; HRA 11,855.00; special allowance 15,682.00;
  meal 1,100.00; LTA 1,000.00; gross reconciliation 0.46.
- Gross 59,274.46; provisional employee PF 1,800.00;
  provisional net 57,474.46 before any additional PT/TDS/other deductions.
- Employer PF assumed 1,800.00; gratuity provision 1,425.55.
- Calculated CTC 62,500.01; source CTC 62,500.00; information difference -0.01.
- PF treatment and gratuity treatment are provisional; payroll remains unreviewed.
- Company PF/ESIC/PT/LWF switches were off and were not changed.

## Validation and artifacts

Tests cover full month, unpaid time, zero pay, historical version selection,
reapplication, confirmation review, immutable confirmed CTC records, unchanged
standard India rules, and separate employer-cost presentation in the report.

```bash
19venv/bin/python odoo-bin -c community.conf -d erp19_sep9 \
  -u ft_greythr_migration --stop-after-init --http-port 0 \
  --test-enable --test-tags /ft_greythr_migration
```

Local backups and logs are in `/home/user/odoo19/.local/greythr_migration/`.
`erp19_sep9_before_payroll.dump` is the database backup before the payroll changes.
Source spreadsheets and staging Excel files stay outside the addon source.
`scripts/import_pilot.py` is restricted to the reviewed single-row export and
`erp19_sep9`; it is not a general bulk importer. No employee data is auto-loaded
by the manifest. No payment or accounting posting is made by the import.

Odoo reference: https://www.odoo.com/documentation/19.0/applications/hr/payroll/payslips.html

## Reference payslip layout (version 19.0.1.2.0)

The **Fingertip Payslip** PDF matches the supplied greytHR layout: A4 portrait,
company name/address/logo, two employee-information columns, Earnings with Master
and Actual amounts, Deductions, totals, net in words, signature notice and print
time. It is the default report on Fingertip: greytHR Monthly and is also available
from a payslip's Print menu. The existing India detailed reports remain available
for employer CTC analysis. Employer costs are excluded from the employee-facing
reference layout, as in the supplied sample.

This is a report-only change. Actual values come from computed payslip lines;
Master values come from the employment version's mapped components and applied
CTC. Nonzero reconciliation amounts remain visible and fractional currency
amounts are preserved rather than silently rounding to the sample's integers.
Zero-only components are hidden. A component with nonzero Master is shown even
when Actual is zero (e.g. a fully unpaid month).

Company branding, employee bank, department, designation and location use Odoo
records; missing values are blank. The PDF is a layout reference, not an instruction
to overwrite those records or import July pay/leave/tax values. Effective workdays
are calendar days within the payslip/contract period minus unpaid worked-day
quantities, excluding OUT entries. Days In Month uses the calendar month. This
presentation does not alter Odoo's payroll proration or attendance records.

The local preview uses the existing June draft; its values therefore differ from
the shared July payslip. Install/upgrade this addon in staging to get the same
report layout; no employee data is embedded in the report template.

For Fingertip companies without a configured logo, the report uses the logo
extracted from the supplied reference PDF. Other companies use only their own
configured logo. This changes report branding only, not company records.

Version 19.0.1.2.1 fixes the salary-structure Template selector: the native
name-based report filter excluded our custom report. The field now includes
Fingertip Payslip explicitly while retaining the original localization filter.
Deploy the complete addon, restart workers, and upgrade the app in the target
database. Existing structures can then select Template = Fingertip Payslip
without changing payroll calculations.

Version 19.0.1.2.2 lists the native meal amount as **Meal Allowance** under Salary
Components (after Fixed Allowance) on the employee Payroll tab and on contract
templates, instead of "Meal Vouchers" under Benefits. It is the same field, so payslip
computation is unchanged; the MEAL earning already prints on the Fingertip and India
payslip PDFs. This is a view-only change: upgrade the app, no worker restart needed.

Version 19.0.1.2.3 stops paying sub-rupee source gross gaps. greytHR's monthly gross
often carries paise from annual CTC / 12 (for example 59,274.46 against mapped earnings
of 59,274.00). A gap under ₹1 is treated as source rounding: the applied wage is the sum
of mapped earnings, and no Gross Reconciliation amount is paid or printed. Gaps of ₹1
or more are still paid and shown, so real mapping differences stay visible. The source
Monthly Gross on the CTC record is kept unchanged. This is a Python change: restart
workers, upgrade the app, then click Apply to Payroll on each applied CTC before
computing payslips (until then Compute Sheet asks for the reapply).

## Quarterly variable pay (version 19.0.1.3.0)

Performance-based variable pay, paid once a quarter rather than accrued monthly.
An employee on ₹60,000 annual variable pay has a ₹15,000 quarterly target; at 80%
performance the approved payout is ₹12,000 and nothing reaches a payslip in the
other two months of the quarter.

**Where the target lives.** Odoo 19 has no `hr.contract`: `hr.employee` delegates
to `hr.version` through `_inherits`, so the version *is* the contract. **Annual
Variable Pay** is stored there and shown on the employee's Payroll tab, together
with the quarterly target (annual / 4, computed) and the record count. Apply to
Payroll copies the source `annual_variable_pay` onto the version, so the target
arrives with the rest of the CTC.

**The quarterly record.** `hr.variable.pay`, one per employee per financial year
per quarter, enforced by a unique constraint. Quarters follow the Indian financial
year, so Q1 is April-June and Q4 is January-March of the next calendar year. The
quarterly target defaults from the contract; the payable amount is
`target x performance % / 100`, and HR can pay a different figure by ticking
**Override Amount**. The override is a separate stored field rather than an editable
computed one, so it is not silently discarded the next time the target or the
percentage changes.

**Workflow.** Draft → Submitted → Approved → Paid, with chatter tracking. Only
`hr_payroll.group_hr_payroll_manager` may approve. Approving freezes the amount and
the quarter; a payroll manager can still correct a paid record, because somebody has
to be able to fix a real payroll error.

**Reaching the payslip.** Approval alone pays nothing. The payslip whose period
contains the record's **payout date** (the quarter end by default, editable — a
quarter closing 30 June is usually paid with July payroll) picks the amount up as
the `VAR_PAY` Other Input. The input is refreshed both when the payslip's period or
employee changes and on Compute Sheet, so approving after creating the payslip still
works. Validating the payslip claims the record; marking it paid sets the record to
Paid; cancelling the payslip releases the quarter again. A record already claimed by
one payslip is never offered to another, which is what prevents a double payment.

**Why VAR_PAY is sequenced 98.** `GROSS_RECON` at sequence 99 plugs `BASIC + ALW` up
to `paid_amount`, so any allowance it cannot see is silently cancelled and net pay
does not move. VAR_PAY therefore runs *before* it, and `GROSS_RECON` adds the input
back before reconciling, leaving it to plug the fixed gross only. `CTC_DIFF` excludes it for the
same reason: that line reconciles against the *fixed* monthly CTC, which variable pay
sits outside by design, so leaving it in would report a CTC shortfall every payout
quarter. `CTC_TOTAL` does include it and rises accordingly — it is the actual employer
cost for the month, and in a payout month that cost really is higher.

**Consequence to confirm before going live:** variable pay is part of `GROSS`, so in a
payout month it raises the gross that the **PT slab** and the **ESIC eligibility
threshold** are tested against. That is normally correct for Indian statutory gross,
but it can move an employee across the ESIC threshold in payout months only. Confirm
this against company policy before the first quarterly run.

**Both India structures are supported, and greytHR is not a prerequisite.** An
employee whose salary is maintained natively in Odoo uses **India: Regular Pay** and
needs no greytHR CTC record at all — set Annual Variable Pay on the contract, approve a
quarter, done. Nothing is re-entered anywhere. That structure has no reconciliation plug
(`GROSS = BASIC + ALW`, `NET = BASIC + ALW + DED`), so the rule sits at sequence 40,
after the last stock allowance and before GROSS, and flows straight through. The
sequence-98 arrangement described above applies only to the greytHR structure.

Do not switch an employee to Fingertip: greytHR Monthly just to get variable pay: that
structure reads every component from an applied greytHR CTC and will refuse to compute
without one ("Apply a dated greytHR CTC record to this employment version first"). It is
for migrated employees, whose figures must trace back to the greytHR source.

Caveat: `l10n_in_hr_payroll`'s own data file resets the stock structure's `rule_ids`, so
after upgrading that module also upgrade `ft_greythr_migration` to re-attach the VAR_PAY
rule to India: Regular Pay.

Menus: Payroll > Payslips > Variable Pay, and Payroll > Reporting > Variable Pay
(pivot and graph, grouped by employee and quarter). The employee form carries a
**Variable Pay** smart button. List, form, search, pivot and graph views are provided,
with filters for employee, department, company, financial year, quarter, each state,
and an "Approved, Not Paid" queue.
