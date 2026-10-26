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
    # Related Model / Related Document pickers for activities created from the
    # Activities menu; they mirror res_model / res_id
    ft_res_model = fields.Selection(
        [
            ('sale.order', 'Sales Order / Pro forma'),
            ('account.move', 'Invoice / Bill'),
            ('account.payment', 'Payment'),
            ('res.partner', 'Customer'),
        ],
        string='Related Model', compute='_compute_ft_res_model', readonly=False,
    )
    ft_res_id = fields.Many2oneReference(
        string='Related Document', model_field='ft_res_model',
        compute='_compute_ft_res_id', readonly=False,
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

    @api.model_create_multi
    def create(self, vals_list):
        # the document must be set before create: access checks, follower
        # subscription and assignee notification all rely on it
        for vals in vals_list:
            model = vals.pop('ft_res_model', False)
            res_id = vals.pop('ft_res_id', False)
            if model and res_id and not vals.get('res_model_id'):
                vals['res_model_id'] = self.env['ir.model']._get_id(model)
                vals['res_id'] = res_id
        return super().create(vals_list)

    @api.depends('res_model')
    def _compute_ft_res_model(self):
        for activity in self:
            activity.ft_res_model = (
                activity.res_model if activity.res_model in ACCOUNTING_ACTIVITY_MODELS else False)

    @api.depends('res_model', 'res_id')
    def _compute_ft_res_id(self):
        for activity in self:
            activity.ft_res_id = activity.res_id if activity.ft_res_model else False

    @api.onchange('ft_res_model')
    def _onchange_ft_res_model(self):
        # a new model invalidates the document picked for the previous one
        if self.ft_res_model != self.res_model:
            self.res_model_id = self.env['ir.model']._get(self.ft_res_model) if self.ft_res_model else False
            self.res_id = False
            self.ft_res_id = False

    @api.onchange('ft_res_id')
    def _onchange_ft_res_id(self):
        # link the document right away so the customer is filled in before saving
        self.res_id = self.ft_res_id

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
