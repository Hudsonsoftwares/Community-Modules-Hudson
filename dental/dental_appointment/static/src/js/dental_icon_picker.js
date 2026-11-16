/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";

export const DENTAL_PRESET_ICONS = [
    // Diagnostic & Examinations
    { id: "fa-stethoscope", name: "Stethoscope", category: "diagnostic", class: "fa-stethoscope", tags: "doctor exam checkup consultation diagnostic general" },
    { id: "fa-eye", name: "X-Ray & Imaging", category: "diagnostic", class: "fa-eye", tags: "xray imaging rvg scan cbct panoramic diagnosis visual examination" },
    { id: "fa-camera", name: "Intraoral Camera", category: "diagnostic", class: "fa-camera", tags: "photo camera intraoral documentation record pictures diagnostic" },
    { id: "fa-search", name: "Second Opinion", category: "diagnostic", class: "fa-search", tags: "search evaluate examination audit second opinion review" },

    // Emergency & Urgent
    { id: "fa-ambulance", name: "Emergency Care", category: "emergency", class: "fa-ambulance", tags: "emergency pain broken tooth trauma urgent accident bleeding" },
    { id: "fa-medkit", name: "First Aid Kit", category: "emergency", class: "fa-medkit", tags: "first aid medkit medical emergency clinic treatment relief" },
    { id: "fa-bell-o", name: "Priority Alert", category: "emergency", class: "fa-bell-o", tags: "alert notification bell reminder urgent critical" },

    // Preventive & Cleaning
    { id: "fa-shield", name: "Teeth Cleaning", category: "preventive", class: "fa-shield", tags: "cleaning hygiene prophylaxis tartar scaling shield plaque polish" },
    { id: "fa-tint", name: "Gum & Periodontal", category: "preventive", class: "fa-tint", tags: "gum perio periodontal bleeding pocket hygiene drop root planing" },
    { id: "fa-refresh", name: "Periodic Maintenance", category: "preventive", class: "fa-refresh", tags: "refresh maintenance cycle periodic aligner change clean" },

    // Pediatric
    { id: "fa-child", name: "Pediatric Dentistry", category: "pediatric", class: "fa-child", tags: "child kid baby pediatric toddler youth fluoride gentle" },

    // Endodontics & Root Canal
    { id: "fa-heartbeat", name: "Root Canal / Pulp", category: "endodontic", class: "fa-heartbeat", tags: "root canal endodontic vitality pulp nerve heartbeat pulse tooth infection" },

    // Cosmetic & Whitening
    { id: "fa-magic", name: "Cosmetic & Whitening", category: "cosmetic", class: "fa-magic", tags: "cosmetic whitening sparkle magic aesthetic smile veneer bleaching laser" },
    { id: "fa-smile-o", name: "Smile Makeover", category: "cosmetic", class: "fa-smile-o", tags: "smile happy aesthetic cosmetic teeth align makeover beauty" },
    { id: "fa-star-o", name: "VIP Deluxe Care", category: "cosmetic", class: "fa-star-o", tags: "vip star premium executive deluxe aesthetic" },

    // Orthodontics
    { id: "fa-sliders", name: "Orthodontics & Aligners", category: "orthodontic", class: "fa-sliders", tags: "orthodontics aligners braces invisalign bite spacing crowding wire" },

    // Surgical & Extractions
    { id: "fa-user-md", name: "Oral Surgeon", category: "surgical", class: "fa-user-md", tags: "surgeon doctor specialist surgery consultation oral maxillofacial" },
    { id: "fa-scissors", name: "Tooth Extraction", category: "surgical", class: "fa-scissors", tags: "extraction surgery tooth removal wisdom cut surgical" },

    // Prosthodontics & Implants
    { id: "fa-anchor", name: "Dental Implant", category: "prosthodontic", class: "fa-anchor", tags: "implant anchor artificial tooth prosthetics titanium fixed crown" },
    { id: "fa-cube", name: "Crown & 3D Scan", category: "prosthodontic", class: "fa-cube", tags: "crown bridge 3d cad cam cerec scan prosthetic restoration" },
    { id: "fa-flask", name: "Dental Lab & Materials", category: "prosthodontic", class: "fa-flask", tags: "lab laboratory materials crown bridge acrylic resin biomaterial" },

    // General, Visits & Recalls
    { id: "fa-calendar-check-o", name: "Routine Recall Checkup", category: "general", class: "fa-calendar-check-o", tags: "recall calendar routine 6 month checkup appointment visit" },
    { id: "fa-check-circle-o", name: "Post-Op Review & Suture", category: "general", class: "fa-check-circle-o", tags: "post op review check healing suture removal follow up" },
    { id: "fa-clock-o", name: "Quick 15-Min Visit", category: "general", class: "fa-clock-o", tags: "quick short consultation express time clock 15 min review" },
    { id: "fa-file-text-o", name: "Treatment Plan & Chart", category: "general", class: "fa-file-text-o", tags: "document report treatment plan notes case record prescription" },
    { id: "fa-hospital-o", name: "Hospital / Inpatient", category: "general", class: "fa-hospital-o", tags: "hospital clinic surgery facility inpatient operatory" },
    { id: "fa-wheelchair", name: "Special Needs Care", category: "general", class: "fa-wheelchair", tags: "special needs wheelchair elderly disabled accessible" },
    { id: "fa-plus-square", name: "Clinic Healthcare", category: "general", class: "fa-plus-square", tags: "medical plus cross clinic pharmacy health general" },
];

export class DentalIconPicker extends Component {
    static template = "dental_appointment.DentalIconPicker";
    static props = {
        ...standardFieldProps,
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            isOpen: false,
            searchQuery: "",
            selectedCategory: "all",
            customIcons: [],
            customInputOpen: false,
            manualClassInput: "",
        });

        onWillStart(async () => {
            await this.loadDatabaseIcons();
        });
    }

    async loadDatabaseIcons() {
        try {
            const dbIcons = await this.orm.searchRead(
                "dental.appointment.icon",
                [["active", "=", true]],
                ["id", "name", "icon_class", "category", "image"],
                { order: "sequence asc, name asc" }
            );
            if (dbIcons && dbIcons.length > 0) {
                this.state.customIcons = dbIcons.map((icon) => ({
                    id: `db_${icon.id}`,
                    name: icon.name,
                    category: icon.category || "general",
                    class: icon.icon_class || "",
                    hasImage: Boolean(icon.image),
                    imageUrl: icon.image ? `/web/image/dental.appointment.icon/${icon.id}/image` : null,
                    tags: `${icon.name} custom ${icon.category || ""} ${icon.icon_class || ""}`.toLowerCase(),
                    isCustom: true,
                }));
            }
        } catch (e) {
            console.warn("Could not load custom icons from database:", e);
        }
    }

    get currentValue() {
        return (this.props.record.data[this.props.name] || "").trim();
    }

    get selectedIcon() {
        const val = this.currentValue;
        if (!val) {
            return {
                id: "default",
                name: _t("No Icon Selected"),
                class: "fa-stethoscope",
                category: "general",
            };
        }
        // Match in database icons
        const dbMatch = this.state.customIcons.find((i) => i.class === val);
        if (dbMatch) return dbMatch;

        // Match in presets
        const presetMatch = DENTAL_PRESET_ICONS.find((i) => i.class === val);
        if (presetMatch) return presetMatch;

        // Custom / manual class
        return {
            id: "manual",
            name: val.replace(/^fa-/, "").replace(/[-_]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
            class: val,
            category: "custom",
            isManual: true,
        };
    }

    get categories() {
        return [
            { id: "all", label: _t("All") },
            { id: "diagnostic", label: _t("Diagnostic") },
            { id: "emergency", label: _t("Emergency") },
            { id: "preventive", label: _t("Cleaning") },
            { id: "pediatric", label: _t("Pediatric") },
            { id: "endodontic", label: _t("Root Canal") },
            { id: "cosmetic", label: _t("Cosmetic") },
            { id: "orthodontic", label: _t("Orthodontics") },
            { id: "surgical", label: _t("Surgery") },
            { id: "prosthodontic", label: _t("Implants/Prosth.") },
            { id: "general", label: _t("General/Recalls") },
        ];
    }

    get filteredIcons() {
        const query = (this.state.searchQuery || "").trim().toLowerCase();
        const cat = this.state.selectedCategory;

        // Merge custom icons and presets
        const all = [...this.state.customIcons, ...DENTAL_PRESET_ICONS];

        return all.filter((icon) => {
            if (cat !== "all" && icon.category !== cat) {
                return false;
            }
            if (!query) {
                return true;
            }
            const nameMatch = icon.name.toLowerCase().includes(query);
            const classMatch = (icon.class || "").toLowerCase().includes(query);
            const tagsMatch = (icon.tags || "").toLowerCase().includes(query);
            return nameMatch || classMatch || tagsMatch;
        });
    }

    async selectIcon(iconItem) {
        if (!iconItem || !iconItem.class) return;
        await this.props.record.update({ [this.props.name]: iconItem.class });
    }

    togglePicker() {
        this.state.isOpen = !this.state.isOpen;
    }

    setCategory(catId) {
        this.state.selectedCategory = catId;
    }

    onSearchInput(ev) {
        this.state.searchQuery = ev.target.value;
    }

    clearSearch() {
        this.state.searchQuery = "";
    }

    toggleCustomInput() {
        this.state.customInputOpen = !this.state.customInputOpen;
        if (this.state.customInputOpen) {
            this.state.manualClassInput = this.currentValue || "fa-";
        }
    }

    async applyManualClass() {
        let cls = (this.state.manualClassInput || "").trim();
        if (cls && !cls.startsWith("fa-") && !cls.startsWith("fa ")) {
            cls = `fa-${cls}`;
        }
        if (cls) {
            await this.props.record.update({ [this.props.name]: cls });
            this.state.customInputOpen = false;
        }
    }

    openIconManager() {
        this.action.doAction("dental_appointment.action_dental_appointment_icon");
    }
}

export const dentalIconPicker = {
    component: DentalIconPicker,
    displayName: _t("Dental Visual Icon Picker"),
    supportedTypes: ["char"],
};

registry.category("fields").add("dental_icon_picker", dentalIconPicker);

