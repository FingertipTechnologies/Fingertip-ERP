# Company workbook review — 29 September 2026

Reviewed `Income_Tax_Calculator_2026_27 - Copy.xlsb`, sheets `INSTRUCTIONS`
and `FY-2026-27`. The original was not edited. Original SHA256:
`eb1b110c9e865b092c0f36d0bb19b01550556e1e69a400589d41b07c7d84ecc0`.

## Current sample reconciliation

| Item | Old regime | New regime |
| --- | ---: | ---: |
| Annual gross, O52/P52 | ₹37,20,000 | ₹37,20,000 |
| Standard deduction, O67/P67 | ₹50,000 | ₹75,000 |
| Professional tax, O68/P68 | ₹2,400 | ₹0 |
| Claimed house-property loss, O72/P72 | ₹2,00,000 | ₹0 |
| Capped 80C, O82/P82 | ₹1,50,000 | ₹0 |
| Taxable income, O96/P96 | ₹33,17,600 | ₹36,45,000 |
| Slab tax, O104/P104 | ₹8,07,780 | ₹6,73,500 |
| Workbook annual result, O113/P113 | ₹8,40,091 | ₹7,00,440 |
| Module annual result after statutory rounding | ₹8,40,090 | ₹7,00,440 |

Eligibility of the workbook's declarations is assumed for this arithmetic
comparison; documentary eligibility is not established by a filled-in cell.
For the same salary in Odoo, enter old-regime approved deductions of ₹3,52,400
(excluding standard deduction), and zero under new regime. Odoo calculates
standard deduction itself. PF must not be counted again outside the capped
80C total. The module does not calculate/approve each investment individually.

## Confirmed workbook defects and cautions

- `O106` incorrectly grants old-regime rebate/marginal relief above ₹5 lakh.
  Native recalculation at taxable income ₹5,00,100 yields ₹104 tax, whereas
  the correct amount is ₹13,020.80 before final rounding (₹13,020 rounded).
  The module correctly gives no old-regime rebate above the threshold.
- `P111` has no final surcharge branch above ₹50 crore. At ₹50,00,00,100
  taxable income it returns zero surcharge. The module retains the 25% new-
  regime surcharge. Normal ₹1 crore / ₹2 crore boundaries, and ₹5 crore old-
  regime boundary, were recalculated and agree before final rounding.
- `O96/P96` display rounded taxable income, but slab formulas use unrounded
  `M223/N232`. `O113/P113` also stop at whole rupees. The module now rounds
  taxable income before slabs/rebate and annual liability after cess to the
  nearest ₹10, ignoring paise and rounding five upwards.
- `L182` labels senior status from approximate ages 59.01/79.1, while the
  actual old-regime tax selects fixed birth-date cutoffs in `N223`. The
  displayed label can therefore disagree with the tax calculation. Odoo
  uses actual age at financial-year end and tax-residency status.
- `O114/P114` count all twelve filled TDS cells in `D41:O41` (₹7,01,000),
  while `O117` says eleven months remain. These inputs must describe the
  same as-of date. Future estimated deductions should not be called paid TDS.
  Odoo uses only prior-month finalized payslips; the module does not import
  this workbook or bank/previous-employer tax credits automatically.
- `L6/L7` are annual tax divided by twelve. `O118/P118` instead deduct paid
  TDS and divide the balance by remaining months. Compare Odoo to the latter
  with the same salary history, tax credits and calculation month. Monthly
  Odoo estimates retain currency precision; the workbook displays whole rupees.

The workbook has broader capital-gains, agricultural-income, perquisite and
investment eligibility calculations. These were not certified as a complete
return-filing calculator and are not silently incorporated into payroll.
The module supports normal salary income and HR-approved eligible deductions.

## Verification and changes

- Read cached values directly from the XLSB; key sample amounts match a
  LibreOffice recalculation of a temporary conversion.
- Inspected formulas and recalculated ten boundary scenarios in disposable
  copies using LibreOffice, without modifying the original. Microsoft Excel
  native recalculation and macros were not run.
- Added statutory rounding to `models/tds_slabs.py`; version 19.0.2.0.1.
- Added tests for the workbook sample, rebate/rounding boundaries, large-income
  surcharge, finalized prior-month tax credits, exclusion of current/future
  credits and an over-deduction producing zero further TDS.
- All 26 Odoo tests passed on `codex_tds_regimes_test`, including employee and
  draft-payslip creation. An initial test fixture incorrectly changed line
  amounts without their stored totals; the corrected fixture passed.
- Changes for this review are confined to `ftp_employee_tds`. No commit/push.
  The running server needs to load the updated Python code before using the
  rounding change; the review did not restart the user's running service.

## Official references

- [Income Tax Department: slabs, rebate, surcharge and cess](https://www.incometax.gov.in/iec/foportal/help/individual/return-applicable-1)
- [Income-tax Act 2025, amended by Finance Act 2026: section 516 rounding](https://www.incometaxindia.gov.in/documents/d/guest/income_tax_act_2025_as_amended_by_fa_act_2026-pdf)
- [Earlier section 288A: rounding total income](https://www.incometaxindia.gov.in/w/section-288a-27)
- [Earlier section 288B: rounding tax payable](https://www.incometaxindia.gov.in/w/section-288b-9)
