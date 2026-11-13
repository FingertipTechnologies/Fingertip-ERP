"""ERP-owned customer codes, contact upsert and code-only legacy sync."""
import logging
import re
from urllib.parse import urlsplit

import requests
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


def norm_site(value):
    value = (value or '').strip().lower()
    if not value:
        return ''
    if '://' not in value:
        value = 'https://' + value
    parsed = urlsplit(value)
    host = (parsed.netloc or parsed.path).split('/')[0].split(':')[0].lower()
    return (host[4:] if host.startswith('www.') else host).rstrip('.')


def norm_name(value):
    return re.sub(r'\s+', ' ', (value or '').strip()).casefold()


def norm_email(value):
    return (value or '').strip().casefold()


def norm_mobile(value):
    return re.sub(r'[^0-9+]', '', value or '')


def contact_identity_key(name, email=None, mobile=None):
    """Identity under one company, using only identifiers supplied by sender.

    When both email and mobile are supplied, BOTH must match. If only one
    exists, match that value. For name-only contacts, use the normalized name.
    """
    email = norm_email(email)
    mobile = norm_mobile(mobile)
    if email and mobile:
        return ('email_mobile', email, mobile)
    if email:
        return ('email', email)
    if mobile:
        return ('mobile', mobile)
    return ('name', norm_name(name))


class ContactMatchError(ValidationError):
    """Contact identity is ambiguous: reject the transaction rather than duplicate."""


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # The original ERP database did not expose res.partner.mobile. Extending the
    # standard model makes the incoming mobile number persist on that database.
    mobile = fields.Char(string='Mobile')
    customer_code = fields.Char(string='Customer Code', copy=False, index=True, readonly=True)
    crm_sync_state = fields.Selection([
        ('pending', 'Pending'), ('success', 'Synchronized'),
        ('not_found', 'Not Found in CRM/PMS'), ('failed', 'Failed')
    ], string='CRM/PMS Sync Status', default='pending', copy=False, index=True)

    _sql_constraints = [
        ('erp_customer_code_unique', 'unique(customer_code)', 'Customer Code must be unique.'),
    ]

    @api.constrains('customer_code', 'is_company')
    def _check_code_company(self):
        for p in self:
            if p.customer_code and not p.is_company:
                raise ValidationError(_('Customer Code can only belong to a company.'))

    @api.model
    def _generate_customer_code(self):
        code = self.env['ir.sequence'].next_by_code('crm.erp.customer.code')
        if not code:
            raise ValidationError(_('ERP Customer Code sequence is not configured.'))
        return code

    @api.model
    def _find_crm_company(self, data, source=None, source_id=None):
        """Match ONLY when normalized name AND normalized website match.

        An existing source-id mapping cannot override changed company identity.
        """
        P = self.sudo().with_context(active_test=False)
        name, site = norm_name(data.get('name')), norm_site(data.get('website'))
        if not name or not site:
            return P.browse(), 'missing_identity'
        # Search all company websites (including archived) to normalize protocols/www.
        # This scan is appropriate for initial migrations; for huge databases use
        # indexed normalized identity fields in a future optimization.
        candidates = P.search([('is_company', '=', True), ('website', '!=', False)])
        exact = candidates.filtered(lambda p: norm_name(p.name) == name and norm_site(p.website) == site)
        if len(exact) > 1:
            return exact, 'ambiguous'
        if exact:
            return exact, 'exact_match'
        return P.browse(), 'not_found'

    @api.model
    def _fill_empty(self, record, data, mapping):
        vals = {}
        for incoming, field_name in mapping.items():
            value = data.get(incoming)
            if value not in (None, '') and field_name in record._fields and not record[field_name]:
                vals[field_name] = value
        if vals:
            record.sudo().write(vals)
        return vals

    @api.model
    def _upsert_crm_contact(self, company, data):
        """Match contact using the sender's available identifiers within its company."""
        P = self.sudo().with_context(active_test=False)
        name = (data.get('name') or '').strip()
        if not name:
            return {'status': 'skipped', 'reason': 'contact_name_missing'}
        email = norm_email(data.get('email'))
        mobile = norm_mobile(data.get('mobile'))
        siblings = P.search([('parent_id', '=', company.id), ('is_company', '=', False),
                             ('type', '=', 'contact')])
        incoming_key = contact_identity_key(name, email, mobile)

        def same(contact):
            # Never partially match an email+mobile pair: different populated
            # values represent different contacts, even if one matches.
            if incoming_key[0] == 'email_mobile':
                return (norm_email(contact.email) == email
                        and norm_mobile(contact.mobile) == mobile)
            if incoming_key[0] == 'email':
                return norm_email(contact.email) == email
            if incoming_key[0] == 'mobile':
                return norm_mobile(contact.mobile) == mobile
            return norm_name(contact.name) == incoming_key[1]

        matches = siblings.filtered(same)
        if len(matches) > 1:
            raise ContactMatchError(_('Multiple contacts match under company %s: %s') % (company.name, name))
        if matches:
            contact = matches[0]
            self._fill_empty(contact, data, {'name': 'name', 'email': 'email', 'phone': 'phone',
                                             'mobile': 'mobile', 'job_title': 'function'})
            return {'status': 'updated', 'erp_contact_id': contact.id}
        # No exact match for the available identifiers: create a distinct
        # contact under this company. Partial email/mobile overlaps are allowed.
        vals = {'name': name, 'parent_id': company.id, 'type': 'contact', 'is_company': False}
        for incoming, field_name in {'email': 'email', 'phone': 'phone', 'mobile': 'mobile',
                                     'job_title': 'function'}.items():
            if data.get(incoming) and field_name in P._fields:
                vals[field_name] = data[incoming]
        contact = P.create(vals)
        return {'status': 'created', 'erp_contact_id': contact.id}

    def _prepare_crm_code_payload(self):
        """Only the exact company identity and ERP-owned code are sent.

        Historical ERP -> CRM/PMS does NOT send contacts or other company fields.
        """
        self.ensure_one()
        return {
            'erp_customer_id': self.id,
            'customer_code': self.customer_code,
            'company': {'name': self.name or '', 'website': self.website or ''},
        }

    def _send_to_crm(self):
        """Update an existing CRM/PMS company only; never request its creation."""
        self.ensure_one()
        config = self.env['ir.config_parameter'].sudo()
        url = (config.get_param('crm_erp_api_receiver.crm_api_url') or '').strip()
        token = (config.get_param('crm_erp_api_receiver.crm_api_token') or '').strip()
        if not url or not token:
            raise UserError(_('Set the CRM/PMS Customer Code API URL and token in ERP settings.'))
        if not (url.startswith('https://') or url.startswith('http://127.0.0.1:')
                or url.startswith('http://localhost:')):
            raise UserError(_('Use HTTPS or a localhost URL for the CRM/PMS receiver.'))
        if not norm_name(self.name) or not norm_site(self.website):
            raise ValidationError(_('ERP company name and website are required for matching.'))
        if not self.customer_code:
            self.write({'customer_code': self._generate_customer_code()})
        response = requests.post(
            url, json=self._prepare_crm_code_payload(),
            headers={'Authorization': 'Bearer ' + token,
                     'Content-Type': 'application/json', 'Accept': 'application/json'},
            timeout=(5, 30), allow_redirects=False,
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict) or result.get('success') is not True:
            raise UserError(_('CRM/PMS did not confirm the code synchronization.'))
        matched = result.get('matched')
        if matched is False:
            self.write({'crm_sync_state': 'not_found'})
            return False
        if matched is not True:
            raise UserError(_('CRM/PMS response is missing the matched flag.'))
        customer = result.get('customer') or {}
        crm_id = customer.get('crm_customer_id')
        if not crm_id or customer.get('customer_code') != self.customer_code:
            raise UserError(_('CRM/PMS response does not confirm the ERP customer code.'))
        self.write({'crm_sync_state': 'success'})
        return True

    @api.model
    def _cron_sync_existing_erp_customers(self):
        """Scan ERP companies in rotating batches; skip successes.

        A cursor in standard ir.config_parameter avoids custom tracking fields
        and prevents failed/unmatched early partners from starving later ones.
        """
        P = self.sudo().with_context(active_test=False)
        config = self.env['ir.config_parameter'].sudo()
        cursor_key = 'crm_erp_api_receiver.crm_sync_scan_cursor'
        try:
            last_id = int(config.get_param(cursor_key, '0') or '0')
        except (TypeError, ValueError):
            last_id = 0
        batch_size = 50
        domain = [('is_company', '=', True), ('id', '>', last_id),
                  ('crm_sync_state', '!=', 'success')]
        companies = P.search(domain, order='id asc', limit=batch_size)
        if not companies:
            # Restart the scan at the smallest company ID on the next pass.
            config.set_param(cursor_key, '0')
            return
        for company in companies:
            try:
                # Check Company Name and Website first
                if not norm_name(company.name) or not norm_site(company.website):
                    _logger.warning(
                        "Skipping ERP customer %s: company name or website is missing.",
                        company.id
                    )
                    continue

                # Generate Customer Code only for valid companies
                if not company.customer_code:
                    company.write({
                        'customer_code': company._generate_customer_code()
                    })

                # Synchronize Customer Code to CRM/PMS
                company._send_to_crm()

            except Exception:
                _logger.exception(
                    'ERP customer code sync failed for partner %s',
                    company.id
                )
                company.write({'crm_sync_state': 'failed'})

            finally:
                config.set_param(cursor_key, str(company.id))