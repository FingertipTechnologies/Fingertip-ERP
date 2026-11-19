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
    crm_source_contact_key = fields.Char(copy=False, readonly=True, index=True)
    customer_code = fields.Char(string='Customer Code', copy=False, index=True, readonly=True,tracking=True,)
    crm_sync_state = fields.Selection([
        ('pending', 'Pending'), ('success', 'Synchronized'),
        ('not_found', 'Not Found in CRM/PMS'), ('failed', 'Failed')
    ], string='CRM/PMS Sync Status', default='pending', copy=False, index=True,tracking=True,)

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
    def _write_crm_changes(self, record, data, mapping):
        """Write only explicitly edited non-blank fields."""
        incoming_fields = data.get('changed_fields')
        if not isinstance(incoming_fields, list):
            return
        vals = {mapping[key]: data[key] for key in mapping
                if key in incoming_fields and mapping[key] in record._fields
                and isinstance(data.get(key), str) and data[key].strip()
                and data[key] != record[mapping[key]]}
        if vals:
            record.write(vals)

    @api.model
    def _apply_crm_company_location(self, company, data):
        changes = data.get('changed_fields')
        if not isinstance(changes, list):
            return
        vals = {}
        country = company.country_id
        if 'country' in changes and data.get('country'):
            country = self.env['res.country'].search(
                [('code', '=ilike', data['country'])], limit=1
            )
            if not country:
                raise ValidationError(_('CRM/PMS country was not found.'))
            vals['country_id'] = country.id
        if ('state' in changes or 'country_id' in vals) and data.get('state'):
            if not country:
                country = self.env['res.country'].search(
                    [('code', '=ilike', data.get('country') or '')], limit=1
                )
                if country:
                    vals['country_id'] = country.id
            if not country:
                raise ValidationError(_('A matching ERP country is required for the CRM/PMS state.'))
            states = self.env['res.country.state']
            domain = [('country_id', '=', country.id)]
            state = states.browse()
            if data.get('state_code'):
                state = states.search(domain + [('code', '=ilike', data['state_code'])], limit=2)
            if not state:
                state = states.search(domain + [('name', '=ilike', data['state'])], limit=2)
            if len(state) != 1:
                raise ValidationError(_('CRM/PMS state was not found uniquely in the ERP country.'))
            vals['state_id'] = state.id
        elif 'country_id' in vals and company.state_id and company.state_id.country_id != country:
            # The old state cannot belong to the newly selected country.
            vals['state_id'] = False
        if vals:
            company.write(vals)

    @api.model
    def _upsert_crm_contact(self, company, data, source=None, source_company_id=None):
        """Resolve saved source identity, then match legacy contacts by pre-edit identity."""
        P = self.sudo().with_context(active_test=False)
        name = (data.get('name') or '').strip()
        if not name:
            return {'status': 'skipped', 'reason': 'contact_name_missing'}
        source_contact_id = str(data.get('source_contact_id') or '').strip()
        source_key = ('%s:%s:%s' % (source, source_company_id, source_contact_id)
                      if source and source_company_id and source_contact_id else False)
        siblings = P.search([('parent_id', '=', company.id), ('is_company', '=', False),
                             ('type', '=', 'contact')])
        matches = siblings.filtered(lambda p: p.crm_source_contact_key == source_key) if source_key else P.browse()
        eligible = siblings.filtered(lambda p: not p.crm_source_contact_key) if source_key else siblings
        previous = data.get('previous_identity')

        def find(identity):
            key = contact_identity_key(identity.get('name'), identity.get('email'), identity.get('mobile'))
            if key[0] == 'email_mobile':
                return eligible.filtered(lambda p: norm_email(p.email) == key[1]
                                         and norm_mobile(p.mobile) == key[2])
            if key[0] == 'email':
                return eligible.filtered(lambda p: norm_email(p.email) == key[1])
            if key[0] == 'mobile':
                return eligible.filtered(lambda p: norm_mobile(p.mobile) == key[1])
            return eligible.filtered(lambda p: norm_name(p.name) == key[1])

        if not matches and isinstance(previous, dict):
            matches = find(previous)
        if not matches:
            matches = find(data)
        if len(matches) > 1:
            raise ContactMatchError(_('Multiple contacts match under company %s: %s') % (company.name, name))
        mapping = {'name': 'name', 'email': 'email', 'phone': 'phone',
                   'mobile': 'mobile', 'job_title': 'function'}
        if matches:
            contact = matches[0]
            if data.get('changed_fields'):
                self._write_crm_changes(contact, data, mapping)
            else:
                self._fill_empty(contact, data, mapping)
            if source_key and not contact.crm_source_contact_key:
                contact.write({'crm_source_contact_key': source_key})
            status = 'updated'
        else:
            vals = {'name': name, 'parent_id': company.id, 'type': 'contact', 'is_company': False}
            if source_key:
                vals['crm_source_contact_key'] = source_key
            for incoming, field_name in mapping.items():
                if data.get(incoming) and field_name in P._fields:
                    vals[field_name] = data[incoming]
            contact = P.create(vals)
            status = 'created'
        return {'status': status, 'erp_contact_id': contact.id, 'source_contact_id': source_contact_id}

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

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        companies = partners.filtered('is_company')

        if not companies:
            return partners

        existing_companies = self.sudo().with_context(active_test=False).search([
            ('is_company', '=', True),
            ('website', '!=', False),
            ('id', 'not in', companies.ids),
        ])

        existing_keys = {
            (norm_name(company.name), norm_site(company.website))
            for company in existing_companies
        }

        for company in companies:
            name = norm_name(company.name)
            website = norm_site(company.website)

            if not name:
                raise ValidationError(_("Company Name is required."))

            if not website:
                raise ValidationError(_("Website is required for a company."))

            key = (name, website)
            if key in existing_keys:
                raise ValidationError(_(
                    "Duplicate company. A company with the same name and website "
                    "already exists in ERP."
                ))

            # Also catch duplicates within the same import or batch.
            existing_keys.add(key)

        return partners