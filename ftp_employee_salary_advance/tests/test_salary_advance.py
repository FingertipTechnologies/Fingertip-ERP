# -*- coding: utf-8 -*-
"""The six scenarios from the specification, end to end on real payslips."""
from dateutil.relativedelta import relativedelta

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSalaryAdvance(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Salary Advance Test Co',
            'country_id': cls.env.ref('base.in').id,
            'currency_id': cls.env.ref('base.INR').id,
        })
        cls.env = cls.env(context=dict(
            cls.env.context, allowed_company_ids=[cls.company.id],
            tracking_disable=True, mail_create_nosubscribe=True,
            mail_create_nolog=True))
        cls.env.user.group_ids |= cls.env.ref('hr.group_hr_manager')
        cls.start = fields.Date.today().replace(day=1) - relativedelta(months=6)
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Rahul Nair', 'company_id': cls.company.id,
            'date_version': cls.start, 'contract_date_start': cls.start,
            'wage': 50000,
        })
        cls.structure = cls.env.ref('hr_payroll.default_structure')
        cls.attendance = cls.env.ref('hr_work_entry.work_entry_type_attendance')

    # ------------------------------------------------------------------
    def _advance(self, amount, installment):
        advance = self.env['hr.salary.advance'].create({
            'employee_id': self.employee.id,
            'advance_amount': amount,
            'monthly_installment': installment,
            'advance_date': self.start,
        })
        advance.action_submit()
        advance.action_approve()
        return advance

    def _payslip(self, month_offset):
        """A payslip for the Nth month after the advance date."""
        date_from = self.start + relativedelta(months=month_offset, day=1)
        date_to = date_from + relativedelta(months=1, days=-1)
        slip = self.env['hr.payslip'].create({
            'name': 'Slip %s' % date_from,
            'employee_id': self.employee.id,
            'date_from': date_from, 'date_to': date_to,
            'struct_id': self.structure.id,
            'worked_days_line_ids': [Command.create({
                'work_entry_type_id': self.attendance.id,
                'number_of_days': 20, 'number_of_hours': 160})],
        })
        slip.compute_sheet()
        return slip

    def _advance_line(self, slip):
        return sum(slip.line_ids.filtered(
            lambda l: l.code == 'SALARY_ADVANCE').mapped('total'))

    # ------------------------------------------------------------------
    def test_01_schedule_60000(self):
        """Scenario 1: 60,000 at 5,000 gives twelve equal installments."""
        advance = self._advance(60000, 5000)
        self.assertEqual(advance.number_of_installments, 12)
        self.assertEqual(len(advance.installment_ids), 12)
        self.assertEqual(set(advance.installment_ids.mapped('amount')), {5000})
        self.assertAlmostEqual(sum(advance.installment_ids.mapped('amount')), 60000, 2)

    def test_02_final_installment_is_trimmed(self):
        """Scenario 2: 52,000 at 5,000 gives ten of 5,000 and one of 2,000."""
        advance = self._advance(52000, 5000)
        amounts = advance.installment_ids.sorted('installment_no').mapped('amount')
        self.assertEqual(len(amounts), 11)
        self.assertEqual(amounts[:10], [5000] * 10)
        self.assertAlmostEqual(amounts[-1], 2000, 2)
        self.assertAlmostEqual(sum(amounts), 52000, 2)

    def test_03_full_recovery_completes_the_advance(self):
        """Twelve finalised payslips recover the lot and close the advance."""
        advance = self._advance(60000, 5000)
        for month in range(1, 13):
            slip = self._payslip(month)
            self.assertAlmostEqual(self._advance_line(slip), -5000, 2)
            slip.action_payslip_done()
        self.assertAlmostEqual(advance.recovered_amount, 60000, 2)
        self.assertAlmostEqual(advance.remaining_amount, 0, 2)
        self.assertEqual(advance.state, 'completed')
        self.assertTrue(advance.completion_date)

    def test_04_draft_payslip_does_not_recover(self):
        """A draft payslip reserves but never moves the balance."""
        advance = self._advance(60000, 5000)
        slip = self._payslip(1)
        self.assertAlmostEqual(self._advance_line(slip), -5000, 2)
        self.assertAlmostEqual(advance.recovered_amount, 0, 2)
        self.assertEqual(advance.installment_ids[0].state, 'pending')
        slip.action_payslip_done()
        self.assertAlmostEqual(advance.recovered_amount, 5000, 2)
        self.assertEqual(advance.installment_ids[0].state, 'deducted')

    def test_05_reset_returns_the_installment(self):
        """Scenario 3: resetting a payslip puts the installment back."""
        advance = self._advance(60000, 5000)
        slip = self._payslip(1)
        slip.action_payslip_done()
        self.assertAlmostEqual(advance.recovered_amount, 5000, 2)
        slip.action_payslip_cancel()
        self.assertAlmostEqual(advance.recovered_amount, 0, 2)
        self.assertAlmostEqual(advance.remaining_amount, 60000, 2)
        self.assertEqual(
            set(advance.installment_ids.mapped('state')), {'pending'})

    def test_06_recompute_does_not_duplicate(self):
        """Scenario 4: recomputing the same payslip deducts once, not twice."""
        advance = self._advance(60000, 5000)
        slip = self._payslip(1)
        slip.compute_sheet()
        slip.compute_sheet()
        self.assertAlmostEqual(self._advance_line(slip), -5000, 2)
        self.assertEqual(len(slip.salary_advance_installment_ids), 1)

    def test_07_second_payslip_same_period_takes_nothing(self):
        """Scenario 4: a second payslip for the same month must not deduct."""
        advance = self._advance(60000, 5000)
        first = self._payslip(1)
        self.assertAlmostEqual(self._advance_line(first), -5000, 2)
        second = self._payslip(1)
        self.assertAlmostEqual(self._advance_line(second), 0, 2)
        self.assertFalse(second.salary_advance_installment_ids)

    def test_08_two_advances_are_combined_but_tracked_apart(self):
        """Scenario 5: 3,000 + 2,000 shows as one 5,000 line, two balances."""
        first = self._advance(30000, 3000)
        second = self._advance(20000, 2000)
        slip = self._payslip(1)
        self.assertAlmostEqual(self._advance_line(slip), -5000, 2)
        slip.action_payslip_done()
        self.assertAlmostEqual(first.recovered_amount, 3000, 2)
        self.assertAlmostEqual(second.recovered_amount, 2000, 2)
        self.assertAlmostEqual(first.remaining_amount, 27000, 2)
        self.assertAlmostEqual(second.remaining_amount, 18000, 2)

    def test_09_completed_advance_stops_deducting(self):
        """Scenario 6: nothing is taken once the advance is completed."""
        advance = self._advance(10000, 5000)
        for month in (1, 2):
            self._payslip(month).action_payslip_done()
        self.assertEqual(advance.state, 'completed')
        later = self._payslip(3)
        self.assertAlmostEqual(self._advance_line(later), 0, 2)

    def test_10_recovery_starts_automatically(self):
        """An approved advance flips to running on the first payslip."""
        advance = self._advance(60000, 5000)
        self.assertEqual(advance.state, 'approved')
        self._payslip(1)
        self.assertEqual(advance.state, 'running')

    # ------------------------------------------------------------------
    def test_11_validations(self):
        advance = self._advance(60000, 5000)
        # Cannot cancel once money has moved.
        self._payslip(1).action_payslip_done()
        with self.assertRaises(UserError):
            advance.action_cancel()
        # Cannot delete once approved.
        with self.assertRaises(UserError):
            advance.unlink()
        # Cannot re-price an approved advance.
        with self.assertRaises(UserError):
            advance.advance_amount = 70000

    def test_12_cancel_before_recovery_is_allowed(self):
        advance = self._advance(60000, 5000)
        advance.action_cancel()
        self.assertEqual(advance.state, 'cancelled')
        self.assertEqual(
            set(advance.installment_ids.mapped('state')), {'cancelled'})
        slip = self._payslip(1)
        self.assertAlmostEqual(self._advance_line(slip), 0, 2)

    def test_13_reference_sequence(self):
        advance = self._advance(60000, 5000)
        self.assertTrue(advance.name.startswith('ADV/'))
        self.assertNotEqual(advance.name, 'New')

    # ------------------------------------------------------------------
    # Schedule drawn up on creation, driven from either direction
    # ------------------------------------------------------------------
    def test_14_schedule_exists_before_approval(self):
        """The schedule is there as soon as the record is saved."""
        advance = self.env['hr.salary.advance'].create({
            'employee_id': self.employee.id,
            'advance_amount': 60000, 'monthly_installment': 5000,
            'advance_date': self.start,
        })
        self.assertEqual(advance.state, 'draft')
        self.assertEqual(len(advance.installment_ids), 12)
        self.assertAlmostEqual(sum(advance.installment_ids.mapped('amount')), 60000, 2)

    def test_15_editing_the_count_redrives_the_installment(self):
        """Typing a number of installments works the monthly amount back out."""
        advance = self.env['hr.salary.advance'].create({
            'employee_id': self.employee.id,
            'advance_amount': 100000, 'monthly_installment': 12000,
            'advance_date': self.start,
        })
        self.assertEqual(advance.number_of_installments, 9)
        advance.number_of_installments = 10
        # 100000 / 10 exactly, and the count must not drift back.
        self.assertAlmostEqual(advance.monthly_installment, 10000, 2)
        self.assertEqual(advance.number_of_installments, 10)
        self.assertEqual(len(advance.installment_ids), 10)
        self.assertAlmostEqual(sum(advance.installment_ids.mapped('amount')), 100000, 2)

    def test_16_count_survives_an_awkward_division(self):
        """9 into 100000 does not divide: rounding up must not add a 10th line."""
        advance = self.env['hr.salary.advance'].create({
            'employee_id': self.employee.id,
            'advance_amount': 100000, 'monthly_installment': 12000,
            'advance_date': self.start,
        })
        advance.number_of_installments = 9
        self.assertEqual(advance.number_of_installments, 9)
        self.assertEqual(len(advance.installment_ids), 9)
        self.assertAlmostEqual(sum(advance.installment_ids.mapped('amount')), 100000, 2)
        # Last line is the remainder, never more than the monthly amount.
        amounts = advance.installment_ids.sorted('installment_no').mapped('amount')
        self.assertLessEqual(amounts[-1], advance.monthly_installment)

    def test_17_changing_the_amount_redraws_the_schedule(self):
        advance = self.env['hr.salary.advance'].create({
            'employee_id': self.employee.id,
            'advance_amount': 60000, 'monthly_installment': 5000,
            'advance_date': self.start,
        })
        advance.advance_amount = 30000
        self.assertEqual(len(advance.installment_ids), 6)
        self.assertAlmostEqual(sum(advance.installment_ids.mapped('amount')), 30000, 2)

    # ------------------------------------------------------------------
    # Already paid
    # ------------------------------------------------------------------
    def test_18_already_paid_reduces_the_balance(self):
        advance = self._advance(60000, 5000)
        advance.installment_ids[0].already_paid = True
        self.assertAlmostEqual(advance.recovered_amount, 5000, 2)
        self.assertAlmostEqual(advance.remaining_amount, 55000, 2)
        advance.installment_ids[0].already_paid = False
        self.assertAlmostEqual(advance.recovered_amount, 0, 2)
        self.assertAlmostEqual(advance.remaining_amount, 60000, 2)

    def test_19_already_paid_is_skipped_by_payroll(self):
        """A settled line is never deducted again.

        Month one's installment was paid by hand, so that payslip takes
        nothing -- the later installments keep their own dates rather than
        being pulled forward.
        """
        advance = self._advance(60000, 5000)
        advance.installment_ids[0].already_paid = True
        first = self._payslip(1)
        self.assertAlmostEqual(self._advance_line(first), 0, 2)
        self.assertFalse(first.salary_advance_installment_ids)
        second = self._payslip(2)
        self.assertAlmostEqual(self._advance_line(second), -5000, 2)
        self.assertEqual(second.salary_advance_installment_ids.installment_no, 2)
        second.action_payslip_done()
        self.assertAlmostEqual(advance.recovered_amount, 10000, 2)
        self.assertAlmostEqual(advance.remaining_amount, 50000, 2)

    def test_20_already_paid_can_complete_the_advance(self):
        advance = self._advance(10000, 5000)
        advance.installment_ids.write({'already_paid': True})
        self.assertAlmostEqual(advance.remaining_amount, 0, 2)
        self.assertEqual(advance.state, 'completed')
        later = self._payslip(1)
        self.assertAlmostEqual(self._advance_line(later), 0, 2)

    def test_21_unticking_reopens_a_completed_advance(self):
        advance = self._advance(10000, 5000)
        advance.installment_ids.write({'already_paid': True})
        self.assertEqual(advance.state, 'completed')
        advance.installment_ids[0].already_paid = False
        self.assertEqual(advance.state, 'running')
        self.assertAlmostEqual(advance.remaining_amount, 5000, 2)

    def test_22_cannot_mark_a_deducted_installment_as_already_paid(self):
        from odoo.exceptions import ValidationError
        advance = self._advance(60000, 5000)
        self._payslip(1).action_payslip_done()
        deducted = advance.installment_ids.filtered(lambda i: i.state == 'deducted')
        self.assertTrue(deducted)
        with self.assertRaises(ValidationError):
            deducted[0].already_paid = True

    def test_23_regenerating_protects_settled_lines(self):
        """Redrawing the schedule must not wipe a line someone ticked off."""
        advance = self.env['hr.salary.advance'].create({
            'employee_id': self.employee.id,
            'advance_amount': 60000, 'monthly_installment': 5000,
            'advance_date': self.start,
        })
        advance.installment_ids[0].already_paid = True
        advance.advance_amount = 30000
        kept = advance.installment_ids.filtered('already_paid')
        self.assertEqual(len(kept), 1)
        self.assertAlmostEqual(advance.recovered_amount, 5000, 2)
        self.assertAlmostEqual(sum(advance.installment_ids.mapped('amount')), 30000, 2)
        self.assertAlmostEqual(advance.remaining_amount, 25000, 2)

    # ------------------------------------------------------------------
    # Editable dates
    # ------------------------------------------------------------------
    def _dates(self, advance):
        return advance.installment_ids.sorted('installment_no').mapped('installment_date')

    def test_24_moving_the_first_date_shifts_the_rest(self):
        """Pull installment 1 back a month and the whole tail follows."""
        advance = self.env['hr.salary.advance'].create({
            'employee_id': self.employee.id,
            'advance_amount': 100000, 'monthly_installment': 10000,
            'advance_date': self.start,
        })
        before = self._dates(advance)
        first = advance.installment_ids.sorted('installment_no')[0]
        first.installment_date = before[0] - relativedelta(months=1)
        after = self._dates(advance)
        self.assertEqual(len(after), 10)
        for index, date in enumerate(after):
            self.assertEqual(date, after[0] + relativedelta(months=index))
        # Every line moved back exactly one month.
        for old, new in zip(before, after):
            self.assertEqual(new, old - relativedelta(months=1))

    def test_25_moving_a_middle_date_leaves_earlier_lines_alone(self):
        advance = self.env['hr.salary.advance'].create({
            'employee_id': self.employee.id,
            'advance_amount': 100000, 'monthly_installment': 10000,
            'advance_date': self.start,
        })
        before = self._dates(advance)
        lines = advance.installment_ids.sorted('installment_no')
        lines[2].installment_date = before[2] + relativedelta(months=2)
        after = self._dates(advance)
        self.assertEqual(after[:2], before[:2])          # 1 and 2 untouched
        self.assertEqual(after[2], before[2] + relativedelta(months=2))
        for index, date in enumerate(after[2:]):
            self.assertEqual(date, after[2] + relativedelta(months=index))

    def test_26_a_non_monthly_date_keeps_the_monthly_cadence(self):
        """Typing the 15th moves the rest to the 15th, not by a day count."""
        advance = self.env['hr.salary.advance'].create({
            'employee_id': self.employee.id,
            'advance_amount': 30000, 'monthly_installment': 10000,
            'advance_date': self.start,
        })
        lines = advance.installment_ids.sorted('installment_no')
        lines[0].installment_date = lines[0].installment_date.replace(day=15)
        after = self._dates(advance)
        self.assertEqual([d.day for d in after], [15, 15, 15])
        self.assertEqual(after[1], after[0] + relativedelta(months=1))

    def test_27_settled_lines_keep_their_dates(self):
        """A deducted line is a fact: shifting the plan must not move it."""
        advance = self._advance(60000, 5000)
        self._payslip(1).action_payslip_done()
        lines = advance.installment_ids.sorted('installment_no')
        deducted = lines.filtered(lambda i: i.state == 'deducted')
        self.assertTrue(deducted)
        fixed_date = deducted[0].installment_date
        pending = lines.filtered(lambda i: i.state == 'pending')
        pending[0].installment_date = pending[0].installment_date + relativedelta(months=1)
        self.assertEqual(deducted[0].installment_date, fixed_date)

    def test_28_redrawing_keeps_a_hand_set_start(self):
        """Changing the amount must not throw away a date somebody moved."""
        advance = self.env['hr.salary.advance'].create({
            'employee_id': self.employee.id,
            'advance_amount': 100000, 'monthly_installment': 10000,
            'advance_date': self.start,
        })
        lines = advance.installment_ids.sorted('installment_no')
        moved = lines[0].installment_date - relativedelta(months=1)
        lines[0].installment_date = moved
        advance.advance_amount = 50000
        after = self._dates(advance)
        self.assertEqual(len(after), 5)
        self.assertEqual(after[0], moved)
        self.assertEqual(after[-1], moved + relativedelta(months=4))

    # ------------------------------------------------------------------
    # Status must agree with the Already Paid toggle
    # ------------------------------------------------------------------
    def test_29_already_paid_shows_as_paid_not_pending(self):
        """Ticking the toggle must not leave the line reading "Pending"."""
        advance = self._advance(100000, 10000)
        line = advance.installment_ids.sorted('installment_no')[0]
        line.already_paid = True
        self.assertEqual(line.state, 'paid')
        self.assertAlmostEqual(advance.recovered_amount, 10000, 2)
        self.assertAlmostEqual(advance.remaining_amount, 90000, 2)
        # Untick and it goes back to being owed.
        line.already_paid = False
        self.assertEqual(line.state, 'pending')
        self.assertAlmostEqual(advance.remaining_amount, 100000, 2)

    def test_30_paid_lines_are_left_alone_by_payroll_and_completion(self):
        advance = self._advance(60000, 5000)
        lines = advance.installment_ids.sorted('installment_no')
        lines[0].already_paid = True
        self.assertEqual(lines[0].state, 'paid')
        # Payroll skips it and the status survives a payslip run.
        self._payslip(2).action_payslip_done()
        self.assertEqual(lines[0].state, 'paid')
        self.assertAlmostEqual(advance.recovered_amount, 10000, 2)
        # Completing the advance must not cancel a settled line.
        lines.filtered(lambda i: i.state == 'pending').write({'already_paid': True})
        self.assertEqual(advance.state, 'completed')
        self.assertFalse(advance.installment_ids.filtered(
            lambda i: i.state == 'cancelled'))

    def test_31_cannot_cancel_once_settled_by_hand(self):
        advance = self._advance(60000, 5000)
        advance.installment_ids.sorted('installment_no')[0].already_paid = True
        with self.assertRaises(UserError):
            advance.action_cancel()
