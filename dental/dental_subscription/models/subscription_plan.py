from odoo import fields, models


class SaleSubscriptionPlan(models.Model):
    _inherit = 'sale.subscription.plan'

    dental_expiry_reminder_days = fields.Integer(
        string='Expiry Reminder (days before)', default=30,
        help='Dental subscriptions with an end date get a renewal reminder this many days before it. '
             '0 disables the reminder.')
    dental_overdue_reminder_days = fields.Integer(
        string='Overdue Reminder Interval (days)', default=7,
        help='How often a payment reminder is sent while a dental subscription has overdue invoices. '
             '0 disables overdue reminders.')
