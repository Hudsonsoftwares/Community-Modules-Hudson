{
    'name': 'Hudson Accounting Enhancements',
    'version': '19.0.1.0.0',
    'category': 'Accounting',
    'summary': (
        'Cash Flow Statement, Annual Report, Executive Summary, Unrealized Currency, '
        'Restructured P&L (Gross Profit, Operating Profit, Net Profit), '
        'Balance Sheet with Equity & Retained Earnings, Auto ECB Currency Rates, '
        'Extended Tax Report with Tax Groups'
    ),
    'description': """
        Comprehensive enhancements to the om_account_accountant community accounting module:

        1. Restructured Profit & Loss with Cost of Revenue, Gross Profit, Operating Expenses,
           Operating Profit, Other Income, and Net Profit breakdown.
        2. Balance Sheet with proper separate Equity section (Share Capital, Retained Earnings,
           Current Year Earnings) split from Liabilities.
        3. Cash Flow Statement (Indirect Method) — Operating, Investing & Financing activities.
        4. Annual Report — Combined year-end financial summary (BS + P&L in one document).
        5. Executive Summary — One-page KPI dashboard with ratios and period comparisons.
        6. Unrealized Currency Gains/Losses wizard and report for open foreign-currency items.
        7. Automatic Currency Rate Updates via the European Central Bank (ECB) XML feed.
        8. Extended Tax Report with tax group breakdown, base vs. tax amount columns.
        9. Budget Items menu correctly linked under Accounting > Management.
        10. Reconciliation improvements: manual journal entry access.
    """,
    'author': 'Hudson Software',
    'website': 'https://www.hudsonsoftwares.com',
    'license': 'LGPL-3',
    'depends': [
        'om_account_accountant',
        'accounting_pdf_reports',
        'om_account_budget',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/account_financial_report_bs_pl.xml',
        'data/currency_rate_cron.xml',
        'views/res_currency_views.xml',
        'views/account_aged_report_views.xml',
        'wizard/account_cash_flow_views.xml',
        'wizard/account_annual_report_views.xml',
        'wizard/account_executive_summary_views.xml',
        'wizard/account_unrealized_currency_views.xml',
        'wizard/account_tax_extended_views.xml',
        'report/report.xml',
        'report/report_aged.xml',
        'report/report_cash_flow.xml',
        'report/report_annual.xml',
        'report/report_executive_summary.xml',
        'report/report_unrealized_currency.xml',
        'report/report_tax_extended.xml',
        'views/menu.xml',
    ],
    'application': False,
    'installable': True,
    'auto_install': False,
    'images': [],
}
