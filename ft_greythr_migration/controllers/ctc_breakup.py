from odoo import http
from odoo.http import content_disposition, request


class CtcBreakupController(http.Controller):

    @http.route('/ft_greythr_migration/ctc_breakup', type='http', auth='user', methods=['GET'])
    def download_ctc_breakup(self, employee_ids='', **kwargs):
        try:
            ids = [int(i) for i in employee_ids.split(',') if i.strip()]
        except ValueError:
            return request.not_found()
        employees = request.env['hr.employee'].browse(ids).exists()
        if not employees:
            return request.not_found()
        employees._ft_check_ctc_breakup_access()
        content = employees._ft_ctc_breakup_xlsx()
        return request.make_response(content, headers=[
            ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            ('Content-Length', len(content)),
            ('Content-Disposition', content_disposition(employees._ft_ctc_breakup_filename())),
        ])
