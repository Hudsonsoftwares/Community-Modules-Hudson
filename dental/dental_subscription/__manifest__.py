{
    'name': 'Dental Memberships & Subscriptions',
    'version': '20.0.1.0.0',
    'category': 'Healthcare/Dental',
    'summary': 'Dental membership plans, family memberships, preventive packages, '
               'orthodontic installments and maintenance subscriptions',
    'description': """
Dental Memberships & Subscriptions
==================================
Builds on the Hudson Subscriptions engine (sale.order based subscriptions, recurring
plans, recurring invoicing cron, renewals, close reasons, MRR analytics). Nothing of
that engine is duplicated here: a dental subscription *is* a ``sale.order`` subscription.

What this module adds:

* Subscription types on recurring products: membership, family membership, preventive
  care package, orthodontic installment plan, post-treatment maintenance.
* Covered members (existing dental patients only) with a per-product member limit and
  a duplicate-membership guard per branch.
* Benefit rules (free or discounted treatments, per billing period / contract year /
  whole term) copied onto each subscription when it is confirmed.
* Automatic application of benefits when a visit or case is billed through the
  standard dental billing flow; usage is the invoice lines themselves, so a cancelled
  invoice gives the benefit back.
* Orthodontic installments financed from a treatment plan: the plan's sessions are
  billed at zero (no double billing) and the contract closes itself after the last
  installment.
* Payment status, overdue tracking, expiry and overdue reminders (daily cron).
* Membership information on patients, appointments and treatment plans.
* Admin Membership Dashboard with live, branch-scoped figures.

Security: see dental_base/SECURITY.md. Subscriptions and invoices are company-owned
(core Odoo rules); benefit entitlements follow their subscription's branch.
""",
    'author': 'Hudson Software Solutions',
    'depends': [
        'hudson_subscriptions',
        'dental_core',
    ],
    'data': [
        'security/dental_subscription_security.xml',
        'security/ir.access.csv',
        'data/subscription_data.xml',
        'data/mail_template_data.xml',
        'data/ir_cron_data.xml',
        'wizard/installment_wizard_views.xml',
        'views/product_template_views.xml',
        'views/subscription_plan_views.xml',
        'views/subscription_benefit_views.xml',
        'views/sale_order_views.xml',
        'views/res_partner_views.xml',
        'views/dental_appointment_views.xml',
        'views/dental_treatment_plan_views.xml',
        'views/dashboard_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'dental_subscription/static/src/dashboard/subscription_dashboard.scss',
            'dental_subscription/static/src/dashboard/subscription_dashboard.js',
            'dental_subscription/static/src/dashboard/subscription_dashboard.xml',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
