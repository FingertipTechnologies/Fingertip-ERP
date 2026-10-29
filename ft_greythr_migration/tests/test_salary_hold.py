from datetime import date

from freezegun import freeze_time

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from . import test_payroll


@tagged('post_install', '-at_install')
class TestSalaryHold(TransactionCase):
    # Same employee and CTC as the payroll test.
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Payroll Mapping Test', 'country_id': cls.env.ref('base.in').id,
            'currency_id': cls.env.ref('base.INR').id,
        })
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=[cls.company.id],
            tracking_disable=True, mail_create_nosubscribe=True, mail_create_nolog=True))
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Payroll Test Employee', 'company_id': cls.company.id,
            'date_version': '2026-06-01', 'contract_date_start': '2026-06-01', 'wage': 30000,
        })
        cls.ctc = cls.env['ft.greythr.ctc'].create({
            'employee_id': cls.employee.id, 'effective_date': '2026-06-01',
            'full_basic': 15000, 'full_hra': 6000, 'full_special_allowance': 7499.5,
            'full_meal_allowance': 1000, 'full_leave_travel_allowance': 500,
            'full_gratuity': 721.15, 'monthly_gross': 30000, 'monthly_ctc': 32521.15,
            'eligible_for_pf': True, 'master_pf_basic': 15000, 'pf_base_limit': 15000,
            'payroll_pf_mode': 'capped',
        })
        cls.ctc.action_apply_to_payroll()
        cls.structure = cls.env.ref('ft_greythr_migration.greythr_structure')

    _slip = test_payroll.TestGreythrPayroll._slip

    def _leave(self, departure='2026-06-20'):
        self.ctc.payroll_reviewed = True
        self.employee.departure_date = departure
        slip = self._slip()
        slip.action_payslip_done()
        return slip

    def test_final_month_payslip_is_held_from_departure(self):
        slip = self._leave()
        self.assertTrue(slip.ft_salary_hold)
        self.assertEqual(slip.ft_hold_release_date, date(2026, 8, 4))
        # Only the month of the departure is held.
        self.assertFalse(self._slip(date_from='2026-07-01', date_to='2026-07-31').ft_salary_hold)

    def test_hold_days_follow_company_setting(self):
        self.company.ft_salary_hold_days = 60
        self.assertEqual(self._leave().ft_hold_release_date, date(2026, 8, 19))

    def test_held_payslip_cannot_be_paid(self):
        slip = self._leave()
        with self.assertRaises(UserError):
            slip.action_payslip_paid()
        with self.assertRaises(UserError):
            slip.action_payslip_payment_report()
        wizard = self.env['hr.payroll.payment.report.wizard'].create({'payslip_ids': slip.ids})
        with self.assertRaises(UserError):  # nothing payable left in the file
            wizard._perform_checks()

    def test_pay_run_pays_the_others_and_closes(self):
        held = self._leave()
        # HR can take a payslip off hold by hand; this one is paid with the run.
        other = self._slip()
        other.ft_salary_hold = False
        other.action_payslip_done()
        run = self.env['hr.payslip.run'].create({
            'name': 'June', 'date_start': '2026-06-01', 'date_end': '2026-06-30',
            'slip_ids': [(6, 0, (held | other).ids)]})
        run.action_paid()
        self.assertEqual(other.state, 'paid')
        self.assertEqual(held.state, 'validated')
        self.assertEqual(run.state, '03_paid')
        run.action_unpaid()
        self.assertEqual(other.state, 'validated')

    def test_release_needs_date_and_exit_clearance(self):
        slip = self._leave()
        with freeze_time('2026-08-10'):
            with self.assertRaises(UserError):  # no exit clearance yet
                slip.action_ft_release_salary()
        with freeze_time('2026-07-01'):
            self.employee.action_ft_exit_clearance()
            with self.assertRaises(UserError):  # before the release date
                slip.action_ft_release_salary()
        with freeze_time('2026-08-04'):
            slip.action_ft_release_salary()
        self.assertFalse(slip.ft_salary_hold)
        self.assertEqual(slip.ft_salary_released_date, date(2026, 8, 4))
        slip.action_payslip_paid()
        self.assertEqual(slip.state, 'paid')

    def test_exit_clearance_waits_for_offboarding_checklist(self):
        self.employee.departure_date = '2026-06-20'
        plan = self.env.ref('hr.offboarding_plan')
        self.employee.activity_schedule(summary=plan.template_ids[0].summary, user_id=self.env.uid)
        with self.assertRaises(UserError):
            self.employee.action_ft_exit_clearance()
        self.employee.activity_ids.action_feedback()
        self.employee.action_ft_exit_clearance()
        self.assertTrue(self.employee.ft_exit_cleared_date)

    def test_exit_clearance_needs_departure(self):
        with self.assertRaises(UserError):
            self.employee.action_ft_exit_clearance()
