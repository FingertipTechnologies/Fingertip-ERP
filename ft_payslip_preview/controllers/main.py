from odoo import http
from odoo.http import content_disposition, request
from odoo.tools.safe_eval import safe_eval


class PayslipPreview(http.Controller):

    @http.route('/ft_payslip_preview/<int:payslip_id>', type='http', auth='user')
    def preview(self, payslip_id, **kwargs):
        """Stream one payslip's PDF inline, rendered the same way Print renders it.

        The report, language and data mirror hr_payroll's /print/payslips
        controller; only the Content-Disposition differs, so the browser shows
        the file instead of saving it.
        """
        if not request.env.user.has_group('hr_payroll.group_hr_payroll_user'):
            return request.not_found()
        payslip = request.env['hr.payslip'].browse(payslip_id).exists()
        if not payslip:
            return request.not_found()
        payslip.check_access('read')
        report = next(iter(payslip._get_pdf_reports()))
        pdf_content, _ = request.env['ir.actions.report'].with_context(
            lang=payslip.employee_id.lang or request.env.lang).sudo()._render_qweb_pdf(
                report, payslip.id, data={'company_id': payslip.company_id})
        if report.print_report_name:
            filename = safe_eval(report.print_report_name, {'object': payslip})
        else:
            filename = '%s - %s' % (request.env._('Payslip'), payslip.name)
        if not filename.lower().endswith('.pdf'):
            filename += '.pdf'
        return request.make_response(pdf_content, headers=[
            ('Content-Type', 'application/pdf'),
            ('Content-Length', len(pdf_content)),
            ('Content-Disposition', content_disposition(filename, disposition_type='inline')),
        ])
