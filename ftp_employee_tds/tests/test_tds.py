# -*- coding: utf-8 -*-
"""TDS arithmetic, projection and spreading."""
from datetime import date

from odoo import Command, fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.ftp_employee_tds.models.tds_slabs import (
    annual_tax_on, standard_deduction, round_statutory_amount,
)


@tagged('post_install', '-at_install')
class TestTds(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'TDS Test Co',
            'country_id': cls.env.ref('base.in').id,
            'currency_id': cls.env.ref('base.INR').id,
        })
        cls.env = cls.env(context=dict(
            cls.env.context, allowed_company_ids=[cls.company.id],
            tracking_disable=True, mail_create_nosubscribe=True,
            mail_create_nolog=True))
        cls.env.user.group_ids |= cls.env.ref('hr_payroll.group_hr_payroll_manager')
        cls.today = date(2026, 4, 15)          # month 1 of FY 2026-27

    def _employee(self, monthly_gross):
        employee = self.env['hr.employee'].create({
            'name': 'TDS Employee', 'company_id': self.company.id,
            'date_version': date(2026, 4, 1),
            'contract_date_start': date(2026, 4, 1),
            'wage': monthly_gross,
        })
        version = employee.sudo().version_id
        # Drive the gross directly: the point here is the tax, not the payroll
        # structure that produced it. Wage and basic move together, or
        # l10n_in's "allowances must not exceed the wage" check fires.
        version.write({'wage': monthly_gross,
                       'l10n_in_basic_salary_amount': monthly_gross})
        return employee, version

    # ------------------------------------------------------------------
    # The arithmetic, against hand-worked statutory examples
    # ------------------------------------------------------------------
    def test_01_slab_maths_is_right(self):
        """FY 2026-27 normal salary income, 75,000 standard deduction."""
        deduction = standard_deduction(self.env, self.today)
        self.assertAlmostEqual(deduction, 75000, 2)
        cases = {400000: 0.0, 800000: 0.0, 1400000: 81900.0, 2400000: 292500.0}
        for gross, expected in cases.items():
            with self.subTest(gross=gross):
                result = annual_tax_on(self.env, gross - deduction, self.today)
                self.assertAlmostEqual(result['total_tax'], expected, 2)

    def test_01b_surcharge_applies_above_fifty_lakh(self):
        deduction = standard_deduction(self.env, self.today)
        below = annual_tax_on(self.env, 4000000 - deduction, self.today)
        above = annual_tax_on(self.env, 8000000 - deduction, self.today)
        self.assertAlmostEqual(below['surcharge'], 0.0, 2)
        self.assertGreater(above['surcharge'], 0.0)

    def test_02_low_income_is_fully_rebated(self):
        """Under the 87A threshold there is no tax at all."""
        result = annual_tax_on(self.env, 500000, self.today)
        self.assertAlmostEqual(result['total_tax'], 0.0, 2)

    def test_03_cess_is_four_percent(self):
        result = annual_tax_on(self.env, 1500000, self.today)
        expected = (result['tax_after_rebate'] + result['surcharge']) * 0.04
        self.assertAlmostEqual(result['cess'], expected, 2)

    # ------------------------------------------------------------------
    # Projection and spreading
    # ------------------------------------------------------------------
    def test_04_projects_from_gross_not_net(self):
        """The whole point: tax follows gross pay, not take-home."""
        employee, version = self._employee(100000)
        figures = version._ftp_tds_breakdown(self.today)
        self.assertAlmostEqual(figures['monthly_gross'], 100000, 2)
        self.assertAlmostEqual(figures['projected_gross'], 1200000, 2)
        self.assertEqual(figures['months_remaining'], 12)

    def test_05_spreads_over_remaining_months(self):
        """Starting in month 10 spreads the year's tax over 3, not 12."""
        employee, version = self._employee(200000)
        april = version._ftp_tds_breakdown(date(2026, 4, 15))
        january = version._ftp_tds_breakdown(date(2027, 1, 15))
        self.assertEqual(april['months_remaining'], 12)
        self.assertEqual(january['months_remaining'], 3)
        # The year's income is the same either way: employed all twelve months.
        self.assertAlmostEqual(april['projected_gross'], 2400000, 2)
        self.assertAlmostEqual(january['projected_gross'], 2400000, 2)
        # Same tax, fewer months left, so each instalment is larger.
        self.assertAlmostEqual(january['total_tax'], april['total_tax'], 2)
        self.assertGreater(january['monthly_tds'], april['monthly_tds'])

    def test_05b_months_without_payslips_are_still_taxed(self):
        """After a migration Odoo has no earlier payslips; income still counts."""
        employee, version = self._employee(100000)
        figures = version._ftp_tds_breakdown(date(2027, 1, 15))
        self.assertEqual(figures['months_employed'], 12)
        self.assertEqual(figures['months_covered_by_payslips'], 0)
        self.assertEqual(figures['months_estimated'], 12)
        self.assertAlmostEqual(figures['projected_gross'], 1200000, 2)

    def test_05c_mid_year_joiner_is_taxed_on_part_year(self):
        employee, version = self._employee(100000)
        version.contract_date_start = date(2026, 10, 1)
        figures = version._ftp_tds_breakdown(date(2026, 10, 15))
        self.assertEqual(figures['months_employed'], 6)   # Oct..Mar
        self.assertAlmostEqual(figures['projected_gross'], 600000, 2)

    def test_06_financial_year_runs_april_to_march(self):
        Version = self.env['hr.version']
        self.assertEqual(Version._ftp_financial_year(date(2026, 4, 1))[0],
                         date(2026, 4, 1))
        self.assertEqual(Version._ftp_financial_year(date(2027, 3, 31))[0],
                         date(2026, 4, 1))
        # March belongs to the year that started the previous April.
        self.assertEqual(Version._ftp_financial_year(date(2027, 3, 31))[1],
                         date(2027, 3, 31))
        self.assertEqual(Version._ftp_months_remaining(date(2027, 3, 1)), 1)

    def test_07_applies_to_the_field_the_rule_reads(self):
        employee, version = self._employee(200000)
        self.assertGreater(version.l10n_in_tds, 0.0)
        version._ftp_apply_tds(self.today)
        self.assertGreater(version.l10n_in_tds, 0.0)
        expected = version._ftp_tds_breakdown(self.today)['monthly_tds']
        self.assertAlmostEqual(version.l10n_in_tds, expected, 2)

    def test_08_opt_out_is_left_alone(self):
        """Manual overrides keep whatever HR typed."""
        employee, version = self._employee(200000)
        version.ftp_tds_auto = False
        version.l10n_in_tds = 4321.0
        version._ftp_apply_tds(self.today)
        self.assertAlmostEqual(version.l10n_in_tds, 4321.0, 2)

    def test_09_company_switch_stops_everything(self):
        employee, version = self._employee(200000)
        self.company.ftp_tds_auto_enabled = False
        version.l10n_in_tds = 0
        version._ftp_apply_tds(self.today)
        self.assertAlmostEqual(version.l10n_in_tds, 0.0, 2)

    def test_10_low_earner_gets_no_tds(self):
        employee, version = self._employee(30000)   # 3.6L/yr, under the rebate
        version._ftp_apply_tds(self.today)
        self.assertAlmostEqual(version.l10n_in_tds, 0.0, 2)

    def test_11_cron_runs_and_is_idempotent(self):
        employee, version = self._employee(200000)
        version.l10n_in_tds = 0
        first = self.env['hr.version']._cron_update_tds()
        self.assertGreaterEqual(first, 1)
        value = version.l10n_in_tds
        second = self.env['hr.version']._cron_update_tds()
        self.assertEqual(second, 0, "nothing should change on a second run")
        self.assertAlmostEqual(version.l10n_in_tds, value, 2)

    def test_12_pay_rise_raises_the_instalment(self):
        employee, version = self._employee(100000)
        version._ftp_apply_tds(self.today)
        before = version.l10n_in_tds
        version.write({'wage': 250000,
                       'l10n_in_basic_salary_amount': 250000})
        version._ftp_apply_tds(self.today)
        self.assertGreater(version.l10n_in_tds, before)

    def test_13_regime_and_approved_deductions(self):
        employee, version = self._employee(200000)
        version.ftp_tax_regime = 'old'
        figures = version._ftp_tds_breakdown(self.today)
        self.assertAlmostEqual(figures['total_tax'], 538200, 2)
        version.write({'ftp_tds_approved_deductions': 150000, 'ftp_tds_deduction_year': 2026})
        self.assertAlmostEqual(version._ftp_tds_breakdown(self.today)['total_tax'], 491400, 2)
        version.ftp_tds_deduction_year = 2025
        self.assertEqual(version._ftp_tds_breakdown(self.today)['approved_deductions'], 0)

    def test_14_residency_age_and_marginal_relief(self):
        self.assertEqual(annual_tax_on(self.env, 1200000, self.today)['total_tax'], 0)
        relief = annual_tax_on(self.env, 1200100, self.today)
        self.assertAlmostEqual(relief['unrounded_total_tax'], 104)
        self.assertEqual(relief['total_tax'], 100)
        self.assertAlmostEqual(annual_tax_on(self.env, 500000, self.today, 'old', False)['total_tax'], 13000)
        self.assertEqual(annual_tax_on(self.env, 500000, self.today, 'old', True, 80)['slab_tax'], 0)
        for regime in ('old', 'new'):
            for boundary in (5000000, 10000000, 20000000):
                base = annual_tax_on(self.env, boundary, self.today, regime)['unrounded_total_tax']
                above = annual_tax_on(self.env, boundary + 100, self.today, regime)['unrounded_total_tax']
                self.assertAlmostEqual(above - base, 104, 2)

    def test_15_save_automatically_recomputes(self):
        employee, version = self._employee(200000)
        self.assertGreater(version.l10n_in_tds, 0)
        before = version.l10n_in_tds
        version.write({'wage': 300000, 'l10n_in_basic_salary_amount': 300000})
        self.assertGreater(version.l10n_in_tds, before)
        version.ftp_tds_auto = False
        version.l10n_in_tds = 1234
        version.write({'wage': 200000, 'l10n_in_basic_salary_amount': 200000})
        self.assertEqual(version.l10n_in_tds, 1234)
        version.ftp_tds_auto = True
        self.assertNotEqual(version.l10n_in_tds, 1234)

    def test_16_payslip_recomputes_for_its_own_month(self):
        employee, version = self._employee(200000)
        structure = self.env.ref('l10n_in_hr_payroll.hr_payroll_structure_in_employee_salary')
        version.structure_type_id = structure.type_id
        slip = self.env['hr.payslip'].create({
            'name': 'TDS April integration test', 'employee_id': employee.id,
            'version_id': version.id, 'struct_id': structure.id,
            'date_from': date(2026, 4, 1), 'date_to': date(2026, 4, 30),
            'company_id': self.company.id,
        })
        version.l10n_in_tds = 1
        slip.compute_sheet()
        tds = slip.line_ids.filtered(lambda line: line.code == 'TDS')
        self.assertAlmostEqual(sum(tds.mapped('total')), -24375, 2)
        slip.compute_sheet()
        self.assertAlmostEqual(sum(slip.line_ids.filtered(lambda line: line.code == 'TDS').mapped('total')), -24375, 2)

    def test_17_regime_change_clears_old_exemptions(self):
        employee, version = self._employee(200000)
        version.write({'ftp_tax_regime': 'old', 'ftp_tds_approved_deductions': 150000})
        version.ftp_tax_regime = 'new'
        self.assertEqual(version.ftp_tds_approved_deductions, 0)

    def test_18_historical_rates(self):
        self.assertEqual(standard_deduction(self.env, date(2024, 3, 31)), 50000)
        self.assertEqual(standard_deduction(self.env, date(2024, 4, 1)), 75000)
        self.assertAlmostEqual(annual_tax_on(self.env, 1350000, date(2024, 3, 31))['total_tax'], 124800)
        self.assertAlmostEqual(annual_tax_on(self.env, 1325000, date(2024, 4, 1))['total_tax'], 109200)

    def test_19_company_workbook_example(self):
        """FY-2026-27!O52:P113: gross 37.2L, approved old deductions 3.524L.

        PT 2,400 + capped 80C 150,000 + eligible house-property loss 200,000.
        Workbook tax is 840,091 old / 700,440 new; statutory rounding makes
        old-regime annual liability 840,090, not the workbook's whole rupee.
        """
        employee, version = self._employee(310000)
        version.write({'ftp_tax_regime': 'old', 'ftp_tds_deduction_year': 2026,
                       'ftp_tds_approved_deductions': 352400})
        old = version._ftp_tds_breakdown(self.today)
        self.assertEqual(old['projected_gross'], 3720000)
        self.assertEqual(old['taxable_income'], 3317600)
        self.assertEqual(old['slab_tax'], 807780)
        self.assertAlmostEqual(old['unrounded_total_tax'], 840091.2)
        self.assertEqual(old['total_tax'], 840090)
        version.ftp_tax_regime = 'new'
        new = version._ftp_tds_breakdown(self.today)
        self.assertEqual(new['taxable_income'], 3645000)
        self.assertEqual(new['slab_tax'], 673500)
        self.assertEqual(new['total_tax'], 700440)
        self.assertEqual(new['monthly_tds'], 58370)

    def test_20_old_regime_has_no_rebate_above_five_lakh(self):
        self.assertEqual(annual_tax_on(self.env, 500000, self.today, 'old')['total_tax'], 0)
        result = annual_tax_on(self.env, 500100, self.today, 'old')
        self.assertEqual(result['rebate'], 0)
        self.assertEqual(result['slab_tax'], 12520)
        self.assertEqual(result['total_tax'], 13020)

    def test_21_rounding_near_rebate_thresholds(self):
        for amount, expected in [(104.99, 100), (105, 110), (125, 130),
                                 (0, 0), (-100, 0), (840091.2, 840090)]:
            with self.subTest(amount=amount):
                self.assertEqual(round_statutory_amount(amount), expected)
        for regime, threshold in [('old', 500000), ('new', 1200000)]:
            below = annual_tax_on(self.env, threshold + 4.99, self.today, regime)
            above = annual_tax_on(self.env, threshold + 5, self.today, regime)
            self.assertEqual(below['taxable_income'], threshold)
            self.assertEqual(below['total_tax'], 0)
            self.assertEqual(above['taxable_income'], threshold + 10)
            self.assertGreater(above['total_tax'], 0)

    def test_22_new_regime_surcharge_does_not_disappear_above_fifty_crore(self):
        # The company's P111 formula has a missing final branch at 50 crore.
        tax = annual_tax_on(self.env, 500000100, self.today)
        self.assertAlmostEqual(tax['surcharge'], tax['tax_after_rebate'] * .25)
        self.assertEqual(tax['total_tax'], 194454040)

    def test_23_prior_paid_tds_reduces_remaining_deduction(self):
        employee, version = self._employee(310000)
        version.write({'ftp_tax_regime': 'old', 'ftp_tds_deduction_year': 2026,
                       'ftp_tds_approved_deductions': 352400})
        structure = self.env.ref('l10n_in_hr_payroll.hr_payroll_structure_in_employee_salary')
        version.structure_type_id = structure.type_id
        slip = self.env['hr.payslip'].create({
            'name': 'TDS prior-month credit test', 'employee_id': employee.id,
            'version_id': version.id, 'struct_id': structure.id,
            'date_from': date(2026, 4, 1), 'date_to': date(2026, 4, 30),
            'company_id': self.company.id,
        })
        slip.compute_sheet()
        gross = slip.line_ids.filtered(lambda line: line.code == 'GROSS')
        gross.write({'amount': 310000, 'quantity': 1, 'rate': 100, 'total': 310000})
        tds = slip.line_ids.filtered(lambda line: line.code == 'TDS')
        tds.write({'amount': -63000, 'quantity': 1, 'rate': 100, 'total': -63000})
        # Mark only this transaction-scoped fixture final; no payment/posting.
        slip.state = 'validated'
        may = version._ftp_tds_breakdown(date(2026, 5, 1))
        self.assertEqual(may['projected_gross'], 3720000)
        self.assertEqual(may['tds_already_deducted'], 63000)
        self.assertEqual(may['months_remaining'], 11)
        self.assertEqual(may['monthly_tds'], 70644.55)
        # Later or current-month payslips must not change a historical estimate.
        april = version._ftp_tds_breakdown(self.today)
        self.assertEqual(april['tds_already_deducted'], 0)
        self.assertEqual(april['months_covered_by_payslips'], 0)
        tds.write({'amount': -900000, 'total': -900000})
        self.assertEqual(version._ftp_tds_breakdown(date(2026, 5, 1))['monthly_tds'], 0)

    # ------------------------------------------------------------------
    # Slab sets as data
    # ------------------------------------------------------------------
    def _company_set(self, **vals):
        """A copy of the FY 2026-27 new-regime set, only for the test company."""
        shared = self.env.ref('ftp_employee_tds.tds_slab_set_new_2026')
        return shared.copy({'company_id': self.company.id, 'active': True, **vals})

    def test_24_seeded_sets_cover_supported_years(self):
        SlabSet = self.env['ftp.tds.slab.set']
        for year in (2023, 2024, 2025, 2026):
            for regime in ('new', 'old'):
                with self.subTest(year=year, regime=regime):
                    self.assertTrue(SlabSet._ftp_find(date(year, 4, 1), regime, self.company))
                    self.assertTrue(SlabSet._ftp_find(date(year + 1, 3, 31), regime, self.company))

    def test_25_company_set_takes_priority_and_edits_change_the_tax(self):
        before = annual_tax_on(self.env, 2325000, self.today, company=self.company)
        company_set = self._company_set(cess_rate=0)
        after = annual_tax_on(self.env, 2325000, self.today, company=self.company)
        self.assertEqual(after['slab_set_id'], company_set.id)
        self.assertEqual(after['cess'], 0)
        self.assertLess(after['total_tax'], before['total_tax'])
        # A rate change entered by HR is picked up without any code change.
        company_set.line_ids.filtered(lambda line: not line.amount_to).rate = 40
        raised = annual_tax_on(self.env, 2500000, self.today, company=self.company)
        self.assertAlmostEqual(raised['slab_tax'], 300000 + 100000 * .40, 2)
        # Other companies still use the shared set.
        other = annual_tax_on(self.env, 2325000, self.today)
        self.assertNotEqual(other['slab_set_id'], company_set.id)

    def test_26_missing_year_asks_for_a_slab_set(self):
        with self.assertRaisesRegex(ValidationError, 'No active TDS slab set'):
            annual_tax_on(self.env, 1000000, date(2035, 4, 1))
        self.env['ftp.tds.slab.set'].create({
            'name': 'FY 2035-36', 'regime': 'new',
            'date_from': date(2035, 4, 1), 'date_to': date(2036, 3, 31),
            'line_ids': [Command.create({'amount_from': 0, 'amount_to': 500000, 'rate': 0}),
                         Command.create({'amount_from': 500000, 'rate': 10})],
        })
        self.assertEqual(annual_tax_on(self.env, 1000000, date(2035, 4, 1))['slab_tax'], 50000)

    def test_27_employee_override(self):
        employee, version = self._employee(200000)
        normal = version._ftp_tds_breakdown(self.today)
        self.assertEqual(version.ftp_tds_slab_set_current_id,
                         self.env['ftp.tds.slab.set']._ftp_find(fields.Date.today(), 'new', self.company))
        # An exception set overlaps the normal one but is never picked automatically.
        special = self._company_set(cess_rate=0, employee_only=True)
        self.assertNotEqual(version._ftp_tds_breakdown(self.today)['slab_set_id'], special.id)
        version.ftp_tds_slab_set_id = special
        overridden = version._ftp_tds_breakdown(self.today)
        self.assertEqual(overridden['slab_set_id'], special.id)
        self.assertLess(overridden['total_tax'], normal['total_tax'])
        # Outside its dates the override is ignored.
        self.assertNotEqual(version._ftp_tds_breakdown(date(2025, 4, 15))['slab_set_id'], special.id)
        # A slab set never carries across a regime change.
        version.ftp_tax_regime = 'old'
        self.assertFalse(version.ftp_tds_slab_set_id)
        with self.assertRaises(ValidationError):
            version.ftp_tds_slab_set_id = special

    def test_28_slab_sets_must_be_complete_and_not_overlap(self):
        SlabSet = self.env['ftp.tds.slab.set']
        base = {'name': 'Broken', 'regime': 'new', 'date_from': date(2040, 4, 1),
                'date_to': date(2041, 3, 31)}
        cases = {
            'gap': [Command.create({'amount_from': 0, 'amount_to': 100, 'rate': 0}),
                    Command.create({'amount_from': 200, 'rate': 10})],
            'not from zero': [Command.create({'amount_from': 100, 'rate': 10})],
            'closed last slab': [Command.create({'amount_from': 0, 'amount_to': 100, 'rate': 0})],
            'no slabs': [],
        }
        for label, lines in cases.items():
            with self.subTest(label), self.assertRaises(ValidationError):
                SlabSet.create({**base, 'line_ids': lines})
        with self.assertRaisesRegex(ValidationError, 'overlaps'):
            self._company_set()
            self._company_set()

    def test_29_used_slab_sets_are_locked_and_copies_start_archived(self):
        employee, version = self._employee(200000)
        company_set = self._company_set()
        structure = self.env.ref('l10n_in_hr_payroll.hr_payroll_structure_in_employee_salary')
        version.structure_type_id = structure.type_id
        slip = self.env['hr.payslip'].create({
            'name': 'TDS lock test', 'employee_id': employee.id,
            'version_id': version.id, 'struct_id': structure.id,
            'date_from': date(2026, 4, 1), 'date_to': date(2026, 4, 30),
            'company_id': self.company.id,
        })
        slip.compute_sheet()
        self.assertEqual(slip.ftp_tds_slab_set_id, company_set)
        company_set.cess_rate = 3        # draft payslips only: still editable
        company_set.cess_rate = 4
        slip.state = 'validated'
        self.assertTrue(company_set.is_locked)
        with self.assertRaises(UserError):
            company_set.cess_rate = 3
        with self.assertRaises(UserError):
            company_set.line_ids[:1].rate = 1
        company_set.name = 'Renaming is fine'
        copy = company_set.copy()
        self.assertFalse(copy.active)
        copy.cess_rate = 3
