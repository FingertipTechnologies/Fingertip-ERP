from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestGreythrHistory(TransactionCase):
    """greytHR's salary statement held as a payslip, to the rupee."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'History Test', 'country_id': cls.env.ref('base.in').id,
            'currency_id': cls.env.ref('base.INR').id,
        })
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=[cls.company.id],
            tracking_disable=True, mail_create_nosubscribe=True, mail_create_nolog=True))
        cls.employee = cls.env['hr.employee'].create({
            'name': 'History Employee', 'company_id': cls.company.id,
            'date_version': '2016-03-01', 'contract_date_start': '2016-03-01', 'wage': 153784,
            'ft_non_taxable_allowance': 20000,
        })
        cls.structure = cls.env.ref('ft_greythr_migration.greythr_history_structure')

    def _slip(self, **amounts):
        types = {t.code: t for t in self.env['hr.payslip.input.type'].search([('code', '=like', 'HIST_%')])}
        slip = self.env['hr.payslip'].create({
            'name': 'Apr 2026', 'employee_id': self.employee.id, 'struct_id': self.structure.id,
            'date_from': '2026-04-01', 'date_to': '2026-04-30',
            'input_line_ids': [Command.create({'input_type_id': types[code].id, 'amount': amount})
                               for code, amount in amounts.items()],
        })
        slip.compute_sheet()
        return slip

    def test_statement_row_to_the_rupee(self):
        # Shebin Mathew, April 2026, from greytHR's salary statement.
        slip = self._slip(HIST_DAYS=30, HIST_EFFECTIVE=30, HIST_BASIC=76892, HIST_HRA=30757,
                          HIST_SPL=37735, HIST_EDU=1200, HIST_MEAL=2200, HIST_LTA=5000,
                          HIST_NTA=20000, HIST_PF=1800, HIST_PT=200, HIST_TDS=13354)
        lines = {l.code: l.total for l in slip.line_ids}
        self.assertEqual(lines['GROSS'], 153784)       # NTA is outside gross
        self.assertEqual(lines['NTA'], 20000)
        self.assertEqual(lines['TDS'], -13354)
        self.assertEqual(lines['NET'], 158430)
        self.assertNotIn('ESICS', lines)
        self.assertEqual(slip.ft_non_taxable_allowance, 0)   # not today's 20,000 again
        self.assertEqual(slip._greythr_days(), (30, 30, 0))

    def test_validates_without_accounting_or_journal_warning(self):
        slip = self._slip(HIST_DAYS=30, HIST_LOP=2, HIST_EFFECTIVE=28, HIST_BASIC=10000,
                          HIST_BONUS=5000, HIST_OTHER=1000)
        self.assertFalse(slip.struct_id.journal_id)
        self.assertFalse([i for i in (slip.issues or {}).values()
                          if (i.get('action') or {}).get('res_model') == 'hr.payroll.structure'])
        slip.action_payslip_done()
        self.assertEqual(slip.state, 'validated')
        self.assertFalse(slip.move_id)
        lines = {l.code: l.total for l in slip.line_ids}
        self.assertEqual(lines['GROSS'], 15000)
        self.assertEqual(lines['NET'], 14000)
        data = slip._ft_report_values()
        self.assertEqual((data['days_in_month'], data['effective_days'], data['lop']), (30, 28, 2))
        self.assertEqual({row['name']: row['master'] for row in data['earnings']}['BASIC'], 10000)
