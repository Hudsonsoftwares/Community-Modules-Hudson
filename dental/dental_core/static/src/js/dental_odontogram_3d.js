/** @odoo-module **/

import { Component, Portal, onMounted, onPatched, onWillUnmount, onWillUpdateProps, signal, useProps, proxy } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

// 3D jaw (arch) view background
const JAW_BACKGROUND = 0xe2e8f0;

// Tooth-by-tooth chart: white teeth with a dark outline on a soft slate background, following
// standard dental charting. The white/outline edge is well above the 3:1 contrast WCAG 1.4.11 asks
// of graphical UI elements; condition colors (caries, restoration, ...) are unchanged.
const CHART_STYLE = {
    toothWhite: 0xffffff,
    toothGlow: 0.16,          // emissive intensity keeping healthy teeth white under scene lighting
    toothRoughness: 0.34,     // satin enamel: shaded enough to keep the 3D tooth shape readable
    outline: 0x1e293b,
    outlineOffset: 0.022,
    background: 0xcbd5e1,
};

// Tooth Studio (tooth-by-tooth view): anatomical side views drawn crown-down in a 44x90 box
// (viewBox -2 0 44 90; apex at the top, occlusal/incisal edge at the bottom) and occlusal views in
// a 44x44 box. Lower teeth and palatal/lingual views reuse the same paths, flipped in CSS.
//
// Each side view is ONE continuous silhouette (crown narrowing into the neck and flowing into the
// root) so the tooth reads as a single solid object. It is filled as cementum, then the part below
// the cemento-enamel junction (`enamel` region, bounded by the curved `cej` line) is re-filled as
// enamel. Proportions follow the average crown/root lengths of each tooth type.
const cejShape = (left, right, peak, y = 50) => ({
    enamel: `M-4 92 L-4 ${y} L${left} ${y} Q20 ${peak} ${right} ${y} L44 ${y} L44 92 Z`,
    cej: `M${left} ${y} Q20 ${peak} ${right} ${y}`,
});

const TOOTH_SHAPES = {
    incisor: {
        // Central incisor, labial view: straight incisal edge, rounded distal corner, conical root
        outline: "M20 4 C17.5 4.5 14 18 12 32 C11 40 10 46 10 50 C9.5 58 7.5 66 7 74 C6.8 80 7.5 85 10 86.5 C15 87.5 25 87.5 30 86.5 C32.8 85.5 33.4 80 33 74 C32.5 66 30.5 58 30 50 C30 46 29 40 28 32 C26 18 22.5 4.5 20 4 Z",
        ...cejShape(10, 30, 40),
        canals: ["M20 9 L20 47"],
        occlusal: "M6.5 19 C8 14.5 14 12.5 22 12.5 C30 12.5 36 14.5 37.5 19 C38 23 34 28 29 30 C25 31.5 19 31.5 15 30 C10 28 6 23 6.5 19 Z",
        grooves: "M8.5 18 C14 16.5 30 16.5 35.5 18 M17 27.5 C19.5 25 24.5 25 27 27.5",
        pits: [],
        cusps: [[22, 16, 6]],
    },
    canine: {
        // Canine, labial view: single pointed cusp with a short mesial slope, longest root
        outline: "M20 1.5 C17 2.5 13.5 17 12 31 C11 40 10.5 46 10.5 50 C9.5 58 7.5 64 7.2 70 C7 75 9.5 79.5 13 82.5 C15.5 84.8 18 87.5 20 89 C22 87.5 24.5 84.8 27 82.5 C30.5 79.5 33 75 32.8 70 C32.5 64 30.5 58 29.5 50 C29.5 46 29 40 28 31 C26.5 17 23 2.5 20 1.5 Z",
        ...cejShape(10.5, 29.5, 41),
        canals: ["M20 6 L20 47"],
        occlusal: "M10 22 C10 15 15.5 9.5 22 9 C28.5 9.5 34 15 34 22 C34 28 28.5 33 22 33.5 C15.5 33 10 28 10 22 Z",
        grooves: "M12 21 C16 19.5 19 18 22 17 C25 18 28 19.5 32 21 M22 17 L22 29",
        pits: [],
        cusps: [[22, 17, 6]],
    },
    premolar: {
        // Premolar, buccal view: prominent buccal cusp, single tapering root
        outline: "M20 6 C17 6.5 14 19 12.8 32 C12 41 11.5 47 11.5 50 C10 57 7.6 63 7.5 69 C7.4 75 9.5 80 13.5 83 C16 85 18 86.5 20 87 C22 86.5 24 85 26.5 83 C30.5 80 32.6 75 32.5 69 C32.4 63 30 57 28.5 50 C28.5 47 28 41 27.2 32 C26 19 23 6.5 20 6 Z",
        ...cejShape(11.5, 28.5, 42),
        canals: ["M20 11 L20 48"],
        occlusal: "M9 20 C9 11 14.5 6 22 6 C29.5 6 35 11 35 20 C35.5 29 30 37.5 22 37.5 C14 37.5 8.5 29 9 20 Z",
        grooves: "M12.5 21.3 C17 22.8 27 22.8 31.5 21.3",
        pits: [[13, 21.3, 0.9], [31, 21.3, 0.9]],
        cusps: [[22, 13, 8], [22, 30, 7]],
    },
    molar: {
        // First molar, buccal view: two buccal cusps with a buccal groove, root trunk splitting into
        // mesio- and disto-buccal roots; the palatal root shows behind them
        outline: "M10 8 C8 9 6 22 6.5 34 C6.8 42 6 47 6 50 C4 57 2.5 64 3 71 C3.3 77 5 81.5 8 83.5 C10.5 85.3 14.5 85.5 17 83.8 C18.3 82.8 19.3 82 20 82.3 C20.7 82 21.7 82.8 23 83.8 C25.5 85.5 29.5 85.3 32 83.5 C35 81.5 36.7 77 37 71 C37.5 64 36 57 34 50 C34 47 33.2 42 33.5 34 C34 22 32 9 30 8 C28 7.5 26.5 14 25 22 C24 28 23 34 20 36 C17 34 16 28 15 22 C13.5 14 12 7.5 10 8 Z",
        backRoot: "M16.5 37 C16 27 17.5 11 20.5 5.5 C23.5 11 24.5 27 23.5 37 Z",
        ...cejShape(6, 34, 46),
        canals: ["M11 12 C10.5 25 12 38 15 47", "M29 12 C29.5 25 28 38 25 47"],
        // Maxillary first molar occlusal table: rhomboid outline, oblique ridge, four cusps
        occlusal: "M7 9 C12 5 29 4.5 35 8.5 C39.5 11.5 40.5 18 39.5 24 C38.5 31 36 36.5 30 38.5 C23 40.5 13 40 8 36.5 C4 33.5 3.2 26 3.8 19 C4.2 14 4.8 11 7 9 Z",
        grooves: "M10.5 17 C14 19.5 18 18.8 21 21.5 C24 24 28 24.5 33 27 M21 21.5 C21.5 16 22.5 11.5 23.5 7.5 M26 25 C25 29.5 24 33 22.5 38",
        pits: [[21, 21.5, 1.1], [10.8, 17, 0.8], [32.6, 26.8, 0.8]],
        cusps: [[12.5, 12.5, 8], [29.5, 11.5, 8], [13, 30, 8], [31, 31, 7]],
    },
};

// Surface zones, clipped to the crown outline. Side views ("side") use the 44x90 box with the
// crown between y=48 and y=87; the occlusal view uses the 44x44 box. Mesial/distal are swapped at
// render time for teeth on the patient's left so mesial always faces the midline.
const SURFACE_ZONES = {
    side: {
        M: { x: 26, y: 48, w: 18, h: 40 },
        D: { x: -4, y: 48, w: 18, h: 40 },
        I: { x: -4, y: 77, w: 48, h: 13 },
        face: { x: 13, y: 54, w: 14, h: 24 },
        cervical: { x: -4, y: 46, w: 48, h: 9 },
        class4_mesial: { x: 23, y: 72, w: 21, h: 18 },
        class4_distal: { x: -4, y: 72, w: 21, h: 18 },
    },
    occlusal: {
        B: { x: 0, y: 0, w: 44, h: 13 },
        L: { x: 0, y: 31, w: 44, h: 13 },
        M: { x: 31, y: 10, w: 13, h: 24 },
        D: { x: 0, y: 10, w: 13, h: 24 },
        O: { x: 14, y: 14, w: 16, h: 16 },
    },
};

// Condition palette (kept in sync with the 3D material colors). `tint` recolours the crown,
// `hideRoots` is for pontics / implants where the natural root is absent.
const CHART_CONDITIONS = {
    caries: { tag: "CAR", color: "#ef4444" },
    restoration: { tag: "FIL", color: "#3b6fe0" },
    crown: { tag: "CRN", color: "#f59e0b", tint: "#fcd34d" },
    root_canal: { tag: "RCT", color: "#8b5cf6" },
    implant: { tag: "IMP", color: "#06b6d4", tint: "#cffafe", hideRoots: true },
    fracture: { tag: "FRX", color: "#e11d48" },
    extraction_indicated: { tag: "EXT", color: "#dc2626" },
    missing: { tag: "MIS", color: "#94a3b8" },
    impacted: { tag: "IMPC", color: "#ec4899" },
    bridge: { tag: "BRG", color: "#6366f1", tint: "#c7d2fe" },
    dummy_permanent: { tag: "PD", color: "#0d9488", tint: "#99f6e4", hideRoots: true },
    dummy_temporary: { tag: "TD", color: "#f97316", tint: "#fed7aa", hideRoots: true },
    other: { tag: "OTH", color: "#64748b" },
    sound: { tag: "", color: "#16a34a" },
};

// Conditions where a per-surface location is clinically meaningful
const SURFACE_CONDITIONS = new Set(["caries", "restoration", "fracture", "other"]);
// Conditions that cover the whole crown (crown drawn filled, every surface of the box filled)
const WHOLE_CROWN_CONDITIONS = new Set(["crown", "bridge", "implant", "dummy_permanent", "dummy_temporary"]);

// Five-surface occlusal diagram of the line-art chart (40x40 box): a cushion-shaped outline split
// into buccal / lingual / mesial / distal trapezoids around the occlusal (incisal) centre.
const BOX_OUTLINE = "M10 2 Q20 4.5 30 2 Q38 2 38 10 Q35.5 20 38 30 Q38 38 30 38 Q20 35.5 10 38 Q2 38 2 30 Q4.5 20 2 10 Q2 2 10 2 Z";
const BOX_PATHS = {
    top: "M0 0 H40 L26 14 H14 Z",
    bottom: "M14 26 H26 L40 40 H0 Z",
    left: "M0 0 L14 14 V26 L0 40 Z",
    right: "M40 0 V40 L26 26 V14 Z",
    centre: "M14 14 H26 V26 H14 Z",
};
const BOX_LINES = "M14 14 L5 5 M26 14 L35 5 M26 26 L35 35 M14 26 L5 35";
const CHART_ACCENT = "#7cb342";

// Restoration options of the Dental panel -> recorded condition + restoration type
const RESTORATION_OPTIONS = {
    filling: { condition: "restoration", type: "filling" },
    veneer: { condition: "restoration", type: "veneer" },
    crown: { condition: "crown", type: "crown" },
    inlay: { condition: "restoration", type: "inlay" },
    root_canal: { condition: "root_canal" },
    implant: { condition: "implant" },
    bridge: { condition: "bridge" },
    dummy_permanent: { condition: "dummy_permanent" },
    dummy_temporary: { condition: "dummy_temporary" },
};
const PATHOLOGY_CONDITIONS = ["caries", "fracture", "impacted", "extraction_indicated", "other"];

// Diagnosis categories suggested in the tooth window for the condition being charted
const DIAGNOSIS_SUGGESTIONS = {
    caries: ["caries", "pulpal"],
    fracture: ["trauma"],
    impacted: ["developmental"],
    extraction_indicated: ["prosthetic", "periapical", "periodontal"],
    missing: ["prosthetic"],
    root_canal: ["pulpal", "periapical"],
    restoration: ["caries"],
    crown: ["caries", "trauma"],
    other: ["other"],
    "": ["caries", "pulpal", "periapical", "periodontal"],
};

const ENDO_TEST_KEYS =["cold", "heat", "electric", "percussion", "palpation", "bite", "chewing", "air", "occlusal_trauma", "sinus_tract"];
const PERIO_SITE_KEYS = ["perio_db", "perio_b", "perio_mb", "perio_dl", "perio_l", "perio_ml"];

export class DentalOdontogram3DField extends Component {
    static template = "dental_core.OdontogramField";
    static components = { Portal };
    props = useProps({
        ...standardFieldProps,
    });

    canvasContainerRef = signal.ref();
    viewportRef = signal.ref();
    wrapperRef = signal.ref();

    get wrapperEl() {
        return typeof this.wrapperRef === "function" ? this.wrapperRef() : (this.wrapperRef?.el || null);
    }

    get containerEl() {
        return typeof this.canvasContainerRef === "function" ? this.canvasContainerRef() : (this.canvasContainerRef?.el || null);
    }

    get viewportEl() {
        return typeof this.viewportRef === "function" ? this.viewportElInternal : (this.viewportRef?.el || null);
    }

    get viewportElInternal() {
        return typeof this.viewportRef === "function" ? this.viewportRef() : null;
    }

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");

        this.patientId = this.getPatientId();
        this.caseId = this.getCaseId();
        this.webglFailed = false;

        this.state = proxy({
            patientId: this.patientId,
            patientName: "",
            patientRef: "",
            patientAge: null,
            patientDob: "",
            caseId: this.caseId,
            caseName: "",
            canEdit: false,
            isDentist: false,
            selectedTooth: null,
            viewMode: "jaw", // 'jaw' (default 3D arch overview) or 'chart' (2-row tooth-by-tooth frontal chart)
            webglError: false,
            webglErrorDetail: "",
            dentitionType: "permanent", // 'primary' (20), 'mixed' (mixed), 'permanent' (32)
            suggestedDentition: "permanent",
            currentView: "front",
            hoveredTooth: null,
            hoveredToothInfo: "",
            tooltipX: 0,
            tooltipY: 0,
            activePanelTab: "record",
            isSaving: false,
            isLoadingModel: false,
            showSeparations: true,
            chartSelection: [], // teeth picked on the 2D chart for bulk "mark as problem"
            chartScreen: "overview", // kept for extensions; the single-tooth studio now opens in its own window
            toothWindowOpen: false, // single-tooth studio shown as a modal window (Esc closes it)
            toothSearch: { open: false, query: "", activeIndex: 0 }, // type-a-number "go to tooth" palette
            dxCategory: "", // Dental panel step: '', 'missing', 'pathology' or 'restoration'
            dxHoverSurface: "", // surface chip under the pointer, previewed on the tooth drawings
            dxDiagnosisQuery: "", // diagnosis search text in the tooth window
            stats: {
                sound: 32,
                caries: 0,
                restoration: 0,
                crown: 0,
                root_canal: 0,
                missing: 0,
                dummy_permanent: 0,
                dummy_temporary: 0,
                total_teeth: 32,
            },
            diagnosisMasters: [],
            newFinding: {
                condition: "caries",
                diagnosis_id: "",
                surfaces: ["O"],
                severity: "moderate",
                treatment_indicated: "",
                notes: "",
                restoration_type: "",
                restoration_material: "",
                restoration_quality: "",
                restoration_detail: "",
                surface_details: [],
                endo_tests: {},
                perio: {},
            },
            teeth: {},
        });
        // Unique prefix for SVG clip-path ids (several odontograms may share a page)
        this.dxUid = `dx${Math.random().toString(36).slice(2, 8)}`;

        // 3D Scene Properties
        this.scene = null;
        this.camera = null;
        this.renderer = null;
        this.controls = null;
        this.toothMeshes = {}; // toothNumber -> { mesh, group, isUpper, basePos, toothNumber }
        this.chartToothMeshes = {}; // toothNumber -> { mesh, outlineMesh, isUpper, basePos, toothNumber, isChart }
        this.chartRoot = null;
        this.savedJawCameraPos = null;
        this.savedJawTarget = null;
        this.raycaster = null;
        this.pointer = null;
        this.lastBreathingMesh = null;
        this.animationFrameId = null;
        this.resizeObserver = null;
        this.intersectionObserver = null;
        this.tabMutationObserver = null;
        this.onWindowResizeBound = null;
        this.is3DReady = false;
        this._needsChartAlign = true;
        this._lastAlignedCanvasWidth = 0;

        this.onGlobalKeydownBound = (ev) => this.onGlobalKeydown(ev);

        onMounted(async () => {
            this._dxSignature = this.recordDiagnosisSignature;
            window.addEventListener("keydown", this.onGlobalKeydownBound, true);
            try {
                await this.init3DScene();
            } catch (err) {
                this.handle3DInitError(err);
            }
            await this.loadOdontogram();
        });

        onWillUpdateProps(async (nextProps) => {
            const nextPatientId = this.getPatientId(nextProps);
            const nextCaseId = this.getCaseId(nextProps);
            if (nextPatientId !== this.patientId || nextCaseId !== this.caseId) {
                this.patientId = nextPatientId;
                this.caseId = nextCaseId;
                await this.loadOdontogram();
            }
        });

        onPatched(async () => {
            if (!this.is3DReady && !this.webglFailed) {
                try {
                    await this.init3DScene();
                } catch (err) {
                    this.handle3DInitError(err);
                }
            }
            const currentPatientId = this.getPatientId();
            const currentCaseId = this.getCaseId();
            const diagnosisSignature = this.recordDiagnosisSignature;
            if (currentPatientId !== this.patientId || currentCaseId !== this.caseId) {
                this.patientId = currentPatientId;
                this.caseId = currentCaseId;
                this._dxSignature = diagnosisSignature;
                await this.loadOdontogram();
            } else if (diagnosisSignature !== this._dxSignature) {
                // A diagnosis was added / confirmed / resolved in the case's Diagnosis list
                const firstRead = this._dxSignature === undefined;
                this._dxSignature = diagnosisSignature;
                if (!firstRead) await this.loadOdontogram();
            }
        });

        onWillUnmount(() => {
            window.removeEventListener("keydown", this.onGlobalKeydownBound, true);
            this.cleanup3D();
        });
    }

    handle3DInitError(err) {
        if (this.renderer && this.is3DReady) {
            // WebGL works; something later (e.g. the GLB model download) failed. Don't brand it a WebGL failure.
            console.warn("Odontogram: 3D scene created but a later step failed:", err);
            this.state.isLoadingModel = false;
            return;
        }
        console.warn("Failed to initialize 3D scene:", err);
        this.cleanup3D();
        this.webglFailed = true;
        this.state.webglError = true;
        this.state.viewMode = "chart";
        this.state.isLoadingModel = false;
    }

    getPatientId(props = this.props) {
        const p = props?.record?.data?.patient_id;
        if (!p) return false;
        if (typeof p === "object" && p.id) return p.id;
        if (Array.isArray(p) && p.length > 0) return p[0];
        if (typeof p === "number") return p;
        return false;
    }

    getCaseId(props = this.props) {
        return props?.record?.resId || props?.record?.data?.id || false;
    }

    // -------------------------------------------------------------------------
    // Getters for Template
    // -------------------------------------------------------------------------

    get upperRightTeeth() {
        if (this.state.dentitionType === "primary") {
            return ["55", "54", "53", "52", "51"];
        } else if (this.state.dentitionType === "mixed") {
            return ["16", "55", "54", "53", "12", "11"];
        }
        return ["18", "17", "16", "15", "14", "13", "12", "11"];
    }

    get upperLeftTeeth() {
        if (this.state.dentitionType === "primary") {
            return ["61", "62", "63", "64", "65"];
        } else if (this.state.dentitionType === "mixed") {
            return ["21", "22", "63", "64", "65", "26"];
        }
        return ["21", "22", "23", "24", "25", "26", "27", "28"];
    }

    get lowerLeftTeeth() {
        if (this.state.dentitionType === "primary") {
            return ["71", "72", "73", "74", "75"];
        } else if (this.state.dentitionType === "mixed") {
            return ["31", "32", "73", "74", "75", "36"];
        }
        return ["31", "32", "33", "34", "35", "36", "37", "38"];
    }

    get lowerRightTeeth() {
        if (this.state.dentitionType === "primary") {
            return ["85", "84", "83", "82", "81"];
        } else if (this.state.dentitionType === "mixed") {
            return ["46", "85", "84", "83", "42", "41"];
        }
        return ["48", "47", "46", "45", "44", "43", "42", "41"];
    }

    get allTeethList() {
        const allNums = [
            ...this.upperRightTeeth,
            ...this.upperLeftTeeth,
            ...this.lowerRightTeeth,
            ...this.lowerLeftTeeth,
        ];
        return allNums.map((tn) => {
            const d = this.state.teeth[tn] || {};
            return {
                number: tn,
                name: d.tooth_name || `Tooth ${tn}`,
                condition: d.condition || "sound",
            };
        });
    }

    // -------------------------------------------------------------------------
    // Dentition Tooth Groups & Clinical Treatment State Helpers
    // -------------------------------------------------------------------------

    get adultPermanentTeeth() {
        const list = [];
        for (let q = 1; q <= 4; q++) {
            for (let p = 1; p <= 8; p++) {
                list.push(`${q}${p}`);
            }
        }
        return list;
    }

    get permanentExclusiveTeeth() {
        return [
            "13", "14", "15", "17", "18",
            "23", "24", "25", "27", "28",
            "33", "34", "35", "37", "38",
            "43", "44", "45", "47", "48",
        ];
    }

    get mixedPermanentTeeth() {
        return ["11", "12", "16", "21", "22", "26", "31", "32", "36", "41", "42", "46"];
    }

    get primaryTeethList() {
        const list = [];
        for (let q = 5; q <= 8; q++) {
            for (let p = 1; p <= 5; p++) {
                list.push(`${q}${p}`);
            }
        }
        return list;
    }

    hasToothChanges(tNum) {
        if (!tNum) return false;
        const tooth = this.state.teeth && this.state.teeth[tNum];
        if (!tooth) return false;

        const isConditionModified = tooth.condition && tooth.condition !== "sound";
        const hasHistory = Array.isArray(tooth.history) && tooth.history.length > 0;
        const hasDiagnoses = Array.isArray(tooth.diagnoses) && tooth.diagnoses.length > 0;
        const hasCompletedTreatments = Array.isArray(tooth.completed_treatments) && tooth.completed_treatments.length > 0;
        const hasProposedTreatments = Array.isArray(tooth.proposed_treatments) && tooth.proposed_treatments.length > 0;
        const hasSessions = Array.isArray(tooth.sessions) && tooth.sessions.length > 0;
        const findingsCount = (tooth.findings_count || 0) > 0;

        // Also check if currently selected tooth has unsaved active finding
        const isCurrentActiveChange = (this.state.selectedTooth === tNum) &&
            this.state.newFinding && this.state.newFinding.condition !== "sound";

        return (
            isConditionModified ||
            hasHistory ||
            hasDiagnoses ||
            hasCompletedTreatments ||
            hasProposedTreatments ||
            hasSessions ||
            findingsCount ||
            isCurrentActiveChange
        );
    }

    hasTreatedPermanentTeeth() {
        return this.adultPermanentTeeth.some((tn) => this.hasToothChanges(tn));
    }

    hasTreatedPermanentExclusiveTeeth() {
        return this.permanentExclusiveTeeth.some((tn) => this.hasToothChanges(tn));
    }

    hasTreatedMixedPermanentTeeth() {
        return this.mixedPermanentTeeth.some((tn) => this.hasToothChanges(tn));
    }

    hasAnyTreatedTeethInCurrentDentition() {
        return this.allTeethList.some((t) => this.hasToothChanges(t.number));
    }

    isDentitionDisabled(targetType) {
        if (!targetType) return false;
        const current = this.state.dentitionType || "permanent";
        if (targetType === current) {
            return false;
        }

        const ranks = { primary: 1, mixed: 2, permanent: 3 };
        const currentRank = ranks[current] || 3;
        const targetRank = ranks[targetType] || 3;

        // Forward switches are naturally allowed: Primary -> Mixed -> Permanent
        if (targetRank > currentRank) {
            return false;
        }

        // Backward switch to Primary:
        // A person treated with permanent teeth or in mixed/permanent dentition cannot regress to deciduous teeth
        if (targetType === "primary") {
            if (this.hasTreatedPermanentTeeth() || this.hasAnyTreatedTeethInCurrentDentition()) {
                return true;
            }
        }

        // Backward switch from Permanent to Mixed:
        // A person treated under permanent dentition (32 teeth) or with permanent-exclusive teeth cannot regress backwards
        if (current === "permanent" && targetType === "mixed") {
            if (
                this.hasTreatedPermanentExclusiveTeeth() ||
                this.hasTreatedPermanentTeeth() ||
                this.hasAnyTreatedTeethInCurrentDentition()
            ) {
                return true;
            }
        }

        return false;
    }

    getDentitionTooltip(targetType) {
        if (this.isDentitionDisabled(targetType)) {
            if (this.state.dentitionType === "permanent") {
                return _t(
                    "Cannot switch back to %s dentition: A patient with findings or treatments on 32 teeth (permanent dentition) cannot be switched backwards.",
                    targetType === "primary" ? _t("Primary") : _t("Mixed")
                );
            }
            if (this.state.dentitionType === "mixed" && targetType === "primary") {
                return _t(
                    "Cannot switch back to Primary dentition: Dental findings or treatments have already been recorded on permanent / mixed teeth."
                );
            }
            return _t("Switching backwards is not allowed once treatments or tooth changes have been recorded.");
        }

        if (targetType === "primary") {
            return _t("Primary / Deciduous Dentition (20 teeth • Ages 0–5)");
        } else if (targetType === "mixed") {
            return _t("Mixed Dentition (Primary & Permanent teeth • Ages 6–12)");
        }
        return _t("Permanent Adult Dentition (Up to 32 teeth • Ages 13+)");
    }

    get selectedToothData() {
        const tn = this.state.selectedTooth;
        if (!tn || !this.state.teeth[tn]) {
            return {
                tooth_name: _t("Select Tooth"),
                condition: "sound",
                surfaces: "",
                severity: "",
                universal_number: "",
                palmer_notation: "",
                history: [],
                diagnoses: [],
                proposed_treatments: [],
                completed_treatments: [],
                sessions: [],
            };
        }
        return this.state.teeth[tn];
    }

    get selectedToothHistory() {
        return this.selectedToothData.history || [];
    }

    get selectedToothTreatments() {
        return this.selectedToothData.proposed_treatments || [];
    }

    getConditionLabel(cond) {
        const labels = {
            sound: _t("Sound / Healthy"),
            caries: _t("Caries / Cavity"),
            restoration: _t("Restoration / Filled"),
            crown: _t("Crown / Cap"),
            root_canal: _t("Root Canal Treated"),
            implant: _t("Dental Implant"),
            missing: _t("Missing Tooth"),
            dummy_permanent: _t("Permanent Dummy Tooth"),
            dummy_temporary: _t("Temporary Dummy Tooth"),
            fracture: _t("Fracture / Chipped"),
            impacted: _t("Impacted"),
            extraction_indicated: _t("Extraction Indicated"),
            bridge: _t("Bridge Pontic"),
            other: _t("Other Finding"),
        };
        return labels[cond] || cond || _t("Sound");
    }

    isMissingTooth(tNum) {
        const cond = this.state.teeth[tNum]?.condition;
        return cond === "missing";
    }

    // -------------------------------------------------------------------------
    // Tooth Studio (tooth-by-tooth view): arch overview + single-tooth workspace
    // -------------------------------------------------------------------------

    get chartMarkOptions() {
        const labels = {
            caries: _t("Caries"),
            restoration: _t("Filling"),
            crown: _t("Crown"),
            root_canal: _t("Root Canal"),
            implant: _t("Implant"),
            fracture: _t("Fracture"),
            extraction_indicated: _t("Extraction"),
            missing: _t("Missing"),
            impacted: _t("Impacted"),
            bridge: _t("Bridge"),
            dummy_permanent: _t("Perm Dummy"),
            dummy_temporary: _t("Temp Dummy"),
            other: _t("Other"),
            sound: _t("Healthy"),
        };
        return Object.entries(labels).map(([key, label]) => ({
            key,
            label,
            color: CHART_CONDITIONS[key].color,
        }));
    }

    get chartConditionCounts() {
        const counts = {};
        for (const { number } of this.allTeethList) {
            const cond = this.state.teeth[number]?.condition || "sound";
            if (cond !== "sound") {
                counts[cond] = (counts[cond] || 0) + 1;
            }
        }
        return counts;
    }

    getToothKind(tNum) {
        const quadrant = Number(String(tNum)[0]);
        const position = Number(String(tNum)[1]);
        if (position <= 2) return "incisor";
        if (position === 3) return "canine";
        // Primary dentition (quadrants 5-8) has no premolars: positions 4-5 are deciduous molars
        if (quadrant >= 5) return "molar";
        return position <= 5 ? "premolar" : "molar";
    }

    isUpperTooth(tNum) {
        return [1, 2, 5, 6].includes(Number(String(tNum)[0]));
    }

    isPatientRightTooth(tNum) {
        return [1, 4, 5, 8].includes(Number(String(tNum)[0]));
    }

    // Zones are drawn for a patient-right tooth (mesial on the viewer's right); mirror for the left side
    mirrorZoneKey(key, mirrored) {
        if (!mirrored) return key;
        const swap = { M: "D", D: "M", class4_mesial: "class4_distal", class4_distal: "class4_mesial" };
        return swap[key] || key;
    }

    getOcclusalZones(tNum, letters) {
        const mirrored = !this.isPatientRightTooth(tNum);
        const zones = [];
        for (const letter of ["B", "L", "M", "D"]) {
            if (letters.includes(letter)) {
                zones.push({ key: letter, ...SURFACE_ZONES.occlusal[this.mirrorZoneKey(letter, mirrored)] });
            }
        }
        if (letters.includes("O") || letters.includes("I")) {
            zones.push({ key: "O", ...SURFACE_ZONES.occlusal.O });
        }
        return zones;
    }

    getSideZones(tNum, letters, details, faceLetter, cervicalCode, isPalatalView) {
        // Seen from the palate the tooth is mirrored left-to-right
        const mirrored = !this.isPatientRightTooth(tNum) !== isPalatalView;
        const zones = [];
        for (const letter of ["M", "D"]) {
            if (letters.includes(letter)) {
                zones.push({ key: letter, ...SURFACE_ZONES.side[this.mirrorZoneKey(letter, mirrored)] });
            }
        }
        if (letters.includes("O") || letters.includes("I")) {
            zones.push({ key: "I", ...SURFACE_ZONES.side.I });
        }
        if (letters.includes(faceLetter)) {
            zones.push({ key: faceLetter, ...SURFACE_ZONES.side.face });
        }
        if (details.includes(cervicalCode)) {
            zones.push({ key: cervicalCode, ...SURFACE_ZONES.side.cervical });
        }
        for (const code of ["class4_mesial", "class4_distal"]) {
            if (details.includes(code)) {
                zones.push({ key: code, ...SURFACE_ZONES.side[this.mirrorZoneKey(code, mirrored)] });
            }
        }
        return zones;
    }

    getStudioTooth(tNum, isUpper = this.isUpperTooth(tNum)) {
        const data = this.state.teeth[tNum] || {};
        const cond = data.condition || "sound";
        const style = CHART_CONDITIONS[cond] || CHART_CONDITIONS.other;
        const kind = this.getToothKind(tNum);
        const letters = SURFACE_CONDITIONS.has(cond) ? (data.surfaces || "").toUpperCase() : "";
        const perio = data.perio || {};
        const fmt = (v) => ({ value: v ? String(v) : "·", level: v >= 5 ? "deep" : v === 4 ? "watch" : "" });
        // Probing sites read distal -> mesial towards the midline
        const ordered = (d, mid, m) => (this.isPatientRightTooth(tNum) ? [d, mid, m] : [m, mid, d]);
        // Surfaces filled on the 5-surface box: the recorded surfaces (occlusal if none was given),
        // or every surface for whole-crown work
        const wholeCrown = WHOLE_CROWN_CONDITIONS.has(cond);
        const boxLetters = SURFACE_CONDITIONS.has(cond) ? letters || "O" : wholeCrown ? "*" : "";
        const isPrimary = Number(String(tNum)[0]) >= 5;
        const condLabel = this.getConditionLabel(cond);
        const surfaceText = SURFACE_CONDITIONS.has(cond) && letters ? ` (${letters})` : "";
        const openDiagnoses = this.getOpenDiagnoses(tNum);
        const diagnosisText = openDiagnoses.length
            ? ` • ${_t("Diagnosis")}: ${openDiagnoses.map((d) => this.diagnosisLabel(d)).join("; ")}`
            : "";
        return {
            num: tNum,
            cond,
            kind,
            isUpper,
            isPrimary,
            dxCount: openDiagnoses.length,
            color: style.color,
            tag: style.tag,
            tint: style.tint || "",
            shape: TOOTH_SHAPES[kind],
            showRoots: !style.hideRoots,
            crownClip: `url(#${this.dxUid}-crown-${kind})`,
            crownFill: wholeCrown ? style.color : "",
            box: this.getBoxRegions(tNum, isUpper, boxLetters, style.color),
            occlusalZones: this.getOcclusalZones(tNum, letters),
            perioOuter: ordered(perio.perio_db, perio.perio_b, perio.perio_mb).map(fmt),
            perioInner: ordered(perio.perio_dl, perio.perio_l, perio.perio_ml).map(fmt),
            clipId: `${this.dxUid}-o-${tNum}`,
            title: `${_t("Tooth")} ${tNum} • ${data.tooth_name || ""} • ${condLabel}${surfaceText}${diagnosisText}`,
            tipName: data.tooth_name || `${_t("Tooth")} ${tNum}`,
            tipCondition: condLabel,
            classes: {
                [`dx-kind-${kind}`]: true,
                [`dx-cond-${cond}`]: true,
                "dx-primary": isPrimary,
                "is-marked": cond !== "sound",
                "is-selected": this.state.chartSelection.length > 1 && this.state.chartSelection.includes(tNum),
                "is-focused": this.state.selectedTooth === tNum,
            },
        };
    }

    // ---- Diagnoses -------------------------------------------------------------

    /** Open (not resolved) patient diagnoses on one tooth, from every visit. */
    getOpenDiagnoses(tNum) {
        const items = this.state.teeth[tNum]?.diagnoses || [];
        // Finding-based entries repeat the patient diagnosis records: keep the records only, and
        // the latest one when the same diagnosis was left open on several visits (newest first)
        const seen = new Set();
        return items.filter((d) => {
            if (!String(d.key || "").startsWith("diagnosis_") || d.status === "resolved" || seen.has(d.diagnosis_id)) {
                return false;
            }
            seen.add(d.diagnosis_id);
            return true;
        });
    }

    diagnosisLabel(diag) {
        return [diag.diagnosis_code, diag.diagnosis_name].filter(Boolean).join(" ");
    }

    get dxToothDiagnoses() {
        const tNum = this.state.selectedTooth;
        if (!tNum) return [];
        const caseId = this.caseId || this.getCaseId();
        return this.getOpenDiagnoses(tNum).map((d) => ({
            ...d,
            label: this.diagnosisLabel(d),
            earlier: Boolean(d.case_id && caseId && d.case_id !== caseId),
        }));
    }

    get dxSelectedDiagnosis() {
        const id = Number(this.state.newFinding.diagnosis_id) || 0;
        if (!id) return null;
        const master = (this.state.diagnosisMasters || []).find((m) => m.id === id);
        return master ? { ...master, label: this.diagnosisLabel({ diagnosis_code: master.code, diagnosis_name: master.name }) } : null;
    }

    /** Search results, or suggestions for the condition being charted when nothing is typed. */
    get dxDiagnosisResults() {
        const masters = this.state.diagnosisMasters || [];
        const taken = new Set(this.dxToothDiagnoses.map((d) => d.diagnosis_id));
        const selected = Number(this.state.newFinding.diagnosis_id) || 0;
        const query = (this.state.dxDiagnosisQuery || "").trim().toLowerCase();
        let list;
        if (query) {
            list = masters.filter((m) => (m.code || "").toLowerCase().includes(query) || (m.name || "").toLowerCase().includes(query));
        } else {
            const condition = this.state.dxCategory ? this.state.newFinding.condition : "";
            const categories = DIAGNOSIS_SUGGESTIONS[condition] || DIAGNOSIS_SUGGESTIONS[""];
            list = masters
                .filter((m) => categories.includes(m.category))
                .sort((a, b) => categories.indexOf(a.category) - categories.indexOf(b.category));
        }
        return list
            .filter((m) => !taken.has(m.id) && m.id !== selected)
            .slice(0, query ? 8 : 6)
            .map((m) => ({ ...m, label: this.diagnosisLabel({ diagnosis_code: m.code, diagnosis_name: m.name }) }));
    }

    setDxDiagnosisQuery(value) {
        this.state.dxDiagnosisQuery = value || "";
    }

    pickDiagnosis(id) {
        this.state.newFinding.diagnosis_id = id;
        this.state.dxDiagnosisQuery = "";
    }

    clearDxDiagnosis() {
        this.state.newFinding.diagnosis_id = "";
    }

    onDiagnosisSearchKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            ev.stopPropagation();
            const first = this.dxDiagnosisResults[0];
            if (first) this.pickDiagnosis(first.id);
        }
    }

    /** Resolve one of the tooth's diagnoses from the tooth window. */
    async resolveToothDiagnosis(diagnosisRecordId) {
        if (!diagnosisRecordId) return;
        this.state.isSaving = true;
        try {
            await this.orm.call("dental.patient.diagnosis", "action_mark_resolved", [[diagnosisRecordId]]);
            await this.reloadAfterDiagnosisChange();
            this.notification.add(_t("Diagnosis resolved"), { type: "success" });
        } catch (error) {
            this.notification.add(error.message || _t("Could not resolve the diagnosis."), { type: "danger" });
        } finally {
            this.state.isSaving = false;
        }
    }

    /** Refresh the chart and the case's Diagnosis list after a diagnosis changed. */
    async reloadAfterDiagnosisChange() {
        const tNum = this.state.selectedTooth;
        await this.loadOdontogram();
        if (tNum && this.state.toothWindowOpen) {
            this.selectTooth(tNum, { keepChartSelection: true });
        }
        await this.notifyRecordChanged();
        if (this.props.record && typeof this.props.record.save === "function") {
            await this.props.record.save();
        }
    }

    /**
     * Ids + statuses of the case's Diagnosis list. Read while rendering so the chart re-renders
     * (and reloads, see onPatched) when a diagnosis is added, confirmed or resolved in that list.
     */
    get recordDiagnosisSignature() {
        const list = this.props.record?.data?.patient_diagnosis_ids;
        const records = list?.records || [];
        return records.map((r) => `${r.resId}:${r.data?.status || ""}`).join(",");
    }

    /**
     * Regions of the 5-surface box for one tooth. Buccal faces the outside of the chart (top for
     * the upper arch, bottom for the lower) and mesial faces the midline. `letters` are the surface
     * letters to fill ("*" fills all of them).
     */
    getBoxRegions(tNum, isUpper, letters = "", color = "") {
        const right = this.isPatientRightTooth(tNum);
        const kind = this.getToothKind(tNum);
        const centre = kind === "incisor" || kind === "canine" ? "I" : "O";
        const regions = [
            { key: "top", code: isUpper ? "B" : "L" },
            { key: "left", code: right ? "D" : "M" },
            { key: "centre", code: centre },
            { key: "right", code: right ? "M" : "D" },
            { key: "bottom", code: isUpper ? "L" : "B" },
        ];
        return regions.map((region) => {
            const on = letters === "*"
                || letters.includes(region.code)
                || (region.key === "centre" && /[OI]/.test(letters));
            return { ...region, path: BOX_PATHS[region.key], fill: on ? color : "" };
        });
    }

    /** Line-art chart: upper arch over lower arch, patient's right on the viewer's left. */
    get chartArches() {
        const build = (key, isUpper, right, left) => ({
            key,
            isUpper,
            count: right.length + left.length,
            teeth: [...right, ...left].map((t, idx) => ({
                ...this.getStudioTooth(t, isUpper),
                midStart: idx === right.length,
            })),
        });
        return [
            build("upper", true, this.upperRightTeeth, this.upperLeftTeeth),
            build("lower", false, this.lowerRightTeeth, this.lowerLeftTeeth),
        ];
    }

    /** One crown clip per tooth type, shared by every drawing (chart and tooth window). */
    get crownClipShapes() {
        return Object.entries(TOOTH_SHAPES).map(([kind, shape]) => ({ kind, enamel: shape.enamel }));
    }

    get boxOutline() {
        return BOX_OUTLINE;
    }

    get boxLines() {
        return BOX_LINES;
    }

    /** Conditions present on the chart, with their tooth count (compact legend). */
    get chartLegend() {
        const counts = this.chartConditionCounts;
        return this.chartMarkOptions
            .filter((opt) => opt.key !== "sound" && counts[opt.key])
            .map((opt) => ({ ...opt, count: counts[opt.key] }));
    }

    /** Compact Permanent / Mixed / Primary switch (replaces the large dentition bar). */
    get dentitionOptions() {
        const labels = { permanent: _t("Permanent"), mixed: _t("Mixed"), primary: _t("Primary") };
        return ["permanent", "mixed", "primary"].map((key) => ({
            key,
            label: labels[key],
            active: this.state.dentitionType === key,
            locked: this.isDentitionDisabled(key),
            suggested: this.state.suggestedDentition === key,
            title: this.getDentitionTooltip(key),
        }));
    }

    /** Colour used to preview the surfaces picked in the tooth window. */
    get dxPendingColor() {
        const cond = this.state.newFinding.condition;
        return (this.state.dxCategory && CHART_CONDITIONS[cond]?.color) || CHART_ACCENT;
    }

    /** Clickable 5-surface diagram of the tooth window, with the surface names around it. */
    get focusSurfaceBox() {
        const tNum = this.state.selectedTooth;
        if (!tNum) return null;
        const chips = this.studioSurfaceChips;
        const labels = {};
        for (const chip of [chips.top, ...chips.middle, chips.bottom]) {
            labels[chip.code] = chip.label;
        }
        const color = this.dxPendingColor;
        const regions = this.getBoxRegions(tNum, this.isUpperTooth(tNum)).map((region) => ({
            ...region,
            label: labels[region.code] || region.code,
            active: this.hasSurface(region.code),
            hovered: this.state.dxHoverSurface === region.code,
            fill: this.hasSurface(region.code) ? color : "",
        }));
        return { regions, byKey: Object.fromEntries(regions.map((r) => [r.key, r])) };
    }

    get studioRailTeeth() {
        return [
            ...this.upperRightTeeth,
            ...this.upperLeftTeeth,
            ...this.lowerLeftTeeth.slice().reverse(),
            ...this.lowerRightTeeth.slice().reverse(),
        ].map((tNum) => {
            const cond = this.state.teeth[tNum]?.condition || "sound";
            return {
                num: tNum,
                color: CHART_CONDITIONS[cond]?.color || CHART_CONDITIONS.other.color,
                classes: {
                    active: this.state.selectedTooth === tNum,
                    "is-marked": cond !== "sound",
                    "jaw-start": tNum === this.lowerLeftTeeth[this.lowerLeftTeeth.length - 1],
                },
            };
        });
    }

    get studioFocusTooth() {
        const tNum = this.state.selectedTooth;
        if (!tNum) return null;
        const tooth = this.getStudioTooth(tNum);
        const finding = this.state.newFinding;
        const letters = finding.surfaces.join("").toUpperCase();
        const details = finding.surface_details;
        // Surface chip under the pointer: single letters are classic surfaces, longer codes are areas
        const hover = this.state.dxHoverSurface;
        const hoverLetters = hover.length === 1 ? hover : "";
        const hoverDetails = hover.length > 1 ? [hover] : [];
        return {
            ...tooth,
            hoverBuccal: hover ? this.getSideZones(tNum, hoverLetters, hoverDetails, "B", "cervical_buccal", false) : [],
            hoverPalatal: hover ? this.getSideZones(tNum, hoverLetters, hoverDetails, "L", "cervical_lingual", true) : [],
            hoverOcclusal: hoverLetters ? this.getOcclusalZones(tNum, hoverLetters) : [],
            name: this.state.teeth[tNum]?.tooth_name || `${_t("Tooth")} ${tNum}`,
            buccalZones: this.getSideZones(tNum, letters, details, "B", "cervical_buccal", false),
            palatalZones: this.getSideZones(tNum, letters, details, "L", "cervical_lingual", true),
            occlusalPending: this.getOcclusalZones(tNum, letters),
            clipBuccal: `${this.dxUid}-fb`,
            clipPalatal: `${this.dxUid}-fp`,
            clipOcclusal: `${this.dxUid}-fo`,
            lingualLabel: tooth.isUpper ? _t("Palatal") : _t("Lingual"),
        };
    }

    get studioSurfaceChips() {
        const tNum = this.state.selectedTooth;
        if (!tNum) return null;
        const kind = this.getToothKind(tNum);
        const anterior = kind === "incisor" || kind === "canine";
        const lingual = this.isUpperTooth(tNum) ? _t("Palatal") : _t("Lingual");
        const centre = anterior
            ? { code: "I", label: _t("Incisal") }
            : { code: "O", label: _t("Occlusal") };
        const mesial = { code: "M", label: _t("Mesial") };
        const distal = { code: "D", label: _t("Distal") };
        const mark = (chip) => ({ ...chip, active: this.hasSurface(chip.code) });
        const detail = (code, label) => ({ code, label, active: this.state.newFinding.surface_details.includes(code) });
        const extras = [
            detail("cervical_buccal", _t("Cervical Buccal")),
            detail("cervical_lingual", _t("Cervical %s", lingual)),
        ];
        if (anterior) {
            extras.push(detail("class4_mesial", _t("Class IV Mesial")), detail("class4_distal", _t("Class IV Distal")));
        }
        return {
            top: mark({ code: "B", label: anterior ? _t("Labial") : _t("Buccal") }),
            // Mesial sits on the midline side, as on the chart
            middle: (this.isPatientRightTooth(tNum) ? [distal, centre, mesial] : [mesial, centre, distal]).map(mark),
            bottom: mark({ code: "L", label: lingual }),
            extras,
        };
    }

    // ---- Dental panel -------------------------------------------------------

    get dxRestorationOptions() {
        const labels = {
            filling: _t("Filling"),
            veneer: _t("Veneer"),
            crown: _t("Crown"),
            inlay: _t("Inlay / Onlay"),
            root_canal: _t("Root Canal"),
            implant: _t("Implant"),
            bridge: _t("Bridge"),
            dummy_permanent: _t("Perm Dummy"),
            dummy_temporary: _t("Temp Dummy"),
        };
        const current = this.dxRestorationKey;
        return Object.entries(labels).map(([key, label]) => ({ key, label, active: key === current }));
    }

    get dxRestorationKey() {
        const { condition, restoration_type } = this.state.newFinding;
        if (this.state.dxCategory !== "restoration") return "";
        if (condition === "restoration") return restoration_type || "filling";
        return RESTORATION_OPTIONS[condition] ? condition : "";
    }

    get dxHasMaterial() {
        return ["filling", "veneer", "crown", "inlay"].includes(this.dxRestorationKey);
    }

    get dxPathologyOptions() {
        return PATHOLOGY_CONDITIONS.map((key) => ({
            key,
            label: this.getConditionLabel(key),
            active: this.state.dxCategory === "pathology" && this.state.newFinding.condition === key,
        }));
    }

    get dxDetailGroups() {
        const f = this.state.newFinding;
        const group = (field, title, options) => ({
            field,
            title,
            options: Object.entries(options).map(([key, label]) => ({ key, label, active: f[field] === key })),
        });
        return [
            group("restoration_material", _t("Treat"), {
                composite: _t("Composite"),
                ceramic: _t("Ceramic"),
                amalgam: _t("Amalgam"),
                gold: _t("Gold"),
                non_precious_metal: _t("Non-Precious Metal"),
                temporary: _t("Temporary"),
            }),
            group("restoration_quality", _t("Quality"), {
                sufficient: _t("Sufficient"),
                uncertain: _t("Uncertain"),
                insufficient: _t("Insufficient"),
            }),
            group("restoration_detail", _t("Detail"), {
                overhang: _t("Overhang"),
                flush: _t("Flush"),
                shortfall: _t("Shortfall"),
            }),
        ];
    }

    get dxEndoTests() {
        const labels = {
            cold: _t("Cold"),
            heat: _t("Heat"),
            electric: _t("Electric"),
            percussion: _t("Percussion"),
            palpation: _t("Palpation"),
            bite: _t("Bite"),
            chewing: _t("Chewing"),
            air: _t("Air"),
            occlusal_trauma: _t("Occlusal Trauma"),
            sinus_tract: _t("Sinus Tract"),
        };
        const tests = this.state.newFinding.endo_tests;
        return ENDO_TEST_KEYS.map((key) => ({
            key,
            label: labels[key],
            result: tests[key] || "",
            symbol: tests[key] === "positive" ? "+" : tests[key] === "negative" ? "−" : "–",
        }));
    }

    get dxPerioSites() {
        const tNum = this.state.selectedTooth;
        const lingual = tNum && !this.isUpperTooth(tNum) ? _t("Lingual") : _t("Palatal");
        const labels = {
            perio_dl: _t("Disto %s", lingual),
            perio_l: lingual,
            perio_ml: _t("Mesio %s", lingual),
            perio_db: _t("Disto Buccal"),
            perio_b: _t("Buccal"),
            perio_mb: _t("Mesio Buccal"),
        };
        const perio = this.state.newFinding.perio;
        return ["perio_dl", "perio_l", "perio_ml", "perio_db", "perio_b", "perio_mb"].map((key) => {
            const value = Number(perio[key]) || 0;
            return { key, label: labels[key], value, level: value >= 5 ? "deep" : value === 4 ? "watch" : "" };
        });
    }

    get dxSummary() {
        const tNum = this.state.selectedTooth;
        if (!tNum) return "";
        const f = this.state.newFinding;
        const chips = this.studioSurfaceChips;
        const surfaceLabels = [chips.top, ...chips.middle, chips.bottom, ...chips.extras]
            .filter((c) => c.active)
            .map((c) => c.label);
        const parts = [tNum, ...surfaceLabels];
        const category = this.state.dxCategory;
        if (category === "restoration" && this.dxRestorationKey) {
            parts.push(this.dxRestorationOptions.find((o) => o.active)?.label);
            if (this.dxHasMaterial) {
                for (const group of this.dxDetailGroups) {
                    parts.push(group.options.find((o) => o.active)?.label);
                }
            }
        } else if (category === "pathology" || category === "missing") {
            parts.push(this.getConditionLabel(f.condition));
            if (category === "pathology" && f.severity) parts.push(f.severity);
        }
        if (this.dxSelectedDiagnosis) {
            parts.push(`${_t("Dx")} ${this.dxSelectedDiagnosis.label}`);
        }
        return parts.filter(Boolean).join(", ");
    }

    openToothStudio(tNum) {
        if (!tNum) return;
        this.state.dxHoverSurface = "";
        this.state.dxDiagnosisQuery = "";
        this.state.chartSelection = [String(tNum)];
        // Open first: selectTooth prepares the studio form (no surface pre-selected on a healthy tooth)
        this.state.toothWindowOpen = true;
        this.selectTooth(tNum, { keepChartSelection: true });
        this.focusToothWindow();
    }

    closeToothWindow() {
        if (!this.state.toothWindowOpen) return;
        this.state.toothWindowOpen = false;
        this.state.dxHoverSurface = "";
        this.state.chartScreen = "overview";
        // The window works on one tooth; Ctrl / Shift + click on the chart starts a fresh multi-selection
        this.state.chartSelection = [];
        // Give keyboard focus back to the chart so the next tooth number can be typed straight away
        const wrapper = this.wrapperEl;
        if (wrapper && typeof wrapper.focus === "function") {
            wrapper.focus({ preventScroll: true });
        }
    }

    /** Runs fn on the element once the Portal (mounted after this render) has put it in the page. */
    whenRendered(selector, fn, attempt = 0) {
        const el = document.querySelector(selector);
        if (el) {
            fn(el);
        } else if (attempt < 12) {
            setTimeout(() => this.whenRendered(selector, fn, attempt + 1), 16);
        }
    }

    focusToothWindow() {
        this.whenRendered(`.o_dx_tooth_modal[data-dx-uid="${this.dxUid}"] .dx-modal-window`, (win) => {
            if (!win.contains(document.activeElement)) win.focus({ preventScroll: true });
        });
    }

    /** Tooth window selector: upper arch over lower arch, patient's right on the viewer's left. */
    get studioPickerRows() {
        const build = (key, label, right, left) => ({
            key,
            label,
            teeth: [...right, ...left].map((tNum, idx) => {
                const data = this.state.teeth[tNum] || {};
                const cond = data.condition || "sound";
                return {
                    num: tNum,
                    midStart: idx === right.length,
                    color: CHART_CONDITIONS[cond]?.color || CHART_CONDITIONS.other.color,
                    title: `${_t("Tooth")} ${tNum} • ${data.tooth_name || ""} • ${this.getConditionLabel(cond)}`,
                    classes: {
                        active: this.state.selectedTooth === tNum,
                        "is-marked": cond !== "sound",
                    },
                };
            }),
        });
        return [
            build("upper", _t("Upper"), this.upperRightTeeth, this.upperLeftTeeth),
            build("lower", _t("Lower"), this.lowerRightTeeth, this.lowerLeftTeeth),
        ];
    }

    /** Teeth in rail order (upper right -> upper left -> lower left -> lower right), for prev / next. */
    get toothSequence() {
        return this.studioRailTeeth.map((t) => t.num);
    }

    neighbourTooth(delta) {
        const seq = this.toothSequence;
        const idx = seq.indexOf(this.state.selectedTooth);
        if (idx < 0 || !seq.length) return "";
        return seq[(idx + delta + seq.length) % seq.length];
    }

    stepTooth(delta) {
        const next = this.neighbourTooth(delta);
        if (next) this.openToothStudio(next);
    }

    // ---- "Go to tooth": type a tooth number anywhere on the chart, Enter opens it ----------

    get toothSearchResults() {
        const query = this.state.toothSearch.query;
        const teeth = this.allTeethList;
        const list = query ? teeth.filter((t) => t.number.startsWith(query)) : teeth;
        return list
            .slice()
            .sort((a, b) => Number(a.number) - Number(b.number))
            .map((t) => ({
                ...t,
                conditionLabel: this.getConditionLabel(t.condition),
                color: CHART_CONDITIONS[t.condition]?.color || CHART_CONDITIONS.other.color,
                isMarked: t.condition !== "sound",
            }));
    }

    get toothSearchHint() {
        const query = this.state.toothSearch.query;
        if (!query) return _t("Type an FDI tooth number, e.g. 36");
        if (!this.toothSearchResults.length) {
            return _t("No tooth %s in the current dentition", query);
        }
        return "";
    }

    isChartVisible() {
        const wrapper = this.wrapperEl;
        if (!wrapper || !wrapper.isConnected) return false;
        // Another notebook page is shown: nothing to jump to
        return wrapper.getClientRects().length > 0;
    }

    isOtherDialogOpen() {
        // An Odoo dialog above the form owns the keyboard
        return Boolean(document.querySelector(".o_dialog .modal, .modal.show"));
    }

    static isEditableTarget(target) {
        if (!target || !(target instanceof Element)) return false;
        if (target.isContentEditable) return true;
        const tag = target.tagName;
        return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
    }

    get toothSearchSelector() {
        return `.o_dx_tooth_search[data-dx-uid="${this.dxUid}"]`;
    }

    openToothSearch(initial = "") {
        this.state.toothSearch.open = true;
        this.state.toothSearch.query = String(initial).replace(/\D/g, "").slice(0, 2);
        this.state.toothSearch.activeIndex = 0;
        this.whenRendered(`${this.toothSearchSelector} input`, (input) => {
            input.focus({ preventScroll: true });
            const end = input.value.length;
            input.setSelectionRange?.(end, end);
        });
    }

    closeToothSearch() {
        if (!this.state.toothSearch.open) return;
        this.state.toothSearch.open = false;
        this.state.toothSearch.query = "";
        this.state.toothSearch.activeIndex = 0;
        if (this.state.toothWindowOpen) {
            this.focusToothWindow();
        } else {
            this.wrapperEl?.focus?.({ preventScroll: true });
        }
    }

    onToothSearchInput(ev) {
        const clean = (ev.target.value || "").replace(/\D/g, "").slice(0, 2);
        if (ev.target.value !== clean) {
            ev.target.value = clean;
        }
        this.state.toothSearch.query = clean;
        this.state.toothSearch.activeIndex = 0;
    }

    onToothSearchKeydown(ev) {
        const results = this.toothSearchResults;
        const search = this.state.toothSearch;
        if (ev.key === "Escape") {
            ev.preventDefault();
            ev.stopPropagation();
            this.closeToothSearch();
        } else if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
            ev.preventDefault();
            ev.stopPropagation();
            if (results.length) {
                const step = ev.key === "ArrowDown" ? 1 : -1;
                search.activeIndex = (search.activeIndex + step + results.length) % results.length;
                setTimeout(() => {
                    document.querySelector(`${this.toothSearchSelector} .dx-search-row.active`)
                        ?.scrollIntoView?.({ block: "nearest" });
                });
            }
        } else if (ev.key === "Enter") {
            ev.preventDefault();
            ev.stopPropagation();
            const exact = results.find((t) => t.number === search.query);
            const pick = exact || results[search.activeIndex] || null;
            if (pick) {
                this.pickToothSearchResult(pick.number);
            } else if (search.query) {
                this.notification.add(_t("Tooth %s is not part of the current dentition.", search.query), {
                    type: "warning",
                });
            }
        } else if (ev.key.length === 1 && !/\d/.test(ev.key) && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
            // Tooth numbers only
            ev.preventDefault();
        }
    }

    pickToothSearchResult(tNum) {
        this.state.toothSearch.open = false;
        this.state.toothSearch.query = "";
        this.state.toothSearch.activeIndex = 0;
        this.openToothStudio(tNum);
    }

    onGlobalKeydown(ev) {
        if (ev.defaultPrevented || ev.isComposing) return;
        const search = this.state.toothSearch;
        const windowOpen = this.state.toothWindowOpen;

        if (search.open) {
            const input = document.querySelector(`${this.toothSearchSelector} input`);
            if (ev.key === "Escape") {
                // Keep Odoo from also discarding / leaving the form
                ev.preventDefault();
                ev.stopImmediatePropagation();
                this.closeToothSearch();
            } else if (input && ev.target !== input && (/^\d$/.test(ev.key) || ev.key === "Enter" || ev.key === "Backspace")) {
                // Focus slipped out of the search box: route the key back to it
                input.focus({ preventScroll: true });
            }
            return;
        }
        if (!windowOpen && (!this.isChartVisible() || this.isOtherDialogOpen())) return;
        const editable = DentalOdontogram3DField.isEditableTarget(ev.target);

        if (windowOpen && ev.key === "Escape") {
            ev.preventDefault();
            ev.stopImmediatePropagation();
            if (editable) ev.target.blur();
            this.closeToothWindow();
            return;
        }
        if (editable || ev.ctrlKey || ev.metaKey || ev.altKey) return;

        if (windowOpen && (ev.key === "ArrowLeft" || ev.key === "ArrowRight")) {
            ev.preventDefault();
            ev.stopImmediatePropagation();
            this.stepTooth(ev.key === "ArrowLeft" ? -1 : 1);
            return;
        }
        // FDI quadrants are 1-8: a leading digit starts the "go to tooth" search
        if (/^[1-8]$/.test(ev.key)) {
            ev.preventDefault();
            ev.stopImmediatePropagation();
            this.openToothSearch(ev.key);
        }
    }

    setDxHoverSurface(code) {
        this.state.dxHoverSurface = code || "";
    }

    setDxCategory(category) {
        this.state.dxCategory = category;
        if (category === "missing") {
            this.setCondition("missing");
        }
    }

    setRestorationOption(key) {
        const option = RESTORATION_OPTIONS[key];
        this.state.newFinding.restoration_type = option.type || "";
        if (!option.type) {
            this.state.newFinding.restoration_material = "";
            this.state.newFinding.restoration_quality = "";
            this.state.newFinding.restoration_detail = "";
        }
        this.setCondition(option.condition);
    }

    setPathology(cond) {
        this.state.newFinding.restoration_type = "";
        this.setCondition(cond);
    }

    toggleDxOption(field, value) {
        this.state.newFinding[field] = this.state.newFinding[field] === value ? "" : value;
        this.notifyRecordChanged();
    }

    toggleSurfaceDetail(code) {
        const details = this.state.newFinding.surface_details;
        const idx = details.indexOf(code);
        if (idx >= 0) {
            details.splice(idx, 1);
        } else {
            details.push(code);
        }
    }

    cycleEndoTest(key) {
        const tests = this.state.newFinding.endo_tests;
        const next = { "": "positive", positive: "negative", negative: "" }[tests[key] || ""];
        if (next) {
            tests[key] = next;
        } else {
            delete tests[key];
        }
    }

    setPerioDepth(site, value) {
        const depth = Math.min(Math.max(parseInt(value, 10) || 0, 0), 20);
        this.state.newFinding.perio[site] = depth;
    }

    async onStudioSave(action = "") {
        const tNum = this.state.selectedTooth;
        if (!tNum) return;
        const caseId = this.caseId || this.getCaseId();
        if (!caseId) {
            this.notification.add(_t("Please save the dental case before recording findings."), {
                type: "warning",
            });
            return;
        }
        const f = this.state.newFinding;
        // With no category picked the visit only records surfaces / tests / probing: keep the condition
        const condition = this.state.dxCategory ? f.condition : this.state.teeth[tNum]?.condition || "sound";
        const hasMaterial = condition === "restoration" || condition === "crown";
        this.state.isSaving = true;
        try {
            const result = await this.orm.call("dental.case", "save_tooth_finding", [caseId], {
                tooth_data: {
                    tooth_number: tNum,
                    condition,
                    diagnosis_id: f.diagnosis_id || false,
                    surfaces: f.surfaces.join(""),
                    severity: f.severity,
                    treatment_indicated: action === "treat" ? this.dxSummary : f.treatment_indicated,
                    notes: f.notes,
                    restoration_type: hasMaterial ? f.restoration_type : "",
                    restoration_material: hasMaterial ? f.restoration_material : "",
                    restoration_quality: hasMaterial ? f.restoration_quality : "",
                    restoration_detail: hasMaterial ? f.restoration_detail : "",
                    surface_details: f.surface_details,
                    clinical_action: action,
                    endo_tests: { ...f.endo_tests },
                    perio: { ...f.perio },
                },
            });
            if (result?.success) {
                const refreshed = result.odontogram_data;
                this.state.teeth = refreshed.teeth || {};
                this.state.stats = refreshed.stats || {};
                this.state.diagnosisMasters = refreshed.diagnosis_masters || this.state.diagnosisMasters;
                this.selectTooth(tNum, { keepChartSelection: true });
                this.updateAllToothMaterials();
                await this.notifyRecordChanged();
                if (this.props.record && typeof this.props.record.save === "function") {
                    await this.props.record.save();
                }
                const messages = {
                    monitor: _t("Tooth %s saved and flagged for monitoring", tNum),
                    treat: _t("Tooth %s saved and marked for treatment", tNum),
                };
                this.notification.add(messages[action] || _t("Tooth %s condition successfully recorded!", tNum), {
                    type: "success",
                });
            }
        } catch (error) {
            console.error("Failed to save tooth finding:", error);
            this.notification.add(error.message || _t("Failed to save tooth finding."), {
                type: "danger",
            });
        } finally {
            this.state.isSaving = false;
        }
    }

    async onStudioReset() {
        this.state.dxCategory = "";
        await this.onClearFinding();
        if (this.state.selectedTooth) {
            this.selectTooth(this.state.selectedTooth, { keepChartSelection: true });
        }
    }

    // ---- Overview selection & bulk marking ---------------------------------

    isChartSelectionCondition(cond) {
        const sel = this.state.chartSelection;
        return sel.length > 0 && sel.every((t) => (this.state.teeth[t]?.condition || "sound") === cond);
    }

    onChartToothClick(tNum, ev) {
        const additive = ev?.ctrlKey || ev?.metaKey || ev?.shiftKey;
        if (!additive) {
            this.openToothStudio(tNum);
            return;
        }
        const idx = this.state.chartSelection.indexOf(tNum);
        if (idx >= 0) {
            this.state.chartSelection.splice(idx, 1);
            if (this.state.selectedTooth === tNum) {
                const last = this.state.chartSelection[this.state.chartSelection.length - 1];
                if (last) {
                    this.selectTooth(last, { keepChartSelection: true });
                } else {
                    this.state.selectedTooth = null;
                }
            }
        } else {
            this.state.chartSelection.push(tNum);
            this.selectTooth(tNum, { keepChartSelection: true });
        }
    }

    onChartToothKeydown(tNum, ev) {
        if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            this.onChartToothClick(tNum, ev);
        }
    }

    clearChartSelection() {
        this.state.chartSelection = [];
        this.state.selectedTooth = null;
        this.updateAllToothMaterials();
    }

    async markChartSelection(cond) {
        const teeth = [...this.state.chartSelection];
        if (!teeth.length) return;
        const caseId = this.caseId || this.getCaseId();
        if (!caseId) {
            this.notification.add(_t("Please save the dental case before recording findings."), {
                type: "warning",
            });
            return;
        }

        // A single tooth uses the surfaces / severity picked in the chart & panel; bulk marking keeps
        // each tooth's previously recorded surfaces.
        const single = teeth.length === 1;
        const finding = this.state.newFinding;
        this.state.isSaving = true;
        try {
            let refreshed = null;
            for (const tNum of teeth) {
                let result;
                if (cond === "sound") {
                    result = await this.orm.call("dental.case", "clear_tooth_finding", [caseId], {
                        tooth_number: tNum,
                    });
                } else {
                    const surfaces = !SURFACE_CONDITIONS.has(cond)
                        ? ""
                        : single
                            ? finding.surfaces.join("")
                            : this.state.teeth[tNum]?.surfaces || "O";
                    result = await this.orm.call("dental.case", "save_tooth_finding", [caseId], {
                        tooth_data: {
                            tooth_number: tNum,
                            condition: cond,
                            diagnosis_id: (single && finding.diagnosis_id) || false,
                            surfaces,
                            severity: single ? finding.severity : "moderate",
                            treatment_indicated: single ? finding.treatment_indicated : "",
                            notes: single ? finding.notes : "",
                        },
                    });
                }
                if (result?.success) {
                    refreshed = result.odontogram_data;
                }
            }

            if (refreshed) {
                this.state.teeth = refreshed.teeth || {};
                this.state.stats = refreshed.stats || {};
                this.state.diagnosisMasters = refreshed.diagnosis_masters || this.state.diagnosisMasters;
            }
            if (this.state.selectedTooth) {
                this.selectTooth(this.state.selectedTooth, { keepChartSelection: true });
            }
            this.updateAllToothMaterials();

            await this.notifyRecordChanged();
            if (this.props.record && typeof this.props.record.save === "function") {
                await this.props.record.save();
            }

            this.notification.add(
                _t("Marked %(teeth)s as %(condition)s", {
                    teeth: single ? _t("Tooth %s", teeth[0]) : _t("%s teeth", teeth.length),
                    condition: this.getConditionLabel(cond),
                }),
                { type: "success" }
            );
        } catch (error) {
            console.error("Failed to mark teeth:", error);
            this.notification.add(error.message || _t("Failed to save tooth finding."), {
                type: "danger",
            });
        } finally {
            this.state.isSaving = false;
        }
    }

    // -------------------------------------------------------------------------
    // Odontogram Data Fetching & State
    // -------------------------------------------------------------------------

    async loadOdontogram() {
        const patientId = this.patientId || this.getPatientId();
        const caseId = this.caseId || this.getCaseId();

        if (!patientId) {
            this.state.patientName = "";
            this.state.patientRef = "";
            this.state.teeth = {};
            this.state.stats = { sound: 32, caries: 0, restoration: 0, missing: 0, other: 0 };
            this.updateAllToothMaterials();
            return;
        }

        try {
            const data = await this.orm.call("dental.case", "get_odontogram_data", [caseId || []], {
                patient_id: patientId,
            });

            this.state.caseId = data.case_id;
            this.state.caseName = data.case_name;
            this.state.canEdit = data.can_edit;
            this.state.isDentist = data.is_dentist;
            this.state.teeth = data.teeth || {};
            this.state.stats = data.stats || {};
            this.state.diagnosisMasters = data.diagnosis_masters || [];

            this.state.patientId = data.patient_id;
            this.state.patientName = data.patient_name;
            this.state.patientRef = data.patient_ref;
            this.state.patientAge = data.patient_age;
            this.state.patientDob = data.patient_dob;
            this.state.suggestedDentition = data.suggested_dentition || "permanent";
            this.state.minimumDentition = data.minimum_dentition || "primary";
            
            // Remember previously selected dentition (persisted across page refreshes)
            let savedDentition = data.saved_dentition || null;
            try {
                if (!savedDentition && caseId) savedDentition = localStorage.getItem(`dental_dentition_case_${caseId}`);
                if (!savedDentition && patientId) savedDentition = localStorage.getItem(`dental_dentition_patient_${patientId}`);
                if (!savedDentition) savedDentition = localStorage.getItem("dental_dentition_type");
            } catch (e) {}

            let determinedDentition = savedDentition || data.suggested_dentition || "permanent";

            // Enforce minimum dentition based on treated teeth:
            // A person treated with permanent teeth or under permanent dentition cannot regress backwards
            if (data.minimum_dentition === "permanent" || this.hasTreatedPermanentExclusiveTeeth()) {
                determinedDentition = "permanent";
            } else if (data.minimum_dentition === "mixed" || this.hasTreatedPermanentTeeth()) {
                if (determinedDentition === "primary") {
                    determinedDentition = "mixed";
                }
            }

            this.state.dentitionType = determinedDentition;

            if (this.state.canEdit && !this.state.activePanelTab) {
                this.state.activePanelTab = "record";
            } else if (!this.state.canEdit) {
                this.state.activePanelTab = "history";
            }

            this.applyDentitionVisibility();
            this.updateAllToothMaterials();
        } catch (error) {
            console.error("Failed to load odontogram data:", error);
        }
    }

    // -------------------------------------------------------------------------
    // Dynamic 3D Asset & Library Loading
    // -------------------------------------------------------------------------

    async ensure3DLibraries() {
        if (!window.MeshoptDecoder) {
            await this.loadScript("/dental_core/static/lib/meshopt_decoder.js");
        }
        if (window.MeshoptDecoder && window.MeshoptDecoder.ready) {
            await window.MeshoptDecoder.ready;
        }
        if (!window.THREE?.GLTFLoader) {
            await this.loadScript("/dental_core/static/lib/GLTFLoader.js");
        }
    }

    loadScript(src) {
        return new Promise((resolve, reject) => {
            const existing = document.querySelector(`script[src="${src}"]`);
            if (existing) {
                if (existing.dataset.loaded === "true" || window.MeshoptDecoder || window.THREE?.GLTFLoader) {
                    return resolve();
                }
                existing.addEventListener("load", () => resolve());
                existing.addEventListener("error", (e) => reject(e));
                return;
            }
            const script = document.createElement("script");
            script.src = src;
            script.async = true;
            script.onload = () => {
                script.dataset.loaded = "true";
                resolve();
            };
            script.onerror = (e) => reject(e);
            document.head.appendChild(script);
        });
    }

    // -------------------------------------------------------------------------
    // 3D Scene Initialization
    // -------------------------------------------------------------------------

    async init3DScene() {
        if (this.is3DReady || this.webglFailed || this._initializing3D || this._webglContextLost) return;
        this._initializing3D = true;
        try {
            await this._init3DSceneInner();
        } finally {
            this._initializing3D = false;
        }
    }

    async _init3DSceneInner() {
        // Never stack WebGL contexts: browsers cap them (~16 per page) and refuse new ones after that,
        // which is what surfaced the "WebGL not available" warning even on capable machines.
        if (this.renderer) {
            this.cleanup3D();
        }
        const THREE = window.THREE;
        if (!THREE) {
            console.error("Three.js library is not available.");
            return;
        }

        const container = this.containerEl;
        if (!container) return;

        const viewport = this.viewportEl;
        const width = container.clientWidth > 50 ? container.clientWidth : (viewport?.clientWidth || 700);
        const height = container.clientHeight > 50 ? container.clientHeight : (viewport?.clientHeight || 500);

        // 1. Scene
        this.scene = new THREE.Scene();
        this.scene.background = new THREE.Color(this.state.viewMode === "chart" ? CHART_STYLE.background : JAW_BACKGROUND);

        // 2. Camera: Centered framing with comfortable reduced default zoom (two steps zoomed out)
        this.camera = new THREE.PerspectiveCamera(36, width / height, 0.1, 1000);
        this.camera.position.set(0, 0.26, 18.8);

        // 3. Renderer with high-quality soft shadows & tone mapping (with graceful fallback if WebGL fails)
        const renderer = this.createWebGLRenderer(THREE);
        if (!renderer) {
            this.webglFailed = true;
            this.state.webglError = true;
            this.state.viewMode = "chart";
            this.state.isLoadingModel = false;
            return;
        }
        const canvas = renderer.domElement;
        this.renderer = renderer;

        // Context loss / restoration listeners
        canvas.addEventListener("webglcontextlost", (event) => {
            event.preventDefault();
            if (canvas.dataset.disposed) return; // our own forceContextLoss() during cleanup
            console.warn("Odontogram: WebGL context lost.");
            // Keep is3DReady/renderer as-is so resize/patch hooks do NOT spawn new contexts
            // while the browser is still recovering; we rebuild on "webglcontextrestored".
            this._webglContextLost = true;
            if (this.animationFrameId) {
                cancelAnimationFrame(this.animationFrameId);
                this.animationFrameId = null;
            }
        }, false);
        canvas.addEventListener("webglcontextrestored", async () => {
            console.info("Odontogram: WebGL context restored.");
            this._webglContextLost = false;
            this.cleanup3D();
            try {
                await this.init3DScene();
                this.updateAllToothMaterials();
            } catch (err) {
                console.warn("Odontogram: failed to rebuild 3D scene after context restore:", err);
            }
        }, false);

        this.renderer.setSize(width, height);
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
        this.renderer.shadowMap.enabled = true;
        this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
        if (THREE.sRGBEncoding) {
            this.renderer.outputEncoding = THREE.sRGBEncoding;
        }
        if (THREE.ACESFilmicToneMapping) {
            this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
            this.renderer.toneMappingExposure = 1.05;
        }
        container.innerHTML = "";
        container.appendChild(this.renderer.domElement);

        // 4. Studio Lighting (Key, Fill, Rim, Ambient)
        this.setupLighting(THREE);

        // 5. Controls
        if (THREE.OrbitControls) {
            this.controls = new THREE.OrbitControls(this.camera, this.renderer.domElement);
            this.controls.enableDamping = true;
            this.controls.dampingFactor = 0.08;
            this.controls.enableZoom = false; // Disable scroll/wheel zooming so page scrolling is completely smooth
            this.controls.enableRotate = true; // Mouse click rotation remains active
            this.controls.enablePan = true;
            this.controls.maxDistance = 28;
            this.controls.minDistance = 3.5;
            this.controls.target.set(0, -0.15, 0);
        }

        // 6. Raycaster
        this.raycaster = new THREE.Raycaster();
        this.pointer = new THREE.Vector2();
        this.pointerDownPos = { x: 0, y: 0 };

        // 7. Ground Contact Shadow Plane
        const shadowPlane = new THREE.Mesh(
            new THREE.PlaneGeometry(32, 32),
            new THREE.ShadowMaterial({ opacity: 0.08 })
        );
        shadowPlane.rotation.x = -Math.PI / 2;
        shadowPlane.position.y = -4.2;
        shadowPlane.receiveShadow = true;
        this.scene.add(shadowPlane);

        // 7b. Tooth-by-Tooth Chart Root Group
        this.chartRoot = new THREE.Group();
        this.chartRoot.name = "chartRoot";
        this.chartRoot.visible = this.state.viewMode === "chart";
        this.scene.add(this.chartRoot);

        // 8. Event Listeners
        this.renderer.domElement.addEventListener("pointerdown", (e) => {
            this.pointerDownPos = { x: e.clientX, y: e.clientY };
        });
        this.renderer.domElement.addEventListener("pointermove", (e) => this.onPointerMove(e));
        this.renderer.domElement.addEventListener("pointerup", (e) => this.onPointerUp(e));
        this.renderer.domElement.addEventListener("click", (e) => this.onPointerUp(e));

        // 9. Observers for dynamic tabs & responsiveness
        if (window.ResizeObserver && viewport) {
            this.resizeObserver = new ResizeObserver(() => {
                this.onWindowResize();
            });
            this.resizeObserver.observe(viewport);
        }

        if (window.IntersectionObserver && viewport) {
            this.intersectionObserver = new IntersectionObserver((entries) => {
                for (const entry of entries) {
                    // Off-screen (scrolled away, other notebook page): the render loop idles
                    this._inView = entry.isIntersecting;
                    if (entry.isIntersecting) {
                        this.onWindowResize();
                    }
                }
            });
            this.intersectionObserver.observe(viewport);
        }

        const tabPane = container.closest(".tab-pane") || container.closest(".o_group");
        if (tabPane) {
            this.tabMutationObserver = new MutationObserver(() => {
                this.onWindowResize();
            });
            this.tabMutationObserver.observe(tabPane, { attributes: true, attributeFilter: ["class", "style"] });
        }

        window.addEventListener("resize", (this.onWindowResizeBound = () => this.onWindowResize()));

        // 10. Start Animation Loop with Breathing Effect for Selection
        this.is3DReady = true;
        const animate = (timestamp) => {
            this.animationFrameId = requestAnimationFrame(animate);
            // Canvas hidden (2D chart shown), scrolled off-screen or browser tab in the background:
            // skip GPU work so the rest of the page scrolls smoothly
            if (this.state.viewMode === "chart" || this._inView === false || document.hidden) return;
            if (this.controls) this.controls.update();
            this.updateSelectionBreathingEffect(timestamp);
            this.renderer.render(this.scene, this.camera);
        };
        animate();

        // 11. Load Anatomically Realistic Dental Model
        await this.loadDentalModel(THREE);
    }

    /**
     * Create the WebGL context ourselves (WebGL2 -> WebGL1, high-quality -> minimal attributes,
     * each on a fresh canvas) and hand it to Three.js. Records the browser's own failure reason
     * (webglcontextcreationerror.statusMessage) so the user sees why 3D is blocked.
     */
    createWebGLRenderer(THREE) {
        const attributeSets = [
            { antialias: true, alpha: true, powerPreference: "default" },
            { antialias: false, alpha: true, powerPreference: "default" },
            { antialias: false, alpha: true, powerPreference: "low-power", failIfMajorPerformanceCaveat: false },
            { antialias: false, alpha: false, depth: true, stencil: false, powerPreference: "low-power", failIfMajorPerformanceCaveat: false },
        ];
        const contextTypes = ["webgl2", "webgl", "experimental-webgl"];
        const reasons = [];
        for (const attrs of attributeSets) {
            for (const type of contextTypes) {
                const canvas = document.createElement("canvas");
                let statusMessage = "";
                const onError = (ev) => { statusMessage = ev.statusMessage || ""; };
                canvas.addEventListener("webglcontextcreationerror", onError, false);
                let context = null;
                try {
                    context = canvas.getContext(type, attrs);
                } catch (e) {
                    statusMessage = statusMessage || String(e);
                }
                canvas.removeEventListener("webglcontextcreationerror", onError, false);
                if (!context || (context.isContextLost && context.isContextLost())) {
                    reasons.push(`${type}${attrs.antialias ? "+aa" : ""}/${attrs.powerPreference}: ${statusMessage || "no context returned"}`);
                    continue;
                }
                try {
                    const renderer = new THREE.WebGLRenderer({ canvas, context, ...attrs });
                    console.info(`Odontogram: WebGL renderer created (${type}).`);
                    this.state.webglErrorDetail = "";
                    return renderer;
                } catch (e) {
                    reasons.push(`${type} (three.js): ${e && e.message ? e.message : e}`);
                    const lose = context.getExtension && context.getExtension("WEBGL_lose_context");
                    if (lose) lose.loseContext();
                }
            }
        }
        const unique = [...new Set(reasons)];
        console.warn("Odontogram: WebGL unavailable. Browser reasons:\n" + unique.join("\n"));
        this.state.webglErrorDetail = unique.find((r) => !r.endsWith("no context returned")) || unique[0] || "";
        return null;
    }

    setupLighting(THREE) {
        // Balanced ambient base
        const ambientLight = new THREE.AmbientLight(0xffffff, 0.54);
        this.scene.add(ambientLight);

        // Warm directional key light
        const keyLight = new THREE.DirectionalLight(0xfffbf5, 0.76);
        keyLight.position.set(6, 14, 11);
        keyLight.castShadow = true;
        keyLight.shadow.mapSize.width = 2048;
        keyLight.shadow.mapSize.height = 2048;
        keyLight.shadow.bias = -0.0001;
        this.scene.add(keyLight);

        // Cool clinical fill light
        const fillLight = new THREE.DirectionalLight(0xe2e8f0, 0.38);
        fillLight.position.set(-7, -4, 9);
        this.scene.add(fillLight);

        // Rim highlight from top-back for enamel and mucosal contours
        const rimLight = new THREE.DirectionalLight(0xffffff, 0.30);
        rimLight.position.set(0, 10, -11);
        this.scene.add(rimLight);

        // Hemisphere light
        const hemiLight = new THREE.HemisphereLight(0xffffff, 0x94a3b8, 0.34);
        this.scene.add(hemiLight);
    }

    createToothOutline(THREE, mesh, options = {}) {
        if (!mesh || !mesh.geometry) return null;

        const outlineMat = new THREE.ShaderMaterial({
            uniforms: {
                offset: { value: options.offset ?? 0.016 },
                color: { value: new THREE.Color(options.color ?? 0x334155) }, // Dark slate outline for crisp separation against light background
                opacity: { value: 0.95 },
            },
            vertexShader: `
                uniform float offset;
                void main() {
                    vec3 transformed = position + normal * offset;
                    gl_Position = projectionMatrix * modelViewMatrix * vec4(transformed, 1.0);
                }
            `,
            fragmentShader: `
                uniform vec3 color;
                uniform float opacity;
                void main() {
                    gl_FragColor = vec4(color, opacity);
                }
            `,
            side: THREE.BackSide,
            transparent: true,
            depthWrite: true,
        });

        const outlineMesh = new THREE.Mesh(mesh.geometry, outlineMat);
        outlineMesh.name = `${mesh.name}_outline`;
        outlineMesh.raycast = () => {};
        outlineMesh.visible = this.state.showSeparations !== false;
        mesh.add(outlineMesh);
        return outlineMesh;
    }

    toggleSeparations() {
        this.state.showSeparations = !this.state.showSeparations;
        for (const tObj of Object.values(this.toothMeshes || {})) {
            if (tObj && tObj.outlineMesh) {
                tObj.outlineMesh.visible = this.state.showSeparations;
            }
        }
        for (const tObj of Object.values(this.chartToothMeshes || {})) {
            if (tObj && tObj.outlineMesh) {
                tObj.outlineMesh.visible = this.state.showSeparations;
            }
        }
    }

    // -------------------------------------------------------------------------
    // Realistic Model Loading & Arch Composition
    // -------------------------------------------------------------------------

    async loadDentalModel(THREE) {
        this.state.isLoadingModel = true;
        try {
            await this.ensure3DLibraries();

            if (!THREE.GLTFLoader) {
                throw new Error("GLTFLoader is not available.");
            }

            const loader = new THREE.GLTFLoader();
            if (window.MeshoptDecoder) {
                loader.setMeshoptDecoder(window.MeshoptDecoder);
            }

            loader.load(
                "/dental_core/static/models/dental_arch.glb",
                (gltf) => {
                    this.onModelLoaded(THREE, gltf);
                    this.state.isLoadingModel = false;
                    this.updateAllToothMaterials();
                },
                undefined,
                (error) => {
                    console.error("Failed to load anatomical GLB model, falling back to procedural arches:", error);
                    this.buildProceduralDentalArches(THREE);
                    this.state.isLoadingModel = false;
                    this.updateAllToothMaterials();
                }
            );
        } catch (err) {
            console.error("Error initializing 3D model loader:", err);
            this.buildProceduralDentalArches(THREE);
            this.state.isLoadingModel = false;
            this.updateAllToothMaterials();
        }
    }

    onModelLoaded(THREE, gltf) {
        if (this.modelRoot) {
            this.scene.remove(this.modelRoot);
        }
        this.toothMeshes = {};

        this.modelRoot = new THREE.Group();
        this.upperJawGroup = new THREE.Group();
        this.lowerJawGroup = new THREE.Group();
        this.modelRoot.add(this.upperJawGroup);
        this.modelRoot.add(this.lowerJawGroup);

        // Realistic gingival tissue materials (rich vascular reddish mucosal tissue)
        const gumMatUpper = new THREE.MeshStandardMaterial({
            color: 0x9b1b30, // Rich, attractive healthy reddish gingiva
            emissive: 0x240408, // Subsurface mucosal warmth
            roughness: 0.28,
            metalness: 0.02,
            side: THREE.DoubleSide,
        });

        const gumMatLower = new THREE.MeshStandardMaterial({
            color: 0x9b1b30,
            emissive: 0x240408,
            roughness: 0.28,
            metalness: 0.02,
            side: THREE.DoubleSide,
        });

        const upperToothNames = new Set([
            "tooth-18", "tooth-17", "tooth-16", "tooth-15", "tooth-14", "tooth-13", "tooth-12", "tooth-11",
            "tooth-21", "tooth-22", "tooth-23", "tooth-24", "tooth-25", "tooth-26", "tooth-27", "tooth-28"
        ]);
        const lowerToothNames = new Set([
            "tooth-48", "tooth-47", "tooth-46", "tooth-45", "tooth-44", "tooth-43", "tooth-42", "tooth-41",
            "tooth-31", "tooth-32", "tooth-33", "tooth-34", "tooth-35", "tooth-36", "tooth-37", "tooth-38"
        ]);

        const nodesToProcess = [];
        gltf.scene.traverse((child) => {
            if (child.isMesh) {
                nodesToProcess.push(child);
            }
        });

        for (const mesh of nodesToProcess) {
            const name = mesh.name;
            mesh.castShadow = true;
            mesh.receiveShadow = true;

            // KHR_mesh_quantization: un-quantize vertex positions & normals from Int16 to standard Float32
            // Three.js CPU Raycaster and bounding calculations require actual Float32 coordinates.
            // Using posAttr.getX/Y/Z(i) correctly decodes interleaved/strided buffers without vertex corruption!
            if (mesh.geometry && mesh.geometry.attributes.position) {
                const posAttr = mesh.geometry.attributes.position;
                if (posAttr.normalized && (posAttr.array instanceof Int16Array || posAttr.isInterleavedBufferAttribute)) {
                    const count = posAttr.count;
                    const floatPositions = new Float32Array(count * 3);
                    for (let i = 0; i < count; i++) {
                        floatPositions[i * 3 + 0] = Math.max(posAttr.getX(i) / 32767.0, -1.0);
                        floatPositions[i * 3 + 1] = Math.max(posAttr.getY(i) / 32767.0, -1.0);
                        floatPositions[i * 3 + 2] = Math.max(posAttr.getZ(i) / 32767.0, -1.0);
                    }
                    mesh.geometry.setAttribute("position", new THREE.BufferAttribute(floatPositions, 3, false));
                }
                const normAttr = mesh.geometry.attributes.normal;
                if (normAttr && normAttr.normalized && (normAttr.array instanceof Int16Array || normAttr.isInterleavedBufferAttribute)) {
                    const count = normAttr.count;
                    const floatNormals = new Float32Array(count * 3);
                    for (let i = 0; i < count; i++) {
                        floatNormals[i * 3 + 0] = Math.max(normAttr.getX(i) / 32767.0, -1.0);
                        floatNormals[i * 3 + 1] = Math.max(normAttr.getY(i) / 32767.0, -1.0);
                        floatNormals[i * 3 + 2] = Math.max(normAttr.getZ(i) / 32767.0, -1.0);
                    }
                    mesh.geometry.setAttribute("normal", new THREE.BufferAttribute(floatNormals, 3, false));
                }
                mesh.geometry.computeBoundingBox();
                mesh.geometry.computeBoundingSphere();
                if (!mesh.geometry.attributes.normal || name.includes("gingiva")) {
                    mesh.geometry.computeVertexNormals();
                }
            }

            if (name === "gingiva-upper") {
                mesh.material = gumMatUpper;
                this.upperJawGroup.add(mesh);
            } else if (name === "gingiva-lower") {
                mesh.material = gumMatLower;
                this.lowerJawGroup.add(mesh);
            } else if (upperToothNames.has(name)) {
                const toothNum = name.replace("tooth-", "");
                const toothMat = new THREE.MeshStandardMaterial({
                    color: 0xf8f6f0, // Natural pearlescent ivory enamel
                    roughness: 0.28,
                    metalness: 0.02,
                    side: THREE.DoubleSide,
                });
                mesh.material = toothMat;
                mesh.userData = { toothNumber: toothNum, isUpper: true };
                this.upperJawGroup.add(mesh);

                const outlineMesh = this.createToothOutline(THREE, mesh);

                this.toothMeshes[toothNum] = {
                    mesh: mesh,
                    outlineMesh: outlineMesh,
                    isUpper: true,
                    basePos: mesh.position.clone(),
                    baseScale: mesh.scale.clone(),
                    toothNumber: toothNum,
                };
            } else if (lowerToothNames.has(name)) {
                const toothNum = name.replace("tooth-", "");
                const toothMat = new THREE.MeshStandardMaterial({
                    color: 0xf8f6f0,
                    roughness: 0.28,
                    metalness: 0.02,
                    side: THREE.DoubleSide,
                });
                mesh.material = toothMat;
                mesh.userData = { toothNumber: toothNum, isUpper: false };
                this.lowerJawGroup.add(mesh);

                const outlineMesh = this.createToothOutline(THREE, mesh);

                this.toothMeshes[toothNum] = {
                    mesh: mesh,
                    outlineMesh: outlineMesh,
                    isUpper: false,
                    basePos: mesh.position.clone(),
                    baseScale: mesh.scale.clone(),
                    toothNumber: toothNum,
                };
            } else {
                // Non-arch bone and sinus structures hidden to maintain pristine dental arch focus
                mesh.visible = false;
            }
        }

        // Also register pediatric deciduous tooth numbers to corresponding anatomical tooth meshes
        const primaryToAdultMap = {
            "55": "16", "54": "14", "53": "13", "52": "12", "51": "11",
            "61": "21", "62": "22", "63": "23", "64": "24", "65": "26",
            "71": "31", "72": "32", "73": "33", "74": "34", "75": "36",
            "81": "41", "82": "42", "83": "43", "84": "44", "85": "46",
        };
        for (const [pNum, aNum] of Object.entries(primaryToAdultMap)) {
            if (this.toothMeshes[aNum]) {
                this.toothMeshes[pNum] = {
                    mesh: this.toothMeshes[aNum].mesh,
                    isUpper: this.toothMeshes[aNum].isUpper,
                    basePos: this.toothMeshes[aNum].basePos,
                    toothNumber: pNum,
                    isPrimary: true,
                };
            }
        }

        // Add Anatomical 3D Tongue nestled comfortably inside the mandibular arch
        const tongueMesh = this.createTongueMesh(THREE);
        this.lowerJawGroup.add(tongueMesh);

        // Separate upper and lower jaws with balanced natural open bite centered in viewport
        // Upper Maxillary Arch: Raised slightly up and leveled
        this.upperJawGroup.position.set(0, 0.42, 0.0);
        this.upperJawGroup.rotation.x = -0.02;

        // Lower Mandibular Arch: Lowered slightly down and leveled
        this.lowerJawGroup.position.set(0, -0.42, 0.0);
        this.lowerJawGroup.rotation.x = 0.02;

        // Center the composite jaws vertically in the viewport
        this.modelRoot.position.set(0, -0.10, 0.1);
        this.scene.add(this.modelRoot);

        // Force full world matrix computation so raycaster hits exact tooth positions immediately
        this.modelRoot.updateMatrixWorld(true);

        this.buildToothChart(THREE);
        this.modelRoot.visible = this.state.viewMode !== "chart";
        if (this.chartRoot) {
            this.chartRoot.visible = this.state.viewMode === "chart";
        }

        this.applyDentitionVisibility();
    }

    createTongueMesh(THREE) {
        const uSegs = 32;
        const vSegs = 32;
        const positions = [];
        const indices = [];
        const uvs = [];

        for (let i = 0; i <= vSegs; i++) {
            const v = i / vSegs; // 0 (tip) to 1 (posterior root)
            const z = 1.05 - v * 3.2;
            const w = 1.40 * Math.sin(Math.PI * Math.pow(v, 0.45)); // Anatomical width

            for (let j = 0; j <= uSegs; j++) {
                const u = (j / uSegs) * 2 - 1; // -1 to +1
                const x = u * w;

                // Dome height nestled below occlusal table
                const hBase = 0.48 * Math.sin(Math.PI * Math.pow(v, 0.55)) * Math.max(0, 1.0 - u * u);
                const sulcus = 0.05 * Math.exp(-12.0 * u * u) * Math.sin(Math.PI * v);
                const y = -1.55 + Math.max(0, hBase - sulcus);

                positions.push(x, y, z);
                uvs.push(j / uSegs, v);
            }
        }

        for (let i = 0; i < vSegs; i++) {
            for (let j = 0; j < uSegs; j++) {
                const a = i * (uSegs + 1) + j;
                const b = (i + 1) * (uSegs + 1) + j;
                const c = (i + 1) * (uSegs + 1) + (j + 1);
                const d = i * (uSegs + 1) + (j + 1);
                indices.push(a, b, d);
                indices.push(b, c, d);
            }
        }

        const geo = new THREE.BufferGeometry();
        geo.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
        geo.setAttribute("uv", new THREE.Float32BufferAttribute(uvs, 2));
        geo.setIndex(indices);
        geo.computeVertexNormals();

        const mat = new THREE.MeshStandardMaterial({
            color: 0xba5464, // Healthy moist tongue mucosal tone
            roughness: 0.45, // Soft organic sheen
            metalness: 0.02,
            side: THREE.DoubleSide,
        });

        const mesh = new THREE.Mesh(geo, mat);
        mesh.castShadow = true;
        mesh.receiveShadow = true;
        return mesh;
    }

    // -------------------------------------------------------------------------
    // Tooth-by-Tooth 3D Frontal Chart Composition
    // -------------------------------------------------------------------------

    buildToothChart(THREE) {
        if (!this.chartRoot) {
            this.chartRoot = new THREE.Group();
            this.chartRoot.name = "chartRoot";
            this.scene.add(this.chartRoot);
        } else {
            while (this.chartRoot.children.length > 0) {
                this.chartRoot.remove(this.chartRoot.children[0]);
            }
        }
        this.chartToothMeshes = {};

        // Forward-facing Y-rotation angles derived from anatomical arch normals relative to +Z
        const upperChartRotY = {
            "11": 0.143,  "12": 0.411,  "13": 0.879,  "14": 1.156,
            "15": 1.306,  "16": 1.535,  "17": 1.595,  "18": 1.567,
            "21": -0.132, "22": -0.412, "23": -0.886, "24": -1.155,
            "25": -1.306, "26": -1.536, "27": -1.599, "28": -1.574,
        };

        const lowerChartRotY = {
            "41": -0.002, "42": 0.331,  "43": 0.774,  "44": 1.002,
            "45": 1.161,  "46": 1.249,  "47": 1.263,  "48": 1.240,
            "31": 0.002,  "32": -0.330, "33": -0.775, "34": -1.002,
            "35": -1.160, "36": -1.250, "37": -1.263, "38": -1.240,
        };

        const upperOrder = [
            "18", "17", "16", "15", "14", "13", "12", "11",
            "21", "22", "23", "24", "25", "26", "27", "28"
        ];
        const lowerOrder = [
            "48", "47", "46", "45", "44", "43", "42", "41",
            "31", "32", "33", "34", "35", "36", "37", "38"
        ];

        const buildRow = (order, isUpper, rotMap, yLevel) => {
            const count = order.length;
            const half = count / 2;
            const spacing = 1.34;
            const midlineGap = 1.50; // Proper gap between central incisors (prevents mesh & outline overlap between 11 and 21)

            for (let i = 0; i < count; i++) {
                const tNum = order[i];
                const origToothObj = this.toothMeshes[tNum];
                if (!origToothObj || !origToothObj.mesh) continue;

                const origMesh = origToothObj.mesh;
                // Create 3D chart mesh with cloned material so jaw and chart visibility/properties operate independently
                const chartMat = origMesh.material.clone();
                const chartMesh = new THREE.Mesh(origMesh.geometry, chartMat);
                chartMesh.castShadow = true;
                chartMesh.receiveShadow = true;
                chartMesh.name = `chart-tooth-${tNum}`;
                chartMesh.userData = { toothNumber: tNum, isUpper, isChart: true };

                let posX;
                if (i < half) {
                    // Right quadrant (displayed on left of midline)
                    posX = -((half - 1 - i) * spacing + midlineGap / 2);
                } else {
                    // Left quadrant (displayed on right of midline)
                    posX = (i - half) * spacing + midlineGap / 2;
                }

                chartMesh.position.set(posX, yLevel, 0.0);
                if (origToothObj.baseScale) {
                    chartMesh.scale.copy(origToothObj.baseScale);
                } else {
                    chartMesh.scale.copy(origMesh.scale);
                }

                if (rotMap && rotMap[tNum] !== undefined) {
                    chartMesh.rotation.y = rotMap[tNum];
                }

                const chartOutline = this.createToothOutline(THREE, chartMesh, {
                    color: CHART_STYLE.outline,
                    offset: CHART_STYLE.outlineOffset,
                });
                this.chartRoot.add(chartMesh);

                this.chartToothMeshes[tNum] = {
                    mesh: chartMesh,
                    outlineMesh: chartOutline,
                    isUpper: isUpper,
                    basePos: chartMesh.position.clone(),
                    baseScale: chartMesh.scale.clone(),
                    toothNumber: tNum,
                    isChart: true,
                };
            }
        };

        // Upper row at y = +2.70 (roots point up, crowns point down toward midline)
        buildRow(upperOrder, true, upperChartRotY, 2.70);
        // Lower row at y = -2.70 (roots point down, crowns point up toward midline)
        buildRow(lowerOrder, false, lowerChartRotY, -2.70);

        // Map deciduous primary teeth pointers
        const primaryToAdultMap = {
            "55": "16", "54": "14", "53": "13", "52": "12", "51": "11",
            "61": "21", "62": "22", "63": "23", "64": "24", "65": "26",
            "71": "31", "72": "32", "73": "33", "74": "34", "75": "36",
            "81": "41", "82": "42", "83": "43", "84": "44", "85": "46",
        };
        for (const [pNum, aNum] of Object.entries(primaryToAdultMap)) {
            if (this.chartToothMeshes[aNum]) {
                this.chartToothMeshes[pNum] = {
                    mesh: this.chartToothMeshes[aNum].mesh,
                    isUpper: this.chartToothMeshes[aNum].isUpper,
                    basePos: this.chartToothMeshes[aNum].basePos,
                    toothNumber: pNum,
                    isPrimary: true,
                    isChart: true,
                };
            }
        }

        this.chartRoot.visible = this.state.viewMode === "chart";
        this.chartRoot.updateMatrixWorld(true);
        this._needsChartAlign = true;
        if (this.state.viewMode === "chart") {
            this.alignChartTeethWithUI();
        }
    }

    // -------------------------------------------------------------------------
    // Fallback Procedural Arches (if GLB asset is unavailable)
    // -------------------------------------------------------------------------

    buildProceduralDentalArches(THREE) {
        this.toothMeshes = {};
        const archRadiusX = 5.6;
        const archRadiusZ = 6.4;

        const upperTeeth = [
            "18", "17", "16", "15", "14", "13", "12", "11",
            "21", "22", "23", "24", "25", "26", "27", "28"
        ];
        this.createProceduralArch(THREE, upperTeeth, +1.75, true, archRadiusX, archRadiusZ);

        const lowerTeeth = [
            "48", "47", "46", "45", "44", "43", "42", "41",
            "31", "32", "33", "34", "35", "36", "37", "38"
        ];
        this.createProceduralArch(THREE, lowerTeeth, -1.75, false, archRadiusX * 0.94, archRadiusZ * 0.94);

        this.buildToothChart(THREE);
        if (this.modelRoot) this.modelRoot.visible = this.state.viewMode !== "chart";
        if (this.chartRoot) this.chartRoot.visible = this.state.viewMode === "chart";
        this.applyDentitionVisibility();
    }

    createProceduralArch(THREE, teethList, yLevel, isUpper, radiusX, radiusZ) {
        const count = teethList.length;
        const angleStep = (Math.PI * 0.96) / (count - 1);

        for (let i = 0; i < count; i++) {
            const toothNum = teethList[i];
            const theta = -Math.PI * 0.48 + i * angleStep;

            const posX = radiusX * Math.sin(theta);
            const posZ = -radiusZ * (1 - Math.cos(theta)) + 1.4;

            const toothGroup = new THREE.Group();
            toothGroup.position.set(posX, yLevel, posZ);
            toothGroup.rotation.y = -theta;
            if (!isUpper) toothGroup.rotation.z = Math.PI;

            const crownGeo = new THREE.CylinderGeometry(0.65, 0.55, 0.95, 16);
            crownGeo.computeVertexNormals();
            const crownMat = new THREE.MeshStandardMaterial({ color: 0xf5f2ec, roughness: 0.28, metalness: 0.04 });
            const crownMesh = new THREE.Mesh(crownGeo, crownMat);
            crownMesh.castShadow = true;
            crownMesh.receiveShadow = true;
            crownMesh.userData = { toothNumber: toothNum, isUpper };
            toothGroup.add(crownMesh);

            const outlineMesh = this.createToothOutline(THREE, crownMesh);
            this.scene.add(toothGroup);

            this.toothMeshes[toothNum] = {
                mesh: crownMesh,
                outlineMesh: outlineMesh,
                group: toothGroup,
                isUpper: isUpper,
                basePos: crownMesh.position.clone(),
                baseScale: crownMesh.scale.clone(),
                toothNumber: toothNum,
            };
        }
    }

    // -------------------------------------------------------------------------
    // Material Updates & Condition Color Coding
    // -------------------------------------------------------------------------

    updateAllToothMaterials() {
        if (!this.is3DReady) return;
        const THREE = window.THREE;
        if (!THREE) return;

        const conditionColors = {
            caries: 0xef4444,               // Alert red (Caries/Cavity)
            restoration: 0x3b82f6,          // Clinical blue (Filled/Restoration)
            crown: 0xf59e0b,               // Lustrous gold (Crown)
            root_canal: 0xa855f7,           // Deep violet (Endodontic)
            implant: 0x06b6d4,              // Titanium cyan (Implant)
            missing: 0x94a3b8,              // Ghost slate (Missing)
            dummy_permanent: 0x0d9488,      // Lustrous Porcelain Teal (Permanent Dummy Tooth)
            dummy_temporary: 0xf97316,      // Warm Acrylic Coral-Amber (Temporary Dummy Tooth)
            fracture: 0xe11d48,             // Rose/Coral (Chipped/Fracture)
            impacted: 0xec4899,             // Pink (Impacted)
            extraction_indicated: 0xdc2626, // Crimson (Extraction)
            bridge: 0x6366f1,               // Indigo (Bridge)
            other: 0x64748b,                // Muted grey (Other)
        };

        // 1. Update 3D Anatomical Jaw Arch Meshes (Overall Mouth View)
        for (const [tNum, toothObj] of Object.entries(this.toothMeshes || {})) {
            if (toothObj.isPrimary) continue;

            const activeNum = this.getActiveToothNumber(tNum);
            const toothInfo = this.state.teeth[activeNum] || { condition: "sound" };
            const cond = toothInfo.condition || "sound";
            const isSelected = this.state.selectedTooth === activeNum;
            const isHovered = this.state.hoveredTooth === activeNum;

            const mesh = toothObj.mesh;
            if (!mesh || !mesh.material) continue;

            const toothLastDigit = parseInt(activeNum.slice(-1), 10) || 1;
            const soundColor = toothLastDigit % 2 === 0 ? 0xfbf9f2 : 0xede8dc;

            let colorHex;
            if (isSelected) {
                if (cond === "sound") {
                    colorHex = 0x0284c7; // Distinct vibrant clinical blue
                } else {
                    colorHex = conditionColors[cond] || 0x0284c7;
                }
            } else {
                colorHex = cond === "sound" ? soundColor : (conditionColors[cond] || soundColor);
            }

            mesh.material.color.setHex(colorHex);

            // JAW OVERALL VIEW: Missing teeth are visually removed from the mouth (authentic empty gap).
            // However, visible MUST remain true so Three.js raycasting continues to hit the empty space!
            if (cond === "missing") {
                if (isSelected) {
                    // When clicked/selected on the empty gap, render an ethereal glowing blue wireframe socket indicator
                    mesh.material.colorWrite = true;
                    mesh.material.depthWrite = false;
                    mesh.material.transparent = true;
                    mesh.material.opacity = 0.38;
                    mesh.material.wireframe = true;
                    mesh.material.color.setHex(0x0284c7);
                } else {
                    // Completely invisible empty space in the mouth arch
                    mesh.material.colorWrite = false;
                    mesh.material.depthWrite = false;
                    mesh.material.transparent = true;
                    mesh.material.opacity = 0.0001;
                    mesh.material.wireframe = false;
                }
                if (toothObj.outlineMesh) {
                    toothObj.outlineMesh.visible = false;
                }
            } else {
                mesh.material.colorWrite = true;
                mesh.material.depthWrite = true;
                mesh.material.transparent = false;
                mesh.material.opacity = 1.0;
                mesh.material.wireframe = false;
                if (toothObj.outlineMesh) {
                    toothObj.outlineMesh.visible = this.state.showSeparations !== false;
                }
            }

            // Material luster & texture for Dummy teeth, Crown, Implant, etc.
            if (cond === "dummy_permanent") {
                mesh.material.metalness = 0.28;
                mesh.material.roughness = 0.18; // Glazed porcelain shine
            } else if (cond === "dummy_temporary") {
                mesh.material.metalness = 0.04;
                mesh.material.roughness = 0.42; // Acrylic provisional finish
            } else if (cond === "crown") {
                mesh.material.metalness = 0.72;
                mesh.material.roughness = 0.22;
            } else if (cond === "implant") {
                mesh.material.metalness = 0.85;
                mesh.material.roughness = 0.20;
            } else {
                mesh.material.metalness = 0.02;
                mesh.material.roughness = cond === "caries" ? 0.38 : (isSelected ? 0.18 : 0.28);
            }

            mesh.material.side = THREE.DoubleSide;

            // Selection & Hover Emissive Setup
            if (isSelected) {
                if (cond === "missing") {
                    mesh.material.emissive.setHex(0x0284c7);
                    mesh.material.emissiveIntensity = 0.50;
                } else if (cond === "sound") {
                    mesh.material.emissive.setHex(0x0284c7);
                    mesh.material.emissiveIntensity = 0.55;
                } else {
                    mesh.material.emissive.setHex(0x38bdf8);
                    mesh.material.emissiveIntensity = 0.60;
                }
            } else if (isHovered) {
                if (cond === "missing") {
                    mesh.material.colorWrite = true;
                    mesh.material.wireframe = true;
                    mesh.material.opacity = 0.22;
                    mesh.material.emissive.setHex(0x38bdf8);
                    mesh.material.emissiveIntensity = 0.35;
                } else {
                    mesh.material.emissive.setHex(cond === "sound" ? 0x0284c7 : colorHex);
                    mesh.material.emissiveIntensity = 0.30;
                }
                if (toothObj.basePos) mesh.position.copy(toothObj.basePos);
                if (toothObj.baseScale) mesh.scale.copy(toothObj.baseScale);
            } else {
                mesh.material.emissive.setHex(0x000000);
                mesh.material.emissiveIntensity = 0.0;
                if (toothObj.basePos) mesh.position.copy(toothObj.basePos);
                if (toothObj.baseScale) mesh.scale.copy(toothObj.baseScale);
            }
        }

        // 2. Update 3D Tooth-by-Tooth Frontal Chart Meshes
        for (const [tNum, toothObj] of Object.entries(this.chartToothMeshes || {})) {
            if (toothObj.isPrimary) continue;

            const activeNum = this.getActiveToothNumber(tNum);
            const toothInfo = this.state.teeth[activeNum] || { condition: "sound" };
            const cond = toothInfo.condition || "sound";
            const isSelected = this.state.selectedTooth === activeNum;
            const isHovered = this.state.hoveredTooth === activeNum;

            const mesh = toothObj.mesh;
            if (!mesh || !mesh.material) continue;

            // Tooth-by-tooth chart: healthy teeth are plain white (charting convention); spacing separates them
            const soundColor = CHART_STYLE.toothWhite;

            let colorHex;
            if (isSelected) {
                if (cond === "sound") {
                    colorHex = 0x0284c7;
                } else {
                    colorHex = conditionColors[cond] || 0x0284c7;
                }
            } else {
                colorHex = cond === "sound" ? soundColor : (conditionColors[cond] || soundColor);
            }

            mesh.material.color.setHex(colorHex);

            // CHART VIEW: Missing tooth is crossed with a cross icon in UI overlay.
            // In 3D chart mesh, render as a faint muted wireframe to emphasize absence.
            if (cond === "missing") {
                mesh.material.colorWrite = true;
                mesh.material.depthWrite = false;
                mesh.material.transparent = true;
                mesh.material.opacity = isSelected ? 0.38 : 0.16;
                mesh.material.wireframe = true;
                mesh.material.color.setHex(0x94a3b8);
                if (toothObj.outlineMesh) {
                    toothObj.outlineMesh.visible = false;
                }
            } else {
                mesh.material.colorWrite = true;
                mesh.material.depthWrite = true;
                mesh.material.transparent = false;
                mesh.material.opacity = 1.0;
                mesh.material.wireframe = false;
                if (toothObj.outlineMesh) {
                    toothObj.outlineMesh.visible = this.state.showSeparations !== false;
                }
            }

            // Dummy luster & texture
            if (cond === "dummy_permanent") {
                mesh.material.metalness = 0.28;
                mesh.material.roughness = 0.18;
            } else if (cond === "dummy_temporary") {
                mesh.material.metalness = 0.04;
                mesh.material.roughness = 0.42;
            } else if (cond === "crown") {
                mesh.material.metalness = 0.72;
                mesh.material.roughness = 0.22;
            } else if (cond === "implant") {
                mesh.material.metalness = 0.85;
                mesh.material.roughness = 0.20;
            } else {
                mesh.material.metalness = 0.02;
                mesh.material.roughness = cond === "caries" ? 0.38 : (isSelected ? 0.18 : CHART_STYLE.toothRoughness);
            }

            mesh.material.side = THREE.DoubleSide;

            // Emissive setup
            if (isSelected) {
                mesh.material.emissive.setHex(0x0284c7);
                mesh.material.emissiveIntensity = 0.55;
            } else if (isHovered) {
                mesh.material.emissive.setHex(cond === "sound" ? 0x0284c7 : colorHex);
                mesh.material.emissiveIntensity = 0.30;
                if (toothObj.basePos) mesh.position.copy(toothObj.basePos);
                if (toothObj.baseScale) mesh.scale.copy(toothObj.baseScale);
            } else {
                // Soft white self-light keeps healthy teeth reading as white instead of shaded grey
                const glow = cond === "sound" ? CHART_STYLE.toothGlow : 0.0;
                mesh.material.emissive.setHex(glow ? CHART_STYLE.toothWhite : 0x000000);
                mesh.material.emissiveIntensity = glow;
                if (toothObj.basePos) mesh.position.copy(toothObj.basePos);
                if (toothObj.baseScale) mesh.scale.copy(toothObj.baseScale);
            }
        }
    }

    applySceneBackground() {
        const THREE = window.THREE;
        if (!THREE || !this.scene) return;
        const hex = this.state.viewMode === "chart" ? CHART_STYLE.background : JAW_BACKGROUND;
        this.scene.background = new THREE.Color(hex);
    }

    getActiveToothNumber(adultToothNum) {
        const dentition = this.state.dentitionType || "permanent";
        if (dentition === "primary") {
            const adultToPrimaryMap = {
                "16": "55", "14": "54", "13": "53", "12": "52", "11": "51",
                "21": "61", "22": "62", "23": "63", "24": "64", "26": "65",
                "31": "71", "32": "72", "33": "73", "34": "74", "36": "75",
                "41": "81", "42": "82", "43": "83", "44": "84", "46": "85",
            };
            return adultToPrimaryMap[adultToothNum] || adultToothNum;
        } else if (dentition === "mixed") {
            const mixedAdultToDeciduous = {
                "14": "54", "13": "53",
                "23": "63", "24": "64", "25": "65",
                "33": "73", "34": "74", "35": "75",
                "43": "83", "44": "84", "45": "85",
            };
            return mixedAdultToDeciduous[adultToothNum] || adultToothNum;
        }
        return adultToothNum;
    }

    // -------------------------------------------------------------------------
    // Raycasting & User Interactions
    // -------------------------------------------------------------------------

    getInteractiveMeshes() {
        const uniqueMeshes = [];
        const seen = new Set();
        const sourceMap = this.state.viewMode === "chart" ? this.chartToothMeshes : this.toothMeshes;
        for (const tObj of Object.values(sourceMap || {})) {
            if (tObj && tObj.mesh && tObj.mesh.visible && !seen.has(tObj.mesh)) {
                seen.add(tObj.mesh);
                uniqueMeshes.push(tObj.mesh);
            }
        }
        return uniqueMeshes;
    }

    findIntersectedTooth(event) {
        if (!this.is3DReady || !this.renderer || !this.camera) return null;

        const rect = this.renderer.domElement.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) return null;

        const x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
        const y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

        this.pointer.set(x, y);
        this.raycaster.setFromCamera(this.pointer, this.camera);

        const interactiveMeshes = this.getInteractiveMeshes();
        if (interactiveMeshes.length === 0) return null;

        // Ensure world matrices are fresh for raycaster
        for (let i = 0; i < interactiveMeshes.length; i++) {
            interactiveMeshes[i].updateMatrixWorld();
        }

        const intersects = this.raycaster.intersectObjects(interactiveMeshes, true);
        if (intersects.length > 0) {
            // Find first intersection with a tooth number
            for (const hitObj of intersects) {
                let curr = hitObj.object;
                while (curr && curr !== this.scene) {
                    const tNum = curr.userData?.toothNumber;
                    if (tNum) {
                        const activeNum = this.getActiveToothNumber(String(tNum));
                        return { toothNumber: activeNum, object: curr, rect };
                    }
                    curr = curr.parent;
                }
            }
        }
        return null;
    }

    onPointerMove(event) {
        if (!this.is3DReady || !this.renderer) return;

        const result = this.findIntersectedTooth(event);
        if (result) {
            const { toothNumber, rect } = result;
            this.renderer.domElement.style.cursor = "pointer";
            const info = this.state.teeth[toothNumber];
            const isMissing = info?.condition === "missing";
            const condLabel = this.getConditionLabel(info?.condition || "sound");
            if (this.state.hoveredTooth !== toothNumber) {
                this.state.hoveredTooth = toothNumber;
                this.state.hoveredToothInfo = isMissing
                    ? `Tooth ${toothNumber} • Missing Tooth (Gap - Click to Inspect)`
                    : `Tooth ${toothNumber} • ${condLabel}`;
                this.updateAllToothMaterials();
            }
            this.state.tooltipX = event.clientX - rect.left;
            this.state.tooltipY = event.clientY - rect.top;
            return;
        }

        if (this.state.hoveredTooth) {
            this.renderer.domElement.style.cursor = this.state.viewMode === "chart" ? "default" : "grab";
            this.state.hoveredTooth = null;
            this.updateAllToothMaterials();
        }
    }

    onPointerUp(event) {
        if (!this.is3DReady || !this.renderer) return;

        // Check if movement between pointer down and up was small (a clean click / tap)
        const dx = event.clientX - (this.pointerDownPos?.x ?? event.clientX);
        const dy = event.clientY - (this.pointerDownPos?.y ?? event.clientY);
        const dragDist = Math.hypot(dx, dy);
        if (dragDist > 16) return; // User was deliberately orbiting or panning

        const result = this.findIntersectedTooth(event);
        if (result) {
            this.openToothStudio(result.toothNumber);
        }
    }

    selectTooth(tNum, { keepChartSelection = false } = {}) {
        if (!tNum) return;
        if (this.lastBreathingMesh) {
            this.resetMeshBreathing(this.lastBreathingMesh);
            this.lastBreathingMesh = null;
        }
        this.state.selectedTooth = String(tNum);
        if (!keepChartSelection) {
            this.state.chartSelection = [this.state.selectedTooth];
        }
        const currentData = this.state.teeth[this.state.selectedTooth];

        // Prepopulate new finding form with current finding defaults
        if (currentData) {
            this.state.newFinding.condition = currentData.condition === "sound" ? "caries" : currentData.condition;
            this.state.newFinding.diagnosis_id = "";
            this.state.newFinding.surfaces = currentData.surfaces ? currentData.surfaces.split("") : ["O"];
            this.state.newFinding.severity = currentData.severity || "moderate";
            this.state.newFinding.treatment_indicated = currentData.treatment_indicated || "";
            this.state.newFinding.notes = "";
        } else {
            this.state.newFinding.condition = "caries";
            this.state.newFinding.diagnosis_id = "";
            this.state.newFinding.surfaces = ["O"];
            this.state.newFinding.severity = "moderate";
            this.state.newFinding.treatment_indicated = "";
            this.state.newFinding.notes = "";
        }

        // Tooth Studio details start from the tooth's latest recorded values
        const data = currentData || {};
        const cond = data.condition || "sound";
        Object.assign(this.state.newFinding, {
            restoration_type: data.restoration_type || "",
            restoration_material: data.restoration_material || "",
            restoration_quality: data.restoration_quality || "",
            restoration_detail: data.restoration_detail || "",
            surface_details: data.surface_details ? data.surface_details.split(",") : [],
            endo_tests: { ...(data.endo_tests || {}) },
            perio: Object.fromEntries(PERIO_SITE_KEYS.map((site) => [site, data.perio?.[site] || 0])),
        });
        if (cond === "missing") {
            this.state.dxCategory = "missing";
        } else if (PATHOLOGY_CONDITIONS.includes(cond)) {
            this.state.dxCategory = "pathology";
        } else if (RESTORATION_OPTIONS[cond] || cond === "restoration") {
            this.state.dxCategory = "restoration";
        } else {
            this.state.dxCategory = "";
        }
        if (this.state.dxCategory) {
            this.state.newFinding.condition = cond;
        } else if (this.state.viewMode === "chart" || this.state.toothWindowOpen) {
            // Healthy tooth opened in the studio: no surface pre-selected
            this.state.newFinding.surfaces = [];
        }

        if (this.state.canEdit) {
            this.state.activePanelTab = "record";
        } else {
            this.state.activePanelTab = "history";
        }

        this.updateAllToothMaterials();
    }

    // -------------------------------------------------------------------------
    // View Controls & Camera Presets
    // -------------------------------------------------------------------------

    async setViewMode(mode) {
        if (this.state.viewMode === mode) return;
        if (mode === "jaw" && (this.webglFailed || this.state.webglError)) {
            // Retry once on demand: the earlier failure may have been transient (GPU reset, context limit).
            this.webglFailed = false;
            this.state.webglError = false;
            try {
                await this.init3DScene();
            } catch (err) {
                this.handle3DInitError(err);
            }
            if (this.webglFailed || !this.renderer) {
                this.webglFailed = true;
                this.state.webglError = true;
                this.notification?.add?.(
                    _t("3D WebGL graphics acceleration is not available in your browser. Using 2D Chart view."),
                    { type: "warning" }
                );
                return;
            }
        }
        if (this.lastBreathingMesh) {
            this.resetMeshBreathing(this.lastBreathingMesh);
            this.lastBreathingMesh = null;
        }

        // The tooth-by-tooth chart is a 2D SVG chart; the 3D jaw scene stays untouched (canvas hidden,
        // rendering paused) so its camera is exactly where the user left it on return.
        this.state.viewMode = mode;
        if (this.modelRoot) this.modelRoot.visible = true;
        if (this.chartRoot) this.chartRoot.visible = false;
        if (mode === "jaw") {
            this.applySceneBackground();
            requestAnimationFrame(() => this.onWindowResize());
        }
        this.updateAllToothMaterials();
    }

    setView(viewName) {
        if (!this.camera || !this.controls) return;
        this.state.currentView = viewName;

        if (viewName === "front") {
            // Anterior front bite overview with reduced default zoom (two steps zoomed out for optimal framing)
            this.camera.position.set(0, 0.26, 18.8);
            this.controls.target.set(0, -0.15, 0);
        } else if (viewName === "upper") {
            // Maxilla view looking up from anterior-inferior at palatal curvature
            this.camera.position.set(0, -10.0, 12.7);
            this.controls.target.set(0, 0.45, 0.2);
        } else if (viewName === "lower") {
            // Mandible view looking down from anterior-superior at teeth & arch
            this.camera.position.set(0, 10.8, 11.9);
            this.controls.target.set(0, -0.45, 0.2);
        } else if (viewName === "occlusal") {
            // Angled 3D occlusal overview
            this.camera.position.set(0, 8.7, 16.5);
            this.controls.target.set(0, -0.10, 0);
        }
        this.controls.update();
    }

    resetCamera() {
        this.setView("front");
    }

    zoomCamera(delta) {
        if (!this.camera || !this.controls) return;
        const target = this.controls.target;
        const offset = this.camera.position.clone().sub(target);
        const factor = delta > 0 ? 1.15 : 0.85;
        offset.multiplyScalar(factor);
        const dist = offset.length();
        if (dist >= this.controls.minDistance && dist <= this.controls.maxDistance) {
            this.camera.position.copy(target).add(offset);
            this.controls.update();
        }
    }

    rotateCamera(angleDelta) {
        if (!this.camera || !this.controls) return;
        const target = this.controls.target;
        const offset = this.camera.position.clone().sub(target);
        const cos = Math.cos(angleDelta);
        const sin = Math.sin(angleDelta);
        const newX = offset.x * cos - offset.z * sin;
        const newZ = offset.x * sin + offset.z * cos;
        this.camera.position.set(target.x + newX, this.camera.position.y, target.z + newZ);
        this.camera.lookAt(target);
        this.controls.update();
    }

    panCamera(deltaX, deltaY) {
        if (!this.camera || !this.controls) return;
        this.camera.position.x += deltaX;
        this.camera.position.y += deltaY;
        this.controls.target.x += deltaX;
        this.controls.target.y += deltaY;
        this.controls.update();
    }

    setDentitionType(type) {
        if (this.isDentitionDisabled(type)) {
            const warningMsg = this.getDentitionTooltip(type);
            this.notification.add(warningMsg, { type: "warning" });
            return;
        }

        this.userOverrodeDentition = true;
        this.state.dentitionType = type;
        this.state.selectedTooth = null;
        this.state.chartSelection = [];
        this.state.chartScreen = "overview";
        this.state.toothWindowOpen = false;
        this.state.toothSearch.open = false;
        const caseId = this.caseId || this.getCaseId();
        const patientId = this.patientId || this.getPatientId();
        try {
            if (caseId) localStorage.setItem(`dental_dentition_case_${caseId}`, type);
            if (patientId) localStorage.setItem(`dental_dentition_patient_${patientId}`, type);
            localStorage.setItem("dental_dentition_type", type);
        } catch (e) {}
        this.notifyRecordChanged();
        this.applyDentitionVisibility();
        this.updateAllToothMaterials();
    }

    applyDentitionVisibility() {
        if (!this.toothMeshes) return;
        const dentition = this.state.dentitionType || "permanent";

        // Permanent: all 32 adult teeth visible
        // Primary: 20 deciduous teeth (FDI 51-55, 61-65, 71-75, 81-85).
        // In 3D jaw model, 20 teeth corresponds to anterior 5 teeth of each quadrant (excluding 18, 17, 27, 28, 38, 37, 47, 48, 15, 25, 35, 45)
        const primaryHiddenAdult = new Set([
            "18", "17", "15",
            "28", "27", "25",
            "38", "37", "35",
            "48", "47", "45",
        ]);

        // Mixed: 24 teeth (6 in each quadrant: permanent 1st molars 16, 26, 36, 46 + primary molars & incisors; excluding 3rd & 2nd permanent molars)
        const mixedHiddenAdult = new Set([
            "18", "17", "28", "27", "38", "37", "48", "47"
        ]);

        for (const [tNum, toothObj] of Object.entries(this.toothMeshes)) {
            if (!toothObj || !toothObj.mesh) continue;
            if (toothObj.isPrimary) continue; // Deciduous entries point to same underlying mesh

            if (dentition === "primary") {
                toothObj.mesh.visible = !primaryHiddenAdult.has(tNum);
            } else if (dentition === "mixed") {
                toothObj.mesh.visible = !mixedHiddenAdult.has(tNum);
            } else {
                toothObj.mesh.visible = true;
            }
        }

        if (this.chartToothMeshes) {
            for (const [tNum, toothObj] of Object.entries(this.chartToothMeshes)) {
                if (!toothObj || !toothObj.mesh) continue;
                if (toothObj.isPrimary) continue;

                if (dentition === "primary") {
                    toothObj.mesh.visible = !primaryHiddenAdult.has(tNum);
                } else if (dentition === "mixed") {
                    toothObj.mesh.visible = !mixedHiddenAdult.has(tNum);
                } else {
                    toothObj.mesh.visible = true;
                }
            }
        }

        if (this.state.viewMode === "chart") {
            this._needsChartAlign = true;
            this.alignChartTeethWithUI();
        }
    }

    onWindowResize() {
        if (!this.is3DReady) {
            this.init3DScene().catch((err) => this.handle3DInitError(err));
            return;
        }
        const viewport = this.viewportEl;
        if (!viewport || !this.camera || !this.renderer) return;
        const width = viewport.clientWidth;
        const height = viewport.clientHeight;
        if (width > 50 && height > 50) {
            this.camera.aspect = width / height;
            this.camera.updateProjectionMatrix();
            this.renderer.setSize(width, height);
            if (this.state.viewMode === "chart") {
                const aspect = width / height;
                const fovRad = ((this.camera.fov || 36) * Math.PI) / 180;
                const halfTan = Math.tan(fovRad / 2);
                const chartRequiredWidth = 28.5;
                const chartRequiredHeight = 12.0;
                const zForWidth = chartRequiredWidth / (2 * halfTan * Math.max(aspect, 0.5));
                const zForHeight = chartRequiredHeight / (2 * halfTan);
                const zDist = Math.max(zForWidth, zForHeight, 24.0);
                this.camera.position.set(0, 0, zDist);
                this.camera.lookAt(0, 0, 0);
                if (this.controls) this.controls.target.set(0, 0, 0);
                this._needsChartAlign = true;
                this.alignChartTeethWithUI();
            } else if (this.controls) {
                this.controls.update();
            }
        }
    }

    alignChartTeethWithUI() {
        if (this.state.viewMode !== "chart" || !this.camera || !this.renderer || !this.chartToothMeshes) {
            return;
        }
        const viewport = this.viewportEl;
        if (!viewport) return;
        const canvasEl = this.renderer.domElement;
        if (!canvasEl) return;
        const canvasRect = canvasEl.getBoundingClientRect();
        if (canvasRect.width <= 0 || canvasRect.height <= 0) return;

        const fovRad = ((this.camera.fov || 36) * Math.PI) / 180;
        const visibleHalfHeight = Math.abs(this.camera.position.z) * Math.tan(fovRad / 2);
        const visibleHalfWidth = visibleHalfHeight * this.camera.aspect;

        const cells = viewport.querySelectorAll(".chart-status-cell[data-tooth-num], .chart-num-btn[data-tooth-num]");
        if (!cells || cells.length === 0) return;

        // Group elements by tooth number to determine the exact horizontal center in the canvas
        const toothXMap = {};
        for (const el of cells) {
            const tNum = el.dataset.toothNum;
            if (!tNum) continue;
            if (toothXMap[tNum] === undefined) {
                const rect = el.getBoundingClientRect();
                if (rect.width > 0) {
                    const pixelCenterX = rect.left + rect.width / 2 - canvasRect.left;
                    const ndcX = (pixelCenterX / canvasRect.width) * 2 - 1;
                    toothXMap[tNum] = ndcX * visibleHalfWidth;
                }
            }
        }

        let anyUpdated = false;
        for (const [tNum, targetX] of Object.entries(toothXMap)) {
            const toothObj = this.chartToothMeshes[tNum];
            if (toothObj && toothObj.mesh) {
                toothObj.mesh.position.x = targetX;
                if (toothObj.basePos) {
                    toothObj.basePos.x = targetX;
                }
                toothObj.mesh.updateMatrixWorld(true);
                anyUpdated = true;
            }
        }

        if (anyUpdated) {
            this._lastAlignedCanvasWidth = canvasRect.width;
            this._needsChartAlign = false;
        }
    }

    // -------------------------------------------------------------------------
    // Panel Form Actions (Record Finding)
    // -------------------------------------------------------------------------

    hasSurface(surf) {
        return this.state.newFinding.surfaces.includes(surf);
    }

    toggleSurface(surf) {
        const idx = this.state.newFinding.surfaces.indexOf(surf);
        if (idx >= 0) {
            this.state.newFinding.surfaces.splice(idx, 1);
        } else {
            this.state.newFinding.surfaces.push(surf);
        }
        this.notifyRecordChanged();
    }

    setSeverity(sev) {
        this.state.newFinding.severity = sev;
        this.notifyRecordChanged();
    }

    setCondition(val) {
        this.state.newFinding.condition = val;
        const tNum = this.state.selectedTooth;
        if (tNum) {
            if (!this.state.teeth[tNum]) {
                this.state.teeth[tNum] = {
                    tooth_number: tNum,
                    condition: val,
                    surfaces: this.state.newFinding.surfaces.join(""),
                    severity: this.state.newFinding.severity,
                };
            } else {
                this.state.teeth[tNum].condition = val;
            }
            this.updateAllToothMaterials();
            this.notifyRecordChanged();
        }
    }

    setNotes(val) {
        this.state.newFinding.notes = val;
        this.notifyRecordChanged();
    }

    async notifyRecordChanged() {
        if (!this.props.record) return;
        const fieldName = this.props.name || "odontogram_chart";
        const chartData = JSON.stringify({
            dentition: this.state.dentitionType,
            teeth: this.state.teeth,
            selected_tooth: this.state.selectedTooth,
            updated_at: new Date().toISOString(),
        });

        try {
            if (typeof this.props.record.update === "function") {
                await this.props.record.update({ [fieldName]: chartData });
            } else if (typeof this.props.update === "function") {
                await this.props.update(chartData);
            }
        } catch (err) {
            console.warn("Could not notify Odoo record of odontogram change:", err);
        }
    }

    async onClearFinding() {
        if (!this.state.selectedTooth) return;
        const caseId = this.caseId || this.getCaseId();
        if (!caseId) {
            this.notification.add(_t("Please save the dental case before clearing findings."), {
                type: "warning",
            });
            return;
        }

        this.state.isSaving = true;

        try {
            const result = await this.orm.call("dental.case", "clear_tooth_finding", [caseId], {
                tooth_number: this.state.selectedTooth,
            });

            if (result && result.success) {
                const refreshed = result.odontogram_data;
                this.state.teeth = refreshed.teeth || {};
                this.state.stats = refreshed.stats || {};
                this.state.diagnosisMasters = refreshed.diagnosis_masters || this.state.diagnosisMasters;

                this.updateAllToothMaterials();

                // Notify Odoo form model & trigger default autosave
                await this.notifyRecordChanged();
                if (this.props.record && typeof this.props.record.save === "function") {
                    await this.props.record.save();
                }

                this.notification.add(
                    _t("Tooth %s marked as sound / cleared!", this.state.selectedTooth),
                    { type: "success" }
                );

                this.state.activePanelTab = "history";
            }
        } catch (error) {
            console.error("Failed to clear tooth finding:", error);
            this.notification.add(error.message || _t("Failed to clear tooth finding."), {
                type: "danger",
            });
        } finally {
            this.state.isSaving = false;
        }
    }

    // -------------------------------------------------------------------------
    // Selection Breathing Effect Animation Loop
    // -------------------------------------------------------------------------

    updateSelectionBreathingEffect(timestamp) {
        const selNum = this.state.selectedTooth;
        if (!selNum) {
            if (this.lastBreathingMesh) {
                this.resetMeshBreathing(this.lastBreathingMesh);
                this.lastBreathingMesh = null;
            }
            return;
        }

        const isChart = this.state.viewMode === "chart";
        const sourceMap = isChart ? this.chartToothMeshes : this.toothMeshes;
        if (!sourceMap) return;

        const toothObj = sourceMap[selNum];
        if (!toothObj || !toothObj.mesh) return;

        const mesh = toothObj.mesh;
        if (this.lastBreathingMesh && this.lastBreathingMesh !== mesh) {
            this.resetMeshBreathing(this.lastBreathingMesh);
        }
        this.lastBreathingMesh = mesh;

        // Smooth organic breathing cycle: ~1.8 seconds per breath
        const t = (timestamp || performance.now()) * 0.0035;
        const pulse = (Math.sin(t) + 1.0) * 0.5; // Smooth 0.0 to 1.0

        // 1. Dynamic emissive glow breathing
        const isMissing = this.isMissingTooth(selNum);
        if (mesh.material) {
            mesh.material.emissiveIntensity = 0.35 + 0.45 * pulse;
            if (isMissing && !isChart) {
                // Ethereal wireframe socket glow breathing in the empty gap
                mesh.material.opacity = 0.28 + 0.20 * pulse;
            }
        }

        // 2. Smooth socket elevation breathing
        if (toothObj.basePos) {
            const isUpper = toothObj.isUpper;
            if (isChart) {
                // In 2-row frontal chart: upper crown points down, lower crown points up
                // Move slightly toward midline (Y) and forward (Z)
                const yOffset = isUpper ? -(0.18 + 0.07 * pulse) : +(0.18 + 0.07 * pulse);
                mesh.position.y = toothObj.basePos.y + yOffset;
                mesh.position.z = toothObj.basePos.z + 0.28 + 0.08 * pulse;
            } else {
                // In 3D jaw
                const liftBase = isUpper ? 0.28 : -0.28;
                const liftPulse = isUpper ? (0.07 * pulse) : (-0.07 * pulse);
                mesh.position.y = toothObj.basePos.y + liftBase + liftPulse;
                mesh.position.z = toothObj.basePos.z + 0.18 + 0.05 * pulse;
            }
        }

        // 3. Subtle organic scale breathing (+4%)
        const baseScale = toothObj.baseScale || { x: 1, y: 1, z: 1 };
        const scaleFactor = 1.0 + 0.04 * pulse;
        mesh.scale.set(baseScale.x * scaleFactor, baseScale.y * scaleFactor, baseScale.z * scaleFactor);
    }

    resetMeshBreathing(mesh) {
        if (!mesh) return;
        const tNum = mesh.userData?.toothNumber;
        const isChart = mesh.userData?.isChart;
        const sourceMap = isChart ? this.chartToothMeshes : this.toothMeshes;
        const toothObj = (tNum && sourceMap) ? sourceMap[tNum] : null;
        if (toothObj) {
            if (toothObj.basePos) {
                mesh.position.copy(toothObj.basePos);
            }
            if (toothObj.baseScale) {
                mesh.scale.copy(toothObj.baseScale);
            }
        }
        if (mesh.material) {
            mesh.material.emissive.setHex(0x000000);
            mesh.material.emissiveIntensity = 0.0;
            if (tNum && this.isMissingTooth(tNum) && !isChart) {
                mesh.material.colorWrite = false;
                mesh.material.wireframe = false;
                mesh.material.opacity = 0.0001;
            }
        }
    }

    // -------------------------------------------------------------------------
    // Cleanup
    // -------------------------------------------------------------------------

    cleanup3D() {
        if (this.lastBreathingMesh) {
            this.resetMeshBreathing(this.lastBreathingMesh);
            this.lastBreathingMesh = null;
        }
        if (this.animationFrameId) {
            cancelAnimationFrame(this.animationFrameId);
        }
        if (this.resizeObserver) {
            this.resizeObserver.disconnect();
        }
        if (this.intersectionObserver) {
            this.intersectionObserver.disconnect();
        }
        if (this.tabMutationObserver) {
            this.tabMutationObserver.disconnect();
        }
        if (this.onWindowResizeBound) {
            window.removeEventListener("resize", this.onWindowResizeBound);
        }
        if (this.controls) {
            this.controls.dispose();
            this.controls = null;
        }
        if (this.animationFrameId) {
            this.animationFrameId = null;
        }
        this.resizeObserver = null;
        this.intersectionObserver = null;
        this.tabMutationObserver = null;
        this.onWindowResizeBound = null;
        if (this.renderer) {
            if (this.renderer.domElement) {
                this.renderer.domElement.dataset.disposed = "1";
            }
            try {
                if (typeof this.renderer.forceContextLoss === "function") {
                    this.renderer.forceContextLoss();
                }
                const gl = this.renderer.getContext();
                if (gl) {
                    const loseContextExt = gl.getExtension("WEBGL_lose_context");
                    if (loseContextExt) {
                        loseContextExt.loseContext();
                    }
                }
                this.renderer.dispose();
            } catch (e) {
                console.warn("Error disposing renderer:", e);
            }
            if (this.renderer.domElement && this.renderer.domElement.parentNode) {
                this.renderer.domElement.parentNode.removeChild(this.renderer.domElement);
            }
            this.renderer = null;
        }
        this.is3DReady = false;
    }
}

export const dentalOdontogram3DField = {
    component: DentalOdontogram3DField,
    displayName: _t("Interactive 3D Odontogram"),
    supportedTypes: ["text", "char"],
};

registry.category("fields").add("dental_odontogram_3d", dentalOdontogram3DField);
