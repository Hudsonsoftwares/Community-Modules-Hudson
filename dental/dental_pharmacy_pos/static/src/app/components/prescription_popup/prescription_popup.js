import { _t } from "@web/core/l10n/translation";
import { Component, onWillStart, useProps, proxy, t } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class PrescriptionPopup extends Component {
    static template = "dental_pharmacy_pos.PrescriptionPopup";
    static components = { Dialog };
    props = useProps({
        partnerId: t.any().optional(false),
        partnerName: t.string().optional(""),
        fetch: t.function(),
        usedLineRefs: t.array().optional([]),
        getPayload: t.function(),
        close: t.function(),
    });

    setup() {
        this.state = proxy({
            search: "",
            onlyPatient: Boolean(this.props.partnerId),
            loading: false,
            error: false,
            prescriptions: [],
            selectedId: false,
            lineIds: [],
        });
        this._searchTimer = null;
        onWillStart(() => this.load());
    }

    get title() {
        return this.state.onlyPatient && this.props.partnerName
            ? _t("Prescriptions of %s", this.props.partnerName)
            : _t("Pending Prescriptions");
    }

    get selected() {
        return this.state.prescriptions.find((rx) => rx.id === this.state.selectedId);
    }

    async load() {
        this.state.loading = true;
        this.state.error = false;
        try {
            const partnerId = this.state.onlyPatient ? this.props.partnerId : false;
            this.state.prescriptions = await this.props.fetch(partnerId, this.state.search);
        } catch {
            this.state.error = true;
            this.state.prescriptions = [];
        }
        this.state.loading = false;
        const first = this.state.prescriptions[0];
        if (!this.selected) {
            this.select(first);
        }
    }

    onSearchInput(ev) {
        this.state.search = ev.target.value;
        clearTimeout(this._searchTimer);
        this._searchTimer = setTimeout(() => this.load(), 350);
    }

    toggleOnlyPatient() {
        this.state.onlyPatient = !this.state.onlyPatient;
        this.state.selectedId = false;
        this.load();
    }

    isUsed(line) {
        return this.props.usedLineRefs.includes(line.id);
    }

    isSellable(line) {
        return line.available_in_pos && !this.isUsed(line);
    }

    select(rx) {
        this.state.selectedId = rx ? rx.id : false;
        this.state.lineIds = rx
            ? rx.lines.filter((l) => this.isSellable(l) && l.available_qty > 0).map((l) => l.id)
            : [];
    }

    toggleLine(line) {
        if (!this.isSellable(line)) {
            return;
        }
        const ids = this.state.lineIds;
        this.state.lineIds = ids.includes(line.id)
            ? ids.filter((id) => id !== line.id)
            : [...ids, line.id];
    }

    stockClass(line) {
        if (line.available_qty <= 0) {
            return "text-danger";
        }
        return line.available_qty < line.remaining_qty ? "text-warning" : "text-success";
    }

    allergyClass(allergy) {
        if (allergy.status === "known") {
            return "alert-danger";
        }
        return allergy.status === "none" ? "alert-success" : "alert-warning";
    }

    confirm() {
        if (!this.selected || !this.state.lineIds.length) {
            return;
        }
        this.props.getPayload({ prescription: this.selected, lineIds: [...this.state.lineIds] });
        this.props.close();
    }
}
