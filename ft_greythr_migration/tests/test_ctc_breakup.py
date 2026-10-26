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

    def test_variable_pay_adds_to_yearly_and_monthly_ctc(self):
        """Both CTC columns carry the variable pay: yearly in full, monthly as a twelfth."""
        v = self.version
        self.assertAlmostEqual(v.ft_monthly_variable_pay, 0, places=2)
        before_annual, before_monthly = v.ft_annual_ctc, v.ft_monthly_ctc
        v.ft_annual_variable_pay = 64000
        self.assertAlmostEqual(v.ft_monthly_variable_pay, 64000 / 12, places=2)   # 5,333.33
        self.assertAlmostEqual(v.ft_annual_ctc, before_annual + 64000, places=2)
        self.assertAlmostEqual(v.ft_monthly_ctc, before_monthly + 64000 / 12, places=2)
        # Monetary fields round to the paisa, so twelve months may differ from
        # the yearly figure by up to 12 x 0.005.
        self.assertAlmostEqual(v.ft_monthly_ctc * 12, v.ft_annual_ctc, delta=0.06)

    def test_variable_pay_stays_out_of_fixed_breakup_and_deductions(self):
        """Only the CTC totals move; fixed pay, gross, deductions and net do not."""
        v = self.version
        untouched = ['ft_annual_gross', 'l10n_in_gross_salary', 'ft_annual_basic',
                     'ft_annual_hra', 'ft_annual_meal', 'ft_annual_lta',
                     'ft_annual_fixed_allowance', 'ft_monthly_total_deductions',
                     'ft_annual_total_deductions', 'ft_monthly_net_payable',
                     'ft_annual_net_payable', 'ft_monthly_professional_tax']
        before = {name: v[name] for name in untouched}
        v.ft_annual_variable_pay = 64000
        for name in untouched:
            self.assertAlmostEqual(v[name], before[name], places=2, msg=name)
        self.assertAlmostEqual(v.ft_annual_gross, 59274 * 12, places=2)
        self.assertAlmostEqual(v.ft_monthly_net_payable, 59274 - 1800, places=2)

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
        self.version.ft_annual_variable_pay = 64000
        self.assertAlmostEqual(
            self.employee.ft_monthly_variable_pay, 64000 / 12, places=2)
        self.assertAlmostEqual(
            self.employee.ft_monthly_ctc, self.version.ft_monthly_ctc, places=2)

    def test_yearly_figures_from_the_greythr_sheet(self):
        # Basavaraju's row: greytHR works yearly first and rounds once, so these
        # are not twelve times the monthly 18,488 / 601 / 445.
        employee = self.env['hr.employee'].create({
            'name': 'Sheet Figures', 'company_id': self.company.id,
            'date_version': '2026-04-01', 'contract_date_start': '2026-04-01', 'wage': 18488,
        })
        ctc = self.env['ft.greythr.ctc'].create({
            'employee_id': employee.id, 'effective_date': '2026-04-01',
            'full_basic': 9244, 'full_hra': 3698, 'full_special_allowance': 5546,
            'full_gratuity': 445, 'full_employer_esic': 601, 'monthly_gross': 18488,
            'monthly_ctc': 26667, 'annual_ctc': 320000, 'annual_variable_pay': 64000,
            'eligible_for_pf': True, 'master_pf_basic': 15000, 'pf_base_limit': 15000,
            'payroll_pf_mode': 'capped',
        })
        ctc.action_apply_to_payroll()
        v = employee.version_id
        # Without the sheet's yearly figures: twelve times monthly.
        self.assertEqual(v.ft_annual_fixed_pay, 18488 * 12)
        self.assertEqual(v.ft_annual_gratuity, 445 * 12)
        ctc.write({'annual_fixed_pay': 221855, 'annual_pf_employer': 21600,
                   'annual_esic_employer': 7210, 'annual_gratuity': 5336})
        self.assertEqual(v.ft_annual_fixed_pay, 221855)
        self.assertEqual(v.ft_annual_esic_employer, 7210)
        self.assertEqual(v.ft_annual_gratuity, 5336)
        self.assertEqual(v.ft_annual_ctc, 320000)
        self.assertEqual(v.ft_monthly_ctc, 26667)
        # The breakup still adds up to its own Gross Total.
        self.assertEqual(v.ft_annual_gross, 18488 * 12)
        self.assertEqual(employee.ft_annual_fixed_pay, 221855)
