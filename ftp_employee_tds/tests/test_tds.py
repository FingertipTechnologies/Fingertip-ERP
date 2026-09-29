# -*- coding: utf-8 -*-
"""TDS arithmetic, projection and spreading."""
from datetime import date

from odoo import Command, fields
from odoo.tests import TransactionCase, tagged

from odoo.addons.ftp_employee_tds.models.tds_slabs import (
    annual_tax_on, standard_deduction,
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
    # The arithmetic, against Odoo's own wizard
    # ------------------------------------------------------------------
    def test_01_slab_maths_is_right(self):
        """Hand-worked figures against the shipped slab chart.

        Slabs 0/3/6/9/12/15L at 0/5/10/15/20/30%, standard deduction 50,000,
        87A threshold 7,00,000, 4% cess. Checked by hand rather than against
        l10n_in's wizard, whose totals are computed from a net-pay projection.
        """
        deduction = standard_deduction(self.env, self.today)
        self.assertAlmostEqual(deduction, 50000, 2)
        cases = {
            # gross: expected total tax
            400000: 0.0,        # taxable 3.5L -> 2,500 slab tax, fully rebated
            800000: 31200.0,    # taxable 7.5L -> 30,000 + 4% cess
            1400000: 124800.0,  # taxable 13.5L -> 120,000 + 4% cess
        }
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
        employee, version = self._employee(100000)
        april = version._ftp_tds_breakdown(date(2026, 4, 15))
        january = version._ftp_tds_breakdown(date(2027, 1, 15))
        self.assertEqual(april['months_remaining'], 12)
        self.assertEqual(january['months_remaining'], 3)
        # The year's income is the same either way: employed all twelve months.
        self.assertAlmostEqual(april['projected_gross'], 1200000, 2)
        self.assertAlmostEqual(january['projected_gross'], 1200000, 2)
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
        self.assertAlmostEqual(version.l10n_in_tds, 0.0, 2)
        version._ftp_apply_tds(self.today)
        self.assertGreater(version.l10n_in_tds, 0.0)
        expected = version._ftp_tds_breakdown(self.today)['monthly_tds']
        self.assertAlmostEqual(version.l10n_in_tds, expected, 2)

    def test_08_opt_out_is_left_alone(self):
        """Old-regime employees keep whatever HR typed."""
        employee, version = self._employee(200000)
        version.ftp_tds_auto = False
        version.l10n_in_tds = 4321.0
        version._ftp_apply_tds(self.today)
        self.assertAlmostEqual(version.l10n_in_tds, 4321.0, 2)

    def test_09_company_switch_stops_everything(self):
        employee, version = self._employee(200000)
        self.company.ftp_tds_auto_enabled = False
        version._ftp_apply_tds(self.today)
        self.assertAlmostEqual(version.l10n_in_tds, 0.0, 2)

    def test_10_low_earner_gets_no_tds(self):
        employee, version = self._employee(30000)   # 3.6L/yr, under the rebate
        version._ftp_apply_tds(self.today)
        self.assertAlmostEqual(version.l10n_in_tds, 0.0, 2)

    def test_11_cron_runs_and_is_idempotent(self):
        employee, version = self._employee(200000)
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
