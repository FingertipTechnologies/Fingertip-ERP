"""Yearly Salary by Employee between a From Date and a To Date instead of a year.

The employee list starts empty; HR adds the employees, chosen from those with
paid payslips between the two dates.
"""
import base64
import io

import xlsxwriter
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import format_date


class YearlySalaryDetail(models.TransientModel):
    _inherit = 'yearly.salary.detail'

    ft_date_from = fields.Date(string='From Date', required=True)
    ft_date_to = fields.Date(string='To Date', required=True)
    related_employee_ids = fields.Many2many(compute='_ft_compute_related_employee_ids')
    employee_ids = fields.Many2many(compute='_ft_compute_employee_ids')

    @api.depends('ft_date_from', 'ft_date_to', 'department_id', 'job_id')
    def _ft_compute_related_employee_ids(self):
        """Employees with a paid payslip between the two dates."""
        Employee = self.env['hr.employee']
        for wizard in self:
            if not wizard.ft_date_from or not wizard.ft_date_to or wizard.ft_date_from > wizard.ft_date_to:
                wizard.related_employee_ids = Employee
                continue
            slips = self.env['hr.payslip'].search([
                ('state', '=', 'paid'),
                ('date_from', '>=', wizard.ft_date_from), ('date_to', '<=', wizard.ft_date_to)])
            wizard.related_employee_ids = Employee.search(
                wizard._get_domain() + [('id', 'in', slips.employee_id.ids)])

    @api.depends('related_employee_ids')
    def _ft_compute_employee_ids(self):
        """Nobody by default; a change of dates or filters only drops picked
        employees who have no paid payslip in the new period."""
        for wizard in self:
            wizard.employee_ids = wizard.employee_ids & wizard.related_employee_ids

    def _ft_check_print(self):
        self.ensure_one()
        if self.ft_date_from > self.ft_date_to:
            raise UserError(_('The From Date must be before the To Date.'))
        if not self.employee_ids:
            raise UserError(_("There must be at least one employee available to generate a report."))

    def print_report(self):
        self._ft_check_print()
        return super().print_report()

    def _ft_excel(self):
        """The PDF's content on one sheet: each employee's block below the previous one."""
        form = self.read()[0]
        report = self.env['report.l10n_in_hr_payroll.report_hryearlysalary']
        date_from, date_to = self.ft_date_from, self.ft_date_to
        month_names, months = report._get_periods_new(form)
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Salary by Employee')
        bold = workbook.add_format({'bold': True})
        title = workbook.add_format({'bold': True, 'align': 'center', 'font_size': 12})
        center = workbook.add_format({'align': 'center'})
        heading = workbook.add_format({'bold': True, 'bg_color': '#E9ECEF', 'border': 1})
        heading_amount = workbook.add_format({'bold': True, 'bg_color': '#E9ECEF', 'border': 1, 'align': 'right'})
        amount = workbook.add_format({'num_format': '#,##0.00'})
        amount_bold = workbook.add_format({'num_format': '#,##0.00', 'bold': True})
        last_col = max(len(months) + 1, 7)
        row = 0
        for employee in report._get_employee(form):
            sheet.merge_range(row, 0, row, last_col, employee.company_id.name or '', title)
            sheet.merge_range(row + 1, 0, row + 1, last_col, _('From Date %(date_from)s To Date %(date_to)s',
                              date_from=date_from.strftime('%d/%m/%Y'), date_to=date_to.strftime('%d/%m/%Y')), center)
            details = ((_('Employee Name'), employee.name), (_('Employee Code'), employee.registration_number),
                       (_('Designation'), employee.job_id.name), (_('Department'), employee.department_id.name))
            for index, (label, value) in enumerate(details):
                sheet.write(row + 2, index * 2, label, bold)
                sheet.write(row + 2, index * 2 + 1, value or '')
            row += 4
            structures = report._get_employee_detail_new(form, employee.id, months, date_from, date_to)
            for structure_name, lines in structures.items():
                sheet.write(row, 0, structure_name, heading)
                for col, name in enumerate(month_names[0], start=1):
                    sheet.write(row, col, name, heading_amount)
                sheet.write(row, len(months) + 1, _('Total'), heading_amount)
                row += 1
                for label, key, bold_codes in ((_('Allowances with Basic:'), 'allow_list', {'BASIC', 'GROSS'}),
                                               (_('Deductions:'), 'deduct_list', {'NET'})):
                    sheet.write(row, 0, label, bold)
                    row += 1
                    for code, values in lines[key]:
                        strong = code in bold_codes
                        sheet.write(row, 0, values[0], bold if strong else None)
                        for col, value in enumerate(values[1:], start=1):
                            sheet.write_number(row, col, value or 0.0, amount_bold if strong else amount)
                        row += 1
                row += 1
            row += 2
        sheet.set_column(0, 0, 32)
        sheet.set_column(1, last_col, 15)
        workbook.close()
        return output.getvalue()

    def action_ft_print_excel(self):
        self._ft_check_print()
        name = _('Yearly Salary by Employee %(date_from)s to %(date_to)s.xlsx',
                 date_from=self.ft_date_from.strftime('%d-%m-%Y'), date_to=self.ft_date_to.strftime('%d-%m-%Y'))
        attachment = self.env['ir.attachment'].create({
            'name': name, 'res_model': self._name, 'res_id': self.id,
            'datas': base64.b64encode(self._ft_excel()),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return {'type': 'ir.actions.act_url', 'url': '/web/content/%s?download=true' % attachment.id, 'target': 'download'}


class ReportHrYearlySalary(models.AbstractModel):
    _inherit = 'report.l10n_in_hr_payroll.report_hryearlysalary'

    @staticmethod
    def _ft_form_period(form):
        if not form.get('ft_date_from') or not form.get('ft_date_to'):
            return False, False
        return fields.Date.to_date(form['ft_date_from']), fields.Date.to_date(form['ft_date_to'])

    def _get_periods_new(self, form):
        """One column per month from the From Date's month to the To Date's."""
        date_from, date_to = self._ft_form_period(form)
        if not date_from:
            return super()._get_periods_new(form)
        names, months, month = [], [], date_from.replace(day=1)
        while month <= date_to:
            names.append(format_date(self.env, month, date_format='MMM yy'))
            months.append(month.strftime('%m-%Y'))
            month += relativedelta(months=1)
        return [names], months

    @api.model
    def _get_report_values(self, docids, data=None):
        form = (data or {}).get('form') or {}
        date_from, date_to = self._ft_form_period(form)
        if not date_from:
            return super()._get_report_values(docids, data)
        if not self.env.context.get('active_model') or not self.env.context.get('active_id'):
            raise UserError(_("Form content is missing, this report cannot be printed."))
        model = self.env.context.get('active_model')
        month_name, months = self._get_periods_new(form)
        employee_data = {employee.id: self._get_employee_detail_new(form, employee.id, months, date_from, date_to)
                         for employee in self._get_employee(form)}
        return {
            'doc_ids': docids,
            'doc_model': model,
            'data': data,
            'docs': self.env[model].browse(self.env.context.get('active_id')),
            'date_from': date_from,
            'date_to': date_to,
            'get_employee': self._get_employee,
            'get_periods': lambda form: month_name,
            'get_employee_detail_new': lambda emp_id: employee_data.get(emp_id, {}),
        }
