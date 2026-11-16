{
    "name": "Barcode",
    "version": "20.0.1.0.0",
    "category": "Inventory/Inventory",
    "summary": "Mobile-friendly barcode scanning app for Inventory operations",
    "depends": [
        # Odoo 20: batch transfers (stock.picking.batch) are part of `stock`;
        # the separate `stock_picking_batch` module no longer exists.
        "stock",
        "mrp",
        "barcodes",
        "barcodes_gs1_nomenclature",
        "web",
    ],
    "data": [
        "security/ir.access.csv",
        "security/barcode_security.xml",
        "views/barcode_menu_views.xml",
        "views/report_barcode_commands.xml",
        "views/report_barcode_demo_sheet.xml",
        "views/product_barcode_views.xml",
        "views/res_config_settings_views.xml",
        "views/stock_location_views.xml",
        "views/stock_picking_views.xml",
        "views/stock_picking_batch_views.xml",
        "data/barcode_data.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "Barcode/static/src/**/*.js",
            "Barcode/static/src/**/*.xml",
            "Barcode/static/src/**/*.scss",
        ],
        "web.assets_backend_lazy": [
            "Barcode/static/src/lazy/**/*",
        ],
    },
    "installable": True,
    "application": True,
    "license": "LGPL-3",
}
