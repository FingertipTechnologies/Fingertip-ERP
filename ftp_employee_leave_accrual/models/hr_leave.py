# -*- coding: utf-8 -*-
"""Maternity and paternity eligibility.

Company policy grants these after two years of service: maternity for six
months, paternity for three days. They are not accrued -- nobody carries a
balance of maternity leave -- so the entitlement is enforced where it is
actually used, on the request itself, and the leave types need no allocation.
"""
import logging

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    def _parental_policies(self, company):
        """(leave type, label, maximum days) for the parental leave types."""
        return [
            (company.ftp_maternity_leave_type_id, _('Maternity'),
             company.ftp_maternity_days),
            (company.ftp_paternity_leave_type_id, _('Paternity'),
             company.ftp_paternity_days),
        ]

    @api.constrains('employee_id', 'holiday_status_id', 'date_from',
                    'number_of_days')
    def _check_parental_leave_policy(self):
        for leave in self:
            employee = leave.employee_id
            if not employee or not leave.holiday_status_id:
                continue
            company = employee.company_id or self.env.company
            for leave_type, label, max_days in leave._parental_policies(company):
                if not leave_type or leave.holiday_status_id != leave_type:
                    continue
                leave._check_parental_service(employee, company, label)
                leave._check_parental_duration(label, max_days)

    def _check_parental_service(self, employee, company, label):
        """Two years on the books before the entitlement opens."""
        required = company.ftp_parental_min_service_years
        if not required:
            return
        joined = employee.sudo().version_id.contract_date_start
        if not joined:
            raise ValidationError(_(
                "%(employee)s has no joining date, so %(label)s leave "
                "eligibility cannot be checked.",
                employee=employee.display_name, label=label))
        start = fields.Date.to_date(leave_start(self))
        served = relativedelta(start, joined).years
        if served < required:
            raise ValidationError(_(
                "%(label)s leave needs %(required)s years of service. "
                "%(employee)s joined on %(joined)s, which is %(served)s "
                "year(s) by %(start)s.",
                label=label, required=required,
                employee=employee.display_name, joined=joined,
                served=served, start=start))

    def _check_parental_duration(self, label, max_days):
        """Measure the calendar span, not Odoo's working-day count.

        number_of_days counts working days, so a 200-day maternity request
        measures about 143 and would slip under a 180 limit -- roughly eight
        months of leave against a six month policy. "Six months" and "three
        days" are both calendar statements, so they are checked as such.
        """
        if not max_days:
            return
        start = self.request_date_from
        end = self.request_date_to or start
        if not start:
            return
        span = (end - start).days + 1
        if span > max_days:
            raise ValidationError(_(
                "%(label)s leave is limited to %(max)s calendar day(s); this "
                "request covers %(asked)s (%(start)s to %(end)s).",
                label=label, max=int(max_days), asked=span,
                start=start, end=end))


def leave_start(leave):
    """The date the leave begins, whichever field carries it."""
    return leave.request_date_from or leave.date_from or fields.Date.context_today(leave)
