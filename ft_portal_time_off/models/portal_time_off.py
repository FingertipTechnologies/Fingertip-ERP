# -*- coding: utf-8 -*-
"""Time off on the employee portal.

Portal users have no rights on time off, so the portal works through this
model with sudo and every rule about who may see or decide what is checked
here, against the user who is logged in:

- everyone sees and applies for their own leave;
- a manager decides the requests of the employees who report to them;
- HR (employees ticked "Approves Time Off on the Portal") and Time Off
  administrators decide everyone's;
- nobody decides their own request.

One approval is final. Odoo's own approve and refuse run, so the approver is
recorded on the leave and the back office shows the same state.
"""
from datetime import date, timedelta

from odoo import _, fields, models
from odoo.exceptions import AccessError, UserError

PENDING_STATES = ('confirm', 'validate1')
STATUS = {
    'confirm': 'pending', 'validate1': 'pending', 'validate': 'approved',
    'refuse': 'refused', 'cancel': 'withdrawn',
}
PERIODS = ('am', 'pm')


def format_days(days):
    whole, rest = int(days), round(days - int(days), 2)
    if rest == 0.5:
        text = ('%d' % whole if whole else '') + '½'
    elif rest:
        text = '%g' % days
    else:
        text = '%d' % whole
    return '%s %s' % (text, _('day') if 0 < days <= 1 else _('days'))


def day_label(day):
    return '%s %d %s' % (day.strftime('%a'), day.day, day.strftime('%b'))


def describe(start, end, from_period, to_period):
    """How the request reads in words, e.g. "Thu 5 Nov afternoon → Fri 6 Nov"."""
    if start == end:
        if from_period == to_period:
            return _('%(day)s, %(period)s only', day=day_label(start),
                     period=_('morning') if from_period == 'am' else _('afternoon'))
        return _('%(day)s, full day', day=day_label(start))
    return '%s%s → %s%s' % (
        day_label(start), _(' afternoon') if from_period == 'pm' else '',
        day_label(end), _(' morning') if to_period == 'am' else '')


class FtPortalTimeOff(models.AbstractModel):
    _name = 'ft.portal.time.off'
    _description = 'Employee Portal Time Off'

    # ------------------------------------------------------------------
    # Who is looking
    # ------------------------------------------------------------------
    def _employee(self, user):
        return user.sudo().employee_id

    def _is_hr(self, user):
        employee = self._employee(user)
        return bool(employee and employee in employee.company_id.sudo().ft_time_off_hr_ids) \
            or user.has_group('hr_holidays.group_hr_holidays_manager')

    def _team(self, user):
        """Employees whose requests this user decides."""
        me = self._employee(user)
        Employee = self.env['hr.employee'].sudo()
        if not me:
            return Employee
        if self._is_hr(user):
            return Employee.search([('company_id', 'in', user.company_ids.ids), ('id', '!=', me.id)])
        return Employee.search([('parent_id', '=', me.id)])

    def _can_decide(self, user, leave):
        me = self._employee(user)
        return bool(me) and leave.state in PENDING_STATES and leave.employee_id != me \
            and leave.employee_id in self._team(user)

    # ------------------------------------------------------------------
    # Leave types and balances
    # ------------------------------------------------------------------
    def _leave_types(self, employee):
        types = self.env['hr.leave.type'].sudo().search([
            ('ft_portal_visible', '=', True), ('company_id', 'in', [False, employee.company_id.id])],
            order='sequence, id')
        allocation = {type_id: info for _name, info, _req, type_id
                      in types.get_allocation_data(employee)[employee]}
        # Offered when the employee has an allocation, even one still at 0
        # days (monthly accrual); maternity and paternity only once granted.
        today = fields.Date.context_today(self)
        allocated = self.env['hr.leave.allocation'].sudo().search([
            ('employee_id', '=', employee.id), ('state', '=', 'validate'), ('holiday_status_id', 'in', types.ids),
            '|', ('date_to', '=', False), ('date_to', '>=', today)]).holiday_status_id
        # The portal shows what is free to plan: today's balance less leave
        # approved or requested for later, without accruals still to come.
        # Odoo's own balance is as of a date, and an accrual allocation only
        # loses future leave on its dates while a regular one loses it at once,
        # so take Odoo's balance at the last planned day and drop the accrual
        # earned until then.
        planned = self.env['hr.leave'].sudo()._read_group([
            ('employee_id', '=', employee.id), ('holiday_status_id', 'in', types.ids),
            ('state', 'in', ('validate',) + PENDING_STATES), ('request_date_from', '>', today)],
            ['holiday_status_id'], ['number_of_days:sum', 'request_date_to:max'])
        last_day = {leave_type.id: last for leave_type, _days, last in planned}
        planned = {leave_type.id: days for leave_type, days, _last in planned}
        pending = self.env['hr.leave'].sudo()._read_group([
            ('employee_id', '=', employee.id), ('holiday_status_id', 'in', types.ids),
            ('state', 'in', PENDING_STATES)], ['holiday_status_id'], ['number_of_days:sum'])
        pending = {leave_type.id: days for leave_type, days in pending}
        result = []
        for leave_type in types:
            info = allocation.get(leave_type.id)
            if leave_type.requires_allocation and (not info or leave_type not in allocated):
                continue
            values = {
                'id': leave_type.id, 'name': leave_type.name,
                'half_day': leave_type.request_unit == 'half_day',
                'unpaid': not leave_type.requires_allocation,
                'limited': leave_type.requires_allocation and not leave_type.allows_negative,
            }
            if leave_type.requires_allocation:
                total, free = info['max_leaves'], info['virtual_remaining_leaves']
                later = planned.get(leave_type.id, 0.0)
                if later:
                    when = last_day[leave_type.id]
                    then = leave_type.get_allocation_data(employee, when)[employee][0][1]
                    # Allocations ending before then also leave the total, so
                    # the accrual earned is the change in total plus those.
                    expiring = sum(self.env['hr.leave.allocation'].sudo().search([
                        ('employee_id', '=', employee.id), ('holiday_status_id', '=', leave_type.id),
                        ('state', '=', 'validate'), ('date_to', '>=', today), ('date_to', '<', when)]).mapped('number_of_days'))
                    free = then['virtual_remaining_leaves'] - (then['max_leaves'] - total + expiring)
                free = round(free, 2)
                left = round(free + later, 2)
                values.update(
                    total=total, left=left, free=free, planned=later, pending=pending.get(leave_type.id, 0.0),
                    taken=round(total - left, 2), ring=max(0.0, min(1.0, free / total)) if total else 0.0)
            else:
                values['taken'] = sum(self.env['hr.leave'].sudo().search([
                    ('employee_id', '=', employee.id), ('holiday_status_id', '=', leave_type.id),
                    ('state', '=', 'validate'), ('request_date_from', '>=', self._year_start())]).mapped('number_of_days'))
            result.append(values)
        return result

    def _format_days(self, days):
        return format_days(days)

    def _year_start(self):
        """1 April of the current financial year."""
        today = fields.Date.context_today(self)
        return date(today.year if today.month >= 4 else today.year - 1, 4, 1)

    # ------------------------------------------------------------------
    # Requests
    # ------------------------------------------------------------------
    def _check_request(self, employee, data):
        """(hr.leave values, days, error) for what the portal form holds."""
        leave_type = next((t for t in self._leave_types(employee)
                           if t['id'] == int(data.get('type_id') or 0)), None)
        if not leave_type:
            return None, 0, _('Choose a leave type.')
        try:
            start = fields.Date.to_date(data.get('date_from') or None)
            end = fields.Date.to_date(data.get('date_to') or None)
        except ValueError:
            return None, 0, _('Pick valid dates.')
        if not start or not end:
            return None, 0, _('Pick both dates.')
        if end < start:
            return None, 0, _('The end date is before the start date.')
        values = {
            'employee_id': employee.id, 'holiday_status_id': leave_type['id'],
            'request_date_from': start, 'request_date_to': end,
        }
        if leave_type['half_day']:
            from_period = data.get('from_period') if data.get('from_period') in PERIODS else 'am'
            to_period = data.get('to_period') if data.get('to_period') in PERIODS else 'pm'
            if start == end and from_period == 'pm' and to_period == 'am':
                return None, 0, _("A one-day leave can't start in the afternoon and end in the morning.")
            values.update(request_date_from_period=from_period, request_date_to_period=to_period)
        leave = self.env['hr.leave'].sudo().new(values)
        days = leave.number_of_days
        if days <= 0:
            return None, 0, _('These dates are not working days.')
        if self.env['hr.leave'].sudo().search_count([
                ('employee_id', '=', employee.id), ('state', 'not in', ('cancel', 'refuse')),
                ('date_from', '<', leave.date_to), ('date_to', '>', leave.date_from)]):
            return None, days, _('You already have leave on these dates.')
        if leave_type['limited'] and days > leave_type['free']:
            return None, days, _(
                'Only %(free)s of %(type)s are free. Shorten the dates, or apply the rest as Loss of Pay.',
                free=format_days(max(leave_type['free'], 0)), type=leave_type['name'])
        return values, days, None

    def _preview(self, user, data):
        employee = self._employee(user)
        if not employee:
            raise AccessError(_('Your login is not linked to an employee.'))
        values, days, error = self._check_request(employee, data)
        summary = ''
        if values:
            summary = describe(values['request_date_from'], values['request_date_to'],
                               values.get('request_date_from_period', 'am'), values.get('request_date_to_period', 'pm'))
        return {'days': days, 'days_label': format_days(days), 'summary': summary, 'error': error}

    def _apply(self, user, data):
        employee = self._employee(user)
        if not employee:
            raise AccessError(_('Your login is not linked to an employee.'))
        values, _days, error = self._check_request(employee, data)
        if error:
            raise UserError(error)
        values['private_name'] = (data.get('reason') or '').strip()
        leave = self.env['hr.leave'].sudo().with_context(mail_create_nosubscribe=True).create(values)
        # Time Off makes the employee a follower, so its status notifications
        # would email them on top of the portal's own decision email.
        leave.message_unsubscribe(partner_ids=(employee.user_id.partner_id | employee.work_contact_id).ids)
        leave.message_post(body=_('Requested on the employee portal by %s.', user.name),
                           subtype_xmlid='mail.mt_note')
        leave._ft_send_mail('request')
        return leave

    def _withdraw(self, user, leave_id):
        leave = self.env['hr.leave'].sudo().browse(int(leave_id)).exists()
        if not leave or leave.employee_id != self._employee(user) or leave.state not in PENDING_STATES:
            raise AccessError(_('This request can no longer be withdrawn.'))
        leave._force_cancel(_('Withdrawn by the employee on the portal.'), 'mail.mt_note', notify_responsibles=False)
        leave._ft_send_mail('withdrawn')
        return leave

    def _decide(self, user, leave_id, decision, reason=''):
        leave = self.env['hr.leave'].sudo().browse(int(leave_id)).exists()
        if not leave or not self._can_decide(user, leave):
            raise AccessError(_('You can no longer decide on this request.'))
        approver = self._employee(user)
        leave = leave.with_context(ft_portal_quiet=True)
        if decision == 'approve':
            leave.action_approve(check_state=False)
            # Odoo takes the approver from the user's employee, which a portal
            # user does not always resolve to; record who decided.
            leave.write({'second_approver_id' if leave.validation_type == 'both' else 'first_approver_id': approver.id})
            leave.message_post(body=_('Approved on the employee portal by %s.', user.name),
                               subtype_xmlid='mail.mt_note')
        elif decision == 'refuse':
            reason = (reason or '').strip()
            if not reason:
                raise UserError(_('Write the reason for refusing. The employee sees it.'))
            leave.ft_portal_refuse_reason = reason
            leave.action_refuse()
            leave.second_approver_id = approver
            leave.message_post(body=_('Refused on the employee portal by %(user)s: %(reason)s',
                                      user=user.name, reason=reason), subtype_xmlid='mail.mt_note')
        else:
            raise UserError(_('Unknown decision.'))
        context = {'ft_decider': approver.name or user.name, 'ft_decider_email': (approver.work_email or user.email or '').strip()}
        leave._ft_send_mail('decided_employee', **context)
        leave._ft_send_mail('decided_approvers', **context)
        return leave

    # ------------------------------------------------------------------
    # Page
    # ------------------------------------------------------------------
    def _leave_values(self, leave):
        half = leave.request_unit_half
        from_period = leave.request_date_from_period if half and leave.request_date_from_period else 'am'
        to_period = leave.request_date_to_period if half and leave.request_date_to_period else 'pm'
        start, end = leave.request_date_from, leave.request_date_to
        employee = leave.employee_id
        if start == end:
            sessions = [(from_period, _('Morning only') if from_period == 'am' else _('Afternoon only'))] \
                if from_period == to_period else [('full', _('Full day'))]
        else:
            sessions = [(from_period, _('Starts morning') if from_period == 'am' else _('Starts afternoon')),
                        (to_period, _('Ends after morning') if to_period == 'am' else _('Ends end of day'))]
        status = STATUS.get(leave.state, 'pending')
        return {
            'id': leave.id, 'employee': employee.name, 'job': employee.job_title or employee.job_id.name or '',
            'initials': ''.join(word[0] for word in (employee.name or '?').split()[:2]).upper(),
            'type': leave.holiday_status_id.name, 'unpaid': not leave.holiday_status_id.requires_allocation,
            'from': start.isoformat(), 'to': end.isoformat(), 'fp': from_period, 'tp': to_period,
            'from_label': day_label(start), 'to_label': day_label(end),
            'day': start.day, 'month': start.strftime('%b'),
            'when': describe(start, end, from_period, to_period), 'sessions': sessions,
            'days': leave.number_of_days, 'days_label': format_days(leave.number_of_days),
            'status': status,
            'status_label': {'pending': _('Waiting for approval'), 'approved': _('Approved'),
                             'refused': _('Refused'), 'withdrawn': _('Withdrawn')}[status],
            'reason': leave.private_name or '', 'refuse_reason': leave.ft_portal_refuse_reason or '',
            'decided_by': ((leave.second_approver_id if leave.state == 'refuse' else leave.first_approver_id)
                           or leave.second_approver_id or leave.first_approver_id).name or '',
            'sent_label': day_label(fields.Date.context_today(self, leave.create_date)),
        }

    def _page_values(self, user):
        employee = self._employee(user)
        Leave = self.env['hr.leave'].sudo()
        year_start = self._year_start()
        today = fields.Date.context_today(self)
        own = Leave.search([('employee_id', '=', employee.id), ('request_date_to', '>=', year_start)],
                           order='request_date_from desc, id desc')
        team = self._team(user)
        is_hr = self._is_hr(user)
        pending = Leave.search([('employee_id', 'in', team.ids), ('state', 'in', PENDING_STATES)],
                               order='create_date, id')
        decided = Leave.search([('employee_id', 'in', team.ids), ('state', 'in', ('validate', 'refuse')),
                                ('request_date_to', '>=', year_start)], order='request_date_from desc, id desc')
        # Balance after approval and who else is off, for each request waiting.
        # The free balance already has every waiting request taken off.
        balances = {}
        for employee_pending in pending.employee_id:
            balances.update({(employee_pending.id, t['id']): t['free']
                             for t in self._leave_types(employee_pending) if not t['unpaid']})
        pending_values = []
        for leave in pending:
            values = self._leave_values(leave)
            values['balance_after'] = balances.get((leave.employee_id.id, leave.holiday_status_id.id))
            others = Leave.search([
                ('employee_id', 'in', team.ids), ('employee_id', '!=', leave.employee_id.id),
                ('state', 'in', ('validate',) + PENDING_STATES),
                ('date_from', '<', leave.date_to), ('date_to', '>', leave.date_from)])
            values['overlap'] = ', '.join(others.employee_id.mapped('name'))
            pending_values.append(values)
        off_today = Leave.search([('employee_id', 'in', team.ids), ('state', '=', 'validate'),
                                  ('request_date_from', '<=', today), ('request_date_to', '>=', today)])
        week_end = today + timedelta(days=7)
        next_week = Leave.search([('employee_id', 'in', team.ids), ('state', 'in', ('validate',) + PENDING_STATES),
                                  ('request_date_from', '<=', week_end), ('request_date_to', '>', today)])
        calendar = employee.resource_calendar_id or employee.company_id.resource_calendar_id
        working_days = sorted({int(day) for day in calendar.attendance_ids.mapped('dayofweek')}) if calendar else [0, 1, 2, 3, 4]
        own_values = [self._leave_values(leave) for leave in own]
        return {
            'ft_employee': employee,
            'ft_manager': employee.parent_id.name or _('HR'),
            'ft_types': self._leave_types(employee),
            'ft_own': own_values,
            'ft_calendar': [{key: leave[key] for key in ('from', 'to', 'fp', 'tp', 'status', 'type', 'unpaid')}
                            for leave in own_values if leave['status'] in ('approved', 'pending')],
            'ft_working_days': working_days,
            'ft_today': today,
            'ft_can_approve': bool(is_hr or team),
            'ft_is_hr': is_hr,
            'ft_pending': pending_values,
            'ft_history': [self._leave_values(leave) for leave in decided],
            'ft_off_today': [(leave.employee_id.name, self._leave_values(leave)['sessions'][0][1])
                             for leave in off_today],
            'ft_next_week': sorted(set(next_week.employee_id.mapped('name'))),
            'ft_format_days': format_days,
        }

    # ------------------------------------------------------------------
    # My account dashboard
    # ------------------------------------------------------------------
    def _day_marks(self, leaves, start, end, working_days):
        """{(employee id, date): (part, waiting)} for the working days of leaves
        between start and end; part is 'f' full day, 'l' morning, 'r' afternoon."""
        marks = {}
        for leave in leaves:
            values = self._leave_values(leave)
            day = max(leave.request_date_from, start)
            while day <= min(leave.request_date_to, end):
                if day.weekday() in working_days:
                    first, last = day == leave.request_date_from, day == leave.request_date_to
                    part = 'f'
                    if first and last and values['fp'] == values['tp']:
                        part = 'l' if values['fp'] == 'am' else 'r'
                    elif first and values['fp'] == 'pm':
                        part = 'r'
                    elif last and values['tp'] == 'am':
                        part = 'l'
                    marks[(leave.employee_id.id, day)] = (part, leave.state in PENDING_STATES)
                day += timedelta(days=1)
        return marks

    def _dashboard_values(self, user):
        values = self._page_values(user)
        employee = values['ft_employee']
        today = values['ft_today']
        Leave = self.env['hr.leave'].sudo()
        working_days = set(values['ft_working_days'])
        tz_now = fields.Datetime.context_timestamp(self.with_context(tz=user.tz or 'Asia/Kolkata'), fields.Datetime.now())
        greeting = _('Good morning') if tz_now.hour < 12 else _('Good afternoon') if tz_now.hour < 17 else _('Good evening')

        joined = employee.contract_date_start
        months = (today.year - joined.year) * 12 + today.month - joined.month if joined else 0
        tenure = (_('%s years', months // 12) if months >= 24 else _('1 year') if months >= 12
                  else _('%s months', months) if months != 1 else _('1 month')) if joined else ''

        own = values['ft_own']
        upcoming = sorted((leave for leave in own if leave['status'] in ('approved', 'pending') and leave['to'] >= today.isoformat()),
                          key=lambda leave: leave['from'])
        waiting = [leave for leave in own if leave['status'] == 'pending']
        taken = {}
        for leave in own:
            if leave['status'] == 'approved' and leave['from'] <= today.isoformat():
                taken[leave['type']] = taken.get(leave['type'], 0) + leave['days']

        # Who appears on the month strip: HR sees whoever is away, a manager
        # their reports, everyone else their own team (same manager).
        month_start = today.replace(day=1)
        month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        Employee = self.env['hr.employee'].sudo()
        if values['ft_is_hr']:
            people = Employee.search([('company_id', 'in', user.company_ids.ids)])
        elif Employee.search_count([('parent_id', '=', employee.id)]):
            people = Employee.search([('parent_id', '=', employee.id)]) | employee
        elif employee.parent_id:
            people = Employee.search([('parent_id', '=', employee.parent_id.id)])
        else:
            people = employee
        month_leaves = Leave.search([
            ('employee_id', 'in', people.ids), ('state', 'in', ('validate',) + PENDING_STATES),
            ('request_date_from', '<=', month_end), ('request_date_to', '>=', month_start)])
        marks = self._day_marks(month_leaves, month_start, month_end, working_days)
        if values['ft_is_hr']:
            people = month_leaves.employee_id | employee
        days = []
        day = month_start
        while day <= month_end:
            days.append({'day': day, 'off': day.weekday() not in working_days, 'today': day == today})
            day += timedelta(days=1)
        labels = {'f': _('full day'), 'l': _('morning'), 'r': _('afternoon')}
        rows = []
        for person in people.sorted(lambda e: (e != employee, e.name or '')):
            cells = []
            for d in days:
                mark = marks.get((person.id, d['day']))
                cells.append(mark and {'part': mark[0], 'wait': mark[1],
                                       'label': '%s: %s%s' % (person.name, labels[mark[0]], _(' (waiting)') if mark[1] else '')})
            rows.append({'name': person.name, 'you': person == employee, 'cells': cells})

        # Manager and HR figures.
        team = self._team(user)
        week_start = today - timedelta(days=today.weekday())
        week_marks = self._day_marks(Leave.search([
            ('employee_id', 'in', team.ids), ('state', '=', 'validate'),
            ('request_date_from', '<=', week_start + timedelta(days=6)), ('request_date_to', '>=', week_start)]),
            week_start, week_start + timedelta(days=6), working_days)
        team_month = sum(0.5 if part != 'f' else 1 for (emp_id, _day), (part, wait) in marks.items()
                         if emp_id in team.ids and not wait)
        values.update({
            'ft_page': 'home',
            'ft_greeting': greeting,
            'ft_now': tz_now,
            'ft_job': employee.job_title or employee.job_id.name or '',
            'ft_joined': joined,
            'ft_tenure': tenure,
            'ft_phone': employee.mobile_phone or employee.work_phone or employee.private_phone or '',
            'ft_next': upcoming[0] if upcoming else None,
            'ft_waiting': waiting,
            'ft_taken_total': sum(taken.values()),
            'ft_taken': sorted(taken.items()),
            'ft_month': month_start,
            'ft_month_days': days,
            'ft_month_rows': rows,
            'ft_week_off': len({emp_id for emp_id, _day in week_marks}),
            'ft_team_month_days': team_month,
        })
        return values
