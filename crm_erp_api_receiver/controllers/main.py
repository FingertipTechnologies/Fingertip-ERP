"""CRM/PMS -> ERP HTTP API; business data lives in res.partner only."""
import hmac
import json
import logging

from odoo import http
from odoo.http import request
from odoo.exceptions import ValidationError
from ..models.res_partner import ContactMatchError

_logger = logging.getLogger(__name__)


class CrmErpCustomerApi(http.Controller):
    @staticmethod
    def _json(data, status):
        return request.make_response(json.dumps(data),
                                     headers=[('Content-Type', 'application/json; charset=utf-8')], status=status)

    @http.route('/api/v1/customers/upsert', type='http', auth='public', methods=['POST'],
                csrf=False, save_session=False)
    def upsert_customer(self, **kwargs):
        expected = request.env['ir.config_parameter'].sudo().get_param('crm_erp_api_receiver.bearer_token', '')
        auth = request.httprequest.headers.get('Authorization', '')
        supplied = auth[7:].strip() if auth.lower().startswith('bearer ') else ''
        if not expected or not supplied or not hmac.compare_digest(expected, supplied):
            return self._json({'success': False, 'error': 'unauthorized', 'message': 'Invalid API credentials.'}, 401)
        if not request.httprequest.is_json:
            return self._json({'success': False, 'error': 'invalid_content_type',
                               'message': 'Send application/json.'}, 415)
        try:
            payload = request.httprequest.get_json(silent=False)
        except Exception:
            return self._json({'success': False, 'error': 'invalid_json', 'message': 'Invalid JSON body.'}, 400)
        if not isinstance(payload, dict) or not isinstance(payload.get('company'), dict) or not isinstance(payload.get('contacts', []), list):
            return self._json({'success': False, 'error': 'invalid_payload',
                               'message': 'Expected company object and contacts list.'}, 400)
        data, contacts = payload['company'], payload.get('contacts', [])
        source = str(payload.get('source_system') or 'crm_pms').strip()
        source_id = str(payload.get('source_company_id') or '').strip()
        if not str(data.get('name') or '').strip() or not str(data.get('website') or '').strip() or not source_id:
            return self._json({'success': False, 'error': 'missing_identity',
                               'message': 'Company name, website and source_company_id are required.'}, 400)
        P = request.env['res.partner'].sudo()
        try:
            with request.env.cr.savepoint():
                company, match = P._find_crm_company(data, source, source_id)
                if match == 'ambiguous':
                    raise ValidationError('Multiple ERP companies share the exact same name and website.')
                if match == 'missing_identity':
                    raise ValidationError('Company name and website are required.')
                mapping = {'email': 'email', 'phone': 'phone', 'vat': 'vat', 'street': 'street',
                           'street2': 'street2', 'city': 'city', 'zip': 'zip'}
                if match == 'not_found':
                    vals = {'name': str(data['name']).strip(), 'website': str(data['website']).strip(),
                            'is_company': True}
                    for incoming, field_name in mapping.items():
                        if data.get(incoming) and field_name in P._fields:
                            vals[field_name] = data[incoming]
                    if data.get('country'):
                        country = request.env['res.country'].sudo().search([('code', '=ilike', data['country'])], limit=1)
                        if country:
                            vals['country_id'] = country.id
                    company = P.create(vals)
                    action = 'created'
                else:
                    P._fill_empty(company, data, mapping)
                    action = 'updated'
                if not company.customer_code:
                    company.customer_code = P._generate_customer_code()
                results = []
                for item in contacts:
                    results.append(P._upsert_crm_contact(company, item) if isinstance(item, dict)
                                   else {'status': 'skipped', 'reason': 'invalid_contact'})
                # Originated in CRM: no separate ERP->CRM cron pass is needed.
                company.write({'crm_sync_state': 'success'})
                result = {'success': True, 'action': action,
                          'customer': {'erp_customer_id': str(company.id), 'customer_code': company.customer_code,
                                       'name': company.name, 'website': company.website},
                          'contacts': results,
                          'message': 'Customer processed. Existing non-empty ERP fields were preserved.'}
            return self._json(result, 201 if action == 'created' else 200)
        except (ValidationError, ContactMatchError) as exc:
            return self._json({'success': False, 'error': 'duplicate_exact_match', 'message': str(exc)}, 409)
        except Exception:
            _logger.exception('CRM/PMS customer API processing failed')
            return self._json({'success': False, 'error': 'processing_error',
                               'message': 'Customer processing failed. Check ERP server logs.'}, 500)
