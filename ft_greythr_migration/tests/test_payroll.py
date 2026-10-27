from lxml import etree

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

    def _slip(self, fraction=1, date_from='2026-06-01', date_to='2026-06-30', struct=None):
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
            'struct_id': (struct or self.structure).id, 'worked_days_line_ids': worked,
        })
        slip.compute_sheet()
        return slip

    def test_full_month_no_double_count(self):
        slip = self._slip()
        lines = {l.code: l.total for l in slip.line_ids}
        # Earnings sum to 29999.5 against a source gross of 30000: the sub-rupee gap is not paid.
        # Like greytHR, every component is paid in whole rupees (7499.5 -> 7500).
        expected = {'BASIC': 15000, 'HRA': 6000, 'SPL': 7500, 'LTA': 500,
            'MEAL': 1000, 'GROSS_RECON': 0, 'GROSS': 30000, 'PF': -1800,
            'PFE': 1800, 'GRATUITY': 721, 'NET': 28200, 'CTC_TOTAL': 32521}
        for code, amount in expected.items():
            self.assertAlmostEqual(lines[code], amount, places=2, msg=code)
        self.assertFalse(self.company.l10n_in_provident_fund)
        self.assertAlmostEqual(self.employee.l10n_in_gross_salary, 29999.5, places=2)
        self.assertEqual(self.employee.l10n_in_leave_travel_allowance, 500)
        self.assertEqual(self.employee.l10n_in_gratuity, 721.15)

    def test_source_gross_gap_paid_only_from_one_rupee(self):
        self.assertEqual(self.ctc.gross_difference, 0)
        self.assertAlmostEqual(self.employee.wage, 29999.5, places=2)
        self.ctc.write({'monthly_gross': 30010})
        self.ctc.action_apply_to_payroll()
        lines = {l.code: l.total for l in self._slip().line_ids}
        self.assertAlmostEqual(lines['GROSS_RECON'], 10, places=2)
        self.assertAlmostEqual(lines['GROSS'], 30010, places=2)

    def test_unpaid_leave_prorates_allowances_and_employer_costs(self):
        slip = self._slip(.5)
        lines = {l.code: l.total for l in slip.line_ids}
        # 10 days without pay in a 30-day month: greytHR pays 20/30 (calendar days).
        for code, amount in {'GROSS': 20000, 'SPL': 5000, 'LTA': 333, 'MEAL': 667,
                'PF': -1200, 'PFE': 1200, 'GRATUITY': 481, 'NET': 18800}.items():
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

    def test_employee_pf_matches_master_pf_basic(self):
        # Basic below the cap: the employee form must show the 1,800 the payslip deducts.
        self.ctc.write({'full_basic': 10000, 'full_special_allowance': 12499.5})
        self.ctc.action_apply_to_payroll()
        version = self.employee.version_id
        self.assertEqual(version.l10n_in_pf_employee_amount, 1800)
        self.assertEqual(version.l10n_in_pf_employer_amount, 1800)
        lines = {l.code: l.total for l in self._slip().line_ids}
        self.assertEqual(lines['PF'], -1800)

    def test_part_month_rounds_like_greythr(self):
        # 1 day LOP in a 31-day month, figures from a greytHR register: each component is
        # rounded to the rupee and PF stays 1,800 while earned basic is above the cap.
        self.ctc.write({'full_basic': 21500, 'full_hra': 8600, 'full_special_allowance': 12899,
                        'full_meal_allowance': 0, 'full_leave_travel_allowance': 0,
                        'full_gratuity': 0, 'monthly_gross': 42999, 'master_pf_basic': 21500})
        self.ctc.action_apply_to_payroll()
        lines = {l.code: l.total for l in self._slip(19 / 20, '2026-07-01', '2026-07-31').line_ids}
        for code, amount in {'BASIC': 20806, 'HRA': 8323, 'SPL': 12483, 'GROSS_RECON': 0,
                             'GROSS': 41612, 'PF': -1800, 'PFE': 1800}.items():
            self.assertEqual(lines[code], amount, code)

    def test_august_with_one_and_half_days_lop(self):
        # 31 days, 1.5 days loss of pay: paid for 29.5 / 31 of the month.
        slip = self._slip(18.5 / 20, '2026-08-01', '2026-08-31')
        self.assertAlmostEqual(slip.paid_amount, 29999.5 * 29.5 / 31, places=2)
        data = slip._ft_report_values()
        self.assertEqual(data['days_in_month'], 31)
        self.assertAlmostEqual(data['effective_days'], 29.5, places=6)
        self.assertAlmostEqual(data['lop'], 1.5, places=6)

    def test_esic_employee_rounds_up(self):
        self.ctc.write({'full_basic': 9244, 'full_hra': 3698, 'full_special_allowance': 5546,
                        'full_meal_allowance': 0, 'full_leave_travel_allowance': 0,
                        'monthly_gross': 18488})
        self.ctc.action_apply_to_payroll()
        self.employee.greythr_esi_eligible = True
        self.employee.version_id.write({'l10n_in_esic': True, 'l10n_in_esic_employee_percentage': 0.0075,
                                        'l10n_in_esic_employer_percentage': 0.0325})
        lines = {l.code: l.total for l in self._slip().line_ids}
        self.assertEqual(lines['ESICS'], -139)   # 0.75% of 18,488 = 138.66

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

    def test_standard_india_employer_costs_are_ctc_costs(self):
        """Employer PF, ESI, LWF and gratuity on Odoo's India structure are CTC costs, not deductions."""
        employer = self.env.ref('ft_greythr_migration.greythr_employer_category')
        standard = self.env.ref('l10n_in_hr_payroll.hr_payroll_structure_in_employee_salary')
        self.assertNotEqual(standard, self.structure)
        for xmlid in ('hr_salary_rule_pfe_with_pf', 'l10n_in_hr_payslip_rule_employer_esicf',
                      'l10n_in_hr_payslip_rule_lwf_employer', 'l10n_in_hr_payslip_rule_gratuity'):
            rule = self.env.ref('l10n_in_hr_payroll.' + xmlid)
            self.assertEqual(rule.category_id, employer, xmlid)
            self.assertEqual(rule.struct_id, standard, xmlid)
        # On a payslip the employer PF line carries the category and stays out of the net.
        self.employee.version_id.write({'l10n_in_provident_fund': True,
                                        'l10n_in_pf_employer_amount': 1800})
        slip = self._slip(struct=standard)
        lines = {line.code: line for line in slip.line_ids}
        self.assertIn('PFE', lines)
        self.assertEqual(lines['PFE'].category_id, employer)
        self.assertIn('GRATUITY', lines)
        self.assertEqual(lines['GRATUITY'].category_id, employer)
        self.assertNotEqual(lines['PFE'].total, 0)
        net_from_categories = sum(line.total for line in slip.line_ids
                                  if line.category_id.code in ('BASIC', 'ALW', 'DED'))
        self.assertAlmostEqual(lines['NET'].total, net_from_categories, places=2)

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

    def test_reference_report_master_actual_and_deductions(self):
        from lxml import html
        slip = self._slip(.5)
        data = slip._ft_report_values()
        self.assertAlmostEqual(data['master_total'], 29999.5, places=2)
        self.assertAlmostEqual(data['gross'], 20000, places=2)
        self.assertEqual(data['deduction_total'], 1200)
        self.assertAlmostEqual(data['net'], 18800, places=2)
        self.assertNotIn('GROSS RECONCILIATION', [row['name'] for row in data['earnings']])
        self.assertEqual(data['lop'], 10)
        self.assertEqual(data['effective_days'], 20)
        self.assertEqual(data['days_in_month'], 30)
        amounts = {row['name']: row for row in data['earnings']}
        self.assertEqual(amounts['LEAVE TRAVEL ALLOWANCE']['master'], 500)
        self.assertEqual(amounts['LEAVE TRAVEL ALLOWANCE']['actual'], 333)
        result, _ = self.env['ir.actions.report']._render_qweb_html(
            'ft_greythr_migration.action_report_fingertip_payslip', slip.ids)
        doc = html.fromstring(result)
        text = doc.text_content()
        for label in ('Payslip for the month of June 2026', 'Master', 'Actual',
                'EMP EFFECTIVE WORKDAYS:', 'PF UAN:', 'LOP:', 'Total Deductions:', 'Print Date:'):
            self.assertIn(label, text)
        self.assertNotIn('Gratuity Provision', text)
        self.assertNotIn('Provident fund - Employer', text)
        self.assertEqual(slip.struct_id.report_id, self.env.ref(
            'ft_greythr_migration.action_report_fingertip_payslip'))

    def test_reference_report_preserves_cents_and_unpaid_master(self):
        slip = self._slip(0)
        data = slip._ft_report_values()
        self.assertEqual(data['gross'], 0)
        self.assertAlmostEqual(data['master_total'], 29999.5, places=2)
        self.assertEqual(slip._ft_report_number(0.46), '0.46')
        self.assertEqual(slip._ft_report_number(15000), '15000')
        self.assertEqual(slip._ft_report_number(None), '')

    def test_template_selector_includes_fingertip_and_standard_reports(self):
        Structure = self.env['hr.payroll.structure']
        domain = Structure.fields_get(['report_id'])['report_id']['domain']
        reports = self.env['ir.actions.report'].search(domain)
        self.assertIn(self.env.ref('ft_greythr_migration.action_report_fingertip_payslip'), reports)
        self.assertIn(self.env.ref('l10n_in_hr_payroll.action_report_payslip_in'), reports)
        self.assertIn(self.env.ref('hr_payroll.action_report_payslip'), reports)
        self.assertTrue(all(r.model == 'hr.payslip' and r.report_type == 'qweb-pdf' for r in reports))

    def test_meal_allowance_listed_with_salary_components(self):
        for model, view in (('hr.employee', 'hr.view_employee_form'),
                            ('hr.version', 'hr.hr_contract_template_form_view')):
            with self.subTest(model=model):
                arch = etree.fromstring(self.env[model].get_view(self.env.ref(view).id, 'form')['arch'])
                meal = arch.xpath("//field[@name='l10n_in_meal_voucher_amount']")
                self.assertEqual(len(meal), 1)
                self.assertEqual(meal[0].get('string'), 'Meal Allowance')
                label = meal[0].getparent().getprevious()
                self.assertEqual((label.tag, label.get('for'), label.get('string')),
                                 ('label', 'l10n_in_meal_voucher_amount', 'Meal Allowance'))
                self.assertEqual(label.getprevious().xpath("field/@name"), ['l10n_in_fixed_allowance'])

    def test_children_education_allowance_reaches_payslip(self):
        """It behaves like a salary component, not a side payment: applying the
        CTC writes it to the version, its own rule pays it, and it lands inside
        gross, so the payslip and the yearly CTC sheet agree on one number."""
        ctc = self.ctc.copy({
            'effective_date': '2026-07-01', 'monthly_gross': 32000,
            'full_children_education_allowance': 2000,
        })
        ctc.action_apply_to_payroll()
        version = self.employee._get_version('2026-07-01')

        # On the version, and twelve times that on the yearly sheet.
        self.assertAlmostEqual(version.ft_children_education_allowance, 2000, places=2)
        self.assertAlmostEqual(version.ft_annual_children_education, 24000, places=2)

        # Inside gross, not bolted on beside it.
        self.assertAlmostEqual(version.l10n_in_gross_salary, 31999.5, places=2)

        slip = self._slip(date_from='2026-07-01', date_to='2026-07-31')
        lines = {l.code: l.total for l in slip.line_ids}
        self.assertAlmostEqual(lines['EDUALW'], 2000, places=2)
        self.assertAlmostEqual(lines['GROSS'], 32000, places=2)
        # Paid once: gross is the earnings, not the earnings plus the allowance.
        self.assertAlmostEqual(
            lines['GROSS'],
            lines['BASIC'] + lines['HRA'] + lines['SPL'] + lines['LTA']
            + lines['MEAL'] + lines['EDUALW'], places=2)

    def test_children_education_allowance_listed_with_salary_components(self):
        for model, view in (('hr.employee', 'hr.view_employee_form'),
                            ('hr.version', 'hr.hr_contract_template_form_view')):
            with self.subTest(model=model):
                arch = etree.fromstring(self.env[model].get_view(self.env.ref(view).id, 'form')['arch'])
                field = arch.xpath("//field[@name='ft_children_education_allowance']")
                self.assertEqual(len(field), 1)

    def test_children_education_allowance_on_india_regular_pay(self):
        """The same allowance on Odoo's own India structure, where there is no
        greytHR CTC to read from: the rule takes it off the version directly,
        and the ALW category carries it into that structure's own gross."""
        attendance = self.env.ref('hr_work_entry.work_entry_type_attendance')
        employee = self.env['hr.employee'].create({
            'name': 'Regular Pay Employee', 'company_id': self.company.id,
            'date_version': '2026-06-01', 'contract_date_start': '2026-06-01',
            'wage': 30000,
        })
        employee.ft_children_education_allowance = 1500
        slip = self.env['hr.payslip'].create({
            'name': 'Regular pay CEA', 'employee_id': employee.id,
            'date_from': '2026-06-01', 'date_to': '2026-06-30',
            'struct_id': self.env.ref(
                'l10n_in_hr_payroll.hr_payroll_structure_in_employee_salary').id,
            'worked_days_line_ids': [Command.create({
                'work_entry_type_id': attendance.id,
                'number_of_days': 20, 'number_of_hours': 160})],
        })
        slip.compute_sheet()
        lines = {l.code: l.total for l in slip.line_ids}
        self.assertAlmostEqual(lines['EDUALW'], 1500, places=2)
        # GROSS on this structure is BASIC + ALW, and EDUALW is an ALW rule.
        basic = sum(l.total for l in slip.line_ids if l.category_id.code == 'BASIC')
        allowances = sum(l.total for l in slip.line_ids if l.category_id.code == 'ALW')
        self.assertAlmostEqual(lines['GROSS'], basic + allowances, places=2)
        self.assertIn('EDUALW', [l.code for l in slip.line_ids
                                 if l.category_id.code == 'ALW'])

    # ------------------------------------------------------------------
    # Fixed Pay must equal the monthly wage
    # ------------------------------------------------------------------
    def test_32_gross_equals_wage_with_meal_allowance(self):
        """l10n_in adds meal on top of the wage; a CTC sheet does not.

        Without the override, an employee on 1,46,379.57 with a 2,200 meal
        allowance shows Fixed Pay of 1,48,579.57 -- 2,200 more than the salary
        actually agreed.
        """
        employee = self.env['hr.employee'].create({
            'name': 'Fixed Pay Employee', 'company_id': self.company.id,
            'date_version': '2026-09-01', 'contract_date_start': '2026-09-01',
            'wage': 146379.57,
        })
        version = employee.sudo().version_id
        version.write({
            'l10n_in_basic_salary_amount': 73190.00,
            'l10n_in_hra': 29276.00,
            'l10n_in_leave_travel_allowance': 3000.00,
            'l10n_in_meal_voucher_amount': 2200.00,
        })
        self.assertAlmostEqual(version.l10n_in_gross_salary, 146379.57, 2)
        # The residual absorbs the meal allowance rather than stacking on top.
        self.assertAlmostEqual(version.l10n_in_fixed_allowance, 38713.57, 2)
        # And the yearly panel follows from it.
        self.assertAlmostEqual(version.ft_annual_gross, 146379.57 * 12, 2)

    def test_33_gross_still_equals_wage_without_add_ons(self):
        """No meal or phone: behaviour is unchanged from standard l10n_in."""
        employee = self.env['hr.employee'].create({
            'name': 'Plain Employee', 'company_id': self.company.id,
            'date_version': '2026-09-01', 'contract_date_start': '2026-09-01',
            'wage': 50000.00,
        })
        version = employee.sudo().version_id
        version.write({'l10n_in_basic_salary_amount': 25000.00,
                       'l10n_in_hra': 10000.00})
        self.assertAlmostEqual(version.l10n_in_gross_salary, 50000.00, 2)

    def test_34_ctc_driven_versions_are_untouched(self):
        """Employees on an applied greytHR CTC keep the CTC's own figure."""
        version = self.employee.sudo().version_id
        self.assertEqual(version.greythr_ctc_id, self.ctc)
        self.assertAlmostEqual(version.l10n_in_fixed_allowance,
                               self.ctc.full_special_allowance, 2)

    def test_bulk_apply_and_review_from_employee_list(self):
        def new_employee(name, gross):
            employee = self.env['hr.employee'].create({
                'name': name, 'company_id': self.company.id,
                'date_version': '2026-06-01', 'contract_date_start': '2026-06-01', 'wage': 1000})
            self.env['ft.greythr.ctc'].create({
                'employee_id': employee.id, 'effective_date': '2026-06-01',
                'full_basic': gross / 2, 'full_special_allowance': gross / 2, 'monthly_gross': gross,
                'eligible_for_pf': True, 'master_pf_basic': 15000, 'pf_base_limit': 15000,
                'payroll_pf_mode': 'capped'})
            return employee
        good = new_employee('Bulk Good', 40000)
        bad = new_employee('Bulk Bad', 0)   # no gross: Apply refuses it
        result = (good | bad).action_greythr_apply_ctc()
        self.assertEqual(good.version_id.wage, 40000)
        self.assertEqual(good.version_id.structure_type_id,
                         self.env.ref('ft_greythr_migration.greythr_structure_type'))
        self.assertFalse(bad.version_id.greythr_ctc_id)
        self.assertEqual(result['params']['type'], 'warning')
        self.assertIn('Bulk Bad', result['params']['message'])

        (good | bad).action_greythr_mark_reviewed()
        self.assertTrue(good.greythr_ctc_ids.payroll_reviewed)
        self.assertFalse(bad.greythr_ctc_ids.payroll_reviewed)
        # Reviewed CTCs are skipped on the next bulk run.
        self.assertIn('0 CTC', good.action_greythr_apply_ctc()['params']['message'])

    def test_payment_advice_reads_ifsc_field(self):
        bank = self.env['res.bank'].create({'name': 'Union Bank of India', 'ifsc_code': 'UBIN0803952'})
        self.employee.bank_account_ids = [Command.create({
            'acc_number': '39510100143214', 'bank_id': bank.id,
            'partner_id': self.employee.work_contact_id.id, 'allow_out_payment': True})]
        self.assertFalse(self.employee._get_employees_with_invalid_ifsc())
        self.ctc.payroll_reviewed = True
        slip = self._slip()
        slip.action_payslip_done()
        wizard = self.env['hr.payroll.payment.report.wizard'].create({'payslip_ids': slip.ids})
        rows = wizard._get_report_data(slip)
        self.assertEqual([row['ifsc_code'] for row in rows], ['UBIN0803952'])
        bank.ifsc_code = False
        self.assertTrue(self.employee._get_employees_with_invalid_ifsc())

    def test_pay_run_post_entries_without_drafts(self):
        run = self.env['hr.payslip.run'].create({
            'name': 'June 2026', 'date_start': '2026-06-01', 'date_end': '2026-06-30'})
        slip = self._slip()
        slip.payslip_run_id = run
        self.assertEqual(run.ft_draft_move_count, 0)
        with self.assertRaises(UserError):
            run.action_ft_post_entries()

    def test_non_taxable_allowance_after_gross(self):
        baseline = {l.code: l.total for l in self._slip().line_ids}
        self.ctc.write({'full_non_taxable_allowance': 1000})
        self.ctc.action_apply_to_payroll()
        self.assertEqual(self.employee.ft_non_taxable_allowance, 1000)
        self.assertEqual(self.employee.wage, baseline['GROSS'] - 0.5)   # wage unchanged (29999.5)
        lines = {l.code: l.total for l in self._slip().line_ids}
        self.assertEqual(lines['NTA'], 1000)
        self.assertEqual(lines['GROSS'], baseline['GROSS'])           # not in gross: PT/ESI untouched
        self.assertEqual(lines['NET'], baseline['NET'] + 1000)        # straight into net
        self.assertEqual(lines['CTC_TOTAL'], baseline['CTC_TOTAL'])   # not in CTC
        self.assertEqual(lines['CTC_DIFF'], baseline['CTC_DIFF'])

    def test_non_taxable_allowance_prorated_and_editable(self):
        self.ctc.write({'full_non_taxable_allowance': 1000})
        self.ctc.action_apply_to_payroll()
        slip = self._slip(.5)      # 10 days without pay in a 30-day month
        self.assertEqual(slip.ft_non_taxable_allowance, 667)
        slip.ft_non_taxable_allowance = 400
        slip.compute_sheet()
        self.assertEqual({l.code: l.total for l in slip.line_ids}['NTA'], 400)
        data = slip._ft_report_values()
        row = next(r for r in data['earnings'] if r['name'] == 'NON-TAXABLE ALLOWANCE')
        self.assertEqual((row['master'], row['actual']), (1000, 400))
