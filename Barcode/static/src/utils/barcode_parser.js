/** @odoo-module **/

export class BarcodeParser {
    constructor(nomenclature) {
        this.rules = nomenclature || [];
        // Sort by sequence
        this.rules.sort((a, b) => a.sequence - b.sequence);
    }

    /**
     * Parses a barcode string against the nomenclature rules
     * @param {string} barcode 
     * @returns {Object} result
     */
    parse(barcode) {
        if (!barcode) return { type: 'error', barcode: barcode };

        for (let rule of this.rules) {
            let pattern = rule.pattern;
            if (!pattern) continue;

            // Odoo patterns sometimes contain {NN} or {NNNDD} for weights/prices.
            // For basic operations (product, location, lot, package), it's usually a standard regex.
            // Replace Odoo's {} syntax with standard regex capture groups for digits if present
            pattern = pattern.replace(/\{N+\}/g, (match) => `(\\d{${match.length - 2}})`);
            pattern = pattern.replace(/\{N+D+\}/g, (match) => `(\\d{${match.length - 2}})`);

            try {
                // Odoo's regex patterns don't always have ^ and $ boundaries, but we usually want exact matches for fixed length
                // However, for safety we will just compile what they give us.
                let regex = new RegExp(`^${pattern}`);
                let match = barcode.match(regex);

                if (match) {
                    return {
                        type: rule.type,      // e.g., 'product', 'location', 'lot', 'package', 'command'
                        barcode: barcode,
                        rule_name: rule.name,
                        match: match          // match[1] might contain extracted value if regex has groups
                    };
                }
            } catch (e) {
                console.warn("Invalid regex pattern in nomenclature rule:", rule.name, pattern);
            }
        }

        // Default fallback if no rule matches
        return { type: 'unknown', barcode: barcode };
    }
}
