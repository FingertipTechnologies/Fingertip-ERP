from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSalaryByEmployeeDates(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Salary Report Test', 'country_id': cls.env.ref('base.in').id,
            'currency_id': cls.env.ref('base.INR').id,
        })
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=[cls.company.id],
                                       tracking_disable=True))
        cls.paid_sep, cls.paid_may, cls.draft_only = cls.env['hr.employee'].create([
            {'name': name, 'company_id': cls.company.id, 'date_version': '2026-04-01',
             'contract_date_start': '2026-04-01', 'wage': 30000}
            for name in ('Paid September', 'Paid May', 'Draft Only')])
        structure = cls.env.ref('ft_greythr_migration.greythr_structure')
        for employee, month, state in ((cls.paid_sep, 9, 'paid'), (cls.paid_may, 5, 'paid'),
                                       (cls.draft_only, 9, 'draft')):
            slip = cls.env['hr.payslip'].create({
                'name': employee.name, 'employee_id': employee.id, 'struct_id': structure.id,
                'date_from': '2026-%02d-01' % month, 'date_to': '2026-%02d-%s' % (month, 30 if month == 9 else 31)})
            slip.write({'state': state, 'done_date': '2026-%02d-28 12:00:00' % month if state == 'paid' else False})

    def _wizard(self, date_from, date_to, **vals):
        return self.env['yearly.salary.detail'].create(dict(vals, ft_date_from=date_from, ft_date_to=date_to))

    def test_no_employee_is_picked_by_default(self):
        wizard = self._wizard('2026-04-01', '2026-10-31')
        self.assertFalse(wizard.employee_ids)

    def test_only_employees_paid_between_the_dates_can_be_picked(self):
        self.assertEqual(self._wizard('2026-04-01', '2026-10-31').related_employee_ids, self.paid_sep | self.paid_may)
        self.assertEqual(self._wizard('2026-09-01', '2026-10-31').related_employee_ids, self.paid_sep)

    def test_changing_the_dates_drops_employees_without_payslips(self):
        wizard = self._wizard('2026-04-01', '2026-10-31', employee_ids=(self.paid_sep | self.paid_may).ids)
        wizard.ft_date_from = '2026-08-01'
        self.assertEqual(wizard.employee_ids, self.paid_sep)

    def test_report_has_one_column_per_month_between_the_dates(self):
        wizard = self._wizard('2026-11-01', '2027-02-28')
        names, months = self.env['report.l10n_in_hr_payroll.report_hryearlysalary']._get_periods_new(wizard.read()[0])
        self.assertEqual(months, ['11-2026', '12-2026', '01-2027', '02-2027'])
        self.assertEqual(len(names[0]), 4)

    def test_from_date_after_to_date_is_refused(self):
        wizard = self._wizard('2026-10-31', '2026-04-01', employee_ids=self.paid_sep.ids)
        with self.assertRaises(UserError):
            wizard.print_report()

    def test_excel_has_the_same_figures_as_the_pdf(self):
        import base64
        import io
        import openpyxl
        slip = self.env['hr.payslip'].search([('employee_id', '=', self.paid_sep.id)])
        rules = slip.struct_id.rule_ids
        self.env['hr.payslip.line'].create([{
            'slip_id': slip.id, 'salary_rule_id': rules.filtered(lambda r: r.code == code)[:1].id,
            'name': name, 'code': code, 'amount': amount, 'total': amount, 'quantity': 1, 'rate': 100,
            'employee_id': self.paid_sep.id, 'version_id': slip.version_id.id,
        } for code, name, amount in (('BASIC', 'Basic Salary', 15000.0), ('NET', 'Net Salary', 13200.0))])
        self.env.flush_all()
        wizard = self._wizard('2026-04-01', '2026-10-31', employee_ids=self.paid_sep.ids)
        action = wizard.action_ft_print_excel()
        attachment = self.env['ir.attachment'].browse(int(action['url'].split('/')[3].split('?')[0]))
        rows = [tuple(row) for row in openpyxl.load_workbook(
            io.BytesIO(base64.b64decode(attachment.datas))).active.iter_rows(values_only=True)]
        self.assertEqual(rows[2][:2], ('Employee Name', 'Paid September'))
        self.assertEqual(rows[4][1:9], ('Apr 26', 'May 26', 'Jun 26', 'Jul 26', 'Aug 26', 'Sep 26', 'Oct 26', 'Total'))
        net = next(row for row in rows if row[0] == 'Net Salary')
        self.assertEqual((net[6], net[8]), (13200.0, 13200.0))
        basic = next(row for row in rows if row[0] == 'Basic Salary')
        self.assertEqual((basic[5], basic[6], basic[8]), (0.0, 15000.0, 15000.0))

    def test_excel_needs_an_employee(self):
        with self.assertRaises(UserError):
            self._wizard('2026-04-01', '2026-10-31').action_ft_print_excel()
