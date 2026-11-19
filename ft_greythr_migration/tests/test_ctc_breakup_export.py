import io

import openpyxl

from odoo.exceptions import AccessError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged


def _setup_employee(cls):
    cls.company = cls.env['res.company'].create({
        'name': 'CTC Export Test', 'country_id': cls.env.ref('base.in').id,
        'currency_id': cls.env.ref('base.INR').id,
    })
    cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=[cls.company.id],
        tracking_disable=True, mail_create_nosubscribe=True, mail_create_nolog=True))
    cls.employee = cls.env['hr.employee'].create({
        'name': 'Basavaraju H S', 'registration_number': 'FT0146', 'job_title': 'Trainee Engineer',
        'company_id': cls.company.id, 'date_version': '2025-09-01', 'contract_date_start': '2025-09-01',
        'wage': 18488,
    })
    cls.version = cls.employee.version_id
    # Monthly column of the reference CTC sheet (Total CTC 3,20,000).
    cls.version.write({
        'l10n_in_basic_salary_amount': 9244, 'l10n_in_hra': 3698, 'l10n_in_fixed_allowance': 5546,
        'l10n_in_meal_voucher_amount': 0, 'l10n_in_leave_travel_allowance': 0,
        'l10n_in_standard_allowance': 0, 'l10n_in_performance_bonus': 0,
        'l10n_in_phone_subscription': 0, 'l10n_in_internet_subscription': 0, 'l10n_in_company_transport': 0,
        'l10n_in_gratuity': 445, 'l10n_in_pf_employee_amount': 1800, 'l10n_in_pf_employer_amount': 1800,
        'ft_annual_variable_pay': 64000,
    })
    # Special Allowance is recomputed as wage less the other parts when those are written: set it last.
    cls.version.write({'l10n_in_fixed_allowance': 5546})
    # ESI is held as a rate of gross: 3.25% employer (600.86 -> 601), 0.75% employee (138.66 -> 139).
    cls.version.write({'l10n_in_esic_employer_percentage': 0.0325, 'l10n_in_esic_employee_percentage': 0.0075})
    # Yearly figures of the same sheet, as imported from greytHR.
    ctc = cls.env['ft.greythr.ctc'].create({
        'employee_id': cls.employee.id, 'effective_date': '2025-09-01', 'monthly_gross': 18488,
        'full_basic': 9244, 'full_hra': 3698, 'full_special_allowance': 5546, 'full_gratuity': 445,
        'annual_fixed_pay': 221854, 'annual_ctc': 320000, 'monthly_ctc': 26667,
        'annual_pf_employer': 21600, 'annual_esic_employer': 7210, 'annual_gratuity': 5336,
        'annual_variable_pay': 64000,
    })
    cls.version.greythr_ctc_id = ctc


def _read(content):
    ws = openpyxl.load_workbook(io.BytesIO(content)).worksheets[0]
    rows = {}
    for label, yearly, monthly in ws.iter_rows(min_col=1, max_col=3, values_only=True):
        if label and label not in rows:
            rows[label] = (yearly, monthly)
    return ws, rows


@tagged('post_install', '-at_install')
class TestCtcBreakupExport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _setup_employee(cls)

    def test_sheet_matches_the_reference_ctc_sheet(self):
        ws, rows = _read(self.employee._ft_ctc_breakup_xlsx())
        self.assertEqual(ws.title, 'FT0146')
        self.assertEqual(rows['Employee Name'][0], 'Basavaraju H S')
        self.assertEqual(rows['Effective From'][0], '2025-09-01')
        expected = {
            'Fixed Pay': (221854, 18488),
            'Variable Pay': (64000, 5333),
            'PF-Employer contribution': (21600, 1800),
            'ESI-Employer contribution': (7210, 601),
            'Gratuity': (5336, 445),
            'Total CTC': (320000, 26667),
            'Basic Salary': (110928, 9244),
            'HRA': (44376, 3698),
            'Food Coupon/Meal Allowances': (0, 0),
            'LTA': (0, 0),
            'Special Allowance': (66552, 5546),
            'Gross Total': (221856, 18488),
            'Food Coupon-(Optional)': (0, 0),
            'Medical Insurance-(Optional)': (0, 0),
            'PF-Employee': (21600, 1800),
            'ESI-Employee': (1664, 139),        # 138.66 x 12, as on the sheet
            'Professional Tax': (0, 0),
            'Income Tax (TDS)': ('-', '-'),
            'Total Deductions': (23264, 1939),
            'Net Payable': (198592, 16549),
        }
        for label, values in expected.items():
            self.assertEqual(rows[label], values, label)

    def test_rows_follow_the_sheet_order(self):
        labels = [r[1] for r in self.employee._ft_ctc_breakup_rows() if r[0] != 'blank']
        self.assertEqual(labels[:8], ['Particulars:', 'Fixed Pay', 'Variable Pay', 'PF-Employer contribution',
                                      'ESI-Employer contribution', 'Gratuity', 'Total CTC', 'Fixed Salary break up:'])
        self.assertEqual(labels[-3:], ['Income Tax (TDS)', 'Total Deductions', 'Net Payable'])

    def test_file_agrees_with_the_salary_tab(self):
        _ws, rows = _read(self.employee._ft_ctc_breakup_xlsx())
        v = self.version
        self.assertEqual(rows['Total CTC'], (round(v.ft_annual_ctc), round(v.ft_monthly_ctc)))
        self.assertEqual(rows['Net Payable'], (round(v.ft_annual_net_payable), round(v.ft_monthly_net_payable)))

    def test_optional_components_only_when_used(self):
        _ws, rows = _read(self.employee._ft_ctc_breakup_xlsx())
        self.assertNotIn('Children Education Allowance', rows)
        self.version.write({'ft_children_education_allowance': 200})
        self.version.write({'l10n_in_fixed_allowance': 5346})
        _ws, rows = _read(self.employee._ft_ctc_breakup_xlsx())
        self.assertEqual(rows['Children Education Allowance'], (2400, 200))
        self.assertEqual(rows['Gross Total'][1], 18488)

    def test_one_sheet_per_employee(self):
        other = self.env['hr.employee'].create({'name': 'Second Employee', 'registration_number': 'FT0999',
                                                'company_id': self.company.id})
        book = openpyxl.load_workbook(io.BytesIO((self.employee | other)._ft_ctc_breakup_xlsx()))
        self.assertEqual(book.sheetnames, ['FT0146', 'FT0999'])
        self.assertEqual((self.employee | other)._ft_ctc_breakup_filename(), 'CTC Breakup - 2 employees.xlsx')
        self.assertEqual(self.employee._ft_ctc_breakup_filename(), 'CTC Breakup - FT0146 - Basavaraju H S.xlsx')

    def test_action_returns_download_url(self):
        action = self.employee.action_ft_download_ctc_breakup()
        self.assertEqual(action['type'], 'ir.actions.act_url')
        self.assertIn('employee_ids=%s' % self.employee.id, action['url'])

    def test_only_payroll_users(self):
        officer = new_test_user(self.env, login='hr_officer_ctc', groups='hr.group_hr_user',
                                company_id=self.company.id)
        with self.assertRaises(AccessError):
            self.employee.with_user(officer).action_ft_download_ctc_breakup()


@tagged('post_install', '-at_install')
class TestCtcBreakupDownload(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _setup_employee(cls)
        cls.payroll_user = new_test_user(cls.env, login='payroll_ctc', password='payroll_ctc_pw',
                                         groups='hr_payroll.group_hr_payroll_user,hr.group_hr_user',
                                         company_id=cls.company.id, company_ids=[cls.company.id])
        new_test_user(cls.env, login='hr_only_ctc', password='hr_only_ctc_pw', groups='hr.group_hr_user',
                      company_id=cls.company.id, company_ids=[cls.company.id])

    def test_download(self):
        self.authenticate('payroll_ctc', 'payroll_ctc_pw')
        res = self.url_open('/ft_greythr_migration/ctc_breakup?employee_ids=%s' % self.employee.id)
        self.assertEqual(res.status_code, 200)
        self.assertIn('spreadsheetml', res.headers['Content-Type'])
        self.assertIn('CTC%20Breakup%20-%20FT0146', res.headers['Content-Disposition'])
        _ws, rows = _read(res.content)
        self.assertEqual(rows['Net Payable'], (198592, 16549))

    def test_download_refused_without_payroll_rights(self):
        self.authenticate('hr_only_ctc', 'hr_only_ctc_pw')
        res = self.url_open('/ft_greythr_migration/ctc_breakup?employee_ids=%s' % self.employee.id)
        self.assertNotEqual(res.status_code, 200)

    def test_download_needs_login(self):
        res = self.url_open('/ft_greythr_migration/ctc_breakup?employee_ids=%s' % self.employee.id,
                            allow_redirects=False)
        self.assertIn(res.status_code, (302, 303))
