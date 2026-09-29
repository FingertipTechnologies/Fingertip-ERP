"""Keep a leave's work entries on the version that was in force.

Odoo 19's hr_work_entry_holidays builds a leave's work entries from every
version whose *contract* overlaps the leave -- that is every version of the
same contract -- and does so once per such version. An employee with two
versions therefore gets one entry per version, each twice its real length,
and the two collide: both land in Conflict, the payslip skips the day, and
the unpaid day is paid in full. Employees with a single version are not
affected, which is why it goes unnoticed until a salary revision.

Two guards fix it without copying the core method:

* a version only produces work entries inside its own validity window, and
* identical work entry values are collapsed before the entries are created.
"""
from datetime import datetime, time

import pytz

from odoo import api, models


class HrVersion(models.Model):
    _inherit = 'hr.version'

    def _get_work_entries_values(self, date_start, date_stop):
        if not isinstance(date_start, datetime):
            return super()._get_work_entries_values(date_start, date_stop)
        vals_list = []
        for version in self:
            start, stop = version._ft_clip_to_version(date_start, date_stop)
            if start is not None:
                vals_list += super(HrVersion, version)._get_work_entries_values(start, stop)
        return vals_list

    def _ft_clip_to_version(self, date_start, date_stop):
        """Intersect a period with this version's validity window, or (None, None)."""
        self.ensure_one()
        version = self.sudo()  # date_start / date_end are HR-manager fields
        if not version.date_start:
            return date_start, date_stop
        tz = pytz.timezone(version._get_tz() or 'UTC')
        aware = date_start.tzinfo is not None

        def bound(day, edge):
            value = tz.localize(datetime.combine(day, edge)).astimezone(pytz.utc)
            return value if aware else value.replace(tzinfo=None)

        start = max(date_start, bound(version.date_start, time.min))
        stop = min(date_stop, bound(version.date_end, time.max)) if version.date_end else date_stop
        if start > stop:
            return None, None
        return start, stop

    @api.model
    def _generate_work_entries_postprocess(self, vals_list):
        seen, unique = set(), []
        for vals in vals_list:
            key = tuple(sorted((field, repr(value)) for field, value in vals.items()))
            if key not in seen:
                seen.add(key)
                unique.append(vals)
        return super()._generate_work_entries_postprocess(unique)
