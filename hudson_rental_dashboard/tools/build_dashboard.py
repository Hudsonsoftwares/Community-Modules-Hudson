# -*- coding: utf-8 -*-
""" Build data/files/rental_dashboard.json of hudson_rental_dashboard from the Sales dashboard of Odoo.

    python tools/build_dashboard.py <odoo addons path>

The Sales dashboard of spreadsheet_dashboard_sale is restricted to the rental lines (is_rental of sale.report) and
reduced to the figures of the Rental dashboard: quotations, rentals and revenue, the daily rentals, and the top
categories, products, salespeople and customers. Run it again after an upgrade of Odoo changes that dashboard.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'hudson_spreadsheet_dashboard', 'tools'))

from dashboard_builder import (  # noqa: E402
    drop_filters, keep_sheets, load_dashboard, odoo_file, relayout, replace_text, restrict_data, write_dashboard,
)

TARGET = os.path.join(os.path.dirname(HERE), 'data', 'files', 'rental_dashboard.json')

RENTAL_LEAF = ['is_rental', '=', True]

# Data sheets of the carousels kept, by sheet name
KEPT_SHEETS = {'Dashboard', 'Data', 'Top Products', 'Top Customers', 'Top Categories', 'Top Salespeople'}
# Filters on what the rental dashboard no longer shows
DROPPED_FILTERS = {'Country', 'Sales Team', 'Source', 'Medium'}

# Figure title -> (new title, x, y, width), laid out like the Rental dashboard of Odoo
LAYOUT = {
    'Quotations': ('Quotations', 0, 9, 214),
    'Orders': ('Rentals', 224, 9, 214),
    'Revenue': ('Revenue', 448, 9, 214),
    'Monthly Sales': ('Daily Rentals', 0, 120, 1000),
    'Top Categories': ('Top Categories', 0, 547, 495),
    'Top Products': ('Top Products', 505, 547, 495),
    'Top Salesperson': ('Top Salespeople', 0, 974, 495),
    'Top Customers': ('Top Customers', 505, 974, 495),
}


def build(source):
    data = load_dashboard(source)
    keep_sheets(data, KEPT_SHEETS)
    drop_filters(data, DROPPED_FILTERS, default_period='last_30_days')
    restrict_data(data, RENTAL_LEAF)

    # Count the orders, not the report lines (one per product of an order)
    for pivot in data['pivots'].values():
        for measure in pivot['measures']:
            if measure['id'] == '__count:sum':
                measure.clear()
                measure.update(id='order_reference', fieldName='order_reference')

    figures = relayout(data['sheets'][0], LAYOUT)
    for chart in figures['Daily Rentals']['data']['chartDefinitions'].values():
        chart['dataSource']['metaData'].update(groupBy=['date:day'], measure='order_reference')
        chart['humanize'] = False
        chart['axesDesign'] = {'y': {'title': {'text': 'Rentals'}}}

    return replace_text(data, {
        '"__count:sum"': '"order_reference"',
        '_t("Orders")': '_t("Rentals")',
        '_t("Total orders")': '_t("Total rentals")',
    })


def main():
    addons = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('ODOO_ADDONS', '')
    source = odoo_file(addons, 'spreadsheet_dashboard_sale', 'data', 'files', 'sales_dashboard.json')
    write_dashboard(build(source), TARGET)


if __name__ == '__main__':
    main()
