# -*- coding: utf-8 -*-
""" Build data/files/manufacturing_dashboard.json from the Manufacturing dashboard of Odoo Online.

Download the dashboard shared from an Odoo Online database (https://<db>.odoo.com/dashboard/share/<id>/<token>) at
https://<db>.odoo.com/dashboard/data/<id>/<token>, then run:

    python build_dashboard.py <downloaded json>

Its layout and styles are kept; its frozen data is replaced by the pivots and Odoo charts below. The OEE comes from
the work center time logs and the average cost from the value of the finished products moves (instead of the cost
analysis of Odoo Enterprise).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'hudson_spreadsheet_dashboard', 'tools'))
from dashboard_builder import (  # noqa: E402
    add_pivot, carousel, figures_at, load_snapshot, odoo_chart, set_cells, write_dashboard,
)

TARGET = os.path.join(os.path.dirname(__file__), '..', 'data', 'files', 'manufacturing_dashboard.json')

PRODUCTION = {
    'Period': ('date_start', 'datetime'),
    'Product': ('product_id', 'many2one'),
    'Operation Type': ('picking_type_id', 'many2one'),
    'Responsible': ('user_id', 'many2one'),
}
TIME_LOG = {
    'Period': ('date_start', 'datetime'),
    'Product': ('workorder_id.production_id.product_id', 'many2one'),
    'Operation Type': ('workorder_id.production_id.picking_type_id', 'many2one'),
    'Responsible': ('workorder_id.production_id.user_id', 'many2one'),
}
FINISHED_MOVE = {
    'Period': ('production_id.date_start', 'datetime'),
    'Product': ('product_id', 'many2one'),
    'Operation Type': ('production_id.picking_type_id', 'many2one'),
    'Responsible': ('production_id.user_id', 'many2one'),
}
ACTIVE = [('state', '!=', 'cancel')]
FINISHED = [('production_id', '!=', False), ('state', '=', 'done')]
ACTION = 'mrp.mrp_production_action'


def build(data):
    for offset, pid in ((0, 1), (-1, 2)):
        period = 'current' if offset == 0 else 'previous'
        add_pivot(data, pid, 'mrp.production', 'KPIs - %s' % period, ['__count', 'product_qty'], PRODUCTION,
                  rows=['state'], domain=ACTIVE, offset=offset)
        add_pivot(data, pid + 2, 'mrp.workcenter.productivity', 'Time - %s' % period, ['duration'], TIME_LOG,
                  offset=offset)
        add_pivot(data, pid + 4, 'mrp.workcenter.productivity', 'Productive time - %s' % period, ['duration'],
                  TIME_LOG, domain=[('loss_type', '=', 'productive')], offset=offset)
        add_pivot(data, pid + 6, 'stock.move', 'Cost - %s' % period, ['value', 'quantity'], FINISHED_MOVE,
                  domain=FINISHED, offset=offset)
    for pid, (name, field, label) in enumerate(
            [('Top Products', 'product_id', 'Product'), ('Top Operation Types', 'picking_type_id', 'Operation Type'),
             ('Top Responsibles', 'user_id', 'Responsible')], start=9):
        add_pivot(data, pid, 'mrp.production', label, ['__count|Orders', 'product_qty|Quantity'], PRODUCTION,
                  rows=[field], domain=ACTIVE + [(field, '!=', False)], sort='product_qty')
        set_cells(data, name, {'A1': '=PIVOT(%d,50,FALSE,FALSE)' % pid})

    cells = {
        'A1': 'KPI', 'B1': 'Current', 'C1': 'Previous', 'D1': 'Current', 'E1': 'Previous',
        'A2': 'Manufacturing orders', 'A3': 'Quantity produced', 'A4': 'Total time (min)', 'A5': 'Lost time (min)',
        'A6': 'Productive time (min)', 'A7': 'OEE', 'A8': 'Average cost / unit',
    }
    for col, pid in (('B', 1), ('C', 2)):
        cells.update({
            '%s2' % col: '=PIVOT.VALUE(%d,"__count")' % pid,
            '%s3' % col: '=PIVOT.VALUE(%d,"product_qty","state","done")' % pid,
            '%s4' % col: '=PIVOT.VALUE(%d,"duration")' % (pid + 2),
            '%s5' % col: '=IFERROR(%s4-%s6)' % (col, col),
            '%s6' % col: '=PIVOT.VALUE(%d,"duration")' % (pid + 4),
            '%s7' % col: '=IFERROR(%s6/%s4)' % (col, col),
            '%s8' % col: '=IFERROR(PIVOT.VALUE(%d,"value")/PIVOT.VALUE(%d,"quantity"))' % (pid + 6, pid + 6),
        })
    for target, source in (('D', 'B'), ('E', 'C')):
        for row in (2, 3, 8):
            cells['%s%d' % (target, row)] = '=FORMAT.LARGE.NUMBER(%s%d)' % (source, row)
        cells['%s7' % target] = '=%s7' % source
    set_cells(data, 'Data', cells)

    figures = figures_at(data)
    carousel(data, figures[(0, 124)], 'Manufacturing Orders', [('Graph', odoo_chart(
        'mrp.production', 'line', ['date_start:week'], '__count', ACTIVE, ACTION, fillArea=True,
    ))], PRODUCTION)
    carousel(data, figures[(0, 538)], 'Quantity by Product', [('Graph', odoo_chart(
        'mrp.production', 'bar', ['product_id', 'state'], 'product_qty', ACTIVE, ACTION, order='DESC',
        stacked=True, legendPosition='right',
    ))], PRODUCTION)
    return data


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    write_dashboard(build(load_snapshot(sys.argv[1], menu_modules=('mrp',))), TARGET)
