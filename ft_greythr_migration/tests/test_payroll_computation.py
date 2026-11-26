"""End to end: a salary entered as a greytHR CTC record, the CTC breakup on the
employee, and the payslip computed from it must all tell the same story."""
from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPayrollComputation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Payroll Computation Test', 'country_id': cls.env.ref('base.in').id,
            'currency_id': cls.env.ref('base.INR').id,
        })
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=[cls.company.id],
            tracking_disable=True, mail_create_nosubscribe=True, mail_create_nolog=True))
        cls.structure = cls.env.ref('ft_greythr_migration.greythr_structure')
        cls.employee = cls.env['hr.employee'].create({
            'name': 'New Joiner', 'company_id': cls.company.id,
            'date_version': '2026-12-01', 'contract_date_start': '2026-12-01', 'wage': 1,
        })
        # A new joiner as HR types it: components, gross, CTC and a yearly variable pay.
        cls.ctc = cls.env['ft.greythr.ctc'].create({
            'employee_id': cls.employee.id, 'effective_date': '2026-12-01',
            'full_basic': 21000, 'full_hra': 10500, 'full_special_allowance': 7300,
            'full_meal_allowance': 1100, 'full_leave_travel_allowance': 1000,
            'full_gratuity': 1010.10, 'monthly_gross': 40900, 'monthly_ctc': 44910.10,
            'annual_variable_pay': 36000,
            'eligible_for_pf': True, 'payroll_pf_mode': 'capped',
            'master_pf_basic': 21000, 'pf_base_limit': 15000,
        })
        cls.ctc.action_apply_to_payroll()
        cls.version = cls.employee.version_id

    def _slip(self, employee=None, date_from='2026-12-01', date_to='2026-12-31'):
        attendance = self.env.ref('hr_work_entry.work_entry_type_attendance')
        slip = self.env['hr.payslip'].create({
            'name': 'Computation Test', 'employee_id': (employee or self.employee).id,
            'date_from': date_from, 'date_to': date_to, 'struct_id': self.structure.id,
            'worked_days_line_ids': [Command.create({
                'work_entry_type_id': attendance.id, 'number_of_days': 23, 'number_of_hours': 184})],
        })
        slip.compute_sheet()
        return {line.code: line.total for line in slip.line_ids}

    def test_applied_ctc_fills_the_salary(self):
        v = self.version
        self.assertEqual(v.wage, 40900)
        self.assertEqual(v.l10n_in_gross_salary, 40900)
        self.assertEqual((v.l10n_in_basic_salary_amount, v.l10n_in_hra, v.l10n_in_fixed_allowance),
                         (21000, 10500, 7300))
        self.assertEqual((v.l10n_in_meal_voucher_amount, v.l10n_in_leave_travel_allowance), (1100, 1000))
        self.assertEqual(v.l10n_in_gratuity, 1010.10)
        self.assertEqual(self.ctc.gross_difference, 0)

    def test_pf_is_twelve_percent_of_gross_capped_at_25000(self):
        # Gross 40,900 is above the 25,000 ceiling: 12% of 25,000.
        self.assertEqual(self.version.l10n_in_pf_employee_amount, 3000)
        self.assertEqual(self.version.l10n_in_pf_employer_amount, 3000)

    def test_breakup_yearly_is_twelve_times_monthly(self):
        v = self.version
        for annual, monthly in (('ft_annual_basic', 21000), ('ft_annual_hra', 10500),
                                ('ft_annual_fixed_allowance', 7300), ('ft_annual_meal', 1100),
                                ('ft_annual_lta', 1000), ('ft_annual_gross', 40900),
                                ('ft_annual_pf_employer', 3000), ('ft_annual_gratuity', 1010.10),
                                ('ft_annual_pf_employee', 3000)):
            self.assertAlmostEqual(v[annual], monthly * 12, places=2, msg=annual)

    def test_breakup_yearly_column_adds_up_to_total_ctc(self):
        v = self.version
        lines = (v.ft_annual_fixed_pay + v.ft_annual_variable_pay + v.ft_annual_pf_employer
                 + v.ft_annual_esic_employer + v.ft_annual_gratuity + v.ft_annual_lwf_employer)
        self.assertAlmostEqual(v.ft_annual_ctc, lines, places=2)
        # 40,900 x 12 + (3,000 + 1,010.10) x 12 + 36,000
        self.assertAlmostEqual(v.ft_annual_ctc, 574921.20, places=2)

    def test_breakup_monthly_ctc_is_a_twelfth_of_yearly(self):
        v = self.version
        self.assertAlmostEqual(v.ft_monthly_ctc, 40900 + 3000 + 1010.10 + 3000, places=2)
        self.assertAlmostEqual(v.ft_monthly_ctc * 12, v.ft_annual_ctc, delta=0.06)

    def test_breakup_net_is_gross_less_deductions(self):
        v = self.version
        self.assertAlmostEqual(v.ft_monthly_net_payable, v.l10n_in_gross_salary - v.ft_monthly_total_deductions, places=2)
        self.assertAlmostEqual(v.ft_annual_net_payable, v.ft_monthly_net_payable * 12, places=2)

    def test_payslip_agrees_with_the_breakup(self):
        v = self.version
        lines = self._slip()
        self.assertEqual(lines['GROSS'], 40900)
        self.assertEqual((lines['BASIC'], lines['HRA'], lines['SPL'], lines['MEAL'], lines['LTA']),
                         (21000, 10500, 7300, 1100, 1000))
        self.assertEqual(lines['PF'], -3000)
        self.assertEqual(lines['PFE'], 3000)
        self.assertEqual(lines['GRATUITY'], 1010)
        self.assertAlmostEqual(lines['GROSS'], v.l10n_in_gross_salary, places=2)
        self.assertAlmostEqual(lines['NET'], v.ft_monthly_net_payable, places=2)
        self.assertAlmostEqual(lines['NET'], lines['GROSS'] + lines['PF'] + lines.get('PT', 0), places=2)
        # Variable pay is a CTC target only: not paid every month.
        self.assertAlmostEqual(lines['CTC_TOTAL'], 40900 + 3000 + 1010, places=2)

    def test_typed_gross_above_the_components_is_flagged_and_paid(self):
        """Monthly gross typed 600 higher than the components add up to: the gap
        shows as Gross Difference and is carried into gross, so HR sees it."""
        self.ctc.write({'monthly_gross': 41500})
        self.ctc.action_apply_to_payroll()
        self.assertEqual(self.ctc.gross_difference, 600)
        self.assertEqual(self.version.l10n_in_gross_salary, 41500)

    def test_revision_from_a_later_date_leaves_the_earlier_month_alone(self):
        """12 LPA from 1-Jan-2027: a new revision makes a new version; December still pays the old salary."""
        revision = self.ctc.copy({
            'effective_date': '2027-01-01', 'full_basic': 47361, 'full_hra': 23680,
            'full_special_allowance': 21581, 'full_gratuity': 2278.06,
            'monthly_gross': 94722, 'monthly_ctc': 100000.06, 'annual_variable_pay': 0,
            'master_pf_basic': 47361,
        })
        revision.action_apply_to_payroll()
        versions = self.employee.version_ids.sorted('date_version')
        self.assertEqual([str(d) for d in versions.mapped('date_version')], ['2026-12-01', '2027-01-01'])
        self.assertEqual(versions[0].wage, 40900)
        self.assertEqual(versions[1].wage, 94722)
        self.assertAlmostEqual(versions[1].ft_monthly_ctc, 100000.06, places=2)
        self.assertAlmostEqual(versions[1].ft_annual_ctc, 1200000.72, places=2)
        self.assertEqual(self._slip()['GROSS'], 40900)
        january = self._slip(date_from='2027-01-01', date_to='2027-01-31')
        self.assertEqual(january['GROSS'], 94722)
        self.assertEqual(january['PF'], -3000)
        self.assertAlmostEqual(january['NET'], 94722 - 3000 + january.get('PT', 0), places=2)
