# -*- coding: utf-8 -*-
# Part of Hudson. See LICENSE file for full copyright and licensing details.

from odoo import http, _
from odoo.http import request
from odoo.exceptions import AccessError, MissingError
from markupsafe import Markup
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager


class SubscriptionCustomerPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super(SubscriptionCustomerPortal, self)._prepare_home_portal_values(counters)
        if 'subscription_count' in counters:
            values['subscription_count'] = request.env['sale.order'].search_count([
                ('is_subscription', '=', True),
                ('partner_id', '=', request.env.user.partner_id.id),
                ('subscription_state', 'in', ['3_progress', '4_paused', '5_renew', '6_churn'])
            ]) if request.env.user.partner_id else 0
        return values

    @http.route(['/my/subscriptions', '/my/subscriptions/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_subscriptions(self, page=1, date_begin=None, date_end=None, sortby=None, **kw):
        values = self._prepare_portal_layout_values()
        partner = request.env.user.partner_id
        SaleOrder = request.env['sale.order']

        domain = [
            ('is_subscription', '=', True),
            ('partner_id', '=', partner.id),
            ('subscription_state', 'in', ['3_progress', '4_paused', '5_renew', '6_churn'])
        ]

        subscription_count = SaleOrder.search_count(domain)
        pager = portal_pager(
            url="/my/subscriptions",
            total=subscription_count,
            page=page,
            step=10
        )

        subscriptions = SaleOrder.search(domain, limit=10, offset=pager['offset'], order='id desc')

        values.update({
            'subscriptions': subscriptions,
            'page_name': 'subscription',
            'pager': pager,
            'default_url': '/my/subscriptions',
        })
        return request.render("hudson_subscriptions.portal_my_subscriptions", values)

    @http.route(['/my/subscriptions/<int:subscription_id>'], type='http', auth="public", website=True)
    def portal_my_subscription_detail(self, subscription_id=None, access_token=None, **kw):
        try:
            subscription = self._document_check_access('sale.order', subscription_id, access_token=access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')

        has_pending_renewal = bool(subscription.renewal_order_ids.filtered(lambda r: r.state in ['draft', 'sent']))
        values = {
            'subscription': subscription,
            'page_name': 'subscription',
            'has_pending_renewal': has_pending_renewal,
            'access_token': access_token,
        }
        return request.render("hudson_subscriptions.portal_subscription_page", values)

    @http.route(['/my/subscriptions/<int:subscription_id>/upsell'], type='http', auth="user", website=True)
    def portal_my_subscription_upsell(self, subscription_id=None, **kw):
        subscription = request.env['sale.order'].browse(subscription_id)
        if not subscription.exists() or subscription.partner_id.id != request.env.user.partner_id.id:
            return request.redirect('/my')

        if not subscription.plan_id.user_add_products:
            return request.redirect(f'/my/subscriptions/{subscription.id}')

        pricelist = getattr(request, 'pricelist', False) or request.env['product.pricelist'].sudo().search([('company_id', 'in', (False, subscription.company_id.id))], limit=1)
        pricing_rules = request.env['product.pricelist.item'].sudo().search([
            ('subscription_plan_id', '=', subscription.plan_id.id),
            ('pricelist_id', '=', pricelist.id),
            ('product_tmpl_id', '!=', False)
        ])
        
        values = {
            'subscription': subscription,
            'pricing_rules': pricing_rules,
            'page_name': 'subscription',
        }
        return request.render("hudson_subscriptions.portal_subscription_upsell", values)

    @http.route(['/my/subscriptions/<int:subscription_id>/upsell/submit'], type='http', auth="user", methods=['POST'], website=True)
    def portal_my_subscription_upsell_submit(self, subscription_id=None, **post):
        subscription = request.env['sale.order'].browse(subscription_id)
        if not subscription.exists() or subscription.partner_id.id != request.env.user.partner_id.id:
            return request.redirect('/my')

        pricelist = getattr(request, 'pricelist', False) or request.env['product.pricelist'].sudo().search([('company_id', 'in', (False, subscription.company_id.id))], limit=1)
        
        order_lines = []
        for key, value in post.items():
            if key.startswith('product_qty_') and value:
                try:
                    qty = float(value)
                    if qty > 0:
                        product_id = int(key.replace('product_qty_', ''))
                        product = request.env['product.product'].sudo().browse(product_id)
                        if product.exists():
                            # Find the pricing rule
                            rule = request.env['product.pricelist.item'].sudo().search([
                                ('subscription_plan_id', '=', subscription.plan_id.id),
                                ('pricelist_id', '=', pricelist.id),
                                ('product_tmpl_id', '=', product.product_tmpl_id.id)
                            ], limit=1)
                            price = rule.fixed_price if rule and rule.compute_price == 'fixed' else product.list_price
                            
                            order_lines.append((0, 0, {
                                'product_id': product.id,
                                'product_uom_qty': qty,
                                'price_unit': price,
                            }))
                except ValueError:
                    pass

        if order_lines:
            upsell_order = request.env['sale.order'].sudo().create({
                'partner_id': subscription.partner_id.id,
                'origin_order_id': subscription.id,
                'is_subscription': True,
                'is_upsell': True,
                'plan_id': subscription.plan_id.id,
                'order_line': order_lines,
            })
            return request.redirect(f'/my/orders/{upsell_order.id}')
            
        return request.redirect(f'/my/subscriptions/{subscription.id}')

    @http.route(['/my/subscriptions/<int:subscription_id>/optional_upsell'], type='http', auth="user", methods=['POST'], website=True)
    def portal_my_subscription_optional_upsell(self, subscription_id=None, **post):
        subscription = request.env['sale.order'].browse(subscription_id)
        if not subscription.exists() or subscription.partner_id.id != request.env.user.partner_id.id:
            return request.redirect('/my')

        product_qtys = {}
        for key, value in post.items():
            if key.startswith('qty_') and value:
                try:
                    qty = float(value)
                    if qty > 0:
                        line_id = int(key.replace('qty_', ''))
                        parent_line = request.env['sale.order.line'].sudo().browse(line_id)
                        if parent_line.exists() and parent_line.order_id.id == subscription.id:
                            product_id = parent_line.product_id.id
                            product_qtys[product_id] = product_qtys.get(product_id, 0) + qty
                except ValueError:
                    pass

        if product_qtys:
            action = subscription.sudo().action_upsell_subscription()
            upsell_order_id = action.get('res_id')
            if upsell_order_id:
                upsell_order = request.env['sale.order'].sudo().browse(upsell_order_id)
                for product_id, qty in product_qtys.items():
                    existing_line = upsell_order.order_line.filtered(lambda l: l.product_id.id == product_id)
                    if existing_line:
                        existing_line[0].product_uom_qty = qty
                return request.redirect(f'/my/orders/{upsell_order.id}')
            
        return request.redirect(f'/my/subscriptions/{subscription.id}')

    @http.route(['/my/subscriptions/<int:order_id>/renew'], type='http', auth="user", website=True)
    def portal_my_subscription_renew(self, order_id=None, **kw):
        order = request.env['sale.order'].browse(order_id)
        if not order.exists() or order.partner_id.id != request.env.user.partner_id.id:
            return request.redirect('/my')

        # Clone the order into a renewal quotation
        renewal_order = order.sudo().copy({
            'origin_order_id': order.id,
            'is_renewal': True,
            'is_subscription': True,
            'subscription_state': 'draft',
            'plan_id': order.plan_id.id,
            'start_date': order.end_date or fields.Date.context_today(order),
            'next_invoice_date': order.end_date or fields.Date.context_today(order),
        })
        order.sudo().message_post(body=_("Renewal quotation %s created from the portal.", renewal_order._get_html_link()))
        
        return request.redirect(f'/my/orders/{renewal_order.id}')

    @http.route(['/my/subscriptions/<int:order_id>/change_plan'], type='http', auth="user", methods=['POST'], website=True)
    def portal_my_subscription_change_plan(self, order_id=None, plan_id=None, **kw):
        order = request.env['sale.order'].browse(order_id)
        if not order.exists() or order.partner_id.id != request.env.user.partner_id.id:
            return request.redirect('/my')

        if plan_id:
            new_plan = request.env['sale.subscription.plan'].sudo().browse(int(plan_id))
            if new_plan.exists():
                order.sudo().write({'plan_id': new_plan.id})
                if order.subscription_state in ['3_progress', '4_paused']:
                    # Recalculate end_date and next_invoice_date if already active
                    start_date = order.start_date or fields.Date.context_today(order)
                    order.sudo().write({
                        'end_date': new_plan.get_next_date(start_date),
                    })
                order.sudo().message_post(body=Markup(_("Subscription plan was changed to <b>%s</b> from the portal.") % new_plan.name))
        
        # If it's a draft quote, redirect to the quote page. If active, redirect to subscription page.
        if order.state in ['draft', 'sent']:
            return request.redirect(f'/my/orders/{order.id}')
        return request.redirect(f'/my/subscriptions/{order.id}')

    @http.route(['/my/subscriptions/<int:order_id>/close'], type='http', auth="user", methods=['POST'], website=True)
    def portal_my_subscription_close(self, order_id=None, close_reason_id=None, **kw):
        order = request.env['sale.order'].browse(order_id)
        if not order.exists() or order.partner_id.id != request.env.user.partner_id.id:
            return request.redirect('/my')

        if close_reason_id:
            reason = request.env['sale.subscription.close.reason'].sudo().browse(int(close_reason_id))
            if reason.exists():
                order.sudo().write({
                    'subscription_state': '6_churn',
                    'close_reason_id': reason.id,
                    'close_date': fields.Date.context_today(order),
                })
                order.sudo().message_post(body=Markup(_("Subscription has been <b>Closed / Churned</b> from the portal.<br/>Reason: %s") % reason.name))

        return request.redirect(f'/my/subscriptions/{order.id}')

