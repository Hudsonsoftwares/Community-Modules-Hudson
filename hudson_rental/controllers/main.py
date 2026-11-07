# -*- coding: utf-8 -*-
# Part of Hudson. See LICENSE file for full copyright and licensing details.

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from odoo import http, _
from odoo.exceptions import UserError
from odoo.http import request, route
from odoo.addons.website_sale.controllers.cart import Cart


def _parse_rental_datetime(value):
    """Parse an ISO datetime sent by the browser into a naive UTC datetime as stored by
    the ORM. Values without an offset are taken in the visitor's timezone."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        tz_name = request.env.context.get('tz') or request.env.user.tz or 'UTC'
        try:
            dt = dt.replace(tzinfo=ZoneInfo(tz_name))
        except Exception:
            dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _check_rental_times(template, pickup, return_dt, tz_name):
    """Error message if the pickup or return time (naive UTC) is outside the times allowed
    by the product's Pickup and Return times, in the visitor's timezone; else False."""
    window = template._get_rental_time_window()
    if window is None:
        return False
    try:
        tz = ZoneInfo(tz_name or request.env.context.get('tz') or request.env.user.tz or 'UTC')
    except Exception:
        tz = timezone.utc
    for dt in (pickup, return_dt):
        local = dt.replace(tzinfo=timezone.utc).astimezone(tz)
        if not template._is_rental_time_allowed(local.hour * 60 + local.minute):
            first, last = window
            return _('%(product)s can only be picked up and returned between %(first)s and %(last)s.',
                     product=template.name, first=template._format_rental_time(first),
                     last=template._format_rental_time(last))
    return False


def _parse_rental_period(template, rental_start_date, rental_end_date, rental_tz):
    """Parse and check the rental period sent by the product page.
    Returns (pickup, return, error message or False), datetimes as naive UTC."""
    if not rental_start_date or not rental_end_date:
        return None, None, _('Please select a rental period for %s.', template.name)
    try:
        pickup = _parse_rental_datetime(rental_start_date)
        return_dt = _parse_rental_datetime(rental_end_date)
    except (TypeError, ValueError):
        return None, None, _('The rental period is not valid.')
    error = _check_rental_times(template, pickup, return_dt, rental_tz) or _check_rental_dates(pickup, return_dt)
    return pickup, return_dt, error


def _check_rental_dates(pickup, return_dt):
    """Return an error message if the rental period can't be booked, else False."""
    if return_dt <= pickup:
        return _('The return must be after the pickup.')
    company = request.env.company.sudo()
    if not company._is_rental_day_available(pickup):
        return _('Pickup is not possible on the selected day. Please choose another date.')
    if not company._is_rental_day_available(return_dt):
        return _('Return is not possible on the selected day. Please choose another date.')
    return False


class WebsiteRental(http.Controller):

    @http.route(['/rental/products'], type='http', auth="public", website=True, sitemap=True)
    def rental_products(self, **kwargs):
        """Display all rental products"""
        products = request.env['product.template'].sudo().search([
            ('is_rental', '=', True),
            ('rental_ok', '=', True),
            ('website_published', '=', True)
        ])

        values = {
            'products': products,
            'page_name': 'rental_products',
        }
        return request.render('hudson_rental.rental_products_template', values)

    @http.route(['/rental/product/<model("product.template"):product>'], type='http', auth="public", website=True, sitemap=False)
    def rental_product_detail(self, product, **kwargs):
        """Rentals are booked from the regular shop page of the product"""
        product = product.sudo()
        if not product.is_rental or not product.website_published:
            return request.redirect('/rental/products')
        return request.redirect(product.website_url)


class WebsiteSaleRentalCart(Cart):

    @route()
    def add_to_cart(self, product_template_id, product_id, quantity, *args,
                    rental_start_date=None, rental_end_date=None, rental_tz=None, **kwargs):
        """Rental products are added to the cart for the rental period chosen on the product page."""
        template = request.env['product.template'].sudo().browse(int(product_template_id or 0)).exists()
        if template.is_rental:
            if rental_tz and not request.env.context.get('tz'):
                # Show the period on the cart line in the timezone the visitor picked it in
                try:
                    ZoneInfo(rental_tz)
                    request.update_context(tz=rental_tz)
                except Exception:
                    pass
            pickup, return_dt, error = _parse_rental_period(template, rental_start_date, rental_end_date, rental_tz)
            if error:
                raise UserError(error)
            kwargs.update(rental_start_date=pickup, rental_end_date=return_dt)
        return super().add_to_cart(product_template_id, product_id, quantity, *args, **kwargs)

    @route('/rental/period/check', type='jsonrpc', auth='public', website=True, methods=['POST'])
    def rental_period_check(self, product_template_id, product_id, quantity=1,
                            rental_start_date=None, rental_end_date=None, rental_tz=None, **kwargs):
        """Check a rental period before adding to cart, so the product page can show what is
        wrong next to the period. Returns {'error': message or False}."""
        template = request.env['product.template'].sudo().browse(int(product_template_id or 0)).exists()
        if not template.is_rental:
            return {'error': False}
        pickup, return_dt, error = _parse_rental_period(template, rental_start_date, rental_end_date, rental_tz)
        if error:
            return {'error': error}
        product = request.env['product.product'].sudo().browse(int(product_id or 0)).exists()
        if not product or not product.is_storable:
            return {'error': False}
        # Adding to the cart applies the period to the whole cart: count what's already there
        cart = request.cart
        in_cart = sum(cart.order_line.filtered(lambda l: l.product_id == product).mapped('product_uom_qty')) if cart else 0
        qty = (int(quantity or 1) or 1) + in_cart
        available = product._get_rental_available_qty(
            pickup, return_dt, (request.env.website.company_id or request.env.company).sudo(),
            exclude_lines=cart.order_line if cart else None)
        return {'error': product._get_rental_unavailable_message(qty, available)}
