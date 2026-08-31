# -*- coding: utf-8 -*-
# Part of Hudson. See LICENSE file for full copyright and licensing details.

from odoo import http, fields, _
from odoo.http import request
from odoo.addons.website_sale.controllers.main import WebsiteSale
import json
from datetime import datetime, timedelta


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

    @http.route(['/rental/product/<model("product.template"):product>'], type='http', auth="public", website=True, sitemap=True)
    def rental_product_detail(self, product, **kwargs):
        """Display rental product details with pricing"""
        if not product.is_rental or not product.rental_ok:
            return request.redirect('/rental/products')
        
        values = {
            'product': product,
            'page_name': 'rental_product',
            'pricing_options': product.rental_pricing_ids.sorted(key=lambda p: p.duration),
        }
        return request.render('hudson_rental.rental_product_detail_template', values)

    @http.route(['/rental/configure'], type='json', auth="public", website=True)
    def rental_configure(self, product_id, pickup_date, return_date, quantity=1, **kwargs):
        """Configure rental dates and calculate price"""
        product = request.env['product.product'].sudo().browse(int(product_id))
        
        if not product.exists() or not product.is_rental:
            return {'error': 'Invalid product'}
        
        try:
            pickup = fields.Datetime.from_string(pickup_date)
            return_dt = fields.Datetime.from_string(return_date)
        except:
            return {'error': 'Invalid dates'}
        
        if return_dt <= pickup:
            return {'error': 'Return date must be after pickup date'}
        
        # Calculate duration and price
        delta = return_dt - pickup
        duration_days = delta.days + (delta.seconds / 86400.0)
        
        price = product.product_tmpl_id.get_rental_price(duration_days, 'day')
        total = price * float(quantity)
        
        return {
            'success': True,
            'duration_days': duration_days,
            'price_unit': price,
            'total': total,
            'currency_symbol': request.env.company.currency_id.symbol,
        }

    @http.route(['/rental/add_to_cart'], type='json', auth="public", website=True)
    def rental_add_to_cart(self, product_id, pickup_date, return_date, quantity=1, **kwargs):
        """Add rental product to cart"""
        product = request.env['product.product'].sudo().browse(int(product_id))
        
        if not product.exists() or not product.is_rental:
            return {'error': 'Invalid product'}
        
        # Create or get sale order
        order = request.website.sale_get_order(force_create=True)
        
        # Add product with rental dates
        order._cart_update(
            product_id=int(product_id),
            add_qty=float(quantity),
            set_qty=0,
        )
        
        # Update line with rental information
        line = order.order_line.filtered(lambda l: l.product_id.id == int(product_id))[-1]
        line.write({
            'is_rental': True,
            'rental_start_date': pickup_date,
            'rental_end_date': return_date,
        })
        line._onchange_rental_price()
        
        return {
            'success': True,
            'cart_quantity': order.cart_quantity,
            'message': _('Product added to cart')
        }

    @http.route(['/rental/check_availability'], type='json', auth="public", website=True)
    def check_rental_availability(self, product_id, pickup_date, return_date, quantity=1, **kwargs):
        """Check if product is available for rental period"""
        product = request.env['product.product'].sudo().browse(int(product_id))
        
        if not product.exists():
            return {'available': False, 'message': 'Product not found'}
        
        # Check stock
        available_qty = product.product_tmpl_id.rental_stock_available
        
        if available_qty >= float(quantity):
            return {
                'available': True,
                'quantity_available': available_qty,
                'message': 'Product available'
            }
        else:
            return {
                'available': False,
                'quantity_available': available_qty,
                'message': f'Only {available_qty} units available'
            }


class WebsiteSaleRental(WebsiteSale):
    
    def _get_mandatory_fields_billing(self, country_id=False):
        """Extend mandatory fields for rental orders"""
        mandatory_fields = super()._get_mandatory_fields_billing(country_id)
        order = request.website.sale_get_order()
        
        # If order contains rental products, add phone as mandatory
        if order and any(line.is_rental for line in order.order_line):
            mandatory_fields.append('phone')
        
        return mandatory_fields
