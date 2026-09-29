from odoo.tests import Form, TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProfessionalTaxSlab(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'PT Slab Test', 'country_id': cls.env.ref('base.in').id,
            'currency_id': cls.env.ref('base.INR').id,
        })
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=[cls.company.id],
            tracking_disable=True, mail_create_nosubscribe=True, mail_create_nolog=True))
        cls.karnataka = cls.env.ref('l10n_in_hr_payroll.l10n_in_rule_parameter_pt_karnataka')
        cls.gujarat = cls.env.ref('l10n_in_hr_payroll.l10n_in_rule_parameter_pt_gujarat')

    def _employee(self, wage):
        return self.env['hr.employee'].create({
            'name': 'PT %s' % wage, 'company_id': self.company.id,
            'date_version': '2026-06-01', 'contract_date_start': '2026-06-01', 'wage': wage,
        })

    def test_slab_follows_wage(self):
        self.assertEqual(self._employee(25000).version_id.pt_rule_parameter_id, self.karnataka)
        version = self._employee(24999).version_id
        self.assertFalse(version.pt_rule_parameter_id)
        version.wage = 30000
        self.assertEqual(version.pt_rule_parameter_id, self.karnataka)
        version.wage = 20000
        self.assertFalse(version.pt_rule_parameter_id)

    def test_manual_choice_kept_until_wage_changes(self):
        version = self._employee(40000).version_id
        version.pt_rule_parameter_id = self.gujarat
        version.l10n_in_pf_employee_type = 'fixed'
        self.assertEqual(version.pt_rule_parameter_id, self.gujarat)
        version.pt_rule_parameter_id = False
        self.assertFalse(version.pt_rule_parameter_id)
        version.wage = 45000
        self.assertEqual(version.pt_rule_parameter_id, self.karnataka)

    def test_employee_form_updates_live(self):
        employee = self._employee(20000)
        with Form(employee) as form:
            form.wage = 26000
            self.assertEqual(form.pt_rule_parameter_id, self.karnataka)
            form.wage = 24000
            self.assertFalse(form.pt_rule_parameter_id)
        self.assertFalse(employee.version_id.pt_rule_parameter_id)
