# -*- coding: utf-8 -*-
"""Income-tax slabs as data, so a Budget change is a new record, not a release.

One slab set holds everything that changes from year to year for one regime:
the slabs, standard deduction, rebate, surcharge bands, cess and the
age-based basic exemptions. The formulas that apply them (rebate marginal
relief, surcharge marginal relief, statutory rounding) stay in code in
``tds_slabs.py``; only a change to *how* tax is worked out needs a release.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

# Fields that decide the tax. Once a validated payslip has been computed with
# a set these are frozen: re-running last year's numbers must give last
# year's answer. Name, notes and active can still change.
LOCKED_FIELDS = {
    'regime', 'date_from', 'date_to', 'company_id', 'employee_only', 'standard_deduction',
    'rebate_income_limit', 'rebate_max', 'rebate_marginal_relief',
    'rebate_residents_only', 'cess_rate', 'line_ids', 'surcharge_ids',
    'age_exemption_ids',
}


class FtpTdsSlabSet(models.Model):
    _name = 'ftp.tds.slab.set'
    _description = 'TDS Slab Set'
    _inherit = ['mail.thread']
    _order = 'date_from desc, regime, company_id'

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    regime = fields.Selection(
        [('new', 'New Regime'), ('old', 'Old Regime')],
        string='Tax Regime', required=True, default='new', tracking=True)
    date_from = fields.Date(string='Valid From', required=True, tracking=True,
        help="Usually 1 April, the start of the financial year.")
    date_to = fields.Date(string='Valid To', required=True, tracking=True,
        help="Usually 31 March, the end of the financial year.")
    company_id = fields.Many2one('res.company', string='Company', tracking=True,
        help="Leave empty to use this set for every company. A company-specific "
             "set takes priority over a shared one for the same dates.")
    employee_only = fields.Boolean(string='Only for Assigned Employees', tracking=True,
        help="Never picked automatically: it applies only to employees who have it as their "
             "Override TDS Slab Set. Use it for exceptions; it may overlap the normal set.")
    currency_id = fields.Many2one('res.currency', required=True,
        default=lambda self: self.env.ref('base.INR'))

    standard_deduction = fields.Monetary(tracking=True,
        help="Standard deduction on salary income, before approved deductions.")
    rebate_income_limit = fields.Monetary(string='Rebate Income Limit', tracking=True,
        help="Taxable income up to which the rebate (section 87A) applies.")
    rebate_max = fields.Monetary(string='Maximum Rebate', tracking=True)
    rebate_marginal_relief = fields.Boolean(string='Rebate Marginal Relief', tracking=True,
        help="Just above the rebate limit, cap the tax at the income above the limit "
             "(new regime from FY 2023-24).")
    rebate_residents_only = fields.Boolean(string='Rebate for Residents Only',
        default=True, tracking=True)
    cess_rate = fields.Float(string='Cess (%)', default=4.0, tracking=True,
        help="Health and education cess, on tax plus surcharge.")

    line_ids = fields.One2many('ftp.tds.slab.line', 'slab_set_id', string='Slabs', copy=True)
    surcharge_ids = fields.One2many('ftp.tds.surcharge.line', 'slab_set_id',
        string='Surcharge Bands', copy=True)
    age_exemption_ids = fields.One2many('ftp.tds.age.exemption', 'slab_set_id',
        string='Age Exemptions', copy=True,
        help="Raises the 0% slab for older employees (old regime: 60+ and 80+).")
    note = fields.Html()
    is_locked = fields.Boolean(compute='_compute_is_locked',
        help="Validated payslips were computed with this set, so its rates can no longer change.")

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------
    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for slab_set in self:
            if slab_set.date_from > slab_set.date_to:
                raise ValidationError(_('"%s": Valid From must be before Valid To.', slab_set.name))

    @api.constrains('active', 'regime', 'date_from', 'date_to', 'company_id', 'employee_only')
    def _check_overlap(self):
        for slab_set in self.filtered(lambda s: s.active and not s.employee_only):
            clash = self.search([
                ('id', '!=', slab_set.id),
                ('employee_only', '=', False),
                ('regime', '=', slab_set.regime),
                ('company_id', '=', slab_set.company_id.id),
                ('date_from', '<=', slab_set.date_to),
                ('date_to', '>=', slab_set.date_from),
            ], limit=1)
            if clash:
                raise ValidationError(_(
                    '"%(this)s" overlaps "%(other)s" for the same regime and company. '
                    'Archive one of them, or change the dates.',
                    this=slab_set.name, other=clash.name))

    @api.constrains('cess_rate', 'standard_deduction', 'rebate_income_limit', 'rebate_max')
    def _check_amounts(self):
        for slab_set in self:
            if min(slab_set.cess_rate, slab_set.standard_deduction,
                   slab_set.rebate_income_limit, slab_set.rebate_max) < 0:
                raise ValidationError(_('"%s": amounts and rates cannot be negative.', slab_set.name))

    @api.constrains('regime', 'line_ids', 'surcharge_ids', 'age_exemption_ids')
    def _check_lines(self):
        for slab_set in self:
            slab_set._ftp_check_slab_lines()

    def _ftp_check_slab_lines(self):
        """Slabs must start at 0, run without gaps or overlaps, and end open."""
        self.ensure_one()
        lines = self.line_ids.sorted('amount_from')
        if not lines:
            raise ValidationError(_('"%s" needs at least one slab.', self.name))
        expected_from = 0.0
        for line in lines:
            if self.currency_id.compare_amounts(line.amount_from, expected_from):
                raise ValidationError(_(
                    '"%(set)s": the slab starting at %(start)s should start at %(expected)s. '
                    'Slabs must start at 0 and follow on without gaps or overlaps.',
                    set=self.name, start=line.amount_from, expected=expected_from))
            if line != lines[-1]:
                if line.amount_to <= line.amount_from:
                    raise ValidationError(_(
                        '"%(set)s": the slab starting at %(start)s needs an upper limit above it. '
                        'Only the last slab may be left open.', set=self.name, start=line.amount_from))
                expected_from = line.amount_to
        if lines[-1].amount_to:
            raise ValidationError(_(
                '"%s": leave the upper limit of the last slab empty so every income is covered.',
                self.name))
        thresholds = self.surcharge_ids.mapped('income_above')
        if len(thresholds) != len(set(thresholds)):
            raise ValidationError(_('"%s": two surcharge bands start at the same income.', self.name))
        ages = self.age_exemption_ids.mapped('min_age')
        if len(ages) != len(set(ages)):
            raise ValidationError(_('"%s": two age exemptions use the same age.', self.name))

    # ------------------------------------------------------------------
    # Locking once payroll has been finalised under a set
    # ------------------------------------------------------------------
    def _ftp_finalised_payslip_count(self):
        """Validated or paid payslips whose TDS this set worked out."""
        return self.env['hr.payslip'].sudo().search_count([
            ('ftp_tds_slab_set_id', 'in', self.ids),
            ('state', 'in', ('validated', 'paid')),
        ], limit=1)

    def _compute_is_locked(self):
        for slab_set in self:
            slab_set.is_locked = bool(slab_set._origin.id and slab_set._origin._ftp_finalised_payslip_count())

    def _ftp_check_editable(self):
        for slab_set in self:
            if slab_set._ftp_finalised_payslip_count():
                raise UserError(_(
                    '"%s" has already been used for validated payslips, so its rates cannot change. '
                    'Duplicate it, adjust the copy, archive this one and activate the copy.',
                    slab_set.name))

    def write(self, vals):
        if LOCKED_FIELDS.intersection(vals):
            self._ftp_check_editable()
        return super().write(vals)

    def unlink(self):
        self._ftp_check_editable()
        return super().unlink()

    def copy_data(self, default=None):
        # The copy would overlap the original, so it starts archived.
        default = dict(default or {})
        vals_list = super().copy_data(default)
        for slab_set, vals in zip(self, vals_list):
            if 'name' not in default:
                vals['name'] = _('%s (copy)', slab_set.name)
            if 'active' not in default:
                vals['active'] = False
        return vals_list

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------
    @api.model
    def _ftp_find(self, on_date, regime, company=None):
        """The active set for this regime on this date; company-specific first."""
        candidates = self.sudo().search([
            ('regime', '=', regime),
            ('date_from', '<=', on_date),
            ('date_to', '>=', on_date),
            ('employee_only', '=', False),
            ('company_id', 'in', [company.id, False] if company else [False]),
        ])
        return candidates.sorted(lambda s: not s.company_id)[:1]

    @api.model
    def _ftp_get(self, on_date, regime, company=None):
        slab_set = self._ftp_find(on_date, regime, company)
        if not slab_set:
            raise ValidationError(_(
                'No active TDS slab set covers %(date)s for the %(regime)s. '
                'Create one under Payroll → Configuration → Salary → TDS Slab Sets, '
                'or switch the employee to manual TDS.',
                date=on_date, regime=dict(self._fields['regime'].selection)[regime]))
        return slab_set

    def _ftp_brackets(self, resident=True, age=0):
        """[(upper, rate)] ready for the slab arithmetic; rates as fractions.

        An age exemption stretches the 0% slab; any band it swallows simply
        ends up empty, exactly as the hard-coded tables used to behave.
        """
        self.ensure_one()
        brackets = [(line.amount_to or float('inf'), line.rate / 100)
                    for line in self.line_ids.sorted('amount_from')]
        exemption = self.age_exemption_ids.filtered(
            lambda e: age >= e.min_age and (resident or not e.residents_only)
        ).sorted('min_age')[-1:]
        if exemption and brackets[0][1] == 0:
            brackets[0] = (exemption.zero_rate_upto, 0.0)
        return brackets

    def _ftp_surcharge_bands(self):
        """[(income above, rate as a fraction)], lowest band first."""
        self.ensure_one()
        return [(band.income_above, band.rate / 100)
                for band in self.surcharge_ids.sorted('income_above')]


class FtpTdsSlabLine(models.Model):
    _name = 'ftp.tds.slab.line'
    _description = 'TDS Slab'
    _order = 'slab_set_id, amount_from'

    slab_set_id = fields.Many2one('ftp.tds.slab.set', required=True, ondelete='cascade', index=True)
    currency_id = fields.Many2one(related='slab_set_id.currency_id')
    amount_from = fields.Monetary(string='Income From', required=True)
    amount_to = fields.Monetary(string='Income Up To',
        help="Leave empty on the last slab: no upper limit.")
    rate = fields.Float(string='Rate (%)', required=True)

    _check_rate = models.Constraint('CHECK(rate >= 0 AND rate <= 100)',
                                    'A slab rate must be between 0% and 100%.')

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines.slab_set_id._ftp_check_editable()
        return lines

    def write(self, vals):
        self.slab_set_id._ftp_check_editable()
        return super().write(vals)

    def unlink(self):
        self.slab_set_id._ftp_check_editable()
        return super().unlink()


class FtpTdsSurchargeLine(models.Model):
    _name = 'ftp.tds.surcharge.line'
    _description = 'TDS Surcharge Band'
    _order = 'slab_set_id, income_above'

    slab_set_id = fields.Many2one('ftp.tds.slab.set', required=True, ondelete='cascade', index=True)
    currency_id = fields.Many2one(related='slab_set_id.currency_id')
    income_above = fields.Monetary(string='Taxable Income Above', required=True)
    rate = fields.Float(string='Surcharge (%)', required=True,
        help="Charged on the tax after rebate. Marginal relief is applied at each band.")

    _check_rate = models.Constraint('CHECK(rate >= 0 AND rate <= 100)',
                                    'A surcharge rate must be between 0% and 100%.')

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines.slab_set_id._ftp_check_editable()
        return lines

    def write(self, vals):
        self.slab_set_id._ftp_check_editable()
        return super().write(vals)

    def unlink(self):
        self.slab_set_id._ftp_check_editable()
        return super().unlink()


class FtpTdsAgeExemption(models.Model):
    _name = 'ftp.tds.age.exemption'
    _description = 'TDS Age-based Exemption'
    _order = 'slab_set_id, min_age'

    slab_set_id = fields.Many2one('ftp.tds.slab.set', required=True, ondelete='cascade', index=True)
    currency_id = fields.Many2one(related='slab_set_id.currency_id')
    min_age = fields.Integer(string='Age From', required=True,
        help="Age at the end of the financial year.")
    zero_rate_upto = fields.Monetary(string='0% Slab Up To', required=True)
    residents_only = fields.Boolean(default=True)

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines.slab_set_id._ftp_check_editable()
        return lines

    def write(self, vals):
        self.slab_set_id._ftp_check_editable()
        return super().write(vals)

    def unlink(self):
        self.slab_set_id._ftp_check_editable()
        return super().unlink()
