"""Salary register of a pay run, laid out like greytHR's register export.

One row per payslip, the amounts taken from the computed payslip lines. Gross
here is everything paid out (Non-Taxable Allowance included, as greytHR shows
it), so Gross + Total Deductions = Net Pay on every row.
"""
import base64
import io

import xlsxwriter

from odoo import models

from .probation import PROBATION_TYPE

# greytHR's column headings, spelling included, so the sheet lines up with
# the registers exported before the move.
EARNING_COLUMNS = [
    ('BASIC', 'BASIC'), ('HRA', 'HRA'), ('SPL', 'SPECIAL ALLOWANCE'),
    ('EDUALW', 'CHILDEREN EDUCTATION ALLOWANCE'), ('MEAL', 'MEAL ALLOWANCE'),
    ('LTA', 'LEAVE TRAVEL ALLOWANCE'), ('NTA', 'NONE TAXABLE ALLOWANCE'),
]
DEDUCTION_COLUMNS = [('PF', 'PF'), ('ESICS', 'ESI'), ('PT', 'PROF TAX'), ('TDS', 'INCOME TAX')]
EARNING_CATEGORIES = ('BASIC', 'ALW', 'FT_NTA')


class HrPayslipRun(models.Model):
    _inherit = 'hr.payslip.run'

    def _ft_register_slips(self):
        self.ensure_one()
        return self.slip_ids.filtered(lambda slip: slip.state != 'cancel').sorted(
            lambda slip: (slip.employee_id.registration_number or '', slip.employee_id.name))

    def _ft_register_extra_earnings(self, slips):
        """Earnings outside greytHR's usual columns (bonus, telephone, variable
        pay...), as (code, heading), so Gross still adds up across the row."""
        fixed = {code for code, _heading in EARNING_COLUMNS}
        extra = {}
        for line in slips.line_ids.sorted('sequence'):
            if (line.category_id.code in EARNING_CATEGORIES and line.code not in fixed
                    and line.total and line.code not in extra):
                extra[line.code] = line.name.upper()
        return list(extra.items())

    def _ft_register_rows(self):
        slips = self._ft_register_slips()
        earnings = EARNING_COLUMNS[:-1] + self._ft_register_extra_earnings(slips) + EARNING_COLUMNS[-1:]
        deduction_codes = {code for code, _heading in DEDUCTION_COLUMNS}
        probation = self.env.ref(PROBATION_TYPE, raise_if_not_found=False)
        rows = []
        for slip in slips:
            lines = slip.line_ids
            total = lambda code: sum(lines.filtered(lambda line: line.code == code).mapped('total'))
            deductions = lines.filtered(lambda line: line.category_id.code == 'DED')
            days_in_month, effective_days, lop = slip._greythr_days()
            employee, version = slip.employee_id, slip.version_id
            rows.append({
                'number': employee.registration_number or '',
                'name': employee.name,
                'joined': version.contract_date_start,
                'left': bool(employee.departure_date and employee.departure_date <= slip.date_to),
                'status': 'Probation' if probation and version.contract_type_id == probation else 'Confirmed',
                'days': days_in_month, 'lop': lop, 'effective': effective_days,
                'earnings': [total(code) for code, _heading in earnings],
                'gross': sum(lines.filtered(lambda line: line.category_id.code in EARNING_CATEGORIES).mapped('total')),
                'deductions': [-total(code) for code, _heading in DEDUCTION_COLUMNS],
                'other': -sum(deductions.filtered(lambda line: line.code not in deduction_codes).mapped('total')),
                'total_deductions': sum(deductions.mapped('total')),
                'net': total('NET'),
            })
        headings = (['Employee No', 'Name', 'Join Date', 'Left?', 'Status', 'DAYS IN MONTH', 'LOP',
                     'EMP EFFECTIVE WORKDAYS'] + [heading for _code, heading in earnings] + ['GROSS']
                    + [heading for _code, heading in DEDUCTION_COLUMNS]
                    + ['OTHER DEDUCTION', 'TOTAL DEDUCTIONS', 'NET PAY'])
        return headings, rows

    def _ft_register_xlsx(self):
        headings, rows = self._ft_register_rows()
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Salary Register')
        bold = workbook.add_format({'bold': True})
        date = workbook.add_format({'num_format': 'd-mmm-yy'})
        sheet.write_row(0, 0, headings, bold)
        for index, row in enumerate(rows, start=1):
            sheet.write(index, 0, row['number'])
            sheet.write(index, 1, row['name'])
            if row['joined']:
                sheet.write_datetime(index, 2, row['joined'], date)
            sheet.write_boolean(index, 3, row['left'])
            sheet.write(index, 4, row['status'])
            sheet.write_row(index, 5, [row['days'], row['lop'], row['effective']] + row['earnings']
                            + [row['gross']] + row['deductions']
                            + [row['other'], row['total_deductions'], row['net']])
        sheet.freeze_panes(1, 2)
        sheet.set_column(0, 0, 12)
        sheet.set_column(1, 1, 30)
        sheet.set_column(2, len(headings) - 1, 13)
        workbook.close()
        return output.getvalue()

    def action_ft_salary_register(self):
        self.ensure_one()
        name = self.env._('Salary Register - %s.xlsx', self.name)
        Attachment = self.env['ir.attachment']
        Attachment.search([('res_model', '=', self._name), ('res_id', '=', self.id), ('name', '=', name)]).unlink()
        attachment = Attachment.create({
            'name': name, 'res_model': self._name, 'res_id': self.id,
            'datas': base64.b64encode(self._ft_register_xlsx()),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return {'type': 'ir.actions.act_url', 'url': '/web/content/%s?download=true' % attachment.id, 'target': 'download'}
