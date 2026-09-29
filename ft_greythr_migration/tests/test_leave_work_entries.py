from datetime import date

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestLeaveWorkEntries(TransactionCase):
    """An unpaid day must reach the payslip whatever the number of versions."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Leave Entries Test', 'country_id': cls.env.ref('base.in').id,
            'currency_id': cls.env.ref('base.INR').id,
        })
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=[cls.company.id],
            tracking_disable=True, mail_create_nosubscribe=True, mail_create_nolog=True))
        cls.unpaid_type = cls.env['hr.leave.type'].create({
            'name': 'Unpaid (test)', 'requires_allocation': False, 'leave_validation_type': 'hr',
            'work_entry_type_id': cls.env.ref('hr_work_entry.work_entry_type_unpaid_leave').id,
            'company_id': cls.company.id,
        })
        cls.standard = cls.env.ref('l10n_in_hr_payroll.hr_payroll_structure_in_employee_salary')

    def _employee(self, name, second_version=False):
        employee = self.env['hr.employee'].create({
            'name': name, 'company_id': self.company.id,
            'date_version': '2026-05-04', 'contract_date_start': '2026-05-04', 'wage': 59274,
        })
        if second_version:
            employee.create_version({'date_version': '2026-09-01', 'wage': 59274})
        employee.version_ids.generate_work_entries(date(2026, 8, 1), date(2026, 9, 30), force=True)
        return employee

    def _approve(self, employee, day_from, day_to=None):
        leave = self.env['hr.leave'].with_context(leave_skip_state_check=True).create({
            'employee_id': employee.id, 'holiday_status_id': self.unpaid_type.id,
            'request_date_from': day_from, 'request_date_to': day_to or day_from,
        })
        leave.sudo().action_approve()
        if leave.state != 'validate':
            leave.sudo().action_validate()
        self.assertEqual(leave.state, 'validate')
        return leave

    def _entries(self, employee, day):
        return self.env['hr.work.entry'].search([('employee_id', '=', employee.id), ('date', '=', day)])

    def _assert_one_unpaid_entry(self, employee, day, version):
        entries = self._entries(employee, day)
        self.assertEqual(len(entries), 1, [(e.work_entry_type_id.code, e.state, e.duration) for e in entries])
        self.assertEqual(entries.work_entry_type_id.code, 'LEAVE90')
        self.assertEqual(entries.duration, 8)
        self.assertNotEqual(entries.state, 'conflict')
        self.assertEqual(entries.version_id, version)

    def test_two_versions_single_day(self):
        employee = self._employee('Two Versions', second_version=True)
        self.assertEqual(len(employee.version_ids), 2)
        self._approve(employee, date(2026, 9, 15))
        self._assert_one_unpaid_entry(employee, date(2026, 9, 15), employee._get_version(date(2026, 9, 15)))
        slip = self.env['hr.payslip'].create({
            'name': 'Sep', 'employee_id': employee.id, 'struct_id': self.standard.id,
            'date_from': date(2026, 9, 1), 'date_to': date(2026, 9, 30),
        })
        slip.compute_sheet()
        by_code = {line.code: line for line in slip.worked_days_line_ids}
        self.assertIn('LEAVE90', by_code)
        self.assertEqual(by_code['LEAVE90'].number_of_days, 1)
        self.assertFalse(by_code['LEAVE90'].is_paid)
        self.assertEqual(by_code['WORK100'].number_of_days, 21)
        self.assertLess(slip.paid_amount, 59274)
        basic = sum(slip.line_ids.filtered(lambda l: l.code == 'BASIC').mapped('total'))
        self.assertLess(basic, employee.version_id.l10n_in_basic_salary_amount)

    def test_leave_across_a_version_change(self):
        employee = self._employee('Across Versions', second_version=True)
        self._approve(employee, date(2026, 8, 31), date(2026, 9, 1))
        self._assert_one_unpaid_entry(employee, date(2026, 8, 31), employee._get_version(date(2026, 8, 31)))
        self._assert_one_unpaid_entry(employee, date(2026, 9, 1), employee._get_version(date(2026, 9, 1)))

    def test_single_version_unchanged(self):
        employee = self._employee('One Version')
        self._approve(employee, date(2026, 9, 15))
        self._assert_one_unpaid_entry(employee, date(2026, 9, 15), employee.version_id)

    def test_refuse_restores_a_normal_day(self):
        employee = self._employee('Refused', second_version=True)
        leave = self._approve(employee, date(2026, 9, 15))
        leave.sudo().action_refuse()
        entries = self._entries(employee, date(2026, 9, 15))
        self.assertEqual(entries.mapped('work_entry_type_id.code'), ['WORK100'])
        self.assertEqual(sum(entries.mapped('duration')), 8)
