# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from datetime import date, datetime, timedelta

class DentalPharmacyDashboard(models.AbstractModel):
    _name = 'dental.pharmacy.dashboard'
    _description = 'Dental Pharmacy Live Analytics Dashboard'

    @api.model
    def get_dashboard_data(self):
        """Fetches live real database metrics for the Pharmacy OWL Dashboard without any mock/dummy fallback data."""
        today = fields.Date.context_today(self)
        start_of_today = datetime.combine(today, datetime.min.time())
        end_of_today = datetime.combine(today, datetime.max.time())

        yesterday = today - timedelta(days=1)
        start_of_yesterday = datetime.combine(yesterday, datetime.min.time())
        end_of_yesterday = datetime.combine(yesterday, datetime.max.time())

        Product = self.env['product.product']
        Lot = self.env['stock.lot']
        Prescription = self.env['dental.prescription']
        Dispense = self.env['dental.pharmacy.dispense']

        # 1. Medicine Catalog Inventory Counts
        medicines = Product.search([('is_medicine', '=', True)])
        total_medicines = len(medicines)
        out_of_stock = len(medicines.filtered(lambda m: m.qty_available <= 0))
        low_stock = len(medicines.filtered(lambda m: 0 < m.qty_available <= m.reorder_level))
        in_stock = len(medicines.filtered(lambda m: m.qty_available > m.reorder_level))

        # 2. Batch / Lot Expiry Counts
        lots = Lot.search([('is_medicine', '=', True)])
        total_batches = len(lots)
        expired_batches = len(lots.filtered(lambda l: l.expiry_status == 'expired'))
        near_expiry_batches = len(lots.filtered(lambda l: l.expiry_status == 'near_expiry'))
        valid_batches = len(lots.filtered(lambda l: l.expiry_status == 'valid'))

        # 3. Prescription Lifecycle Counts
        all_rx = Prescription.search([])
        total_prescriptions = len(all_rx)
        today_rx_count = Prescription.search_count([('prescription_date', '=', today)])
        yesterday_rx_count = Prescription.search_count([('prescription_date', '=', yesterday)])

        # Calculate prescription growth vs yesterday
        prescriptions_trend_is_up = False
        prescriptions_trend_is_down = False
        if yesterday_rx_count > 0:
            diff = today_rx_count - yesterday_rx_count
            pct = round((abs(diff) / yesterday_rx_count) * 100)
            if diff > 0:
                prescriptions_growth = f"+{pct}%"
                prescriptions_trend_is_up = True
            elif diff < 0:
                prescriptions_growth = f"-{pct}%"
                prescriptions_trend_is_down = True
            else:
                prescriptions_growth = "0%"
        elif today_rx_count > 0:
            prescriptions_growth = f"+{today_rx_count}"
            prescriptions_trend_is_up = True
        else:
            prescriptions_growth = "0%"

        pending_prescriptions = Prescription.search_count([('state', '=', 'confirmed')])
        partially_dispensed = Prescription.search_count([('state', '=', 'partially_dispensed')])
        fully_dispensed = Prescription.search_count([('state', '=', 'fully_dispensed')])
        draft_prescriptions = Prescription.search_count([('state', '=', 'draft')])

        # 4. Dispensing Financial & Operational Metrics
        today_dispenses = Dispense.search([
            ('dispense_date', '>=', start_of_today),
            ('dispense_date', '<=', end_of_today),
            ('state', '=', 'dispensed')
        ])
        today_dispensed_lines_qty = int(sum(today_dispenses.line_ids.mapped('qty_to_dispense')))
        today_dispensed_count = today_dispensed_lines_qty if today_dispensed_lines_qty > 0 else len(today_dispenses)
        today_dispensed_amount = sum(today_dispenses.mapped('amount_total'))

        yesterday_dispenses = Dispense.search([
            ('dispense_date', '>=', start_of_yesterday),
            ('dispense_date', '<=', end_of_yesterday),
            ('state', '=', 'dispensed')
        ])
        yesterday_dispensed_lines_qty = int(sum(yesterday_dispenses.line_ids.mapped('qty_to_dispense')))
        yesterday_dispensed_count = yesterday_dispensed_lines_qty if yesterday_dispensed_lines_qty > 0 else len(yesterday_dispenses)

        dispensed_trend_is_up = False
        dispensed_trend_is_down = False
        if yesterday_dispensed_count > 0:
            diff = today_dispensed_count - yesterday_dispensed_count
            pct = round((abs(diff) / yesterday_dispensed_count) * 100)
            if diff > 0:
                medicines_dispensed_growth = f"+{pct}%"
                dispensed_trend_is_up = True
            elif diff < 0:
                medicines_dispensed_growth = f"-{pct}%"
                dispensed_trend_is_down = True
            else:
                medicines_dispensed_growth = "0%"
        elif today_dispensed_count > 0:
            medicines_dispensed_growth = f"+{today_dispensed_count}"
            dispensed_trend_is_up = True
        else:
            medicines_dispensed_growth = "0%"

        all_dispensed = Dispense.search([('state', '=', 'dispensed')])
        total_dispensed_amount = sum(all_dispensed.mapped('amount_total'))

        # 5. Stock Status Breakdown (Real Numbers for Donut Chart)
        calc_total_items = total_medicines
        if calc_total_items > 0:
            in_stock_pct = round((in_stock / calc_total_items) * 100)
            low_stock_pct = round((low_stock / calc_total_items) * 100)
            out_of_stock_pct = round((out_of_stock / calc_total_items) * 100)
        else:
            in_stock_pct = 0
            low_stock_pct = 0
            out_of_stock_pct = 0

        expiring_soon_pct = round((near_expiry_batches / max(total_batches, 1)) * 100) if total_batches > 0 else 0

        stock_breakdown = {
            'total_items': calc_total_items,
            'in_stock': in_stock,
            'in_stock_pct': in_stock_pct,
            'low_stock': low_stock,
            'low_stock_pct': low_stock_pct,
            'expiring_soon': near_expiry_batches,
            'expiring_soon_pct': expiring_soon_pct,
            'out_of_stock': out_of_stock,
            'out_of_stock_pct': out_of_stock_pct,
            'inactive': 0,
            'inactive_pct': 0,
        }

        # 6. Dispensing Activity (Real Last 7 Days Chart Data from DB)
        day_labels = []
        rx_activity = []
        dispensed_activity = []
        for i in range(6, -1, -1):
            d = today - timedelta(days=i)
            day_labels.append(d.strftime('%d %b'))

            rx_count = Prescription.search_count([('prescription_date', '=', d)])
            rx_activity.append(rx_count)

            d_start = datetime.combine(d, datetime.min.time())
            d_end = datetime.combine(d, datetime.max.time())
            day_dispenses = Dispense.search([
                ('dispense_date', '>=', d_start),
                ('dispense_date', '<=', d_end),
                ('state', '=', 'dispensed')
            ])
            day_disp_lines_qty = int(sum(day_dispenses.line_ids.mapped('qty_to_dispense')))
            dispensed_activity.append(day_disp_lines_qty if day_disp_lines_qty > 0 else len(day_dispenses))

        chart_activity = {
            'labels': day_labels,
            'prescriptions': rx_activity,
            'dispensed': dispensed_activity,
        }

        # 7. Recent Prescriptions List (Real Records Only)
        recent_rx_db = Prescription.search([], order='prescription_date desc, id desc', limit=6)
        recent_prescriptions = []
        status_map = {
            'confirmed': 'Pending',
            'partially_dispensed': 'Partial',
            'fully_dispensed': 'Dispensed',
            'draft': 'Draft',
            'cancelled': 'Cancelled',
        }
        for rx in recent_rx_db:
            date_str = rx.prescription_date.strftime('%d %b %Y') if rx.prescription_date else ''
            recent_prescriptions.append({
                'id': rx.id,
                'ref': rx.name,
                'patient': rx.patient_id.name or 'Patient',
                'doctor': rx.dentist_id.name or 'Dentist',
                'date': date_str,
                'status': status_map.get(rx.state, (rx.state or 'Pending').title()),
            })

        # 8. Low Stock Medicines List (Real Records Only)
        low_stock_records = medicines.filtered(lambda m: m.qty_available <= m.reorder_level)
        low_stock_list = []
        for m in low_stock_records[:6]:
            form_label = dict(m._fields['dosage_form'].selection).get(m.dosage_form, 'Medicine') if hasattr(m, 'dosage_form') and m.dosage_form else 'Medicine'
            low_stock_list.append({
                'id': m.product_tmpl_id.id if hasattr(m, 'product_tmpl_id') else m.id,
                'name': m.name,
                'type': form_label,
                'current': int(m.qty_available),
                'min_qty': int(m.reorder_level),
            })

        # 9. Expiry Alerts List (Real Records Only)
        critical_lots = lots.filtered(lambda l: l.expiry_status in ('expired', 'near_expiry'))
        critical_lots_sorted = sorted(critical_lots, key=lambda l: (l.expiry_date or date(2099, 12, 31)))
        expiry_alerts_list = []
        for l in critical_lots_sorted[:6]:
            exp_str = l.expiry_date.strftime('%d %b %Y') if l.expiry_date else 'No Date'
            expiry_alerts_list.append({
                'id': l.id,
                'medicine': l.product_id.name or 'Medicine',
                'batch': l.name or 'BATCH',
                'expiry': exp_str,
                'status': l.expiry_status,
            })

        return {
            'total_medicines': total_medicines,
            'in_stock': in_stock,
            'low_stock': low_stock,
            'out_of_stock': out_of_stock,
            'total_batches': total_batches,
            'valid_batches': valid_batches,
            'near_expiry_batches': near_expiry_batches,
            'expired_batches': expired_batches,
            'total_prescriptions': total_prescriptions,
            'pending_prescriptions': pending_prescriptions,
            'partially_dispensed': partially_dispensed,
            'fully_dispensed': fully_dispensed,
            'draft_prescriptions': draft_prescriptions,
            'prescriptions_today': today_rx_count,
            'prescriptions_growth': prescriptions_growth,
            'prescriptions_trend_is_up': prescriptions_trend_is_up,
            'prescriptions_trend_is_down': prescriptions_trend_is_down,
            'medicines_dispensed_today': today_dispensed_count,
            'medicines_dispensed_growth': medicines_dispensed_growth,
            'dispensed_trend_is_up': dispensed_trend_is_up,
            'dispensed_trend_is_down': dispensed_trend_is_down,
            'today_dispensed_count': today_dispensed_count,
            'today_dispensed_amount': today_dispensed_amount,
            'total_dispensed_amount': total_dispensed_amount,
            'currency_symbol': self.env.company.currency_id.symbol or '$',
            'stock_breakdown': stock_breakdown,
            'chart_activity': chart_activity,
            'recent_prescriptions': recent_prescriptions,
            'low_stock_medicines': low_stock_list,
            'expiry_alerts': expiry_alerts_list,
        }

    @api.model
    def action_generate_reorder_rfq(self):
        """Finds all medicines below reorder level and automatically drafts RFQs grouped by vendor."""
        medicines = self.env['product.product'].search([
            ('is_medicine', '=', True),
            ('type', '!=', 'service')
        ])
        low_stock_medicines = medicines.filtered(lambda m: m.qty_available <= m.reorder_level)

        if not low_stock_medicines:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Stock Levels Sufficient'),
                    'message': _('All pharmacy medicines have sufficient inventory. No replenishment RFQ needed.'),
                    'type': 'info',
                    'sticky': False,
                }
            }

        vendor_products = {}
        fallback_vendor = self.env['res.partner'].search([('supplier_rank', '>', 0)], limit=1)
        if not fallback_vendor:
            fallback_vendor = self.env['res.partner'].search([('is_company', '=', True)], limit=1)

        for med in low_stock_medicines:
            vendor = med.manufacturer_id or (med.seller_ids and med.seller_ids[0].partner_id) or fallback_vendor
            if not vendor:
                continue
            if vendor not in vendor_products:
                vendor_products[vendor] = []
            vendor_products[vendor].append(med)

        created_pos = self.env['purchase.order']
        for vendor, meds in vendor_products.items():
            po_vals = {
                'partner_id': vendor.id,
                'company_id': self.env.company.id,
                'origin': _('Auto Pharmacy Low Stock Replenishment'),
                'order_line': []
            }
            for med in meds:
                req_qty = max(20.0, float((med.reorder_level * 2) - med.qty_available))
                po_vals['order_line'].append((0, 0, {
                    'name': f"Replenishment: {med.display_name}",
                    'product_id': med.id,
                    'product_qty': req_qty,
                    'uom_id': med.uom_po_id.id if hasattr(med, 'uom_po_id') and med.uom_po_id else med.uom_id.id,
                    'price_unit': med.standard_price or 10.0,
                    'date_planned': fields.Datetime.now(),
                }))
            po = self.env['purchase.order'].create(po_vals)
            created_pos |= po

        if len(created_pos) == 1:
            return {
                'name': _('Replenishment Purchase Order %s', created_pos.name),
                'type': 'ir.actions.act_window',
                'res_model': 'purchase.order',
                'res_id': created_pos.id,
                'view_mode': 'form',
                'target': 'current',
            }
        else:
            return {
                'name': _('Low Stock Replenishment RFQs'),
                'type': 'ir.actions.act_window',
                'res_model': 'purchase.order',
                'view_mode': 'list,form',
                'domain': [('id', 'in', created_pos.ids)],
                'target': 'current',
            }

