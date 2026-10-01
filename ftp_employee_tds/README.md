# Automatic employee TDS (India)

## What was wrong

Version 19.0.1.0.0 only ran through a monthly cron or the company settings
button. Salary changes and payslip computation did not call it. Its employee
recompute method was not exposed in the employee view. It also used Odoo's
bundled FY 2023-24 slab chart and ₹50,000 standard deduction for later years.
A zero value alone does not indicate a fault: low-income employees legitimately
have no salary TDS.

## Use

Install/upgrade `ftp_employee_tds`, then open Payroll → Employees → employee →
Tax Deductions. Enable Automatic TDS at company and employee level. Select
New Regime (default) or Old Regime and verify Indian Tax Resident status.
The old regime uses date of birth to determine senior-citizen slabs; a missing
birthday conservatively uses the under-60 exemption.

Enter Deduction FY Start Year (2026 means April 2026–March 2027) and, if needed,
Approved Annual Deductions / Exemptions. This is an HR-verified total after
applicable caps, **excluding standard deduction**. Under old regime it can
include eligible HRA exemption, PT, 80C including employee PF, 80D, etc.
Under new regime include only legally permitted amounts, such as eligible
employer NPS. No automatic HRA/declaration verification is provided. A regime
change clears previously approved deductions unless a replacement total is
explicitly supplied with the change. Amounts from another FY are ignored.

Save salary/tax inputs to calculate TDS. Recompute TDS also runs it immediately.
Regular draft payslip computation refreshes it using the payslip month rather
than today's date. The monthly scheduled job remains as a fallback. Company
settings' recompute button is restricted to the selected company.
Switch Automatic TDS off to retain a manually agreed amount.

## Calculation and supported scope

Normal salary income; dated old/new slabs, standard deduction, resident
rebate, new-regime rebate marginal relief, surcharge marginal relief and cess.
The rates come from TDS slab sets (below); a date no active set covers raises
an explicit error instead of silently reusing stale rates.

## TDS slab sets (19.0.3.0.0)

Rates are data, not code: Payroll → Configuration → Salary → TDS Slab Sets.
One set per regime per financial year holds the slabs, standard deduction,
rebate limit and cap, rebate marginal relief, cess %, surcharge bands and the
age-based 0% slab (old regime 60+/80+). FY 2023-24 to FY 2026-27 are loaded
as `noupdate` data, identical to the figures hard-coded up to 19.0.2.0.1; the
original regression tests pass unchanged against them.

- **New financial year / Budget change:** duplicate last year's set (copies
  start archived), change dates and rates, then activate it. No code release.
- **Automatic pick:** the active set covering the payslip month for the
  employee's regime. A company-specific set beats a shared (no company) one.
  Active automatic sets of the same regime and company may not overlap.
- **Employee exceptions:** tick *Only for Assigned Employees* on a set and pick
  it as the employee's *Override TDS Slab Set*. It applies only for its dates;
  a regime change clears it. *TDS Slab Set in Use* shows today's set.
- **Audit and lock:** each regular payslip records the set that worked out its
  TDS. Once such a payslip is validated, the set's rates are frozen (name,
  notes and archiving remain editable); correct it by copy-and-replace.
- **Still code:** the formulas — slab arithmetic, rebate and surcharge marginal
  relief, statutory ₹10 rounding. A new *kind* of rule needs a release.

Projection = finalized prior-month GROSS in this company plus current monthly
gross for uncovered employment months. Prior-month finalized TDS is deducted
from annual liability; the remainder is spread over the months left in the FY.
Current/future finalized slips are excluded when recalculating a historical
month. Missing months are estimated, not treated as zero income. Negative TDS
refund lines reduce the credit instead of becoming additional credit.

This remains a monthly salary estimator: split-month payroll, special-rate
income, previous-employer/migration opening balances and exact final settlement
need manual review/override. Already validated payslip lines are not changed.
Annual exemptions must be reviewed each FY and when the employee changes regime.

For an April-start resident under 60, ₹2,00,000 gross/month and no additional
deductions, FY 2026-27 annual tax is ₹2,92,500 under new regime and ₹5,38,200
under old regime. April TDS is ₹24,375 and ₹44,850 respectively. Starting
collection later without previous TDS produces higher monthly instalments.

## Official references

- [Income Tax Department: AY 2026-27 slabs, rebate, surcharge and cess](https://www.incometax.gov.in/iec/foportal/help/individual/return-applicable-1)
- [Income Tax Department: salary and standard deduction](https://www.incometaxindia.gov.in/en/income-from-salary)
- [Finance Bill 2026 memorandum: TY 2026-27 salary rates](https://www.incometaxindia.gov.in/documents/81799/11848482/memo-2026.pdf/fe530cfa-9c49-fc5c-4bfa-fc96fd5e7b7a?t=1770008674037)

## Regression test command

Run against an isolated test database (the tests create employee/payslip
records in rolled-back transactions):

```sh
19venv/bin/python odoo-bin -c community.conf -d codex_tds_regimes_test \
  -u ftp_employee_tds --test-enable --test-tags /ftp_employee_tds \
  --stop-after-init --http-port=8097 --max-cron-threads=0
```

## Verified staging run — 29 September 2026

Installed version 19.0.2.0.0 on local `erp19_staging_sep28`. All 21 module
regression tests passed on isolated `codex_tds_regimes_test` (cron and outgoing
mail servers disabled there). The staging employee form compiled successfully.

Persisted review samples in `erp19_staging_sep28`:

| Employee | Employee ID | Draft September payslip ID | Monthly TDS |
| --- | ---: | ---: | ---: |
| [TDS TEST] New Regime - 200000 Gross | 10 | 24 | ₹41,785.71 |
| [TDS TEST] Old Regime - 200000 Gross | 11 | 25 | ₹76,885.71 |

Both use ₹2 lakh monthly gross, an April 2026 employment start, no additional
approved deductions, resident status and no previous TDS. September spreads
the annual tax over seven remaining months. Payslips are draft, not posted.
Tharun N (ID 8) has ₹18,488 monthly gross in this database, projected annual
gross ₹2,21,856, and correctly computes ₹0 TDS.

These are local staging results; the remote server needs the updated addon
files and a module upgrade before it receives the same behavior.

## Company calculator review

See [WORKBOOK_REVIEW.md](WORKBOOK_REVIEW.md) for the supplied XLSB comparison,
confirmed workbook issues and scope. Version 19.0.2.0.1 adds statutory rounding
of taxable income and annual tax to ₹10; monthly estimates retain currency
precision. The expanded regression suite passes all 26 tests.
