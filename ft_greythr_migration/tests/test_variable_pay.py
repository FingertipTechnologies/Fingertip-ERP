from dateutil.relativedelta import relativedelta

from odoo import Command, fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestVariablePay(TransactionCase):
    """Variable pay typed on the payslip, up to the annual target per FY."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Variable Pay Test', 'country_id': cls.env.ref('base.in').id,
            'currency_id': cls.env.ref('base.INR').id,
        })
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=[cls.company.id],
            tracking_disable=True, mail_create_nosubscribe=True, mail_create_nolog=True))
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Variable Pay Employee', 'company_id': cls.company.id,
            'date_version': '2026-04-01', 'contract_date_start': '2026-04-01', 'wage': 30000,
        })
        cls.ctc = cls.env['ft.greythr.ctc'].create({
            'employee_id': cls.employee.id, 'effective_date': '2026-04-01',
            'full_basic': 15000, 'full_hra': 6000, 'full_special_allowance': 7500,
            'full_meal_allowance': 1000, 'full_leave_travel_allowance': 500,
            'full_gratuity': 721.15, 'monthly_gross': 30000, 'monthly_ctc': 32521.15,
            'annual_variable_pay': 60000,
            'eligible_for_pf': True, 'master_pf_basic': 15000, 'pf_base_limit': 15000,
            'payroll_pf_mode': 'capped', 'payroll_reviewed': True,
        })
        cls.ctc.action_apply_to_payroll()
        cls.structure = cls.env.ref('ft_greythr_migration.greythr_structure')

    def _slip(self, date_from='2026-06-01', date_to='2026-06-30', amount=0):
        attendance = self.env.ref('hr_work_entry.work_entry_type_attendance')
        slip = self.env['hr.payslip'].create({
            'name': 'VP Slip', 'employee_id': self.employee.id,
            'date_from': date_from, 'date_to': date_to, 'struct_id': self.structure.id,
            'worked_days_line_ids': [Command.create({
                'work_entry_type_id': attendance.id,
                'number_of_days': 20, 'number_of_hours': 160})],
        })
        if amount:
            slip.ft_variable_pay_amount = amount
        slip.compute_sheet()
        return slip

    def _lines(self, slip):
        return {line.code: line.total for line in slip.line_ids}

    # ------------------------------------------------------------------
    def test_annual_target_on_the_version(self):
        self.assertEqual(self.employee.ft_annual_variable_pay, 60000)
        with self.assertRaises(ValidationError):
            self.employee.version_id.ft_annual_variable_pay = -1

    def test_nothing_paid_unless_typed(self):
        self.assertNotIn('VAR_PAY', self._lines(self._slip()))

    def test_typed_amount_reaches_gross_and_net(self):
        """VAR_PAY must survive the gross reconciliation."""
        baseline = self._lines(self._slip())
        lines = self._lines(self._slip('2026-07-01', '2026-07-31', amount=12000))
        self.assertAlmostEqual(lines['VAR_PAY'], 12000, places=2)
        self.assertAlmostEqual(lines['GROSS'], baseline['GROSS'] + 12000, places=2)
        self.assertAlmostEqual(lines['NET'], baseline['NET'] + 12000, places=2)
        self.assertAlmostEqual(lines['CTC_TOTAL'], baseline['CTC_TOTAL'] + 12000, places=2)
        # Variable pay sits outside the fixed monthly CTC.
        self.assertAlmostEqual(lines['CTC_DIFF'], baseline['CTC_DIFF'], places=2)

    def test_limited_to_the_annual_target(self):
        first = self._slip(amount=50000)
        first.action_payslip_done()
        slip = self._slip('2026-07-01', '2026-07-31')
        self.assertEqual(slip.ft_variable_pay_paid_fy, 50000)
        self.assertEqual(slip.ft_variable_pay_remaining, 10000)
        with self.assertRaises(ValidationError):
            slip.ft_variable_pay_amount = 15000
        slip.ft_variable_pay_amount = 10000
        slip.compute_sheet()
        self.assertAlmostEqual(self._lines(slip)['VAR_PAY'], 10000, places=2)
        with self.assertRaises(ValidationError):
            slip.ft_variable_pay_amount = -1

    def test_draft_and_cancelled_payslips_do_not_count(self):
        self._slip(amount=40000)                    # draft
        cancelled = self._slip('2026-05-01', '2026-05-31', amount=20000)
        cancelled.action_payslip_cancel()
        slip = self._slip('2026-07-01', '2026-07-31')
        self.assertEqual(slip.ft_variable_pay_paid_fy, 0)
        self.assertEqual(slip.ft_variable_pay_remaining, 60000)

    def test_two_drafts_cannot_both_be_confirmed_over_target(self):
        a = self._slip(amount=40000)
        b = self._slip('2026-07-01', '2026-07-31', amount=40000)
        a.action_payslip_done()
        with self.assertRaises(ValidationError):
            b.action_payslip_done()

    def test_financial_year_runs_april_to_march(self):
        self._slip('2027-03-01', '2027-03-31', amount=60000).action_payslip_done()
        # Still FY 2026-27: nothing left.
        with self.assertRaises(ValidationError):
            self._slip('2026-12-01', '2026-12-31', amount=1)
        # April 2027 starts a new financial year.
        april = self._slip('2027-04-01', '2027-04-30', amount=60000)
        self.assertEqual(april.ft_variable_pay_paid_fy, 0)

    def test_no_target_means_no_variable_pay(self):
        self.ctc.write({'annual_variable_pay': 0})
        self.ctc.action_apply_to_payroll()
        with self.assertRaises(ValidationError):
            self._slip(amount=1000)

    def test_employee_shows_paid_and_remaining(self):
        # The employee shows the financial year we are in today.
        start = fields.Date.today().replace(day=1)
        self._slip(start, start + relativedelta(months=1, days=-1), amount=15000).action_payslip_done()
        self.assertEqual(self.employee.ft_variable_pay_paid_fy, 15000)
        self.assertEqual(self.employee.ft_variable_pay_remaining, 45000)


@tagged('post_install', '-at_install')
class TestVariablePayRegularStructure(TransactionCase):
    """The stock India structure pays it too, without any greytHR CTC."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Regular VP Test', 'country_id': cls.env.ref('base.in').id,
            'currency_id': cls.env.ref('base.INR').id,
        })
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=[cls.company.id],
            tracking_disable=True, mail_create_nosubscribe=True, mail_create_nolog=True))
        cls.structure = cls.env.ref(
            'l10n_in_hr_payroll.hr_payroll_structure_in_employee_salary')
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Native Salary Employee', 'company_id': cls.company.id,
            'date_version': '2026-04-01', 'contract_date_start': '2026-04-01',
            'wage': 17226, 'structure_type_id': cls.structure.type_id.id,
        })
        cls.employee.version_id.ft_annual_variable_pay = 60000

    def _slip(self, amount=0):
        att = self.env.ref('hr_work_entry.work_entry_type_attendance')
        slip = self.env['hr.payslip'].create({
            'name': 'Regular VP', 'employee_id': self.employee.id,
            'date_from': '2026-06-01', 'date_to': '2026-06-30', 'struct_id': self.structure.id,
            'worked_days_line_ids': [Command.create({
                'work_entry_type_id': att.id, 'number_of_days': 20, 'number_of_hours': 160})],
        })
        slip.ft_variable_pay_amount = amount
        slip.compute_sheet()
        return {line.code: line.total for line in slip.line_ids}

    def test_payout_reaches_gross_and_net_without_a_ctc(self):
        self.assertFalse(self.employee.version_id.greythr_ctc_id)
        baseline = self._slip()
        lines = self._slip(12000)
        self.assertAlmostEqual(lines['VAR_PAY'], 12000, places=2)
        self.assertAlmostEqual(lines['GROSS'], baseline['GROSS'] + 12000, places=2)
        self.assertAlmostEqual(lines['NET'], baseline['NET'] + 12000, places=2)
