# -*- coding: utf-8 -*-
from datetime import date, timedelta

from dateutil.relativedelta import MO, relativedelta

from odoo.exceptions import AccessError, UserError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class PortalTimeOffCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        LeaveType = cls.env['hr.leave.type']
        cls.casual = LeaveType.create({
            'name': 'Portal Casual', 'requires_allocation': True, 'request_unit': 'half_day',
            'leave_validation_type': 'hr', 'ft_portal_visible': True, 'company_id': cls.company.id})
        cls.lop = LeaveType.create({
            'name': 'Portal LOP', 'requires_allocation': False, 'request_unit': 'half_day',
            'leave_validation_type': 'hr', 'ft_portal_visible': True, 'company_id': cls.company.id})
        cls.maternity = LeaveType.create({
            'name': 'Portal Maternity', 'requires_allocation': True, 'request_unit': 'day',
            'leave_validation_type': 'hr', 'ft_portal_visible': True, 'company_id': cls.company.id})
        cls.hidden = LeaveType.create({
            'name': 'Back Office Only', 'requires_allocation': False, 'company_id': cls.company.id})

        def person(login, **values):
            user = new_test_user(cls.env, login=login, groups='base.group_portal', password=login + '-pass1234')
            employee = cls.env['hr.employee'].sudo().create(dict(
                name=login.title(), user_id=user.id, company_id=cls.company.id, work_email=login + '@example.com', **values))
            return user, employee

        cls.manager_user, cls.manager = person('manager')
        cls.user, cls.employee = person('employee', parent_id=cls.manager.id)
        cls.other_user, cls.other = person('other')
        cls.hr_user, cls.hr = person('hrperson')
        cls.company.ft_time_off_hr_ids = cls.hr
        cls.env['hr.leave.allocation'].create({
            'name': 'Casual', 'employee_id': cls.employee.id, 'holiday_status_id': cls.casual.id,
            'number_of_days': 3, 'date_from': date.today() - timedelta(days=30), 'allocation_type': 'regular',
        }).action_approve()
        # A Monday far enough ahead that nothing else is booked.
        cls.monday = date.today() + relativedelta(days=21, weekday=MO(+1))

    def service(self):
        return self.env['ft.portal.time.off'].sudo()

    def request(self, user=None, **values):
        data = {'type_id': self.casual.id, 'date_from': self.monday.isoformat(), 'date_to': self.monday.isoformat(),
                'from_period': 'am', 'to_period': 'pm', 'reason': 'Family function'}
        data.update(values)
        return self.service()._apply(user or self.user, data)


@tagged('post_install', '-at_install')
class TestPortalTimeOff(PortalTimeOffCase):

    def test_portal_manager_is_not_back_office_approver(self):
        # Both would fail with "exclusive groups" if the portal manager became the Time Off approver.
        self.assertFalse(self.employee.leave_manager_id)
        self.other.parent_id = self.manager
        self.assertFalse(self.other.leave_manager_id)
        # What the back-office form sends after changing the manager.
        self.other.write({'parent_id': False})
        self.other.write({'parent_id': self.manager.id, 'leave_manager_id': self.manager_user.id})
        self.assertFalse(self.other.leave_manager_id)
        self.assertFalse(self.manager_user.has_group('base.group_user'))
        self.assertEqual(self.service()._team(self.manager_user), self.employee | self.other)

    def test_types_offered(self):
        offered = {t['name']: t for t in self.service()._leave_types(self.employee)}
        # Maternity has no allocation for this employee; the last type is not shown on the portal.
        self.assertIn('Portal Casual', offered)
        self.assertIn('Portal LOP', offered)
        self.assertNotIn('Portal Maternity', offered)
        self.assertNotIn('Back Office Only', offered)
        # An allocation still at 0 days (monthly accrual not started) is shown, with nothing free.
        self.env['hr.leave.allocation'].create({
            'name': 'Accrual', 'employee_id': self.other.id, 'holiday_status_id': self.casual.id,
            'number_of_days': 0, 'date_from': date.today(), 'allocation_type': 'accrual',
            'accrual_plan_id': self.env['hr.leave.accrual.plan'].create({'name': 'Monthly'}).id,
        }).action_approve()
        zero = {t['name']: t for t in self.service()._leave_types(self.other)}['Portal Casual']
        self.assertEqual((zero['total'], zero['free']), (0, 0))
        casual = offered['Portal Casual']
        self.assertEqual((casual['total'], casual['left'], casual['free']), (3, 3, 3))

    def test_half_days_counted_like_odoo(self):
        preview = self.service()._preview
        day = self.monday.isoformat()
        tuesday = (self.monday + timedelta(days=1)).isoformat()
        morning = preview(self.user, {'type_id': self.casual.id, 'date_from': day, 'date_to': day,
                                      'from_period': 'am', 'to_period': 'am'})
        self.assertEqual((morning['days'], morning['error']), (0.5, None))
        self.assertIn('morning only', morning['summary'])
        span = preview(self.user, {'type_id': self.casual.id, 'date_from': day, 'date_to': tuesday,
                                   'from_period': 'pm', 'to_period': 'pm'})
        self.assertEqual(span['days'], 1.5)
        self.assertEqual(span['days_label'], '1½ days')
        backwards = preview(self.user, {'type_id': self.casual.id, 'date_from': day, 'date_to': day,
                                        'from_period': 'pm', 'to_period': 'am'})
        self.assertIn("can't start in the afternoon", backwards['error'])
        saturday = (self.monday - timedelta(days=2)).isoformat()
        weekend = preview(self.user, {'type_id': self.lop.id, 'date_from': saturday, 'date_to': saturday})
        self.assertEqual(weekend['error'], 'These dates are not working days.')

    def test_balance_is_enforced(self):
        friday = (self.monday + timedelta(days=4)).isoformat()
        too_long = self.service()._preview(self.user, {'type_id': self.casual.id, 'date_from': self.monday.isoformat(),
                                                        'date_to': friday, 'from_period': 'am', 'to_period': 'pm'})
        self.assertIn('Only 3 days of Portal Casual are free', too_long['error'])
        with self.assertRaises(UserError):
            self.request(date_to=friday)
        # Loss of Pay needs no balance.
        self.assertEqual(self.request(type_id=self.lop.id, date_to=friday).number_of_days, 5)

    def test_manager_approves(self):
        leave = self.request(from_period='pm')
        self.assertEqual((leave.state, leave.number_of_days, leave.private_name), ('confirm', 0.5, 'Family function'))
        with self.assertRaises(AccessError):
            self.service()._decide(self.other_user, leave.id, 'approve')
        with self.assertRaises(AccessError):
            self.service()._decide(self.user, leave.id, 'approve')
        self.service()._decide(self.manager_user, leave.id, 'approve')
        self.assertEqual(leave.state, 'validate')
        self.assertEqual(leave.first_approver_id, self.manager)
        with self.assertRaises(AccessError):
            self.service()._decide(self.hr_user, leave.id, 'refuse', 'Too late')
        casual = next(t for t in self.service()._leave_types(self.employee) if t['name'] == 'Portal Casual')
        # Approved for a later date: still in today's balance, but no longer free to plan.
        self.assertEqual((casual['left'], casual['planned'], casual['free']), (3, 0.5, 2.5))
        self.assertEqual(self.service()._page_values(self.user)['ft_own'][0]['decided_by'], 'Manager')

    def test_hr_refuses_with_reason(self):
        leave = self.request()
        with self.assertRaises(UserError):
            self.service()._decide(self.hr_user, leave.id, 'refuse', '  ')
        self.service()._decide(self.hr_user, leave.id, 'refuse', 'Release week')
        self.assertEqual((leave.state, leave.ft_portal_refuse_reason), ('refuse', 'Release week'))
        self.assertEqual(leave.second_approver_id, self.hr)
        values = self.service()._page_values(self.user)
        self.assertEqual(values['ft_own'][0]['refuse_reason'], 'Release week')
        self.assertEqual(values['ft_own'][0]['status'], 'refused')

    def test_withdraw_own_pending_only(self):
        leave = self.request()
        with self.assertRaises(AccessError):
            self.service()._withdraw(self.manager_user, leave.id)
        self.service()._withdraw(self.user, leave.id)
        self.assertEqual(leave.state, 'cancel')
        with self.assertRaises(AccessError):
            self.service()._withdraw(self.user, leave.id)

    def test_overlap_refused(self):
        self.request()
        again = self.service()._preview(self.user, {'type_id': self.lop.id, 'date_from': self.monday.isoformat(),
                                                     'date_to': self.monday.isoformat()})
        self.assertEqual(again['error'], 'You already have leave on these dates.')

    def mails(self, subject_start):
        return self.env['mail.mail'].sudo().search([('subject', '=like', subject_start + '%')])

    def test_emails(self):
        Mail = self.env['mail.mail'].sudo()
        before = Mail.search([]).ids
        leave = self.request(from_period='pm')
        request = self.mails('Leave request: Employee')
        self.assertEqual(len(request), 1)
        self.assertIn('manager@example.com', request.email_to)
        self.assertIn('hrperson@example.com', request.email_to)
        self.assertNotIn('employee@example.com', request.email_to)
        self.assertEqual(request.email_from, 'Fingertip Time Off <support@fingertipplus.com>')
        self.assertIn('hrperson@example.com', request.reply_to)
        self.assertIn('Family function', request.body_html)
        self.assertIn('afternoon only', request.body_html)
        self.assertIn('Balance after approval', request.body_html)

        self.service()._decide(self.manager_user, leave.id, 'refuse', 'Release week')
        to_employee = self.mails('Your Portal Casual is refused')
        self.assertEqual(to_employee.email_to, '"Employee" <employee@example.com>')
        self.assertIn('Release week', to_employee.body_html)
        self.assertIn('Manager', to_employee.body_html)
        others = self.mails('Refused: Employee')
        # The manager decided, so only HR is told.
        self.assertEqual(others.email_to, '"Hrperson" <hrperson@example.com>')
        # Odoo's own "has been refused" message is not emailed as well.
        new = Mail.search([('id', 'not in', before)])
        self.assertEqual(sorted(new.mapped('subject')), sorted([
            'Leave request: Employee · Portal Casual', 'Your Portal Casual is refused', 'Refused: Employee · Portal Casual']))

        withdrawn = self.request(date_from=(self.monday + timedelta(days=1)).isoformat(),
                                 date_to=(self.monday + timedelta(days=1)).isoformat())
        self.service()._withdraw(self.user, withdrawn.id)
        mail = self.mails('Withdrawn: Employee')
        self.assertIn('manager@example.com', mail.email_to)
        self.assertIn('hrperson@example.com', mail.email_to)

    def test_approval_sends_only_portal_emails(self):
        Mail = self.env['mail.mail'].sudo()
        before = Mail.search([]).ids
        leave = self.request()
        self.service()._decide(self.hr_user, leave.id, 'approve')
        self.env.flush_all()
        self.env.cr.precommit.run()   # tracking notifications are sent at commit
        new = Mail.search([('id', 'not in', before)])
        self.assertEqual(sorted(new.mapped('subject')), sorted([
            'Leave request: Employee · Portal Casual', 'Your Portal Casual is approved', 'Approved: Employee · Portal Casual']))
        self.assertEqual(self.mails('Approved: Employee').email_to, '"Manager" <manager@example.com>')
        # The decision is still in the leave's history.
        self.assertTrue(any(body.startswith('Approved on the employee portal by')
                            for body in leave.message_ids.mapped(lambda m: m.body.striptags())))

    def test_email_without_manager_goes_to_hr_and_admin(self):
        self.env.ref('base.user_admin').email = 'admin@example.com'
        self.env['hr.leave.allocation'].create({
            'name': 'Casual', 'employee_id': self.other.id, 'holiday_status_id': self.casual.id,
            'number_of_days': 3, 'date_from': date.today() - timedelta(days=30), 'allocation_type': 'regular',
        }).action_approve()
        self.request(user=self.other_user)
        mail = self.mails('Leave request: Other')
        self.assertIn('hrperson@example.com', mail.email_to)
        self.assertIn('admin@example.com', mail.email_to)

    def test_hr_list_decides(self):
        leave = self.request()
        self.company.ft_time_off_hr_ids = False
        with self.assertRaises(AccessError):
            self.service()._decide(self.hr_user, leave.id, 'approve')
        self.company.ft_time_off_hr_ids = self.hr
        self.service()._decide(self.hr_user, leave.id, 'approve')
        self.assertEqual(leave.state, 'validate')

    def test_dashboard_team_strip(self):
        self.request()
        rows = {row['name']: row for row in self.service()._dashboard_values(self.manager_user)['ft_month_rows']}
        # A manager sees their reports and themselves; an employee sees their own team.
        self.assertEqual(set(rows), {'Manager', 'Employee'})
        employee_rows = [row['name'] for row in self.service()._dashboard_values(self.user)['ft_month_rows']]
        self.assertEqual(employee_rows, ['Employee'])
        values = self.service()._dashboard_values(self.user)
        self.assertEqual(len(values['ft_waiting']), 1)
        self.assertEqual(values['ft_next']['from'], self.monday.isoformat())

    def test_who_sees_what(self):
        leave = self.request()
        manager = self.service()._page_values(self.manager_user)
        self.assertTrue(manager['ft_can_approve'])
        self.assertEqual([p['id'] for p in manager['ft_pending']], [leave.id])
        self.assertEqual(manager['ft_pending'][0]['balance_after'], 2)
        other = self.service()._page_values(self.other_user)
        self.assertFalse(other['ft_can_approve'])
        self.assertFalse(other['ft_pending'])
        hr = self.service()._page_values(self.hr_user)
        self.assertIn(leave.id, [p['id'] for p in hr['ft_pending']])
        # Nobody gets their own request to decide.
        self.assertNotIn(leave.id, [p['id'] for p in self.service()._page_values(self.user)['ft_pending']])


@tagged('post_install', '-at_install')
class TestPortalTimeOffPages(HttpCase, PortalTimeOffCase):

    def test_pages(self):
        self.request()
        self.authenticate('employee', 'employee-pass1234')
        page = self.url_open('/my/time-off')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Apply for leave', page.text)
        self.assertIn('Portal Casual', page.text)
        self.assertNotIn('Team approvals', page.text)
        self.assertIn('/my/time-off', self.url_open('/my').text)

        self.authenticate('manager', 'manager-pass1234')
        page = self.url_open('/my/time-off?view=team')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Team approvals', page.text)
        self.assertIn('Family function', page.text)

    def test_dashboard(self):
        self.request()
        self.authenticate('employee', 'employee-pass1234')
        page = self.url_open('/my')
        self.assertEqual(page.status_code, 200)
        for text in ('Your time off', 'Employee', 'Manager', 'Team on leave', 'Coming soon', 'Change password', '1 request'):
            self.assertIn(text, page.text)
        self.assertNotIn('Waiting for you', page.text)
        self.assertNotIn('Your Invoices', page.text)

        self.authenticate('manager', 'manager-pass1234')
        page = self.url_open('/my')
        self.assertIn('Waiting for you', page.text)
        self.assertIn('Family function', self.url_open('/my/time-off?view=team').text)

        # A portal user who is not an employee keeps Odoo's own page.
        new_test_user(self.env, login='customer', groups='base.group_portal', password='customer-pass1234')
        self.authenticate('customer', 'customer-pass1234')
        page = self.url_open('/my')
        self.assertEqual(page.status_code, 200)
        self.assertNotIn('Team on leave', page.text)
