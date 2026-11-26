"""Salary edited on the Payroll tab becomes the salary revision behind it."""
from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSalaryRevisionWorkflow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Salary Revision Test', 'country_id': cls.env.ref('base.in').id,
            'currency_id': cls.env.ref('base.INR').id,
        })
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=[cls.company.id],
            tracking_disable=True, mail_create_nosubscribe=True, mail_create_nolog=True))
        cls.structure = cls.env.ref('ft_greythr_migration.greythr_structure')
        # A new joiner, filled in on the employee form in one go.
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Payroll Tab Joiner', 'company_id': cls.company.id,
            'date_version': '2026-12-01', 'contract_date_start': '2026-12-01',
            'greythr_pf_eligible': True, 'ft_gratuity_eligible': True,
            'wage': 47350, 'l10n_in_basic_salary_amount': 23675, 'l10n_in_hra': 11837.5,
            'l10n_in_meal_voucher_amount': 1100, 'l10n_in_leave_travel_allowance': 1000,
        })
        cls.version = cls.employee.version_ids

    def _slip(self, date_from='2026-12-01', date_to='2026-12-31'):
        attendance = self.env.ref('hr_work_entry.work_entry_type_attendance')
        slip = self.env['hr.payslip'].create({
            'name': 'Revision Test', 'employee_id': self.employee.id,
            'date_from': date_from, 'date_to': date_to, 'struct_id': self.structure.id,
            'worked_days_line_ids': [Command.create({
                'work_entry_type_id': attendance.id, 'number_of_days': 22, 'number_of_hours': 176})],
        })
        slip.compute_sheet()
        return slip

    def test_new_joiner_gets_a_reviewed_revision(self):
        rows = self.employee.greythr_ctc_ids
        self.assertEqual(len(rows), 1)
        row = rows
        self.assertEqual(str(row.effective_date), '2026-12-01')
        self.assertEqual(self.version.greythr_ctc_id, row)
        self.assertEqual(self.version.structure_type_id, self.env.ref('ft_greythr_migration.greythr_structure_type'))
        self.assertTrue(row.payroll_reviewed)
        self.assertEqual((row.full_basic, row.full_hra, row.full_meal_allowance, row.full_leave_travel_allowance),
                         (23675, 11837.5, 1100, 1000))
        # Special Allowance is the balance of the wage.
        self.assertEqual(row.full_special_allowance, 47350 - 23675 - 11837.5 - 1100 - 1000)
        self.assertEqual(self.version.l10n_in_gross_salary, 47350)
        self.assertEqual(row.monthly_gross, 47350)
        self.assertEqual(row.gross_difference, 0)
        # Gratuity 4.81% of Basic in whole rupees; PF 12% of 25,000.
        self.assertEqual(row.full_gratuity, 1139)
        self.assertEqual(self.version.l10n_in_pf_employee_amount, 3000)
        self.assertEqual(row.monthly_ctc, 47350 + 3000 + 1139)
        self.assertEqual(row.annual_ctc, (47350 + 3000 + 1139) * 12)
        self.assertTrue(row.eligible_for_pf)
        self.assertEqual(row.payroll_pf_mode, 'capped')

    def test_payslip_pays_what_the_payroll_tab_shows(self):
        lines = {line.code: line.total for line in self._slip().line_ids}
        self.assertEqual(lines['GROSS'], 47350)
        self.assertEqual((lines['BASIC'], lines['HRA'], lines['SPL']), (23675, 11838, 9738))
        self.assertEqual(lines['PF'], -3000)
        self.assertEqual(lines['GRATUITY'], 1139)
        self.assertAlmostEqual(lines['NET'], self.version.ft_monthly_net_payable, delta=1)
        self.assertEqual(self.version.ft_monthly_ctc, 47350 + 3000 + 1139)

    def test_wage_change_keeps_the_other_amounts(self):
        self.employee.write({'wage': 61234})
        v = self.version
        self.assertEqual((v.l10n_in_basic_salary_amount, v.l10n_in_hra, v.l10n_in_meal_voucher_amount,
                          v.l10n_in_leave_travel_allowance), (23675, 11837.5, 1100, 1000))
        self.assertEqual(v.l10n_in_fixed_allowance, 61234 - 23675 - 11837.5 - 1100 - 1000)
        self.assertEqual(v.l10n_in_gross_salary, 61234)
        row = self.employee.greythr_ctc_ids
        self.assertEqual(len(row), 1, 'a correction on the same version updates its revision')
        self.assertEqual(row.monthly_gross, 61234)
        self.assertEqual(row.full_special_allowance, v.l10n_in_fixed_allowance)
        self.assertTrue(row.payroll_reviewed)
        self.assertEqual(self._slip().line_ids.filtered(lambda l: l.code == 'GROSS').total, 61234)

    def test_basic_change_moves_gratuity_and_special_only(self):
        self.employee.write({'l10n_in_basic_salary_amount': 25000})
        v = self.version
        self.assertEqual(v.l10n_in_gratuity, 1203)                  # 25,000 x 4.81% = 1,202.50
        self.assertEqual(v.l10n_in_hra, 11837.5)
        self.assertEqual(v.l10n_in_fixed_allowance, 47350 - 25000 - 11837.5 - 1100 - 1000)
        self.assertEqual(self.employee.greythr_ctc_ids.full_gratuity, 1203)

    def test_revision_from_a_new_date(self):
        """12 LPA from 1-Jan-2027: a new version from that date, then the Payroll tab."""
        january = self.employee.create_version({'date_version': '2027-01-01'})
        january.write({'wage': 94722, 'l10n_in_basic_salary_amount': 47361, 'l10n_in_hra': 23680})
        rows = self.employee.greythr_ctc_ids.sorted('effective_date')
        self.assertEqual([str(d) for d in rows.mapped('effective_date')], ['2026-12-01', '2027-01-01'])
        self.assertEqual(rows[0].monthly_gross, 47350, 'the December revision is untouched')
        self.assertEqual(january.greythr_ctc_id, rows[1])
        self.assertEqual(rows[1].full_gratuity, 2278)
        self.assertEqual(rows[1].monthly_ctc, 94722 + 3000 + 2278)
        self.assertEqual(rows[1].annual_ctc, (94722 + 3000 + 2278) * 12)
        self.assertEqual(self._slip().line_ids.filtered(lambda l: l.code == 'GROSS').total, 47350)
        jan = {l.code: l.total for l in self._slip('2027-01-01', '2027-01-31').line_ids}
        self.assertEqual(jan['GROSS'], 94722)
        self.assertEqual(jan['PF'], -3000)

    def test_new_version_without_salary_change_adds_no_revision(self):
        self.employee.create_version({'date_version': '2027-01-01'})
        self.assertEqual(len(self.employee.greythr_ctc_ids), 1)

    def test_untick_gratuity(self):
        self.employee.write({'ft_gratuity_eligible': False})
        self.assertEqual(self.version.l10n_in_gratuity, 0)
        self.assertEqual(self.employee.greythr_ctc_ids.full_gratuity, 0)
        self.assertEqual(self.employee.greythr_ctc_ids.monthly_ctc, 47350 + 3000)

    def test_not_pf_eligible(self):
        self.employee.write({'greythr_pf_eligible': False})
        row = self.employee.greythr_ctc_ids
        self.assertEqual(self.version.l10n_in_pf_employee_amount, 0)
        self.assertFalse(row.eligible_for_pf)
        self.assertEqual(row.payroll_pf_mode, 'none')
        self.assertEqual(row.monthly_ctc, 47350 + 1139)
        self.assertNotIn('PF', {l.code for l in self._slip().line_ids if l.total})

    def test_variable_pay_counts_in_ctc(self):
        self.employee.write({'ft_annual_variable_pay': 36000})
        row = self.employee.greythr_ctc_ids
        self.assertEqual(row.annual_variable_pay, 36000)
        self.assertEqual(row.monthly_ctc, 47350 + 3000 + 1139 + 3000)
        self.assertEqual(row.annual_ctc, (47350 + 3000 + 1139) * 12 + 36000)

    def test_components_the_structure_does_not_pay_are_refused(self):
        with self.assertRaises(UserError):
            self.employee.write({'l10n_in_standard_allowance': 500})

    def test_salary_in_confirmed_payslips_cannot_change(self):
        self._slip().write({'state': 'validated'})
        with self.assertRaises(UserError):
            self.employee.write({'wage': 50000})

    def test_apply_to_payroll_still_works_for_imports(self):
        ctc = self.env['ft.greythr.ctc'].create({
            'employee_id': self.employee.id, 'effective_date': '2027-02-01',
            'full_basic': 30000, 'full_hra': 15000, 'full_special_allowance': 5000,
            'monthly_gross': 50000, 'monthly_ctc': 54443, 'full_gratuity': 1443,
            'eligible_for_pf': True, 'payroll_pf_mode': 'capped', 'master_pf_basic': 30000,
            'pf_base_limit': 15000,
        })
        ctc.action_apply_to_payroll()
        self.assertEqual(len(self.employee.greythr_ctc_ids), 2, 'applying adds no row of its own')
        february = self.employee.version_ids.filtered(lambda v: str(v.date_version) == '2027-02-01')
        self.assertEqual(february.greythr_ctc_id, ctc)
        self.assertEqual(february.wage, 50000)
        self.assertTrue(february.ft_gratuity_eligible)
        self.assertFalse(ctc.payroll_reviewed, 'an imported row still waits for review')
