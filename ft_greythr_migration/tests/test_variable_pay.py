from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged, new_test_user
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestVariablePay(TransactionCase):
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
        cls.input_type = cls.env.ref('ft_greythr_migration.input_type_variable_pay')

    def _record(self, **vals):
        values = {
            'employee_id': self.employee.id, 'company_id': self.company.id,
            'financial_year': 2026, 'quarter': 'q1', 'performance_percentage': 80,
        }
        values.update(vals)
        return self.env['hr.variable.pay'].create(values)

    def _slip(self, date_from='2026-06-01', date_to='2026-06-30'):
        attendance = self.env.ref('hr_work_entry.work_entry_type_attendance')
        slip = self.env['hr.payslip'].create({
            'name': 'VP Slip', 'employee_id': self.employee.id,
            'date_from': date_from, 'date_to': date_to, 'struct_id': self.structure.id,
            'worked_days_line_ids': [Command.create({
                'work_entry_type_id': attendance.id,
                'number_of_days': 20, 'number_of_hours': 160})],
        })
        slip.compute_sheet()
        return slip

    # ------------------------------------------------------------------
    # Targets on the contract
    # ------------------------------------------------------------------
    def test_quarterly_target_is_annual_over_four(self):
        self.assertEqual(self.employee.ft_annual_variable_pay, 60000)
        self.assertEqual(self.employee.ft_quarterly_variable_pay, 15000)
        self.assertEqual(self.employee.version_id.ft_quarterly_variable_pay, 15000)

    def test_annual_target_cannot_be_negative(self):
        with self.assertRaises(ValidationError):
            self.employee.version_id.ft_annual_variable_pay = -1

    def test_target_defaults_from_contract(self):
        self.assertEqual(self._record().quarterly_target, 15000)

    # ------------------------------------------------------------------
    # Quarter arithmetic (Indian financial year)
    # ------------------------------------------------------------------
    def test_quarters_follow_indian_financial_year(self):
        expected = {
            'q1': ('2026-04-01', '2026-06-30'), 'q2': ('2026-07-01', '2026-09-30'),
            'q3': ('2026-10-01', '2026-12-31'), 'q4': ('2027-01-01', '2027-03-31'),
        }
        for quarter, (start, end) in expected.items():
            record = self._record(quarter=quarter)
            self.assertEqual(str(record.date_start), start, quarter)
            self.assertEqual(str(record.date_end), end, quarter)
            self.assertEqual(str(record.payout_date), end, quarter)
            record.unlink()
        self.assertEqual(self._record().financial_year_label, 'FY 2026-27')

    # ------------------------------------------------------------------
    # Amounts
    # ------------------------------------------------------------------
    def test_payable_is_target_times_performance(self):
        record = self._record()
        self.assertEqual(record.amount_computed, 12000)
        self.assertEqual(record.amount_payable, 12000)

    def test_manual_override_survives_recompute(self):
        record = self._record()
        record.write({'use_override': True, 'amount_override': 13500})
        self.assertEqual(record.amount_payable, 13500)
        # Changing a driver of the calculated amount must not wipe the override.
        record.performance_percentage = 50
        self.assertEqual(record.amount_computed, 7500)
        self.assertEqual(record.amount_payable, 13500)

    def test_negative_amounts_rejected(self):
        with self.assertRaises(ValidationError):
            self._record(performance_percentage=-10)
        record = self._record()
        with self.assertRaises(ValidationError):
            record.write({'use_override': True, 'amount_override': -5})

    def test_duplicate_quarter_rejected(self):
        self._record()
        # savepoint so the failed INSERT does not poison the test transaction.
        with self.assertRaises(Exception), mute_logger('odoo.sql_db'), self.cr.savepoint():
            self._record()
            self.env.flush_all()

    # ------------------------------------------------------------------
    # Workflow and access
    # ------------------------------------------------------------------
    def test_workflow_states(self):
        record = self._record()
        self.assertEqual(record.state, 'draft')
        record.action_submit()
        self.assertEqual(record.state, 'submitted')
        record.action_approve()
        self.assertEqual(record.state, 'approved')
        self.assertEqual(record.approved_by_id, self.env.user)
        self.assertTrue(record.approval_date)

    def test_only_payroll_manager_approves(self):
        officer = new_test_user(
            self.env, login='vp_officer', groups='hr_payroll.group_hr_payroll_user',
            company_id=self.company.id)
        record = self._record()
        record.action_submit()
        with self.assertRaises(UserError):
            record.with_user(officer).action_approve()

    def test_approved_record_is_frozen_for_officer(self):
        officer = new_test_user(
            self.env, login='vp_officer2', groups='hr_payroll.group_hr_payroll_user',
            company_id=self.company.id)
        record = self._record()
        record.action_submit()
        record.action_approve()
        with self.assertRaises(UserError):
            record.with_user(officer).write({'performance_percentage': 100})

    # ------------------------------------------------------------------
    # Payslip integration
    # ------------------------------------------------------------------
    def _approved(self, **vals):
        record = self._record(**vals)
        record.action_submit()
        record.action_approve()
        return record

    def test_approved_amount_reaches_payslip_gross_and_net(self):
        """The whole point: VAR_PAY must survive the gross reconciliation."""
        baseline = {line.code: line.total for line in self._slip().line_ids}
        self._approved()
        lines = {line.code: line.total for line in self._slip().line_ids}
        self.assertAlmostEqual(lines['VAR_PAY'], 12000, places=2)
        # Fixed gross is unchanged; gross and net both rise by exactly the payout.
        self.assertAlmostEqual(lines['GROSS'], baseline['GROSS'] + 12000, places=2)
        self.assertAlmostEqual(lines['NET'], baseline['NET'] + 12000, places=2)
        # CTC_TOTAL is actual employer cost for the month, so it rightly rises.
        self.assertAlmostEqual(lines['CTC_TOTAL'], baseline['CTC_TOTAL'] + 12000, places=2)
        # CTC_DIFF reconciles against the FIXED monthly CTC, which variable pay
        # sits outside of, so it must not move - a nonzero value here would be
        # reported as a mapping error every payout quarter.
        self.assertAlmostEqual(lines['CTC_DIFF'], baseline['CTC_DIFF'], places=2)
        self.assertAlmostEqual(lines['CTC_DIFF'], 0, places=2)

    def test_no_monthly_accrual_outside_payout_period(self):
        self._approved()
        lines = {line.code: line.total for line in self._slip('2026-05-01', '2026-05-31').line_ids}
        self.assertNotIn('VAR_PAY', lines)

    def test_input_line_created_with_right_type(self):
        self._approved()
        slip = self._slip()
        inputs = slip.input_line_ids.filtered(lambda i: i.input_type_id == self.input_type)
        self.assertEqual(len(inputs), 1)
        self.assertEqual(inputs.code, 'VAR_PAY')
        self.assertAlmostEqual(inputs.amount, 12000, places=2)

    def test_payslip_lifecycle_links_and_pays(self):
        record = self._approved()
        slip = self._slip()
        slip.action_payslip_done()
        self.assertEqual(record.payslip_id, slip)
        self.assertEqual(record.state, 'approved')
        slip.action_payslip_paid()
        self.assertEqual(record.state, 'paid')

    def test_cannot_be_paid_twice(self):
        record = self._approved()
        first = self._slip()
        first.action_payslip_done()
        self.assertEqual(record.payslip_id, first)
        # A second payslip for the same period must not pick the amount up again.
        second = self._slip()
        self.assertFalse(second.input_line_ids.filtered(
            lambda i: i.input_type_id == self.input_type))

    def test_cancelling_payslip_releases_the_quarter(self):
        record = self._approved()
        slip = self._slip()
        slip.action_payslip_done()
        slip.action_payslip_cancel()
        self.assertFalse(record.payslip_id)
        self.assertEqual(record.state, 'approved')

    def test_paid_record_cannot_be_deleted(self):
        record = self._approved()
        slip = self._slip()
        slip.action_payslip_done()
        with self.assertRaises(UserError):
            record.unlink()


@tagged('post_install', '-at_install')
class TestVariablePayRegularStructure(TransactionCase):
    """Variable pay on stock India: Regular Pay, with no greytHR CTC involved.

    This is the path for employees whose salary is maintained natively in Odoo
    rather than imported from greytHR: nothing is re-entered on a CTC record,
    and no CTC is applied to the version at all.
    """
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Regular Pay VP Test', 'country_id': cls.env.ref('base.in').id,
            'currency_id': cls.env.ref('base.INR').id,
        })
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=[cls.company.id],
            tracking_disable=True, mail_create_nosubscribe=True, mail_create_nolog=True))
        cls.structure = cls.env.ref(
            'l10n_in_hr_payroll.hr_payroll_structure_in_employee_salary')
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Native Salary Employee', 'company_id': cls.company.id,
            'date_version': '2026-04-01', 'contract_date_start': '2026-04-01',
            'wage': 17226,
            'structure_type_id': cls.structure.type_id.id,
        })
        # The only thing HR sets for variable pay: the annual target.
        cls.employee.version_id.ft_annual_variable_pay = 60000

    def _slip(self, date_from, date_to):
        att = self.env.ref('hr_work_entry.work_entry_type_attendance')
        slip = self.env['hr.payslip'].create({
            'name': 'Regular VP', 'employee_id': self.employee.id,
            'date_from': date_from, 'date_to': date_to, 'struct_id': self.structure.id,
            'worked_days_line_ids': [Command.create({
                'work_entry_type_id': att.id,
                'number_of_days': 20, 'number_of_hours': 160})],
        })
        slip.compute_sheet()
        return slip

    def test_no_greythr_ctc_is_required(self):
        self.assertFalse(self.employee.version_id.greythr_ctc_id)
        self.assertEqual(self.employee.ft_quarterly_variable_pay, 15000)

    def test_payout_reaches_gross_and_net_without_a_ctc(self):
        baseline = {line.code: line.total for line in self._slip('2026-06-01', '2026-06-30').line_ids}
        record = self.env['hr.variable.pay'].create({
            'employee_id': self.employee.id, 'company_id': self.company.id,
            'financial_year': 2026, 'quarter': 'q1', 'performance_percentage': 80,
        })
        record.action_submit()
        record.action_approve()
        self.assertEqual(record.amount_payable, 12000)
        lines = {line.code: line.total for line in self._slip('2026-06-01', '2026-06-30').line_ids}
        self.assertAlmostEqual(lines['VAR_PAY'], 12000, places=2)
        self.assertAlmostEqual(lines['GROSS'], baseline['GROSS'] + 12000, places=2)
        self.assertAlmostEqual(lines['NET'], baseline['NET'] + 12000, places=2)

    def test_nothing_in_a_non_payout_month(self):
        record = self.env['hr.variable.pay'].create({
            'employee_id': self.employee.id, 'company_id': self.company.id,
            'financial_year': 2026, 'quarter': 'q1', 'performance_percentage': 80,
        })
        record.action_submit()
        record.action_approve()
        lines = {line.code: line.total for line in self._slip('2026-05-01', '2026-05-31').line_ids}
        self.assertNotIn('VAR_PAY', lines)
