# -*- coding: utf-8 -*-
"""The eight scenarios from the specification."""
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestLeaveAccrual(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Leave Accrual Test Co',
            'country_id': cls.env.ref('base.in').id,
        })
        cls.env = cls.env(context=dict(
            cls.env.context, allowed_company_ids=[cls.company.id],
            tracking_disable=True, mail_create_nosubscribe=True,
            mail_create_nolog=True))
        cls.env.user.group_ids |= cls.env.ref('hr.group_hr_manager')

        from odoo.addons.ftp_employee_leave_accrual.models.leave_policy_setup \
            import setup_leave_policy
        cls.casual_plan, cls.sick_plan = setup_leave_policy(cls.env, cls.company)
        cls.company.invalidate_recordset()

        cls.confirmed = cls.env.ref('hr.contract_type_permanent')
        cls.probation = cls.env.ref(
            'l10n_in_hr_payroll.l10n_in_contract_type_probation')
        cls.intern = cls.env.ref('hr.contract_type_intern')
        cls.consultant = cls.env.ref(
            'ftp_employee_leave_accrual.contract_type_consultant')
        cls.start = date(2026, 4, 1)

    def _employee(self, name, contract_type):
        return self.env['hr.employee'].create({
            'name': name, 'company_id': self.company.id,
            'date_version': self.start, 'contract_date_start': self.start,
            'contract_type_id': contract_type.id,
        })

    def _allocations(self, employee, leave_type=None):
        domain = [('employee_id', '=', employee.id), ('state', '!=', 'refuse')]
        if leave_type:
            domain.append(('holiday_status_id', '=', leave_type.id))
        return self.env['hr.leave.allocation'].sudo().search(domain)

    # ------------------------------------------------------------------
    def test_01_probation_gets_nothing(self):
        """Scenario 1: Rahul on Probation receives no allocation."""
        rahul = self._employee('Rahul Nair', self.probation)
        self.assertFalse(self._allocations(rahul))

    def test_02_confirming_creates_both(self):
        """Scenario 2: Probation -> Confirmed creates casual and sick."""
        rahul = self._employee('Rahul Nair', self.probation)
        self.assertFalse(self._allocations(rahul))
        rahul.contract_type_id = self.confirmed
        allocations = self._allocations(rahul)
        self.assertEqual(len(allocations), 2)
        self.assertEqual(
            set(allocations.mapped('accrual_plan_id')),
            {self.casual_plan, self.sick_plan})
        # Approved, or Odoo will never accrue against them.
        self.assertEqual(set(allocations.mapped('state')), {'validate'})
        self.assertEqual(set(allocations.mapped('allocation_type')), {'accrual'})

    def test_03_cron_does_not_duplicate(self):
        """Scenario 3: running the sweep again changes nothing."""
        rahul = self._employee('Rahul Nair', self.confirmed)
        self.assertEqual(len(self._allocations(rahul)), 2)
        self.env['hr.employee']._cron_ensure_leave_allocations()
        self.env['hr.employee']._cron_ensure_leave_allocations()
        self.assertEqual(len(self._allocations(rahul)), 2)

    def test_04_consultant_gets_nothing(self):
        """Scenario 4: Anjali the consultant receives no allocation."""
        anjali = self._employee('Anjali Menon', self.consultant)
        self.env['hr.employee']._cron_ensure_leave_allocations()
        self.assertFalse(self._allocations(anjali))

    def test_05_intern_gets_nothing(self):
        """Scenario 5: Arun the intern receives no allocation."""
        arun = self._employee('Arun Kumar', self.intern)
        self.env['hr.employee']._cron_ensure_leave_allocations()
        self.assertFalse(self._allocations(arun))

    def test_06_only_the_missing_one_is_created(self):
        """Scenario 6: casual already there, only sick is added."""
        # Build the half-allocated state honestly: not yet eligible, with a
        # casual allocation already granted by hand.
        employee = self._employee('Half Allocated', self.probation)
        casual_type = self.company.ftp_casual_leave_type_id
        sick_type = self.company.ftp_sick_leave_type_id
        self.env['hr.leave.allocation'].sudo().create({
            'name': 'Casual by hand',
            'employee_id': employee.id,
            'holiday_status_id': casual_type.id,
            'accrual_plan_id': self.casual_plan.id,
            'allocation_type': 'accrual',
            'date_from': self.start,
            'number_of_days': 0.0,
        }).action_approve()
        self.assertEqual(len(self._allocations(employee)), 1)

        employee.contract_type_id = self.confirmed
        allocations = self._allocations(employee)
        self.assertEqual(len(allocations), 2, "only the sick one should be added")
        self.assertEqual(
            len(self._allocations(employee, casual_type)), 1,
            "the existing casual allocation must not be duplicated")
        self.assertEqual(len(self._allocations(employee, sick_type)), 1)

    # ------------------------------------------------------------------
    # Carry-over is Odoo's job; what this module owns is the configuration.
    # ------------------------------------------------------------------
    def test_07_casual_plan_carries_over_on_1_april(self):
        """Scenario 7: casual leave rolls into the new financial year."""
        self.assertTrue(self.casual_plan.can_be_carryover)
        self.assertEqual(self.casual_plan.carryover_date, 'other')
        self.assertEqual(self.casual_plan.carryover_month, '4')
        self.assertEqual(self.casual_plan.carryover_day, '1')
        level = self.casual_plan.level_ids
        self.assertEqual(len(level), 1)
        self.assertEqual(level.frequency, 'monthly')
        self.assertAlmostEqual(level.added_value, 1.0, 2)
        self.assertEqual(level.action_with_unused_accruals, 'all')

    def test_08_sick_plan_loses_the_balance_on_1_april(self):
        """Scenario 8: sick leave does not carry forward."""
        self.assertEqual(self.sick_plan.carryover_month, '4')
        self.assertEqual(self.sick_plan.carryover_day, '1')
        level = self.sick_plan.level_ids
        self.assertEqual(level.frequency, 'monthly')
        self.assertAlmostEqual(level.added_value, 0.5, 2)
        self.assertEqual(level.action_with_unused_accruals, 'lost')

    def test_09_carry_forward_limit_is_configurable(self):
        """The cap reaches the plan rather than being hardcoded."""
        company = self.env['res.company'].create({'name': 'Capped Co'})
        company.ftp_casual_max_carryover = 12
        from odoo.addons.ftp_employee_leave_accrual.models.leave_policy_setup \
            import setup_leave_policy
        casual, _sick = setup_leave_policy(self.env, company)
        self.assertEqual(casual.level_ids.carryover_options, 'limited')
        self.assertEqual(casual.level_ids.postpone_max_days, 12)

    def test_10_odoo_actually_accrues_and_rolls_over(self):
        """Drive Odoo's own engine across 1 April and check both plans.

        Casual keeps its balance, sick is reset. Nothing in this module
        touches the numbers -- this is the standard accrual doing the work.
        """
        employee = self._employee('Rollover Nair', self.confirmed)
        allocations = self._allocations(employee)
        casual = allocations.filtered(
            lambda a: a.accrual_plan_id == self.casual_plan)
        sick = allocations.filtered(
            lambda a: a.accrual_plan_id == self.sick_plan)
        # Accrue from 1 April to the following 1 March: eleven monthly runs.
        allocations._process_accrual_plans(date_to=date(2027, 3, 1))
        casual_before = casual.number_of_days
        sick_before = sick.number_of_days
        self.assertGreater(casual_before, 0, "casual leave should have accrued")
        self.assertGreater(sick_before, 0, "sick leave should have accrued")
        # Cross the financial year boundary.
        allocations._process_accrual_plans(date_to=date(2027, 4, 2))
        self.assertGreaterEqual(
            casual.number_of_days, casual_before,
            "casual leave must survive the 1 April rollover")
        self.assertLess(
            sick.number_of_days, sick_before + 0.5,
            "sick leave must not carry its old balance past 1 April")

    # ------------------------------------------------------------------
    def test_11_losing_eligibility_keeps_history(self):
        """Going back to Probation must not delete anything."""
        rahul = self._employee('Rahul Nair', self.confirmed)
        allocations = self._allocations(rahul)
        self.assertEqual(len(allocations), 2)
        rahul.contract_type_id = self.probation
        self.assertEqual(len(self._allocations(rahul)), 2)
        self.assertTrue(all(a.exists() for a in allocations))

    def test_12_start_date_prefers_the_confirmation_date(self):
        employee = self._employee('Dated Nair', self.probation)
        employee.sudo().version_id.trial_date_end = date(2026, 10, 1)
        employee.contract_type_id = self.confirmed
        allocations = self._allocations(employee)
        self.assertEqual(set(allocations.mapped('date_from')), {date(2026, 10, 1)})

    def test_13_start_date_falls_back_to_joining_date(self):
        employee = self._employee('Joined Nair', self.probation)
        employee.sudo().version_id.trial_date_end = False
        employee.contract_type_id = self.confirmed
        allocations = self._allocations(employee)
        self.assertEqual(set(allocations.mapped('date_from')), {self.start})

    def test_14_disabled_policy_creates_nothing(self):
        self.company.ftp_leave_accrual_enabled = False
        employee = self._employee('Switched Off', self.confirmed)
        self.assertFalse(self._allocations(employee))

    def test_15_server_action_processes_only_eligible(self):
        """HR selects three employees; only the confirmed one is processed."""
        # Create them with the automation off, so nothing is allocated yet and
        # the server action is what does the work.
        self.company.ftp_leave_accrual_enabled = False
        rahul = self._employee('Rahul Nair', self.confirmed)
        anjali = self._employee('Anjali Menon', self.consultant)
        arun = self._employee('Arun Kumar', self.intern)
        self.assertFalse(self._allocations(rahul))
        self.company.ftp_leave_accrual_enabled = True

        (rahul | anjali | arun).action_generate_leave_allocations()
        self.assertEqual(len(self._allocations(rahul)), 2)
        self.assertFalse(self._allocations(anjali))
        self.assertFalse(self._allocations(arun))

    def test_16_multi_company_does_not_mix(self):
        other = self.env['res.company'].create({'name': 'Other Co'})
        from odoo.addons.ftp_employee_leave_accrual.models.leave_policy_setup \
            import setup_leave_policy
        setup_leave_policy(self.env, other)
        employee = self.env['hr.employee'].create({
            'name': 'Other Co Employee', 'company_id': other.id,
            'date_version': self.start, 'contract_date_start': self.start,
            'contract_type_id': self.confirmed.id,
        })
        allocations = self._allocations(employee)
        self.assertEqual(len(allocations), 2)
        self.assertEqual(
            set(allocations.mapped('accrual_plan_id.company_id')), {other})
        self.assertNotIn(self.casual_plan, allocations.mapped('accrual_plan_id'))

    # ------------------------------------------------------------------
    # HR clarifications: 10-day cap, Trainee stage, parental leave
    # ------------------------------------------------------------------
    def test_17_carry_forward_is_capped_at_ten(self):
        """HR: carry forward a maximum of 10 casual leaves annually."""
        company = self.env['res.company'].create({'name': 'Cap Default Co'})
        self.assertAlmostEqual(company.ftp_casual_max_carryover, 10.0, 2)
        from odoo.addons.ftp_employee_leave_accrual.models.leave_policy_setup \
            import setup_leave_policy
        casual, sick = setup_leave_policy(self.env, company)
        self.assertEqual(casual.level_ids.carryover_options, 'limited')
        self.assertEqual(casual.level_ids.postpone_max_days, 10)
        # Everything else collapses.
        self.assertEqual(sick.level_ids.action_with_unused_accruals, 'lost')

    def test_18_changing_the_cap_reaches_the_existing_plan(self):
        """The setting must not be decorative once the plan exists."""
        from odoo.addons.ftp_employee_leave_accrual.models.leave_policy_setup \
            import setup_leave_policy
        self.company.ftp_casual_max_carryover = 6
        self.company.ftp_casual_monthly_accrual = 1.5
        setup_leave_policy(self.env, self.company)
        self.assertEqual(self.casual_plan.level_ids.postpone_max_days, 6)
        self.assertAlmostEqual(self.casual_plan.level_ids.added_value, 1.5, 2)

    def test_19_trainee_is_not_eligible(self):
        """HR's fifth stage: Trainee gets no monthly accrual."""
        trainee_type = self.env.ref(
            'ftp_employee_leave_accrual.contract_type_trainee')
        trainee = self._employee('Divya Pillai', trainee_type)
        self.env['hr.employee']._cron_ensure_leave_allocations()
        self.assertFalse(self._allocations(trainee))

    def _parental_leave(self, employee, leave_type, days, start):
        return self.env['hr.leave'].sudo().create({
            'name': 'Parental', 'employee_id': employee.id,
            'holiday_status_id': leave_type.id,
            'request_date_from': start,
            'request_date_to': start + relativedelta(days=int(days) - 1),
        })

    def test_20_parental_leave_needs_two_years_of_service(self):
        """HR: maternity and paternity apply after 2 years of service."""
        from odoo.exceptions import ValidationError
        employee = self._employee('New Joiner', self.confirmed)
        maternity = self.company.ftp_maternity_leave_type_id
        self.assertTrue(maternity)
        # Joined 1 April 2026; asking in the same year is too early.
        with self.assertRaises(ValidationError):
            self._parental_leave(employee, maternity, 5, date(2026, 6, 1))

    def test_21_parental_leave_allowed_after_two_years(self):
        employee = self._employee('Long Server', self.confirmed)
        paternity = self.company.ftp_paternity_leave_type_id
        leave = self._parental_leave(employee, paternity, 3, date(2028, 6, 1))
        self.assertTrue(leave.exists())

    def test_22_paternity_is_capped_at_three_days(self):
        from odoo.exceptions import ValidationError
        employee = self._employee('Long Server', self.confirmed)
        paternity = self.company.ftp_paternity_leave_type_id
        with self.assertRaises(ValidationError):
            self._parental_leave(employee, paternity, 10, date(2028, 6, 1))

    def test_25_maternity_cap_counts_calendar_days(self):
        """200 calendar days is ~143 working days and used to slip through."""
        from odoo.exceptions import ValidationError
        employee = self._employee('Long Server', self.confirmed)
        maternity = self.company.ftp_maternity_leave_type_id
        with self.assertRaises(ValidationError):
            self._parental_leave(employee, maternity, 200, date(2028, 6, 1))
        # Six months exactly is still fine.
        leave = self._parental_leave(employee, maternity, 180, date(2029, 6, 1))
        self.assertTrue(leave.exists())

    def test_26_service_rule_applies_to_maternity_too(self):
        """The setting governs both, not just paternity."""
        from odoo.exceptions import ValidationError
        employee = self._employee('New Joiner', self.confirmed)
        for leave_type in (self.company.ftp_maternity_leave_type_id,
                           self.company.ftp_paternity_leave_type_id):
            with self.subTest(leave_type=leave_type.name):
                with self.assertRaises(ValidationError):
                    self._parental_leave(employee, leave_type, 3, date(2026, 6, 1))

    def test_23_parental_types_are_company_owned(self):
        """Must not adopt one of the dozen localisation maternity types."""
        maternity = self.company.ftp_maternity_leave_type_id
        paternity = self.company.ftp_paternity_leave_type_id
        self.assertEqual(maternity.company_id, self.company)
        self.assertEqual(paternity.company_id, self.company)
        # Granted on the event, so no allocation stands behind them.
        self.assertFalse(maternity.requires_allocation)
        self.assertFalse(paternity.requires_allocation)

    def test_24_probation_still_gets_nothing(self):
        """HR: probation employees have no paid leave, absences are LOP."""
        rahul = self._employee('Rahul Nair', self.probation)
        self.env['hr.employee']._cron_ensure_leave_allocations()
        self.assertFalse(self._allocations(rahul))
