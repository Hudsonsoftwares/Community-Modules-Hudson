# -*- coding: utf-8 -*-
""" Build data/files/crm_leads_dashboard.json and crm_pipeline_dashboard.json from the Leads and Pipeline dashboards
of Odoo Online.

Download each dashboard shared from an Odoo Online database (https://<db>.odoo.com/dashboard/share/<id>/<token>) at
https://<db>.odoo.com/dashboard/data/<id>/<token>, then run:

    python build_dashboard.py <downloaded leads json> <downloaded pipeline json>

Their layout and styles are kept; their frozen data is replaced by the pivots, lists and Odoo charts below.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'hudson_spreadsheet_dashboard', 'tools'))
from dashboard_builder import (  # noqa: E402
    add_list, add_pivot, carousel, figures_at, load_snapshot, odoo_chart, set_cells, write_dashboard,
)

FILES = os.path.join(os.path.dirname(__file__), '..', 'data', 'files')

LEAD = {
    'Period': ('create_date', 'datetime'),
    'Country': ('country_id', 'many2one'),
    'Tags': ('tag_ids', 'many2many'),
    'Lost Reason': ('lost_reason_id', 'many2one'),
    'Medium': ('medium_id', 'many2one'),
    'Campaign': ('campaign_id', 'many2one'),
    'Source': ('source_id', 'many2one'),
    'Sales Team': ('team_id', 'many2one'),
    'Salesperson': ('user_id', 'many2one'),
}
OPPORTUNITY = {
    'Period': ('date_deadline', 'date'),
    'Stage': ('stage_id', 'many2one'),
    'Salesperson': ('user_id', 'many2one'),
    'Sales Team': ('team_id', 'many2one'),
    'Country': ('country_id', 'many2one'),
    'City': ('city', 'char'),
    'Medium': ('medium_id', 'many2one'),
    'Source': ('source_id', 'many2one'),
}
# The lost leads are archived
ALL_LEADS = ['|', ('active', '=', True), ('active', '=', False)]
OPPORTUNITIES = [('type', '=', 'opportunity')]
GEO = {'legendPosition': 'left', 'colorScale': {'minColor': '#f7fbff', 'midColor': '#6aaed6', 'maxColor': '#08306b'}}
LEADS_ACTION = 'crm.crm_opportunity_report_action_lead'
PIPELINE_ACTION = 'crm.crm_opportunity_report_action'


def add_top(data, pid, field, label, chains, domain, count_only=False):
    """ Pivot of the leads by `field` (headed `label`) for a "Top" sheet: their number and expected revenue, the
    largest first.
    """
    measures = ['__count|# Leads'] if count_only else ['__count|# Leads', 'expected_revenue|Revenue']
    return add_pivot(data, pid, 'crm.lead', label, measures, chains, rows=[field],
                     domain=list(domain) + [(field, '!=', False)], sort=measures[-1].split('|')[0])


def build_leads(data):
    add_pivot(data, 1, 'crm.lead', 'KPIs - current', ['__count', 'expected_revenue', 'day_close:sum', 'day_open:sum'],
              LEAD, rows=['won_status'], domain=ALL_LEADS)
    add_pivot(data, 2, 'crm.lead', 'KPIs - previous', ['__count', 'expected_revenue', 'day_close:sum', 'day_open:sum'],
              LEAD, rows=['won_status'], domain=ALL_LEADS, offset=-1)
    tops = [
        ('Top Countries', 'country_id', 'Country'), ('Top Tags', 'tag_ids', 'Tag'),
        ('Top Lost Reasons', 'lost_reason_id', 'Lost Reason'), ('Top Mediums', 'medium_id', 'Medium'),
        ('Top Campaigns', 'campaign_id', 'Campaign'), ('Top Sources', 'source_id', 'Source'),
        ('Top Sales Teams', 'team_id', 'Sales Team'), ('Top Salespeople', 'user_id', 'Salesperson'),
    ]
    for pid, (name, field, label) in enumerate(tops, start=3):
        add_top(data, pid, field, label, LEAD, ALL_LEADS, count_only=field == 'lost_reason_id')
        set_cells(data, name, {'A1': '=PIVOT(%d,50,FALSE,FALSE)' % pid})

    cells = {
        'A1': 'KPI', 'B1': 'Current period', 'C1': 'Previous period', 'D1': 'Current period', 'E1': 'Previous period',
        'A2': 'Won leads', 'A3': 'Total leads', 'A4': 'Close rate', 'A5': 'Average deal size', 'A6': 'Revenue',
        'A7': 'Total days to win', 'A8': 'Total days to assign', 'A9': 'Days to win', 'A10': 'Days to assign',
    }
    for col, pid in (('B', 1), ('C', 2)):
        cells.update({
            '%s2' % col: '=PIVOT.VALUE(%d,"__count","won_status","won")' % pid,
            '%s3' % col: '=PIVOT.VALUE(%d,"__count")' % pid,
            '%s4' % col: '=IFERROR(%s2/%s3)' % (col, col),
            '%s5' % col: '=IFERROR(%s6/%s2)' % (col, col),
            '%s6' % col: '=PIVOT.VALUE(%d,"expected_revenue","won_status","won")' % pid,
            '%s7' % col: '=PIVOT.VALUE(%d,"day_close:sum","won_status","won")' % pid,
            '%s8' % col: '=PIVOT.VALUE(%d,"day_open:sum")' % pid,
            '%s9' % col: '=IFERROR(%s7/%s2)' % (col, col),
            '%s10' % col: '=IFERROR(%s8/%s3)' % (col, col),
        })
    for target, source in (('D', 'B'), ('E', 'C')):
        for row in range(2, 7):
            cells['%s%d' % (target, row)] = '=FORMAT.LARGE.NUMBER(%s%d)' % (source, row)
        for row in (7, 8):
            cells['%s%d' % (target, row)] = '=%s%d' % (source, row)
        for row in (9, 10):
            cells['%s%d' % (target, row)] = '=IFERROR(ROUND(%s%d,1)&" days")' % (source, row)
    set_cells(data, 'Data', cells)

    figures = figures_at(data)
    carousel(data, figures[(0, 124)], 'Leads', [
        ('Graph', odoo_chart('crm.lead', 'line', ['create_date:month'], '__count', ALL_LEADS, LEADS_ACTION,
                             fillArea=True, axesDesign={'y': {'title': {'text': 'Leads'}}})),
        ('Campaigns', 'Top Campaigns', 3),
        ('Sources', 'Top Sources', 3),
    ], LEAD)
    carousel(data, figures[(0, 534)], 'Top Countries', [
        ('Map', odoo_chart('crm.lead', 'geo', ['country_id'], 'expected_revenue', ALL_LEADS, LEADS_ACTION, **GEO)),
        ('Top 50', 'Top Countries', 3),
    ], LEAD)
    return data


def build_pipeline(data):
    add_pivot(data, 1, 'crm.lead', 'KPIs - current', ['__count', 'expected_revenue'], OPPORTUNITY,
              rows=['won_status'], domain=OPPORTUNITIES)
    add_pivot(data, 2, 'crm.lead', 'KPIs - previous', ['__count', 'expected_revenue'], OPPORTUNITY,
              rows=['won_status'], domain=OPPORTUNITIES, offset=-1)
    tops = [
        ('Top Pipeline', 'stage_id', 'Stage'), ('Top Countries', 'country_id', 'Country'),
        ('Revenue by Source', 'source_id', 'Source'), ('Top Cities', 'city', 'City'),
        ('Top Mediums', 'medium_id', 'Medium'), ('Top Salespeople', 'user_id', 'Salesperson'),
        ('Top Sales Teams', 'team_id', 'Sales Team'),
    ]
    for pid, (name, field, label) in enumerate(tops, start=3):
        add_top(data, pid, field, label, OPPORTUNITY, OPPORTUNITIES)
        set_cells(data, name, {'A1': '=PIVOT(%d,50,FALSE,FALSE)' % pid})
    add_list(data, 1, 'crm.lead', 'Top Opportunities', [
        ('name', 'Opportunity'), ('stage_id', 'Stage'), ('user_id', 'Salesperson'), ('country_id', 'Country'),
        ('expected_revenue', 'Revenue'), ('probability', 'Success (%)'),
    ], OPPORTUNITY, domain=OPPORTUNITIES + [('won_status', '=', 'pending')], order='expected_revenue',
        action='crm.crm_lead_action_pipeline')
    set_cells(data, 'Top Opportunities', {'A1': '=ODOO.LIST(1,50)'})

    cells = {
        'A1': 'KPI', 'B1': 'Current', 'C1': 'Previous', 'D1': 'Current', 'E1': 'Previous',
        'A2': 'Expected count', 'A3': 'Closed count', 'A4': 'Expected revenue', 'A5': 'Closed revenue',
        'A6': 'Percentage closed', 'A7': 'To close',
    }
    for col, pid in (('B', 1), ('C', 2)):
        cells.update({
            '%s2' % col: '=PIVOT.VALUE(%d,"__count")' % pid,
            '%s3' % col: '=PIVOT.VALUE(%d,"__count","won_status","won")' % pid,
            '%s4' % col: '=PIVOT.VALUE(%d,"expected_revenue")' % pid,
            '%s5' % col: '=PIVOT.VALUE(%d,"expected_revenue","won_status","won")' % pid,
            '%s6' % col: '=IFERROR(%s3/%s2)' % (col, col),
            '%s7' % col: '=PIVOT.VALUE(%d,"__count","won_status","pending")' % pid,
        })
    for target, source in (('D', 'B'), ('E', 'C')):
        for row in (2, 3, 4, 5, 7):
            cells['%s%d' % (target, row)] = '=FORMAT.LARGE.NUMBER(%s%d)' % (source, row)
        cells['%s6' % target] = '=%s6' % source
    set_cells(data, 'Data', cells)

    figures = figures_at(data)
    # Odoo Online charts the opportunities against labels of the (empty) dashboard sheet
    top = next(iter(figures[(0, 128)]['data']['chartDefinitions'].values()))
    top['dataSource']['labelRange'] = "'Top Opportunities'!A1:A51"
    carousel(data, figures[(0, 566)], 'Pipeline', [
        ('Funnel', odoo_chart('crm.lead', 'funnel', ['stage_id'], '__count', OPPORTUNITIES, PIPELINE_ACTION,
                              cumulative=True, horizontal=True)),
        ('Top 50', 'Top Pipeline', 3),
    ], OPPORTUNITY)
    carousel(data, figures[(505, 566)], 'Forecast', [
        ('Graph', odoo_chart('crm.lead', 'bar', ['date_deadline:month', 'team_id'], 'expected_revenue',
                             OPPORTUNITIES, PIPELINE_ACTION, stacked=True,
                             axesDesign={'y': {'title': {'text': 'Revenue'}}})),
    ], OPPORTUNITY)
    carousel(data, figures[(0, 1004)], 'Top Countries', [
        ('Map', odoo_chart('crm.lead', 'geo', ['country_id'], 'expected_revenue', OPPORTUNITIES, PIPELINE_ACTION,
                           **GEO)),
        ('Top 50', 'Top Countries', 3),
    ], OPPORTUNITY)
    carousel(data, figures[(505, 1004)], 'Revenue by Source', [
        ('Graph', odoo_chart('crm.lead', 'treemap', ['source_id'], 'expected_revenue', OPPORTUNITIES,
                             PIPELINE_ACTION)),
        ('Top 50', 'Revenue by Source', 3),
    ], OPPORTUNITY)
    return data


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    write_dashboard(build_leads(load_snapshot(sys.argv[1], menu_modules=('crm',))),
                    os.path.join(FILES, 'crm_leads_dashboard.json'))
    write_dashboard(build_pipeline(load_snapshot(sys.argv[2], menu_modules=('crm',))),
                    os.path.join(FILES, 'crm_pipeline_dashboard.json'))
