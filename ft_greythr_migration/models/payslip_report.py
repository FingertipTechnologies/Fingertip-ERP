import base64
import calendar

from odoo import fields, models
from odoo.tools import file_open, format_date, format_datetime

from .payroll import NATIVE_COMPONENTS


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    def _ft_report_values(self):
        """Report actual computed lines; never recompute salary or round it to match a sample."""
        self.ensure_one()
        version = self.version_id
        employee = self.employee_id
        ctc = version.greythr_ctc_id
        specs = [
            ('BASIC', 'BASIC', 'full_basic'), ('HRA', 'HRA', 'full_hra'),
            ('SPL', 'SPECIAL ALLOWANCE', 'full_special_allowance'),
            ('MEAL', 'MEAL ALLOWANCE', 'full_meal_allowance'),
            ('LTA', 'LEAVE TRAVEL ALLOWANCE', 'full_leave_travel_allowance'),
            ('CAR', 'CONVEYANCE ALLOWANCE', 'full_conveyance'),
            ('MOB', 'TELEPHONE ALLOWANCE', 'full_telephone_charges'),
            ('MEDALW', 'MEDICAL ALLOWANCE', 'full_medical_allowance'),
            ('CONSULT', 'CONSULTANCY FEES', 'full_consultancy_fees'),
            ('EDUALW', 'CHILDREN EDUCATION ALLOWANCE', 'full_children_education_allowance'),
            ('ATTIRE', 'ATTIRE ALLOWANCE', 'full_attire_allowance'),
            ('BOOKS', 'BOOKS AND PERIODICALS', 'full_book_and_periodicals'),
            ('GROSS_RECON', 'GROSS RECONCILIATION', 'gross_difference'),
        ]
        earnings = []
        seen = set()
        for code, label, source in specs:
            lines = self.line_ids.filtered(lambda line: line.code == code and line.appears_on_payslip)
            actual = sum(lines.mapped('total'))
            master = (version[NATIVE_COMPONENTS[source]] if source in NATIVE_COMPONENTS else ctc[source]) if ctc else 0
            # Keep master salary visible for a fully unpaid month.
            if lines and (actual or master):
                earnings.append({'name': label, 'master': master, 'actual': actual})
            seen.add(code)
        for line in self.line_ids.filtered(lambda l: l.appears_on_payslip and
                l.category_id.code in ('BASIC', 'ALW') and l.code not in seen and l.total):
            earnings.append({'name': line.name.upper(), 'master': None, 'actual': line.total})
        labels = {'PF': 'PF', 'PT': 'PROF TAX', 'TDS': 'TDS', 'ESICS': 'ESI'}
        deductions = [{'name': labels.get(line.code, line.name.upper()), 'actual': -line.total}
            for line in self.line_ids.filtered(lambda l: l.appears_on_payslip and
                l.category_id.code == 'DED' and l.total)]
        gross = sum(row['actual'] for row in earnings)
        total_deductions = sum(row['actual'] for row in deductions)
        net = sum(self.line_ids.filtered(lambda l: l.code == 'NET').mapped('total'))
        lop = sum(self.worked_days_line_ids.filtered(lambda line:
            not line.is_paid and line.code != 'OUT').mapped('number_of_days'))
        start = max(self.date_from, version.contract_date_start or self.date_from)
        end = min(self.date_to, version.contract_date_end or self.date_to)
        days = max((end - start).days + 1, 0)
        bank = employee.primary_bank_account_id
        sex = dict(version._fields['sex']._description_selection(self.env)).get(version.sex, '')
        stamp = format_datetime(self.env, fields.Datetime.now(), tz=self.env.user.tz or 'Asia/Kolkata', dt_format='dd MMM yyyy, hh:mm a')
        words = self.currency_id.with_context(lang='en_US').amount_to_text(net)
        if words.endswith(' Rupees'):
            words = 'Rupees ' + words[:-7]
        logo = self.company_id.logo
        if not logo and self.company_id.name.upper().startswith('FINGERTIP'):
            with file_open('ft_greythr_migration/static/src/img/fingertip_logo.png', 'rb') as image:
                logo = base64.b64encode(image.read())
        return {
            'logo': logo,
            'earnings': earnings, 'deductions': deductions,
            'row_count': max(len(earnings), len(deductions), 5),
            'master_total': sum(row['master'] or 0 for row in earnings),
            'gross': gross, 'deduction_total': total_deductions, 'net': net,
            'words': words, 'gender': sex,
            'month': format_date(self.env, self.date_from, date_format='MMMM yyyy'),
            'joining': format_date(self.env, version.contract_date_start, date_format='dd MMM yyyy') if version.contract_date_start else '',
            'days_in_month': calendar.monthrange(self.date_from.year, self.date_from.month)[1],
            'effective_days': max(days - lop, 0), 'lop': lop,
            'bank_name': bank.bank_id.name or '', 'bank_account': bank.acc_number or '',
            'designation': version.job_id.name or employee.job_title or '',
            'department': version.department_id.name or '',
            'location': version.work_location_id.name or self.company_id.city or '',
            'print_date': stamp,
        }

    def _ft_report_number(self, value):
        if value is None:
            return ''
        value = self.currency_id.round(value)
        if value == int(value):
            return str(int(value))
        return f'{value:.{self.currency_id.decimal_places}f}'
