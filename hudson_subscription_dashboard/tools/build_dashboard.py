# -*- coding: utf-8 -*-
""" Build the files of data/files from the Subscriptions, MRR Evolution, Retention and Salesperson dashboards of Odoo
Online.

Download each dashboard shared from an Odoo Online database (https://<db>.odoo.com/dashboard/share/<id>/<token>) at
https://<db>.odoo.com/dashboard/data/<id>/<token>, then run:

    python build_dashboard.py <subscriptions json> <mrr evolution json> <retention json> <salesperson json>

Their layout, styles and formulas are kept; their frozen data is replaced by the pivots, lists and Odoo charts below.
The subscription logs of Odoo Enterprise are replaced by sale.subscription.event.report.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'hudson_spreadsheet_dashboard', 'tools'))
from dashboard_builder import (  # noqa: E402
    add_list, add_pivot, carousel, figures_at, load_snapshot, odoo_chart, set_cells, set_format, sheet,
    write_dashboard,
)

FILES = os.path.join(os.path.dirname(__file__), '..', 'data', 'files')

EVENT = 'sale.subscription.event.report'
LINE = 'sale.subscription.line.report'
ACTIVE = [('subscription_state', 'in', ['3_progress', '4_paused', '5_renew'])]
SUBSCRIPTIONS = [('is_subscription', '=', True), ('is_upsell', '=', False)]
QUOTATIONS = SUBSCRIPTIONS + [('subscription_state', 'in', ['draft', 'sent'])]
POSTED_INVOICES = [('state', '=', 'posted'), ('move_type', 'in', ['out_invoice', 'out_refund'])]
RECURRING = POSTED_INVOICES + [('product_id.recurring_invoice', '=', True)]
NON_RECURRING = POSTED_INVOICES + [('product_id.recurring_invoice', '!=', True)]
# (type of event, count column, MRR column) of the data of the Retention dashboard
EVENT_COLUMNS = [('0_creation', 'D', 'F'), ('15_contraction', 'H', 'J'), ('1_expansion', 'L', 'N'), ('2_churn', 'P', 'R')]
GEO = {'legendPosition': 'left', 'colorScale': {'minColor': '#f7fbff', 'midColor': '#6aaed6', 'maxColor': '#08306b'}}
ACTION = 'hudson_subscriptions.action_subscription_orders'


def top(data, pid, model, label, field, measures, chains, domain, sort):
    """ Pivot of `model` by `field` (headed `label`) for a "Top" sheet, the largest first. """
    return add_pivot(data, pid, model, label, measures, chains, rows=[field],
                     domain=list(domain) + [(field, '!=', False)], sort=sort)


def update_cells(data, name, cells):
    sheet(data, name)['cells'].update(cells)


def build_subscriptions(data):
    line = {
        'Country': ('country_id', 'many2one'), 'Product': ('product_tmpl_id', 'many2one'),
        'Customer': ('partner_id', 'many2one'), 'Sales Team': ('team_id', 'many2one'),
        'Salesperson': ('user_id', 'many2one'), 'Source': ('source_id', 'many2one'),
        'Medium': ('medium_id', 'many2one'),
    }
    order = {
        'Country': ('partner_id.country_id', 'many2one'), 'Product': ('order_line.product_template_id', 'many2one'),
        'Customer': ('partner_id', 'many2one'), 'Sales Team': ('team_id', 'many2one'),
        'Salesperson': ('user_id', 'many2one'), 'Source': ('source_id', 'many2one'),
        'Medium': ('medium_id', 'many2one'),
    }
    event = {key: line[key] for key in ('Country', 'Customer', 'Sales Team', 'Salesperson')}
    mrr = ['order_id:count_distinct|# Subscriptions', 'recurring_monthly|MRR']
    add_pivot(data, 1, LINE, 'Active subscriptions', mrr, line, domain=ACTIVE)
    add_pivot(data, 2, LINE, 'Churned subscriptions', mrr, line, domain=[('subscription_state', '=', '6_churn')])
    add_pivot(data, 3, EVENT, 'MRR changes', ['amount_signed'], event, rows=['event_type'])
    update_cells(data, 'Data', {
        'B2': '=PIVOT.VALUE(3,"amount_signed")',
        'B3': '=PIVOT.VALUE(1,"recurring_monthly")',
        'B4': '=B3*12',
        'B5': '=PIVOT.VALUE(3,"amount_signed","event_type","0_creation")',
        'B6': '=PIVOT.VALUE(1,"order_id:count_distinct")',
        'B8': '=PIVOT.VALUE(2,"order_id:count_distinct")',
        'B10': '=PIVOT.VALUE(2,"recurring_monthly")',
    })
    # The lifespan (in months) would inherit the percentage format of the churn rate
    set_format(data, 'Data', ['B11'], '0.0')
    tops = [
        ('Top Plans', 'Plans', 'template_id'), ('Top Products', 'Product', 'product_tmpl_id'),
        ('Top Sales Team', 'Sales Team', 'team_id'), ('Top Salesman', 'Salesperson', 'user_id'),
        ('Top Recurrences', 'Recurrence', 'plan_id'), ('Top Countries', 'Countries', 'country_id'),
    ]
    for pid, (name, label, field) in enumerate(tops, start=4):
        measures = mrr if field != 'plan_id' else ['order_id:count_distinct|# Subscriptions', 'recurring_monthly|Value']
        top(data, pid, LINE, label, field, measures, line, ACTIVE, 'recurring_monthly')
        set_cells(data, name, {'A1': '=PIVOT(%d,50,FALSE,FALSE)' % pid})
    columns = [('partner_id', 'Customer'), ('user_id', 'Salesperson'), ('recurring_monthly', 'MRR')]
    add_list(data, 1, 'sale.order', 'Top Quotations', columns, order, domain=QUOTATIONS, order='recurring_monthly',
             action=ACTION)
    add_list(data, 2, 'sale.order', 'Top Subscriptions', columns, order, domain=SUBSCRIPTIONS + ACTIVE,
             order='recurring_monthly', action=ACTION)
    set_cells(data, 'Top Quotations', {'A1': '=ODOO.LIST(1,50)'})
    set_cells(data, 'Top Subscriptions', {'A1': '=ODOO.LIST(2,50)'})

    figures = figures_at(data)
    # Odoo Online titles the table of the salespeople "Top Plans"
    figures[(505, 1734)]['data']['title']['text'] = 'Top Salespeople'
    for position, title, field in (((0, 130), 'MRR by Category', 'categ_id'),
                                   ((505, 130), 'MRR by Recurrence', 'plan_id'),
                                   ((0, 531), 'MRR by Country', 'country_id'),
                                   ((505, 531), 'MRR by Sales Team', 'team_id')):
        carousel(data, figures[position], title, [('Graph', odoo_chart(
            LINE, 'pie', [field], 'recurring_monthly', ACTIVE, legendPosition='top'))], line)
    carousel(data, figures[(505, 2135)], 'Top Countries', [
        ('Map', odoo_chart(LINE, 'geo', ['country_id'], 'recurring_monthly', ACTIVE, **GEO)),
        ('Top 50', 'Top Countries', 3),
    ], line)
    return data


def build_mrr_evolution(data):
    for gf in data['globalFilters']:
        if gf['label'] == 'Salesperon':
            gf['label'] = 'Salesperson'
    event = {
        'Date': ('event_date', 'date'), 'Country': ('country_id', 'many2one'), 'Customer': ('partner_id', 'many2one'),
        'Sales Team': ('team_id', 'many2one'), 'Salesperson': ('user_id', 'many2one'),
        'Recurrence': ('plan_id', 'many2one'),
    }
    invoice = {
        'Date': ('invoice_date', 'date'), 'Country': ('country_id', 'many2one'), 'Customer': ('partner_id', 'many2one'),
        'Sales Team': ('team_id', 'many2one'), 'Salesperson': ('invoice_user_id', 'many2one'),
    }
    add_pivot(data, 1, EVENT, 'MRR changes', ['amount_signed'], event, rows=['event_type'])
    add_pivot(data, 2, 'account.invoice.report', 'Recurring invoiced', ['price_subtotal'], invoice, domain=RECURRING)
    add_pivot(data, 3, 'account.invoice.report', 'Non recurring invoiced', ['price_subtotal'], invoice,
              domain=NON_RECURRING)
    update_cells(data, 'Data', {
        'B2': '=PIVOT.VALUE(1,"amount_signed","event_type","0_creation")',
        'B4': '=PIVOT.VALUE(1,"amount_signed","event_type","15_contraction")',
        'B5': '=PIVOT.VALUE(1,"amount_signed","event_type","1_expansion")',
        'B8': '=PIVOT.VALUE(1,"amount_signed","event_type","2_churn")',
        'B12': '=PIVOT.VALUE(2,"price_subtotal")',
        'B13': '=PIVOT.VALUE(3,"price_subtotal")',
    })
    set_format(data, 'Data', ['B14:B15'], '0.00%')
    tops = [('MRR by Recurrence', 'Recurrence', 'plan_id'), ('MRR by Team', 'Sales Team', 'team_id'),
            ('Top Salesperson', 'Salesperson', 'user_id'), ('MRR by Country', 'Country', 'country_id')]
    for pid, (name, label, field) in enumerate(tops, start=4):
        top(data, pid, EVENT, label, field, ['amount_signed|MRR'], event, [], 'amount_signed')
        set_cells(data, name, {'A1': '=PIVOT(%d,50,FALSE,FALSE)' % pid})
    columns = [('partner_id', 'Customer'), ('plan_id', 'Recurrence'), ('amount_signed', 'MRR')]
    add_list(data, 1, EVENT, 'Top Upgrades', columns, event, domain=[('event_type', '=', '1_expansion')],
             order='amount_signed')
    add_list(data, 2, EVENT, 'Worst Downgrades', columns, event, domain=[('event_type', '=', '15_contraction')],
             order='amount_signed', ascending=True)
    set_cells(data, 'Top Upgrades', {'A1': '=ODOO.LIST(1,50)'})
    set_cells(data, 'Worst Downgrades', {'A1': '=ODOO.LIST(2,50)'})

    figures = figures_at(data)
    # Cumulated from the start (MRR changes before the period included): the MRR at the end of each month
    mrr = odoo_chart(EVENT, 'line', ['event_date:month'], 'amount_signed', fillArea=True, cumulative=True)
    mrr['dataSource']['cumulatedStart'] = True
    carousel(data, figures[(0, 125)], 'MRR', [('Graph', mrr)], event)
    carousel(data, figures[(0, 579)], 'MRR Breakdown', [('Graph', odoo_chart(
        EVENT, 'bar', ['event_date:month', 'event_type'], 'amount_signed', stacked=True,
    ))], event)
    carousel(data, figures[(505, 1849)], 'MRR by Country', [
        ('Map', odoo_chart(EVENT, 'geo', ['country_id'], 'amount_signed', **GEO)),
        ('Top 50', 'MRR by Country', 2),
    ], event)
    return data


def build_retention(data):
    # No global filter: the monthly and daily MRR changes of all the subscriptions
    add_pivot(data, 1, EVENT, 'Monthly MRR changes', ['__count', 'amount_signed'], {},
              rows=['event_date:month'], columns=['event_type'])
    add_pivot(data, 2, EVENT, 'Daily MRR changes', ['__count', 'amount_signed'], {},
              rows=['event_date:day'], columns=['event_type'])
    cells = {}
    for event_type, count, mrr in EVENT_COLUMNS:
        cells['%s9' % count] = '=PIVOT.VALUE(1,"__count","event_type","%s")' % event_type
        cells['%s9' % mrr] = '=PIVOT.VALUE(1,"amount_signed","event_type","%s")' % event_type
        for pid, rows, date, granularity in ((1, range(12, 37), '$C', 'month'), (2, range(41, 71), '$B', 'day')):
            for row in rows:
                group = '"event_date:%s",%s%d,"event_type","%s"' % (granularity, date, row, event_type)
                cells['%s%d' % (count, row)] = '=PIVOT.VALUE(%d,"__count",%s)' % (pid, group)
                cells['%s%d' % (mrr, row)] = '=PIVOT.VALUE(%d,"amount_signed",%s)' % (pid, group)
    update_cells(data, 'Data', cells)
    # Revenue churn and net retention rates, not amounts
    set_format(data, 'Data', ['U12:V36', 'U41:V70'], '0.00%')
    return data


def build_salesperson(data):
    event = {
        'Period': ('event_date', 'date'), 'Country': ('country_id', 'many2one'),
        'Sales Team': ('team_id', 'many2one'), 'Salesperson': ('user_id', 'many2one'),
    }
    order = {
        'Country': ('partner_id.country_id', 'many2one'), 'Sales Team': ('team_id', 'many2one'),
        'Salesperson': ('user_id', 'many2one'),
    }
    invoice = {
        'Period': ('invoice_date', 'date'), 'Country': ('country_id', 'many2one'),
        'Sales Team': ('team_id', 'many2one'), 'Salesperson': ('invoice_user_id', 'many2one'),
    }
    add_pivot(data, 1, EVENT, 'MRR changes', ['__count', 'amount_signed'], event, rows=['event_type'])
    add_pivot(data, 2, 'sale.order', 'Subscriptions', ['__count', 'recurring_monthly'], order,
              domain=SUBSCRIPTIONS + ACTIVE)
    add_pivot(data, 3, 'account.invoice.report', 'Non recurring invoiced', ['price_subtotal'], invoice,
              domain=NON_RECURRING)
    cells = {}
    for row, event_type in ((2, '0_creation'), (4, '1_expansion'), (6, '15_contraction'), (8, '2_churn')):
        cells['B%d' % row] = '=PIVOT.VALUE(1,"__count","event_type","%s")' % event_type
        cells['B%d' % (row + 1)] = '=PIVOT.VALUE(1,"amount_signed","event_type","%s")' % event_type
    cells.update({
        'B10': '=PIVOT.VALUE(2,"recurring_monthly")',
        'B11': '=PIVOT.VALUE(2,"__count")',
        'B12': '=PIVOT.VALUE(3,"price_subtotal")',
        # Before the period: without its MRR changes, new and churned subscriptions
        'C10': '=B10-SUM(B3,B5,B7,B9)',
        'C11': '=B11-N(B2)+N(B8)',
    })
    update_cells(data, 'Data', cells)
    add_pivot(data, 4, 'sale.order', 'Plans', ['__count|# Subscriptions', 'recurring_monthly|MRR'], order,
              rows=['plan_id'], domain=SUBSCRIPTIONS + ACTIVE, sort='recurring_monthly')
    set_cells(data, 'Top Recurrence', {'A1': '=PIVOT(4,50,FALSE,FALSE)'})
    columns = [('order_id', 'Subscriptions'), ('amount_signed', 'Value'), ('recurring_monthly', 'MRR')]
    lists = [('Worst Churn', '2_churn', True), ('Top New', '0_creation', False),
             ('Worst Contraction', '15_contraction', True), ('Top Expansion', '1_expansion', False)]
    for lid, (name, event_type, ascending) in enumerate(lists, start=1):
        add_list(data, lid, EVENT, name, columns, event, domain=[('event_type', '=', event_type)],
                 order='amount_signed', ascending=ascending)
        set_cells(data, name, {'A1': '=ODOO.LIST(%d,50)' % lid})

    figures = figures_at(data)
    carousel(data, figures[(0, 126)], 'MRR Breakdown', [('Graph', odoo_chart(
        EVENT, 'bar', ['event_type'], 'amount_signed', axesDesign={'y': {'title': {'text': 'MRR Change'}}},
    ))], event)
    return data


if __name__ == '__main__':
    if len(sys.argv) != 5:
        sys.exit(__doc__)
    modules = ('sale', 'sale_management', 'hudson_subscriptions')
    for path, build, target in zip(sys.argv[1:], (build_subscriptions, build_mrr_evolution, build_retention,
                                                  build_salesperson),
                                   ('subscriptions', 'mrr_evolution', 'retention', 'salesperson')):
        write_dashboard(build(load_snapshot(path, menu_modules=modules)),
                        os.path.join(FILES, '%s_dashboard.json' % target))
