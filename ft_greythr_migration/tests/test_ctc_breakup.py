from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCtcBreakup(TransactionCase):
    """Annual CTC breakup, checked against the Fingertip CTC sheet for FT0174."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'CTC Breakup Test', 'country_id': cls.env.ref('base.in').id,
            'currency_id': cls.env.ref('base.INR').id,
        })
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=[cls.company.id],
            tracking_disable=True, mail_create_nosubscribe=True, mail_create_nolog=True))
        cls.employee = cls.env['hr.employee'].create({
            'name': 'CTC Sheet Employee', 'company_id': cls.company.id,
            'date_version': '2026-04-01', 'contract_date_start': '2026-04-01',
            'wage': 59274,
        })
        # The monthly column of the reference sheet.
        cls.version = cls.employee.version_id
        cls.version.write({
            'l10n_in_basic_salary_amount': 29637,
            'l10n_in_hra': 11855,
            'l10n_in_meal_voucher_amount': 1100,
            'l10n_in_leave_travel_allowance': 1000,
            'l10n_in_fixed_allowance': 15682,
            'l10n_in_standard_allowance': 0,
            'l10n_in_performance_bonus': 0,
            'l10n_in_phone_subscription': 0,
            'l10n_in_internet_subscription': 0,
            'l10n_in_company_transport': 0,
            'l10n_in_gratuity': 1426,
            'l10n_in_pf_employee_amount': 1800,
            'l10n_in_pf_employer_amount': 1800,
        })

    def test_yearly_is_twelve_times_monthly(self):
        v = self.version
        self.assertAlmostEqual(v.ft_annual_basic, 29637 * 12, places=2)     # 3,55,644
        self.assertAlmostEqual(v.ft_annual_hra, 11855 * 12, places=2)       # 1,42,260
        self.assertAlmostEqual(v.ft_annual_meal, 1100 * 12, places=2)       #   13,200
        self.assertAlmostEqual(v.ft_annual_lta, 1000 * 12, places=2)        #   12,000
        self.assertAlmostEqual(v.ft_annual_fixed_allowance, 15682 * 12, places=2)

    def test_gross_total_reconciles_with_the_lines_above_it(self):
        """Gross Total must equal the sum of the components printed above it."""
        v = self.version
        components = sum([
            v.ft_annual_basic, v.ft_annual_hra, v.ft_annual_standard_allowance,
            v.ft_annual_performance_bonus, v.ft_annual_lta, v.ft_annual_fixed_allowance,
            v.ft_annual_meal, v.ft_annual_phone, v.ft_annual_internet,
            v.ft_annual_transport])
        self.assertAlmostEqual(v.ft_annual_gross, components, places=2)
        self.assertAlmostEqual(v.ft_annual_gross, 59274 * 12, places=2)     # 7,11,288

    def test_total_ctc_is_gross_plus_employer_cost(self):
        v = self.version
        expected = (59274 + 1800 + 1426) * 12       # gross + PF employer + gratuity
        self.assertAlmostEqual(v.ft_annual_ctc, expected, places=2)
        self.assertAlmostEqual(v.ft_monthly_ctc, 59274 + 1800 + 1426, places=2)

    def test_variable_pay_adds_to_ctc_but_not_to_monthly(self):
        """Variable pay is annual in CTC and zero per month - the whole design."""
        v = self.version
        before_annual, before_monthly = v.ft_annual_ctc, v.ft_monthly_ctc
        v.ft_annual_variable_pay = 60000
        self.assertAlmostEqual(v.ft_annual_ctc, before_annual + 60000, places=2)
        self.assertAlmostEqual(v.ft_monthly_ctc, before_monthly, places=2)

    def test_deductions_and_net(self):
        v = self.version
        self.assertAlmostEqual(v.ft_annual_pf_employee, 1800 * 12, places=2)
        self.assertAlmostEqual(v.ft_monthly_total_deductions, 1800, places=2)
        self.assertAlmostEqual(v.ft_annual_total_deductions, 1800 * 12, places=2)
        self.assertAlmostEqual(v.ft_monthly_net_payable, 59274 - 1800, places=2)
        self.assertAlmostEqual(v.ft_annual_net_payable, (59274 - 1800) * 12, places=2)

    def test_professional_tax_zero_when_not_configured(self):
        self.assertFalse(self.version.l10n_in_pt)
        self.assertAlmostEqual(self.version.ft_monthly_professional_tax, 0, places=2)
        self.assertAlmostEqual(self.version.ft_annual_professional_tax, 0, places=2)

    def test_readable_from_the_employee(self):
        """The delegated fields must resolve, not raise, from hr.employee."""
        self.assertAlmostEqual(
            self.employee.ft_annual_ctc, self.version.ft_annual_ctc, places=2)
        self.assertAlmostEqual(
            self.employee.ft_annual_gross, self.version.ft_annual_gross, places=2)
        self.assertAlmostEqual(
            self.employee.ft_annual_basic, self.version.ft_annual_basic, places=2)
