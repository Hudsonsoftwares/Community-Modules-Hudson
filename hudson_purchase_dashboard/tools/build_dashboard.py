# -*- coding: utf-8 -*-
""" Build data/files/purchase_dashboard.json from the Purchase dashboard of Odoo Online.

Download the dashboard shared from an Odoo Online database (https://<db>.odoo.com/dashboard/share/<id>/<token>) at
https://<db>.odoo.com/dashboard/data/<id>/<token>, then run:

    python build_dashboard.py <downloaded json>

Its layout and styles are kept; its frozen data is replaced by the pivots, lists and Odoo charts below. The on-time
deliveries and late receipts of Odoo Enterprise come from purchase.receipt.report.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'hudson_spreadsheet_dashboard', 'tools'))
from dashboard_builder import (  # noqa: E402
    add_list, add_pivot, carousel, figures_at, load_snapshot, odoo_chart, set_cells, sheet, write_dashboard,
)

TARGET = os.path.join(os.path.dirname(__file__), '..', 'data', 'files', 'purchase_dashboard.json')

REPORT = {
    'Order date': ('date_approve', 'datetime'),
    'Vendor': ('partner_id', 'many2one'),
    'Buyer': ('user_id', 'many2one'),
    'Product': ('product_id', 'many2one'),
    'Product Category': ('category_id', 'many2one'),
}
ORDER = {
    'Order date': ('date_approve', 'datetime'),
    'Vendor': ('partner_id', 'many2one'),
    'Buyer': ('user_id', 'many2one'),
    'Product': ('order_line.product_id', 'many2one'),
    'Product Category': ('order_line.product_id.categ_id', 'many2one'),
}
RECEIPT = {
    'Order date': ('date_done', 'datetime'),
    'Vendor': ('partner_id', 'many2one'),
    'Buyer': ('user_id', 'many2one'),
}
CONFIRMED = [('state', '=', 'purchase')]
GOODS = CONFIRMED + [('product_id.type', '=', 'consu')]
ACTION = 'purchase.action_purchase_order_report_all'


def build(data):
    kpis = ['__count', 'order_id:count_distinct', 'price_total', 'qty_ordered', 'qty_received', 'delay', 'delay_pass',
            'days_to_arrival']
    add_pivot(data, 1, 'purchase.report', 'KPIs - current', kpis, REPORT, domain=CONFIRMED)
    add_pivot(data, 2, 'purchase.report', 'KPIs - previous', kpis, REPORT, domain=CONFIRMED, offset=-1)
    add_pivot(data, 3, 'purchase.report', 'Receptions - current', ['qty_ordered', 'qty_received'], REPORT, domain=GOODS)
    add_pivot(data, 4, 'purchase.report', 'Receptions - previous', ['qty_ordered', 'qty_received'], REPORT,
              domain=GOODS, offset=-1)
    add_pivot(data, 5, 'purchase.receipt.report', 'On time - current', ['on_time_rate', 'delay'], RECEIPT,
              rows=['partner_id'], sort='on_time_rate')
    add_pivot(data, 6, 'purchase.receipt.report', 'On time - previous', ['on_time_rate'], RECEIPT, offset=-1)
    add_pivot(data, 7, 'purchase.report', 'Vendors by value', ['order_id:count_distinct', 'price_total'], REPORT,
              rows=['partner_id'], domain=CONFIRMED, sort='price_total')
    add_pivot(data, 8, 'purchase.report', 'Vendors by lead time', ['days_to_arrival'], REPORT,
              rows=['partner_id'], domain=CONFIRMED, sort='days_to_arrival')
    add_pivot(data, 9, 'purchase.report', 'Product', [
        '__count|Count', 'price_total|Total', 'qty_ordered|Qty Ordered', 'price_average|Average Cost',
        'delay_pass|Days to Receive',
    ], REPORT, rows=['product_id'], domain=CONFIRMED, sort='price_total')
    add_list(data, 1, 'purchase.order', 'Top Purchase Orders', [
        ('name', 'Order Reference'), ('partner_id', 'Vendor'), ('user_id', 'Buyer'), ('date_approve', 'Order Date'),
        ('amount_total', 'Total'),
    ], ORDER, domain=CONFIRMED, order='amount_total', action='purchase.purchase_form_action')
    add_list(data, 2, 'purchase.receipt.report', 'Late Receipts', [('name', 'Picking Name'), ('delay', 'Delay (Days)')],
             RECEIPT, domain=[('delay', '>', 0)], order='delay')

    cells = {
        'A1': 'Order date Filter', 'B1': '=ODOO.FILTER.VALUE("Order date")',
        'B2': 'Count', 'C2': 'Order', 'D2': 'Total', 'E2': 'Qty Ordered', 'F2': 'Qty Received',
        'G2': 'Days to Confirm', 'H2': 'Days to Receive', 'I2': 'Average order', 'J2': 'Fill rate',
        'A3': 'Previous period', 'A4': 'Selected period',
        'A8': 'Orders with reception picking', 'B9': 'Qty Ordered', 'C9': 'Qty Received', 'D9': 'Fill rate',
        'A10': 'Previous period', 'A11': 'Selected period',
        'B10': '=IF($B$1<>"",PIVOT.VALUE(4,"qty_ordered"),"N/A")',
        'C10': '=IF($B$1<>"",PIVOT.VALUE(4,"qty_received"),"N/A")',
        'D10': '=IFERROR(C10/B10,"N/A")',
        'B11': '=PIVOT.VALUE(3,"qty_ordered")', 'C11': '=PIVOT.VALUE(3,"qty_received")',
        'D11': '=IFERROR(C11/B11,"N/A")',
        'B14': 'On time deliveries', 'B15': 'Selected period', 'C15': 'Previous period',
        'B16': 'On-Time Delivery Rate', 'C16': 'On-Time Delivery Rate', 'A17': 'Total',
        'B17': '=IFERROR(PIVOT.VALUE(5,"on_time_rate")/100,"N/A")',
        'C17': '=IF($B$1<>"",IFERROR(PIVOT.VALUE(6,"on_time_rate")/100,"N/A"),"N/A")',
        'H14': 'Total', 'H15': 'Delay (Days)', 'H17': '=IFERROR(PIVOT.VALUE(5,"delay"),"")',
        'A34': 'Orders value by vendor', 'B35': 'Orders count', 'C35': 'Total value',
        'A54': 'Lead time top 10', 'B55': 'Lead time', 'C55': 'Global value',
    }
    for col, spec in zip('BCDEF', ['__count', 'order_id:count_distinct', 'price_total', 'qty_ordered', 'qty_received']):
        cells['%s3' % col] = '=IF($B$1<>"",PIVOT.VALUE(2,"%s"),"N/A")' % spec
        cells['%s4' % col] = '=PIVOT.VALUE(1,"%s")' % spec
    for col, spec in (('G', 'delay'), ('H', 'delay_pass')):
        cells['%s3' % col] = '=IF($B$1<>"",IFERROR(ROUND(PIVOT.VALUE(2,"%s"),0)&" days","N/A"),"N/A")' % spec
        cells['%s4' % col] = '=IFERROR(ROUND(PIVOT.VALUE(1,"%s"),0)&" days","N/A")' % spec
    cells.update({
        'I3': '=IF($B$1<>"",IFERROR(D3/C3,"N/A"),"N/A")', 'I4': '=IFERROR(D4/C4,"N/A")',
        'J3': '=IF($B$1<>"",IFERROR(F3/E3,"N/A"),"N/A")', 'J4': '=IFERROR(F4/E4,"N/A")',
    })
    for i in range(1, 11):
        rate, value, lead = 17 + i, 35 + i, 55 + i
        cells['A%d' % rate] = '=IFERROR(PIVOT.HEADER(5,"#partner_id",%d),"")' % i
        cells['B%d' % rate] = '=IFERROR(PIVOT.VALUE(5,"on_time_rate","#partner_id",%d),"")' % i
        cells['A%d' % value] = '=IFERROR(PIVOT.HEADER(7,"#partner_id",%d),"")' % i
        cells['B%d' % value] = '=IFERROR(PIVOT.VALUE(7,"order_id:count_distinct","#partner_id",%d),"")' % i
        cells['C%d' % value] = '=IFERROR(PIVOT.VALUE(7,"price_total","#partner_id",%d),"")' % i
        cells['A%d' % lead] = '=IFERROR(PIVOT.HEADER(8,"#partner_id",%d),"")' % i
        cells['B%d' % lead] = '=IFERROR(PIVOT.VALUE(8,"days_to_arrival","#partner_id",%d),"")' % i
        cells['C%d' % lead] = '=IF(A%d<>"",PIVOT.VALUE(1,"days_to_arrival"),"")' % lead
    set_cells(data, 'KPIs', cells)
    sheet(data, 'KPIs')['formats']['B17:C17'] = 3  # 0.00%
    set_cells(data, 'Top Purchase Orders by Value', {'A1': '=ODOO.LIST(1,50)'})
    set_cells(data, 'Top Late Receipts', {'A1': '=ODOO.LIST(2,50)'})
    set_cells(data, 'Top Purchased Products', {'A1': '=PIVOT(9,50,FALSE,FALSE)'})

    figures = figures_at(data)
    # The pivot of the vendors by lead time is already sorted: chart its rows (Odoo Online sorts a copy of them)
    lead_time = next(iter(figures[(0, 1511)]['data']['chartDefinitions'].values()))['dataSource']
    lead_time.update(labelRange='KPIs!A55:A65', dataSets=[
        {'dataSetId': '0', 'dataRange': 'KPIs!B55:B65'}, {'dataSetId': '1', 'dataRange': 'KPIs!C55:C65'},
    ])
    carousel(data, figures[(0, 245)], 'Purchased Value', [('Graph', odoo_chart(
        'purchase.report', 'line', ['date_approve:day'], 'price_total', CONFIRMED, ACTION, fillArea=True,
        axesDesign={'y': {'title': {'text': 'Purchase Value'}}, 'x': {'title': {'text': 'Confirmation Date'}}},
    ))], REPORT)
    carousel(data, figures[(0, 667)], 'On Time Deliveries', [('Graph', odoo_chart(
        'purchase.receipt.report', 'bar', ['partner_id'], 'on_time_rate', order='DESC',
        axesDesign={'y': {'title': {'text': '% of On Time Deliveries'}}, 'x': {'title': {'text': 'Vendors'}}},
    ))], RECEIPT)
    carousel(data, figures[(0, 1933)], 'Average Cost Evolution', [('Graph', odoo_chart(
        'purchase.report', 'line', ['date_approve:month', 'product_id'], 'price_average', CONFIRMED, ACTION,
        legendPosition='none', axesDesign={'y': {'title': {'text': 'Products Purchased cost'}}},
    ))], REPORT)
    carousel(data, figures[(505, 2777)], 'Purchases by Buyer', [('Graph', odoo_chart(
        'purchase.report', 'pie', ['user_id'], 'price_total', CONFIRMED, ACTION, legendPosition='top',
    ))], REPORT)
    return data


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    write_dashboard(build(load_snapshot(sys.argv[1], menu_modules=('purchase',))), TARGET)
