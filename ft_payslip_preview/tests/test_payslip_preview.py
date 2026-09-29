from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestPayslipPreview(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True,
                                       mail_create_nosubscribe=True, mail_create_nolog=True))
        cls.payroll_user = cls.env['res.users'].create({
            'name': 'Preview Payroll User', 'login': 'ft_preview_payroll',
            'password': 'ft_preview_payroll_pw',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id,
                                  cls.env.ref('hr_payroll.group_hr_payroll_user').id])],
        })
        cls.plain_user = cls.env['res.users'].create({
            'name': 'Preview Plain User', 'login': 'ft_preview_plain',
            'password': 'ft_preview_plain_pw',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        employee = cls.env['hr.employee'].create({
            'name': 'Preview Employee', 'company_id': cls.env.company.id,
            'date_version': '2026-01-01', 'contract_date_start': '2026-01-01', 'wage': 30000,
            'structure_type_id': cls.env.ref('hr.structure_type_employee').id,
        })
        cls.payslip = cls.env['hr.payslip'].create({
            'name': 'Preview Slip', 'employee_id': employee.id,
            'date_from': '2026-09-01', 'date_to': '2026-09-30',
            'struct_id': cls.env.ref('hr_payroll.default_structure').id,
        })
        cls.payslip.compute_sheet()

    def test_button_opens_a_dialog(self):
        action = self.payslip.action_ft_preview_pdf()
        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'ft_payslip_preview')
        self.assertEqual(action['params']['url'], '/ft_payslip_preview/%s' % self.payslip.id)

    def test_preview_is_served_inline(self):
        self.assertTrue(self.payslip.line_ids)
        self.authenticate('ft_preview_payroll', 'ft_preview_payroll_pw')
        response = self.url_open('/ft_payslip_preview/%s' % self.payslip.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Content-Type'], 'application/pdf')
        self.assertTrue(response.headers['Content-Disposition'].startswith('inline;'))
        self.assertIn('.pdf', response.headers['Content-Disposition'])
        self.assertTrue(response.content)

    def test_missing_payslip_is_not_found(self):
        self.authenticate('ft_preview_payroll', 'ft_preview_payroll_pw')
        response = self.url_open('/ft_payslip_preview/%s' % (self.payslip.id + 100000))
        self.assertEqual(response.status_code, 404)

    def test_non_payroll_user_is_refused(self):
        self.authenticate('ft_preview_plain', 'ft_preview_plain_pw')
        response = self.url_open('/ft_payslip_preview/%s' % self.payslip.id)
        self.assertEqual(response.status_code, 404)
