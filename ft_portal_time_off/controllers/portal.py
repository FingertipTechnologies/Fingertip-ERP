# -*- coding: utf-8 -*-
import json

from werkzeug.urls import url_encode

from odoo import http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal


class TimeOffPortal(CustomerPortal):

    def _ft_time_off(self):
        return request.env['ft.portal.time.off'].sudo()

    def _prepare_portal_layout_values(self):
        values = super()._prepare_portal_layout_values()
        values['ft_time_off_access'] = bool(request.env.user.sudo().employee_id)
        return values

    @http.route()
    def home(self, **kw):
        # Employees get the Fingertip dashboard; any other portal user keeps Odoo's page.
        service = self._ft_time_off()
        if not service._employee(request.env.user):
            return super().home(**kw)
        values = self._prepare_portal_layout_values()
        values.update(service._dashboard_values(request.env.user))
        return request.render('ft_portal_time_off.portal_my_dashboard', values)

    @http.route('/my/time-off', type='http', auth='user', website=True)
    def portal_my_time_off(self, view='me', done=None, error=None, **kw):
        service = self._ft_time_off()
        if not service._employee(request.env.user):
            return request.redirect('/my')
        values = self._prepare_portal_layout_values()
        values.update(service._page_values(request.env.user))
        if view == 'team' and not values['ft_can_approve']:
            view = 'me'
        values.update({
            'page_name': 'time_off', 'ft_page': 'timeoff', 'ft_view': view, 'ft_done': done, 'ft_error': error,
            'ft_calendar_json': json.dumps(values['ft_calendar']),
            'ft_working_days_json': json.dumps(values['ft_working_days']),
        })
        return request.render('ft_portal_time_off.portal_my_time_off', values)

    @http.route('/my/time-off/preview', type='jsonrpc', auth='user')
    def portal_time_off_preview(self, **data):
        return self._ft_time_off()._preview(request.env.user, data)

    @http.route('/my/time-off/apply', type='http', auth='user', methods=['POST'], website=True)
    def portal_time_off_apply(self, **data):
        try:
            self._ft_time_off()._apply(request.env.user, data)
        except (UserError, ValidationError, AccessError) as e:
            return request.redirect('/my/time-off?' + url_encode({'error': e.args[0]}))
        return request.redirect('/my/time-off?done=applied')

    @http.route('/my/time-off/<int:leave_id>/withdraw', type='http', auth='user', methods=['POST'], website=True)
    def portal_time_off_withdraw(self, leave_id, **kw):
        try:
            self._ft_time_off()._withdraw(request.env.user, leave_id)
        except (UserError, ValidationError, AccessError) as e:
            return request.redirect('/my/time-off?' + url_encode({'error': e.args[0]}))
        return request.redirect('/my/time-off?done=withdrawn')

    @http.route('/my/time-off/<int:leave_id>/decide', type='jsonrpc', auth='user')
    def portal_time_off_decide(self, leave_id, decision, reason=''):
        leave = self._ft_time_off()._decide(request.env.user, leave_id, decision, reason)
        return {'state': leave.state}
