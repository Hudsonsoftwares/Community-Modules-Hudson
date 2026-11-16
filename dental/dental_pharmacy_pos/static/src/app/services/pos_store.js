import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { PrescriptionPopup } from "@dental_pharmacy_pos/app/components/prescription_popup/prescription_popup";
import { PatientInfoPopup } from "@dental_pharmacy_pos/app/components/patient_info_popup/patient_info_popup";

patch(PosStore.prototype, {
    get isPharmacyCounter() {
        return Boolean(this.config.dental_pharmacy_counter);
    },

    get dentalWalkinPartnerId() {
        const raw = this.config.raw?.dental_walkin_partner_id;
        return (Array.isArray(raw) ? raw[0] : raw) || this.config.dental_walkin_partner_id?.id || false;
    },

    async dentalCall(method, args = []) {
        return await this.data.call("pos.config", method, [[this.config.id], ...args]);
    },

    // ------------------------------------------------------------------
    // Patient alert (allergies, pending prescriptions, medicine history)
    // ------------------------------------------------------------------
    setPartnerToCurrentOrder(partner) {
        super.setPartnerToCurrentOrder(...arguments);
        if (this.isPharmacyCounter && partner) {
            this.dentalShowPatientInfo(partner, { onlyIfRelevant: true });
        }
    },

    async dentalShowPatientInfo(partner, { onlyIfRelevant = false } = {}) {
        let info;
        try {
            info = await this.dentalCall("dental_get_patient_info", [partner.id]);
        } catch {
            this.notification.add(_t("Patient details could not be loaded (offline?)."), {
                type: "warning",
            });
            return;
        }
        if (!info || info.is_walkin) {
            return;
        }
        const relevant =
            info.allergy.status !== "none" || info.pending_count > 0 || info.history.length;
        if (onlyIfRelevant && !relevant) {
            return;
        }
        const openPrescriptions = await makeAwaitable(this.dialog, PatientInfoPopup, {
            partnerName: partner.name,
            info,
        });
        if (openPrescriptions) {
            await this.dentalOpenPrescriptions();
        }
    },

    // ------------------------------------------------------------------
    // Prescriptions
    // ------------------------------------------------------------------
    async dentalOpenPrescriptions() {
        const partner = this.getOrder()?.getPartner();
        const walkinId = this.dentalWalkinPartnerId;
        const partnerId = partner && partner.id !== walkinId ? partner.id : false;
        const selection = await makeAwaitable(this.dialog, PrescriptionPopup, {
            partnerId,
            partnerName: partnerId ? partner.name : "",
            fetch: (pid, search) => this.dentalCall("dental_get_prescriptions", [pid, search]),
            usedLineRefs: this.dentalUsedRxLineRefs(),
        });
        if (selection) {
            await this.dentalAddPrescription(selection.prescription, selection.lineIds);
        }
    },

    dentalUsedRxLineRefs() {
        return (this.getOrder()?.getOrderlines() || [])
            .map((line) => line.dental_rx_line_ref)
            .filter(Boolean);
    },

    async dentalEnsurePartner(partnerId) {
        let partner = this.models["res.partner"].get(partnerId);
        if (!partner) {
            await this.data.read("res.partner", [partnerId]);
            partner = this.models["res.partner"].get(partnerId);
        }
        return partner;
    },

    async dentalEnsureProduct(rxLine) {
        let product = this.models["product.product"].get(rxLine.product_id);
        if (!product) {
            await this.loadNewProducts([["id", "=", rxLine.product_tmpl_id]]);
            product = this.models["product.product"].get(rxLine.product_id);
        }
        return product;
    },

    async dentalPickLot(product) {
        const lots = await this.data.call("pos.order.line", "get_existing_lots", [
            this.company.id,
            this.config.id,
            product.id,
        ]);
        return lots?.[0] || false;
    },

    formatDentalDosage(prescription, rxLine) {
        const parts = [rxLine.frequency, rxLine.duration ? _t("%s days", rxLine.duration) : ""];
        if (rxLine.route) {
            parts.push(rxLine.route);
        }
        const dosage = parts.filter(Boolean).join(", ");
        return [prescription.name, dosage, rxLine.instructions].filter(Boolean).join(" | ");
    },

    async dentalAddPrescription(prescription, lineIds) {
        let order = this.getOrder();
        if (!order) {
            order = this.addNewOrder();
        }
        const currentPartner = order.getPartner();
        if (currentPartner?.id !== prescription.partner_id) {
            if (order.getOrderlines().length && currentPartner) {
                // Never mix two patients on one invoice
                order = this.addNewOrder();
                this.notification.add(
                    _t("A new order was started for %s.", prescription.patient)
                );
            }
            const partner = await this.dentalEnsurePartner(prescription.partner_id);
            if (partner) {
                // Direct setter: the patient alert was already shown in the prescription popup
                order.setPartner(partner);
            }
        }
        const skipped = [];
        const used = new Set(this.dentalUsedRxLineRefs());
        for (const rxLine of prescription.lines.filter((l) => lineIds.includes(l.id))) {
            if (used.has(rxLine.id)) {
                continue;
            }
            const product = await this.dentalEnsureProduct(rxLine);
            if (!product) {
                skipped.push(_t("%s (not sold at this counter)", rxLine.medicine));
                continue;
            }
            const vals = {
                product_tmpl_id: product.product_tmpl_id,
                product_id: product,
                qty: rxLine.remaining_qty,
                dental_rx_line_ref: rxLine.id,
                customer_note: this.formatDentalDosage(prescription, rxLine),
            };
            if (["lot", "serial"].includes(product.tracking)) {
                const lot = await this.dentalPickLot(product);
                if (!lot) {
                    skipped.push(_t("%s (no unexpired batch in stock)", rxLine.medicine));
                    continue;
                }
                vals.pack_lot_ids = [["create", { lot_name: lot.name }]];
            }
            await this.addLineToCurrentOrder(vals, {}, false);
        }
        if (skipped.length) {
            this.dialog.add(AlertDialog, {
                title: _t("Some medicines were not added"),
                body: skipped.join("\n"),
            });
        }
    },

    // ------------------------------------------------------------------
    // Batches: earliest expiry first, expired never (the server filters and sorts them)
    // ------------------------------------------------------------------
    async editLots(product, packLotLinesToEdit) {
        if (!this.isPharmacyCounter || packLotLinesToEdit.length) {
            return await super.editLots(...arguments);
        }
        let lot;
        try {
            lot = await this.dentalPickLot(product);
        } catch {
            return await super.editLots(...arguments);
        }
        if (!lot) {
            this.dialog.add(AlertDialog, {
                title: _t("No sellable batch"),
                body: _t(
                    "%s has no unexpired batch in stock at this counter.",
                    product.display_name
                ),
            });
            return null;
        }
        if (lot.dental_expiry_date) {
            this.notification.add(
                _t("Batch %(lot)s (expires %(date)s) selected: earliest expiry first.", {
                    lot: lot.name,
                    date: lot.dental_expiry_date,
                })
            );
        }
        return { newPackLotLines: [{ lot_name: lot.name }] };
    },

    // ------------------------------------------------------------------
    // Payment: every pharmacy sale is invoiced and batch-tracked
    // ------------------------------------------------------------------
    async pay() {
        const order = this.getOrder();
        if (!this.isPharmacyCounter || !order) {
            return await super.pay(...arguments);
        }
        const missingLot = order
            .getOrderlines()
            .filter(
                (line) =>
                    ["lot", "serial"].includes(line.getProduct().tracking) &&
                    !line.hasValidProductLot()
            );
        if (missingLot.length) {
            this.dialog.add(AlertDialog, {
                title: _t("Batch number required"),
                body: _t(
                    "Select the batch for: %s",
                    missingLot.map((line) => line.getProduct().display_name).join(", ")
                ),
            });
            return;
        }
        if (!order.getPartner()) {
            const walkinId = this.dentalWalkinPartnerId;
            const walkin = walkinId && (await this.dentalEnsurePartner(walkinId));
            if (walkin) {
                order.setPartner(walkin);
            }
        }
        if (order.getPartner() && !order.isToInvoice()) {
            order.setToInvoice(true);
        }
        return await super.pay(...arguments);
    },
});
