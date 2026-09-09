from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestGreythrPayroll(TransactionCase):
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

    def _slip(self, fraction=1, date_from='2026-06-01', date_to='2026-06-30'):
        attendance = self.env.ref('hr_work_entry.work_entry_type_attendance')
        unpaid = self.env.ref('hr_work_entry.work_entry_type_unpaid_leave')
        worked = []
        if fraction:
            worked.append(Command.create({'work_entry_type_id': attendance.id,
                'number_of_days': 20 * fraction, 'number_of_hours': 160 * fraction}))
        if fraction < 1:
            worked.append(Command.create({'work_entry_type_id': unpaid.id,
                'number_of_days': 20 * (1-fraction), 'number_of_hours': 160 * (1-fraction)}))
        slip = self.env['hr.payslip'].create({
            'name': 'Mapping Test', 'employee_id': self.employee.id,
            'date_from': date_from, 'date_to': date_to,
            'struct_id': self.structure.id, 'worked_days_line_ids': worked,
        })
        slip.compute_sheet()
        return slip

    def test_full_month_no_double_count(self):
        slip = self._slip()
        lines = {l.code: l.total for l in slip.line_ids}
        expected = {'BASIC': 15000, 'HRA': 6000, 'SPL': 7499.5, 'LTA': 500,
            'MEAL': 1000, 'GROSS_RECON': .5, 'GROSS': 30000, 'PF': -1800,
            'PFE': 1800, 'GRATUITY': 721.15, 'NET': 28200, 'CTC_TOTAL': 32521.15}
        for code, amount in expected.items():
            self.assertAlmostEqual(lines[code], amount, places=2, msg=code)
        self.assertFalse(self.company.l10n_in_provident_fund)
        self.assertAlmostEqual(self.employee.l10n_in_gross_salary, 30000, places=2)
        self.assertEqual(self.employee.l10n_in_leave_travel_allowance, 500)
        self.assertEqual(self.employee.l10n_in_gratuity, 721.15)

    def test_unpaid_leave_prorates_allowances_and_employer_costs(self):
        slip = self._slip(.5)
        lines = {l.code: l.total for l in slip.line_ids}
        for code, amount in {'GROSS': 15000, 'LTA': 250, 'MEAL': 500,
                'PF': -900, 'PFE': 900, 'GRATUITY': 360.58, 'NET': 14100}.items():
            self.assertAlmostEqual(lines[code], amount, places=2, msg=code)

    def test_zero_paid_time(self):
        slip = self._slip(0)
        self.assertFalse(any(line.total for line in slip.line_ids))

    def test_review_required_and_pf_pending(self):
        slip = self._slip()
        with self.assertRaises(UserError):
            slip.action_payslip_done()
        self.ctc.write({'payroll_pf_mode': 'pending'})
        self.ctc.action_apply_to_payroll()
        self.ctc.write({'payroll_reviewed': True})
        with self.assertRaises(UserError):
            slip.action_payslip_done()

    def test_reapply_is_idempotent_and_source_edit_invalidates_review(self):
        self.ctc.write({'payroll_reviewed': True})
        self.ctc.write({'full_meal_allowance': 1200})
        self.assertFalse(self.ctc.payroll_reviewed)
        with self.assertRaises(UserError):
            self._slip()
        self.ctc.action_apply_to_payroll()
        self.ctc.action_apply_to_payroll()
        self.assertEqual(len(self.employee.version_ids), 1)
        slip = self._slip()
        self.assertAlmostEqual(slip.line_ids.filtered(lambda l: l.code == 'GROSS').total, 30000)

    def test_historical_versions_and_mid_month_split(self):
        later = self.ctc.copy({'effective_date': '2026-07-15', 'full_leave_travel_allowance': 800})
        later.action_apply_to_payroll()
        june = self._slip()
        self.assertAlmostEqual(june.line_ids.filtered(lambda l: l.code == 'LTA').total, 500)
        with self.assertRaises(UserError):
            self._slip(date_from='2026-07-01', date_to='2026-07-31')

    def test_confirmed_ctc_cannot_be_rewritten(self):
        slip = self._slip()
        slip.write({'state': 'validated'})  # Avoid accounting/payment side effects in this immutability test.
        with self.assertRaises(UserError):
            self.ctc.write({'full_hra': 6100})
        with self.assertRaises(UserError):
            self.ctc.action_apply_to_payroll()

    def test_standard_india_structure_unchanged(self):
        rule = self.env.ref('l10n_in_hr_payroll.hr_salary_rule_pfe_with_pf')
        self.assertEqual(rule.category_id, self.env.ref('hr_payroll.DED'))
        self.assertNotEqual(rule.struct_id, self.structure)

    def test_report_separates_employer_costs(self):
        from lxml import html
        slip = self._slip()
        for report, selector in [
            ('l10n_in_hr_payroll.action_report_payslip_in', "//div[@id='payslip_lines_table']"),
            ('l10n_in_hr_payroll.payslip_details_report', "//div[contains(@class, 'page')]/table[1]"),
        ]:
            result, _ = self.env['ir.actions.report']._render_qweb_html(report, slip.ids)
            doc = html.fromstring(result)
            costs = doc.xpath("//div[@name='greythr_employer_costs']")
            self.assertEqual(len(costs), 1)
            self.assertIn('Gratuity Provision', costs[0].text_content())
            earnings = doc.xpath(selector)[0]
            self.assertNotIn('Gratuity Provision', earnings.text_content())
            self.assertNotIn('Provident fund - Employer', earnings.text_content())
            self.assertIn('Leave Travel Allowance', earnings.text_content())
