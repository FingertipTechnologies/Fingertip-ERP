import ast
from datetime import date

from freezegun import freeze_time
from lxml import etree
from psycopg2 import IntegrityError

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestSalesForecast(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Forecast = cls.env['ft.sales.forecast']
        cls.partner = cls.env['res.partner'].create({'name': 'Forecast Customer'})
        # Isolated from whatever forecasts the database already holds
        cls.marker = 'test-forecast-marker'

    def _create(self, *dates):
        return self.Forecast.create([{
            'partner_id': self.partner.id,
            'date': day,
            'amount': 100,
            'description': self.marker,
        } for day in dates])

    def _filter_domain(self, name):
        arch = etree.fromstring(self.env.ref('ft_sales_forecast.ft_sales_forecast_view_search').arch)
        # literal_eval fails on anything but the flat literal the web client accepts
        return ast.literal_eval(arch.xpath(f"//filter[@name='{name}']")[0].get('domain'))

    def _matching(self, name):
        forecasts = self.Forecast.search(
            self._filter_domain(name) + [('description', '=', self.marker)])
        return sorted(forecasts.mapped('date'))

    @freeze_time('2026-11-06')
    def test_month_filters_use_whole_months(self):
        self._create('2026-10-31', '2026-11-01', '2026-11-30', '2026-12-01', '2026-12-31',
                     '2027-01-01', '2027-01-31', '2027-02-01', '2027-04-30', '2027-05-01')
        self.assertEqual(self._matching('filter_this_month'),
                         [date(2026, 11, 1), date(2026, 11, 30)])
        self.assertEqual(self._matching('filter_next_month'),
                         [date(2026, 12, 1), date(2026, 12, 31)])
        next_3 = self._matching('filter_next_3_months')
        self.assertEqual((next_3[0], next_3[-1]), (date(2026, 11, 1), date(2027, 1, 31)))
        next_6 = self._matching('filter_next_6_months')
        self.assertEqual((next_6[0], next_6[-1]), (date(2026, 11, 1), date(2027, 4, 30)))

    def test_financial_year_runs_april_to_march(self):
        self._create('2026-03-31', '2026-04-01', '2027-03-31', '2027-04-01')
        expected = [date(2026, 4, 1), date(2027, 3, 31)]
        for today in ('2026-04-01', '2026-11-06', '2027-01-15', '2027-03-31'):
            with self.subTest(today=today), freeze_time(today):
                self.assertEqual(self._matching('filter_financial_year'), expected)

    @freeze_time('2026-11-06')
    def test_past_excludes_today(self):
        self._create('2026-11-05', '2026-11-06')
        self.assertEqual(self._matching('filter_past'), [date(2026, 11, 5)])

    def test_amount_uses_company_currency(self):
        forecast = self._create('2026-11-06')
        self.assertEqual(forecast.currency_id, self.env.company.currency_id)

    def test_amount_must_be_positive(self):
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.Forecast.create({'partner_id': self.partner.id, 'date': '2026-11-06', 'amount': 0})

    def test_only_sales_users_have_access(self):
        forecast = self._create('2026-11-06')
        salesman = new_test_user(self.env, 'forecast_salesman', groups='sales_team.group_sale_salesman')
        forecast.with_user(salesman).write({'amount': 250})
        self.assertEqual(forecast.amount, 250)

        internal = new_test_user(self.env, 'forecast_internal', groups='base.group_user')
        with self.assertRaises(AccessError):
            forecast.with_user(internal).read(['amount'])
