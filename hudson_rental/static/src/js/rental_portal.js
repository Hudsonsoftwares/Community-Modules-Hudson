/** @odoo-module **/

odoo.define('hudson_rental.portal', function (require) {
    'use strict';

    var publicWidget = require('web.public.widget');

    publicWidget.registry.RentalPortalWidget = publicWidget.Widget.extend({
        selector: '.o_portal_rental',
        events: {
            'click .rental_extend_btn': '_onExtendClick',
        },

        _onExtendClick: function (ev) {
            ev.preventDefault();
            // Handle rental extension from portal
            var orderId = $(ev.currentTarget).data('order-id');
            window.location.href = '/my/rentals/' + orderId + '/extend';
        }
    });

    return publicWidget.registry.RentalPortalWidget;
});
