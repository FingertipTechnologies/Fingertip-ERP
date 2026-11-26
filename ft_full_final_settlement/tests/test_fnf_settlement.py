from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestFnfSettlement(TransactionCase):
    """Joined 1-Apr-2020, resigned 10-Nov-2026, last day 30-Nov-2026, on a
    50,000 gross / 25,000 Basic salary, 6.5 days of casual leave left and a
    20,000 salary advance not yet recovered."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'F&F Test', 'country_id': cls.env.ref('base.in').id,
            'currency_id': cls.env.ref('base.INR').id,
        })
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=[cls.company.id],
            tracking_disable=True, mail_create_nosubscribe=True, mail_create_nolog=True))
        cls.casual = cls.env['hr.leave.type'].create({
            'name': 'Casual Leave (F&F test)', 'company_id': cls.company.id, 'requires_allocation': True,
            'request_unit': 'half_day'})
        cls.company.ft_fnf_encash_leave_type_ids = cls.casual
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Leaving Employee', 'company_id': cls.company.id,
            'date_version': '2020-04-01', 'contract_date_start': '2020-04-01',
            'greythr_pf_eligible': True, 'ft_gratuity_eligible': True,
            'wage': 50000, 'l10n_in_basic_salary_amount': 25000, 'l10n_in_hra': 12500,
            'ft_resignation_date': '2026-11-10',
        })
        allocation = cls.env['hr.leave.allocation'].create({
            'name': 'Casual 2026', 'employee_id': cls.employee.id, 'holiday_status_id': cls.casual.id,
            'number_of_days': 6.5, 'date_from': '2026-04-01', 'allocation_type': 'regular'})
        allocation.action_approve()
        advance = cls.env['hr.salary.advance'].create({
            'employee_id': cls.employee.id, 'advance_amount': 20000, 'monthly_installment': 10000,
            'advance_date': '2026-11-15'})
        advance.action_submit()
        advance.action_approve()
        cls.advance = advance
        cls.employee.departure_date = '2026-11-30'

    def _settlement(self):
        action = self.employee.action_ft_fnf_settlement()
        return self.env['ft.fnf.settlement'].with_context(action['context']).create({})

    def test_figures_from_the_settings(self):
        self.assertEqual(self.company.ft_fnf_notice_days, 90)
        fnf = self._settlement()
        self.assertEqual((str(fnf.resignation_date), str(fnf.last_working_date), str(fnf.joining_date)),
                         ('2026-11-10', '2026-11-30', '2020-04-01'))
        self.assertEqual((fnf.monthly_gross, fnf.monthly_basic), (50000, 25000))
        # Casual leave: 6.5 days x 50,000 / 30
        self.assertEqual(fnf.encash_days, 6.5)
        self.assertEqual(fnf.encash_amount, 10833)
        # 6 years 8 months: the part year counts, 15/26 x 25,000 x 7
        self.assertEqual(fnf.service_text, '6 years 8 months 0 days')
        self.assertEqual(fnf.gratuity_years, 7)
        self.assertEqual(fnf.gratuity_amount, 100962)
        # 21 of 90 days served: 69 days x 50,000 / 30
        self.assertEqual((fnf.notice_days, fnf.notice_served, fnf.notice_shortfall), (90, 21, 69))
        self.assertEqual(fnf.notice_recovery, 115000)
        self.assertEqual(fnf.advance_recovery, 20000)
        self.assertEqual(fnf.total_dues, 10833 + 100962)
        self.assertEqual(fnf.total_recoveries, 115000 + 20000)
        self.assertEqual(fnf.net_amount, 10833 + 100962 - 115000 - 20000)

    def test_hr_typed_amounts(self):
        fnf = self._settlement()
        fnf.write({'variable_pay_due': 12000, 'other_dues': 3000, 'other_recoveries': 25000, 'tds_amount': 4000})
        self.assertEqual(fnf.total_dues, 10833 + 100962 + 12000 + 3000)
        self.assertEqual(fnf.total_recoveries, 115000 + 20000 + 25000 + 4000)
        fnf.action_refresh()
        self.assertEqual(fnf.variable_pay_due, 12000, 'recalculating keeps what HR typed')

    def test_approve_creates_the_settlement_payslip(self):
        fnf = self._settlement()
        fnf.tds_amount = 1000
        fnf.action_approve()
        slip = fnf.payslip_id
        self.assertEqual(fnf.state, 'approved')
        self.assertEqual(slip.struct_id, self.env.ref('ft_full_final_settlement.fnf_structure'))
        lines = {line.code: line.total for line in slip.line_ids}
        self.assertEqual(lines['FNF_LEAVE_ENC'], 10833)
        self.assertEqual(lines['FNF_GRATUITY'], 100962)
        self.assertEqual(lines['FNF_NOTICE'], -115000)
        self.assertEqual(lines['SALARY_ADVANCE'], -20000)
        self.assertEqual(lines['FNF_TDS'], -1000)
        self.assertEqual(lines['NET'], fnf.net_amount)
        self.assertTrue(slip.ft_salary_hold, 'held with the last salary until released')
        # Validating the payslip recovers the whole advance.
        slip.action_payslip_done()
        self.assertEqual(set(self.advance.installment_ids.mapped('state')), {'deducted'})
        self.assertEqual(self.advance.remaining_amount, 0)
        slip.ft_salary_hold = False
        slip.action_payslip_paid()
        self.assertEqual(fnf.state, 'paid')

    def test_reset_to_draft_removes_the_payslip(self):
        fnf = self._settlement()
        fnf.action_approve()
        slip = fnf.payslip_id
        fnf.action_reset_to_draft()
        self.assertEqual(fnf.state, 'draft')
        self.assertFalse(slip.exists())
        self.assertEqual(set(self.advance.installment_ids.mapped('payslip_id').ids), set())
        fnf.action_cancel()
        self.assertEqual(fnf.state, 'cancel')

    def test_validated_payslip_blocks_reset(self):
        fnf = self._settlement()
        fnf.action_approve()
        fnf.payslip_id.action_payslip_done()
        with self.assertRaises(UserError):
            fnf.action_reset_to_draft()

    def test_one_settlement_per_employee(self):
        self._settlement()
        with mute_logger('odoo.sql_db'), self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self._settlement()
        # Opening it again from the employee shows the same one.
        self.assertTrue(self.employee.action_ft_fnf_settlement().get('res_id'))

    def test_no_resignation_no_notice_recovery(self):
        self.employee.ft_resignation_date = False
        fnf = self._settlement()
        self.assertEqual((fnf.notice_shortfall, fnf.notice_recovery), (0, 0))

    def test_settings_change_the_figures(self):
        company = self.company
        company.write({'ft_fnf_encash_basis': 'basic', 'ft_fnf_encash_divisor': 26,
                       'ft_fnf_notice_days': 60, 'ft_fnf_notice_basis': 'basic',
                       'ft_fnf_gratuity_part_year_months': 9})
        fnf = self._settlement()
        self.assertEqual(fnf.encash_amount, round(6.5 * 25000 / 26))           # 6,250
        self.assertEqual(fnf.notice_shortfall, 39)
        self.assertEqual(fnf.notice_recovery, round(39 * 25000 / 30))          # 32,500
        self.assertEqual(fnf.gratuity_years, 6, '8 months no longer counts as a year')
        self.assertEqual(fnf.gratuity_amount, round(15 / 26 * 25000 * 6))      # 86,538

    def test_gratuity_minimum_service_and_cap(self):
        self.company.ft_fnf_gratuity_min_years = 7
        fnf = self._settlement()
        self.assertEqual(fnf.gratuity_amount, 0)
        self.assertIn('Less than 7 years', fnf.gratuity_note)
        self.company.write({'ft_fnf_gratuity_min_years': 5, 'ft_fnf_gratuity_cap': 50000})
        fnf.action_refresh()
        self.assertEqual(fnf.gratuity_amount, 50000)
        self.assertIn('capped', fnf.gratuity_note)

    def test_gratuity_only_when_ticked(self):
        self.company.ft_fnf_gratuity_rule = 'ticked'
        self.employee.ft_gratuity_eligible = False
        fnf = self._settlement()
        self.assertEqual(fnf.gratuity_amount, 0)

    def test_gratuity_confirmed_by_hr(self):
        self.company.ft_fnf_gratuity_rule = 'manual'
        fnf = self._settlement()
        self.assertEqual(fnf.gratuity_amount, 100962)
        with self.assertRaises(UserError):
            fnf.action_approve()
        fnf.gratuity_confirmed = True
        fnf.action_approve()
        self.assertEqual(fnf.state, 'approved')

    def test_statement_prints(self):
        fnf = self._settlement()
        html = self.env['ir.actions.report']._render_qweb_html(
            'ft_full_final_settlement.report_fnf_statement', fnf.ids)[0].decode()
        self.assertIn('Full & Final Settlement Statement', html)
        self.assertIn('Leaving Employee', html)
        self.assertIn('Net Amount Recoverable from the Employee', html)
