from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'
    crm_erp_receiver_token = fields.Char(string='CRM/PMS API Bearer Token',
                                         config_parameter='crm_erp_api_receiver.bearer_token',
                                         groups='base.group_system')
    crm_pms_api_url = fields.Char(string='CRM/PMS Customer Code API URL',
                                  config_parameter='crm_erp_api_receiver.crm_api_url',
                                  help='Example: http://127.0.0.1:8019/api/v1/erp/customer-code/sync')
    crm_pms_api_token = fields.Char(string='CRM/PMS Receiver Bearer Token',
                                    config_parameter='crm_erp_api_receiver.crm_api_token',
                                    groups='base.group_system')
