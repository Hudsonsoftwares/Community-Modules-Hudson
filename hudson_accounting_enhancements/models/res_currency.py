import logging
import urllib.request
from xml.etree import ElementTree
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# ECB provides daily rates relative to EUR
ECB_URL = 'https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml'
ECB_NS = {
    'gesmes': 'http://www.gesmes.org/xml/2002-08-01',
    'ecb': 'http://www.ecb.int/vocabulary/2002-08-31/eurofxref',
}


class ResCurrency(models.Model):
    _inherit = 'res.currency'

    @api.model
    def _fetch_ecb_rates_data(self):
        """
        Fetch ECB XML feed and return a dict {currency_code: rate_vs_eur}.
        ECB gives: 1 EUR = rate[currency_code]
        """
        try:
            with urllib.request.urlopen(ECB_URL, timeout=15) as response:
                xml_data = response.read()
        except Exception as e:
            raise UserError(
                _('Failed to connect to ECB server: %s\n'
                  'Please check your internet connection.') % str(e)
            )

        try:
            root = ElementTree.fromstring(xml_data)
        except ElementTree.ParseError as e:
            raise UserError(_('Failed to parse ECB XML response: %s') % str(e))

        # ECB XML structure: Envelope > Cube > Cube[@time] > Cube[@currency @rate]
        cube_time = root.find('.//ecb:Cube[@time]', ECB_NS)
        if cube_time is None:
            raise UserError(_('Could not find rate data in ECB XML feed.'))

        ecb_rates = {'EUR': 1.0}  # EUR is the base
        for cube in cube_time.findall('ecb:Cube', ECB_NS):
            currency_code = cube.get('currency')
            rate_str = cube.get('rate')
            if currency_code and rate_str:
                try:
                    ecb_rates[currency_code] = float(rate_str)
                except (ValueError, TypeError):
                    _logger.warning('Invalid rate for %s: %s', currency_code, rate_str)

        return ecb_rates

    @api.model
    def _update_currency_rates(self, company=None):
        """
        Fetch ECB rates and update res.currency.rate for active currencies.

        Odoo rate convention (v16+):
          res.currency.rate.rate = amount of this currency per 1 company currency
          i.e. if company_currency = USD and EUR rate = 0.93, then 1 USD = 0.93 EUR

        ECB gives: 1 EUR = ecb_rate[foreign]
        Conversion formula:
          company_rate_vs_eur = ecb_rate[company_currency]  (or 1.0 if company_currency = EUR)
          odoo_rate[foreign] = ecb_rate[foreign] / company_rate_vs_eur
          (= amount of foreign currency per 1 company_currency)
        """
        company = company or self.env.company
        ecb_rates = self._fetch_ecb_rates_data()

        company_currency = company.currency_id
        company_currency_code = company_currency.name

        # Rate of company currency vs EUR
        if company_currency_code == 'EUR':
            company_vs_eur = 1.0
        elif company_currency_code in ecb_rates:
            company_vs_eur = ecb_rates[company_currency_code]
        else:
            raise UserError(
                _('Your company currency (%s) is not available in the ECB feed. '
                  'ECB provides EUR-based rates. Please set your base currency to EUR '
                  'or a currency listed by ECB.') % company_currency_code
            )

        today = fields.Date.today()
        active_currencies = self.search([('active', '=', True)])
        CurrencyRate = self.env['res.currency.rate']
        updated_count = 0
        skipped = []

        for currency in active_currencies:
            if currency.name == company_currency_code:
                continue  # skip company's own currency

            if currency.name not in ecb_rates:
                skipped.append(currency.name)
                continue

            # 1 EUR = ecb_rates[currency.name] units of foreign
            # 1 company_currency = company_vs_eur units of EUR
            #                    = company_vs_eur * ecb_rates[foreign] units of foreign
            # → odoo_rate = ecb_rates[foreign] / company_vs_eur
            odoo_rate = ecb_rates[currency.name] / company_vs_eur

            # Find or create today's rate record
            existing = CurrencyRate.search([
                ('currency_id', '=', currency.id),
                ('name', '=', today),
                ('company_id', '=', company.id),
            ], limit=1)

            rate_vals = {
                'currency_id': currency.id,
                'name': today,
                'rate': odoo_rate,
                'company_id': company.id,
            }

            if existing:
                existing.write({'rate': odoo_rate})
            else:
                CurrencyRate.create(rate_vals)

            updated_count += 1

        if skipped:
            _logger.info(
                'ECB rate update: skipped currencies not in ECB feed: %s',
                ', '.join(skipped)
            )
        _logger.info(
            'ECB rate update complete: %d currencies updated for %s',
            updated_count, today
        )
        return updated_count

    def action_fetch_ecb_rates(self):
        """Button action: manually fetch ECB rates for current company."""
        updated = self._update_currency_rates()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Currency Rates Updated'),
                'message': _(
                    '%d currency rates have been successfully fetched '
                    'from the European Central Bank (ECB) for today.'
                ) % updated,
                'type': 'success',
                'sticky': False,
            },
        }
