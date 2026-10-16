from odoo import api, fields, models

ACCOUNTING_ACTIVITY_MODELS = ('sale.order', 'account.move', 'account.payment', 'res.partner')

MOVE_TYPE_GROUPS = {
    'customer_invoice': ('out_invoice', 'out_refund', 'out_receipt'),
    'vendor_bill': ('in_invoice', 'in_refund', 'in_receipt'),
    'journal_entry': ('entry',),
}


class MailActivity(models.Model):
    _inherit = 'mail.activity'

    ft_document_type = fields.Selection(
        [
            ('sale_order', 'Sales Order'),
            ('customer_invoice', 'Customer Invoice / Credit Note'),
            ('vendor_bill', 'Vendor Bill / Refund'),
            ('journal_entry', 'Journal Entry'),
            ('payment', 'Payment'),
            ('partner', 'Customer / Contact'),
        ],
        string='Document Type',
        compute='_compute_ft_document_type',
        search='_search_ft_document_type',
    )
    ft_partner_id = fields.Many2one(
        'res.partner', string='Customer',
        compute='_compute_ft_partner_id', store=True, index='btree_not_null',
    )
    ft_activity_date = fields.Date(
        string='Date', compute='_compute_ft_activity_date', store=True, index=True,
        help='Done date for completed activities, due date for pending ones.',
    )

    @api.depends('res_model', 'res_id')
    def _compute_ft_partner_id(self):
        for activity in self:
            partner = self.env['res.partner']
            if activity.res_model in ACCOUNTING_ACTIVITY_MODELS and activity.res_id:
                record = self.env[activity.res_model].sudo().browse(activity.res_id).exists()
                if activity.res_model == 'res.partner':
                    partner = record
                elif record:
                    partner = record.partner_id
            activity.ft_partner_id = partner.commercial_partner_id or partner

    @api.depends('date_done', 'date_deadline')
    def _compute_ft_activity_date(self):
        for activity in self:
            activity.ft_activity_date = activity.date_done or activity.date_deadline

    @api.depends('res_model', 'res_id')
    def _compute_ft_document_type(self):
        move_ids = self.filtered(lambda a: a.res_model == 'account.move').mapped('res_id')
        move_types = {
            move.id: move.move_type
            for move in self.env['account.move'].sudo().browse(move_ids).exists()
        }
        for activity in self:
            doc_type = False
            if activity.res_model == 'sale.order':
                doc_type = 'sale_order'
            elif activity.res_model == 'account.payment':
                doc_type = 'payment'
            elif activity.res_model == 'res.partner':
                doc_type = 'partner'
            elif activity.res_model == 'account.move':
                move_type = move_types.get(activity.res_id)
                doc_type = next(
                    (group for group, types in MOVE_TYPE_GROUPS.items() if move_type in types),
                    False,
                )
            activity.ft_document_type = doc_type

    def _search_ft_document_type(self, operator, value):
        if operator not in ('in', 'not in'):
            return NotImplemented
        domains = []
        for doc_type in value:
            if doc_type == 'sale_order':
                domains.append([('res_model', '=', 'sale.order')])
            elif doc_type == 'payment':
                domains.append([('res_model', '=', 'account.payment')])
            elif doc_type == 'partner':
                domains.append([('res_model', '=', 'res.partner')])
            elif doc_type in MOVE_TYPE_GROUPS:
                moves = self.env['account.move'].sudo()._search(
                    [('move_type', 'in', MOVE_TYPE_GROUPS[doc_type])])
                domains.append([('res_model', '=', 'account.move'), ('res_id', 'in', moves)])
        domain = fields.Domain.OR(domains) if domains else fields.Domain.FALSE
        return domain if operator == 'in' else ~domain
