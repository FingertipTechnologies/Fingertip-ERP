from odoo import api, fields, models
from odoo.exceptions import UserError


class HrPayslipRun(models.Model):
    _inherit = 'hr.payslip.run'

    ft_draft_move_count = fields.Integer(
        'Draft Journal Entries', compute='_compute_ft_draft_move_count')

    def _ft_draft_moves(self):
        # Entries of payslips validated before payroll accounting was set up
        # have no lines and cannot be posted; they are left out.
        return self.slip_ids.move_id.filtered(lambda move: move.state == 'draft' and move.line_ids)

    @api.depends('slip_ids.move_id.state')
    def _compute_ft_draft_move_count(self):
        for run in self:
            run.ft_draft_move_count = len(run.sudo()._ft_draft_moves())

    def action_ft_post_entries(self):
        """Post the draft journal entries of this run's payslips, so each
        payslip can then be paid."""
        moves = self._ft_draft_moves()
        if not moves:
            raise UserError(self.env._('This pay run has no draft journal entries to post.'))
        moves.action_post()
        empty = self.slip_ids.filtered(
            lambda slip: slip.move_id.state == 'draft' and not slip.move_id.line_ids)
        message = self.env._('%s journal entries posted.', len(moves))
        if empty:
            message += '\n' + self.env._(
                'Not posted, the journal entry is empty (reset these payslips to draft and '
                'validate them again): %s', ', '.join(empty.employee_id.mapped('name')))
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'message': message, 'type': 'warning' if empty else 'success',
                       'sticky': bool(empty), 'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'}},
        }
