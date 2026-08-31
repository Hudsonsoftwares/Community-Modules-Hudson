/** @odoo-module **/

odoo.define('hudson_rental.configurator', function (require) {
    'use strict';

    var publicWidget = require('web.public.widget');
    var ajax = require('web.ajax');

    publicWidget.registry.RentalConfigurator = publicWidget.Widget.extend({
        selector: '.rental_configurator',
        events: {
            'change #pickup_date': '_onDateChange',
            'change #return_date': '_onDateChange',
            'change #quantity': '_onQuantityChange',
            'click #check_availability': '_checkAvailability',
        },

        start: function () {
            this._super.apply(this, arguments);
            this.productId = this.$el.data('product-id');
        },

        _onDateChange: function () {
            this._calculatePrice();
        },

        _onQuantityChange: function () {
            this._calculatePrice();
        },

        _calculatePrice: function () {
            var self = this;
            var pickupDate = this.$('#pickup_date').val();
            var returnDate = this.$('#return_date').val();
            var quantity = this.$('#quantity').val() || 1;

            if (!pickupDate || !returnDate) {
                return;
            }

            ajax.jsonRpc('/rental/configure', 'call', {
                product_id: this.productId,
                pickup_date: pickupDate,
                return_date: returnDate,
                quantity: quantity
            }).then(function (result) {
                if (result.success) {
                    self.$('#duration_display').text(result.duration_days.toFixed(1) + ' days');
                    self.$('#price_display').text(result.total.toFixed(2) + ' ' + result.currency_symbol);
                    self.$('#rental_calculation').show();
                } else if (result.error) {
                    self.displayNotification({
                        message: result.error,
                        type: 'danger',
                    });
                }
            });
        },

        _checkAvailability: function () {
            var self = this;
            var pickupDate = this.$('#pickup_date').val();
            var returnDate = this.$('#return_date').val();
            var quantity = this.$('#quantity').val() || 1;

            if (!pickupDate || !returnDate) {
                return;
            }

            ajax.jsonRpc('/rental/check_availability', 'call', {
                product_id: this.productId,
                pickup_date: pickupDate,
                return_date: returnDate,
                quantity: quantity
            }).then(function (result) {
                var message = result.available ? 
                    'Product is available!' : 
                    'Product is not available for the selected dates';
                
                self.displayNotification({
                    message: message,
                    type: result.available ? 'success' : 'warning',
                });
            });
        }
    });

    return publicWidget.registry.RentalConfigurator;
});
