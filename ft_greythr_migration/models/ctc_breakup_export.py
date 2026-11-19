"""CTC breakup as an Excel file, in the shape of the Fingertip CTC sheet.

Employees > select one or more > Actions > Download CTC Breakup (Excel). One worksheet per
employee, from the contract version in force today. Every figure is a field of the read-only
CTC breakup in ctc_breakup.py (the Salary tab), so the file and the form always agree.
"""
import io

import xlsxwriter

from odoo import _, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_round

PAYROLL_GROUP = 'hr_payroll.group_hr_payroll_user'
# Indian digit grouping: 1,23,45,678
INR_FORMAT = '[>=10000000]##\\,##\\,##\\,##0;[>=100000]##\\,##\\,##0;##,##0'


def _rupees(amount):
    return float_round(amount or 0.0, precision_digits=0, rounding_method='HALF-UP')


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    def _ft_ctc_breakup_rows(self):
        """Rows of the breakup: (kind, label, yearly, monthly).

        kind: 'section' heading, 'line', 'total' (bold), 'gross' / 'net' (orange band),
        'tax' (yellow band), 'blank'. yearly/monthly None prints '-'.
        """
        self.ensure_one()
        v = self.sudo().version_id
        optional = [
            # (label, yearly field, monthly field) shown only when not zero
            ('Children Education Allowance', 'ft_annual_children_education', 'ft_children_education_allowance'),
            ('Standard Allowance', 'ft_annual_standard_allowance', 'l10n_in_standard_allowance'),
            ('Performance Bonus', 'ft_annual_performance_bonus', 'l10n_in_performance_bonus'),
            ('Phone Subscription', 'ft_annual_phone', 'l10n_in_phone_subscription'),
            ('Internet Subscription', 'ft_annual_internet', 'l10n_in_internet_subscription'),
            ('Company Transport', 'ft_annual_transport', 'l10n_in_company_transport'),
        ]
        rows = [
            ('header', 'Particulars:', 'Yearly', 'Monthly'),
            ('line', 'Fixed Pay', v.ft_annual_fixed_pay, v.l10n_in_gross_salary),
            ('line', 'Variable Pay', v.ft_annual_variable_pay, v.ft_monthly_variable_pay),
            ('line', 'PF-Employer contribution', v.ft_annual_pf_employer, v.l10n_in_pf_employer_amount),
            ('line', 'ESI-Employer contribution', v.ft_annual_esic_employer, v.l10n_in_esic_employer_amount),
            ('line', 'Gratuity', v.ft_annual_gratuity, v.l10n_in_gratuity),
        ]
        if v.ft_annual_lwf_employer:
            rows.append(('line', 'LWF-Employer contribution', v.ft_annual_lwf_employer,
                         v.l10n_in_lwf_employer_contribution))
        rows += [
            ('total', 'Total CTC', v.ft_annual_ctc, v.ft_monthly_ctc),
            ('section', 'Fixed Salary break up:', None, None),
            ('line', 'Basic Salary', v.ft_annual_basic, v.l10n_in_basic_salary_amount),
            ('line', 'HRA', v.ft_annual_hra, v.l10n_in_hra),
            ('line', 'Food Coupon/Meal Allowances', v.ft_annual_meal, v.l10n_in_meal_voucher_amount),
            ('line', 'LTA', v.ft_annual_lta, v.l10n_in_leave_travel_allowance),
        ]
        rows += [('line', label, v[yearly], v[monthly]) for label, yearly, monthly in optional if v[yearly]]
        rows += [
            ('line', 'Special Allowance', v.ft_annual_fixed_allowance, v.l10n_in_fixed_allowance),
            ('gross', 'Gross Total', v.ft_annual_gross, v.l10n_in_gross_salary),
            ('blank', '', None, None),
            ('section', 'Deductions:', None, None),
            ('line', 'Food Coupon-(Optional)', 0, 0),
            ('line', 'Medical Insurance-(Optional)', v.ft_annual_medical_insurance, v.l10n_in_medical_insurance_total),
            ('line', 'PF-Employee', v.ft_annual_pf_employee, v.l10n_in_pf_employee_amount),
            ('line', 'ESI-Employee', v.ft_annual_esic_employee, v.l10n_in_esic_employee_amount),
            ('line', 'Professional Tax', v.ft_annual_professional_tax, v.ft_monthly_professional_tax),
        ]
        if v.ft_annual_lwf_employee:
            rows.append(('line', 'LWF-Employee', v.ft_annual_lwf_employee, v.l10n_in_lwf_employee_contribution))
        rows += [
            # Not a fixed monthly figure: worked out on each payslip, so it stays out of the totals.
            ('tax', 'Income Tax (TDS)', None, None),
            ('total', 'Total Deductions', v.ft_annual_total_deductions, v.ft_monthly_total_deductions),
            ('net', 'Net Payable', v.ft_annual_net_payable, v.ft_monthly_net_payable),
        ]
        return rows

    def _ft_ctc_breakup_xlsx(self):
        """The workbook for these employees, as bytes."""
        if not self:
            raise UserError(_('Select at least one employee.'))
        output = io.BytesIO()
        book = xlsxwriter.Workbook(output, {'in_memory': True})
        base = {'font_name': 'Arial', 'font_size': 10, 'border': 1, 'valign': 'vcenter'}
        fmt = {
            'title': book.add_format({'font_name': 'Arial', 'bold': True, 'font_size': 13}),
            'label': book.add_format({'font_name': 'Arial', 'font_size': 10, 'bold': True}),
            'info': book.add_format({'font_name': 'Arial', 'font_size': 10}),
            'header': book.add_format(dict(base, bold=True, bg_color='#BDD7EE')),
            'header_num': book.add_format(dict(base, bold=True, bg_color='#BDD7EE', align='center')),
        }
        bands = {'line': {}, 'total': {'bold': True}, 'section': {'bold': True},
                 'gross': {'bold': True, 'bg_color': '#FFC000'}, 'net': {'bold': True, 'bg_color': '#FFC000'},
                 'tax': {'bg_color': '#FFFF00'}, 'blank': {}}
        for kind, extra in bands.items():
            fmt[kind] = book.add_format(dict(base, **extra))
            fmt[kind + '_num'] = book.add_format(dict(base, num_format=INR_FORMAT, align='right', **extra))
            fmt[kind + '_dash'] = book.add_format(dict(base, align='center', **extra))
        used = set()
        for employee in self.sorted(lambda e: (e.registration_number or '~', e.name or '')):
            name = (employee.registration_number or employee.name or 'Employee')[:31]
            for ch in '[]:*?/\\':
                name = name.replace(ch, ' ')
            sheet_name, n = name, 1
            while sheet_name.lower() in used:
                n += 1
                sheet_name = '%s (%s)' % (name[:26], n)
            used.add(sheet_name.lower())
            ws = book.add_worksheet(sheet_name)
            ws.set_column(0, 0, 34)
            ws.set_column(1, 2, 14)
            version = employee.sudo().version_id
            ws.write(0, 0, 'CTC Breakup', fmt['title'])
            info = [
                ('Employee Name', employee.name),
                ('Employee ID', employee.registration_number or ''),
                ('Designation', employee.job_title or employee.job_id.name or ''),
                ('Department', employee.department_id.name or ''),
                ('Date of Joining', fields.Date.to_string(version.contract_date_start) or ''),
                ('Effective From', fields.Date.to_string(version.date_version) or ''),
            ]
            row = 2
            for label, value in info:
                ws.write(row, 0, label, fmt['label'])
                ws.write(row, 1, value, fmt['info'])
                row += 1
            row += 1
            for kind, label, yearly, monthly in employee._ft_ctc_breakup_rows():
                if kind == 'header':
                    ws.write(row, 0, label, fmt['header'])
                    ws.write(row, 1, yearly, fmt['header_num'])
                    ws.write(row, 2, monthly, fmt['header_num'])
                elif kind in ('section', 'blank'):
                    ws.write(row, 0, label, fmt[kind])
                    ws.write_blank(row, 1, None, fmt[kind])
                    ws.write_blank(row, 2, None, fmt[kind])
                else:
                    ws.write(row, 0, label, fmt[kind])
                    for col, amount in ((1, yearly), (2, monthly)):
                        if amount is None:
                            ws.write(row, col, '-', fmt[kind + '_dash'])
                        else:
                            ws.write_number(row, col, _rupees(amount), fmt[kind + '_num'])
                row += 1
            ws.write(row + 1, 0, 'Income Tax (TDS) is worked out on each payslip and is not included in Net Payable.',
                     fmt['info'])
        book.close()
        return output.getvalue()

    def _ft_ctc_breakup_filename(self):
        if len(self) == 1:
            label = ' - '.join(filter(None, [self.registration_number, self.name]))
            return 'CTC Breakup - %s.xlsx' % label.replace('/', '-')
        return 'CTC Breakup - %s employees.xlsx' % len(self)

    def _ft_check_ctc_breakup_access(self):
        if not self.env.user.has_group(PAYROLL_GROUP):
            raise AccessError(_('Only Payroll users can download a CTC breakup.'))
        self.check_access('read')

    def action_ft_download_ctc_breakup(self):
        self._ft_check_ctc_breakup_access()
        if not self:
            raise UserError(_('Select at least one employee.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/ft_greythr_migration/ctc_breakup?employee_ids=%s' % ','.join(map(str, self.ids)),
            'target': 'self',
        }
