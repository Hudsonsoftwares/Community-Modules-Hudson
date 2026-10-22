# Part of Hudson Community. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ── Existing fields (preserved) ──────────────────────────────────────────

    field_service_default_hourly_rate = fields.Float(
        string='Default Hourly Rate',
        config_parameter='hudson_field_service.default_hourly_rate',
        default=50.0,
        help='Default hourly rate used when creating invoices for field service time.',
    )
    field_service_auto_invoice = fields.Boolean(
        string='Auto-Invoice on Completion',
        config_parameter='hudson_field_service.auto_invoice',
        default=False,
        help='Automatically open the invoice wizard when a field service order is marked done.',
    )

    # ── Scheduling ────────────────────────────────────────────────────────────

    fs_project_planning = fields.Boolean(
        string='Project Planning',
        config_parameter='hudson_field_service.fs_project_planning',
        default=True,
        help=(
            'Allow field service orders to be linked to project tasks. '
            'Materials added to the order will be invoiced against the '
            'project\'s originating sale order when available.'
        ),
    )
    fs_planning_enabled = fields.Boolean(
        string='Enable Planning Schedule',
        config_parameter='hudson_field_service.fs_planning_enabled',
        default=True,
        help='Enable the full planning schedule with roles, shift templates, and resource allocation.',
    )
    fs_planning_auto_plan = fields.Boolean(
        string='Auto Plan',
        config_parameter='hudson_field_service.fs_planning_auto_plan',
        default=True,
        help='Enable automatic scheduling of field service orders based on role and availability.',
    )

    # ── Field Service features ────────────────────────────────────────────────

    fs_timesheets = fields.Boolean(
        string='Timesheets',
        config_parameter='hudson_field_service.fs_timesheets',
        default=True,
        help='Enable time tracking on field service orders via the built-in timer.',
    )
    fs_billing = fields.Boolean(
        string='Billing',
        config_parameter='hudson_field_service.fs_billing',
        default=True,
        help=(
            'Invoice time and materials to customers. '
            'When enabled, products added to a field service order are '
            'automatically synced to the linked (or auto-created) sale order.'
        ),
    )
    fs_worksheets = fields.Boolean(
        string='Worksheets',
        config_parameter='hudson_field_service.fs_worksheets',
        default=True,
        help='Allow technicians to document the work performed using the Worksheet tab.',
    )
    fs_products = fields.Boolean(
        string='Products',
        config_parameter='hudson_field_service.fs_products',
        default=True,
        help='Track materials and parts used during field service visits.',
    )
    fs_hide_prices = fields.Boolean(
        string='Hide Prices on Customer Report',
        config_parameter='hudson_field_service.fs_hide_prices',
        default=False,
        help='Remove unit prices and subtotals from the PDF report sent to customers.',
    )
    fs_customer_signature = fields.Boolean(
        string='Customer Report & Signature',
        config_parameter='hudson_field_service.fs_customer_signature',
        default=True,
        help=(
            'Enable the customer report (PDF) and allow customers to provide '
            'a digital signature via the customer portal.'
        ),
    )
    fs_geolocation = fields.Boolean(
        string='Geolocation',
        config_parameter='hudson_field_service.fs_geolocation',
        default=True,
        help=(
            'Track technicians\' GPS location when they start/resume a timer. '
            'Managers can view all active technicians on the Live Map.'
        ),
    )
    fs_location_radius = fields.Float(
        string='Location Radius (meters)',
        config_parameter='hudson_field_service.fs_location_radius',
        default=500.0,
        help='Radius around the customer address. Used for validation or live map alerts.',
    )
    fs_radius_validation = fields.Boolean(
        string='Radius Sign In',
        config_parameter='hudson_field_service.fs_radius_validation',
        default=False,
        help='Strictly allow sign in/out only within the specified radius of the customer location.',
    )

    # ── Sale Order & Invoicing ─────────────────────────────────────────────────

    fs_auto_sale_order = fields.Boolean(
        string='Auto-create Sale Order for Products',
        config_parameter='hudson_field_service.fs_auto_sale_order',
        default=True,
        help=(
            'Automatically create a sale order when products are added to a '
            'standalone field service order (i.e., not linked to a project sale order). '
            'Products will be added as sale order lines and invoiced via that SO.'
        ),
    )

    # ── Customer Satisfaction ─────────────────────────────────────────────────

    fs_customer_ratings = fields.Boolean(
        string='Customer Ratings',
        config_parameter='hudson_field_service.fs_customer_ratings',
        default=False,
        help=(
            'Automatically send a satisfaction survey to the customer when a '
            'field service order is marked as Done.'
        ),
    )
    fs_rating_survey_id = fields.Many2one(
        'survey.survey',
        string='Rating Survey Template',
        config_parameter='hudson_field_service.fs_rating_survey_id',
        help='The survey sent to customers after a completed intervention.',
    )

    # ── Inventory & Stock ─────────────────────────────────────────────────────

    fs_stock_deduction = fields.Boolean(
        string='Automatic Stock Deduction',
        config_parameter='hudson_field_service.fs_stock_deduction',
        default=False,
        help='Automatically deduct stock (create and validate a delivery order) when a field service order is marked Done.',
    )
    fs_default_picking_type_id = fields.Many2one(
        'stock.picking.type',
        string='Default Picking Type',
        config_parameter='hudson_field_service.fs_default_picking_type_id',
        domain="[('code', '=', 'outgoing')]",
        help='The operation type used to deduct stock for field service products.',
    )

