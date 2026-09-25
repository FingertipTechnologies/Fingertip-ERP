# -*- coding: utf-8 -*-
"""A first-class IFSC field for the bank accounts salaries are paid into.

Odoo ships no IFSC field: ``res.bank.bic`` is the BIC/SWIFT code, and Indian
databases habitually overload it with the IFSC because there is nowhere else
to put it. That overloading is lossy -- a bank holding both a real SWIFT code
and an IFSC can only keep one -- so the IFSC gets its own field here, and the
payslip prints it beside the employee's bank account number.
"""
import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# RBI format: four alphabetic bank code, '0' reserved, six alphanumeric branch.
IFSC_PATTERN = re.compile(r'^[A-Z]{4}0[A-Z0-9]{6}$')


class ResBank(models.Model):
    _inherit = 'res.bank'

    ifsc_code = fields.Char(
        string="IFSC Code", index=True,
        help="Indian Financial System Code: the 11-character RBI code that "
             "identifies this bank branch, for example HDFC0001208.")

    @api.constrains('ifsc_code')
    def _check_ifsc_code(self):
        """Validate shape only when a code is present, so banks outside India
        are unaffected and the field stays optional."""
        for bank in self:
            if bank.ifsc_code and not IFSC_PATTERN.match(bank.ifsc_code):
                raise ValidationError(_(
                    "%(code)s is not a valid IFSC code. An IFSC is 11 "
                    "characters: four letters, then 0, then six letters or "
                    "digits -- for example HDFC0001208.",
                    code=bank.ifsc_code))

    @api.model_create_multi
    def create(self, vals_list):
        # Mirror what base does for bic: codes are canonically upper case.
        for vals in vals_list:
            if vals.get('ifsc_code'):
                vals['ifsc_code'] = vals['ifsc_code'].strip().upper()
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('ifsc_code'):
            vals['ifsc_code'] = vals['ifsc_code'].strip().upper()
        return super().write(vals)


class ResPartnerBank(models.Model):
    _inherit = 'res.partner.bank'

    # Same related-field pattern base uses for bank_bic, so payroll staff can
    # set the IFSC on the employee's salary account without opening the bank.
    bank_ifsc = fields.Char(
        related='bank_id.ifsc_code', readonly=False, string="IFSC Code")
