/** @odoo-module **/

import { Component, onMounted, onPatched, onWillUnmount, onWillUpdateProps, signal, useProps, proxy } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class DentalOdontogram3DField extends Component {
    static template = "dental_core.OdontogramField";
    props = useProps({
        ...standardFieldProps,
    });

    canvasContainerRef = signal.ref();
    viewportRef = signal.ref();

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
            },
            teeth: {},
        });

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

        onMounted(async () => {
            await this.init3DScene();
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
            if (!this.is3DReady) {
                await this.init3DScene();
            }
            const currentPatientId = this.getPatientId();
            const currentCaseId = this.getCaseId();
            if (currentPatientId !== this.patientId || currentCaseId !== this.caseId) {
                this.patientId = currentPatientId;
                this.caseId = currentCaseId;
                await this.loadOdontogram();
            }
            if (this.state.viewMode === "chart") {
                this._needsChartAlign = true;
                this.alignChartTeethWithUI();
            }
        });

        onWillUnmount(() => {
            this.cleanup3D();
        });
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

    get selectedToothDiagnoses() {
        return this.selectedToothData.diagnoses || [];
    }

    get selectedToothTreatments() {
        return this.selectedToothData.proposed_treatments || [];
    }

    get selectedToothCompletedTreatments() {
        return this.selectedToothData.completed_treatments || [];
    }

    get selectedToothSessions() {
        return this.selectedToothData.sessions || [];
    }

    isSurfaceAffected(surf) {
        const tn = this.state.selectedTooth;
        if (!tn || !this.state.teeth[tn]) return false;
        const currentData = this.state.teeth[tn];
        const s = currentData.surfaces || "";
        return s.toUpperCase().includes(surf.toUpperCase());
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

    isDummyTooth(tNum) {
        const cond = this.state.teeth[tNum]?.condition;
        return cond === "dummy_permanent" || cond === "dummy_temporary";
    }

    getDummyType(tNum) {
        const cond = this.state.teeth[tNum]?.condition;
        if (cond === "dummy_permanent") return "permanent";
        if (cond === "dummy_temporary") return "temporary";
        return false;
    }

    getToothStripClasses(tNum) {
        const cond = this.state.teeth[tNum]?.condition || "sound";
        const isActive = this.state.selectedTooth === tNum;
        return {
            active: isActive,
            "is-missing": cond === "missing",
            "is-dummy-perm": cond === "dummy_permanent",
            "is-dummy-temp": cond === "dummy_temporary",
            [`cond-${cond}`]: true,
        };
    }

    getToothChartClasses(tNum) {
        const cond = this.state.teeth[tNum]?.condition || "sound";
        const isActive = this.state.selectedTooth === tNum;
        const isHovered = this.state.hoveredTooth === tNum;
        return {
            active: isActive,
            hovered: isHovered,
            "is-missing": cond === "missing",
            "is-dummy-perm": cond === "dummy_permanent",
            "is-dummy-temp": cond === "dummy_temporary",
            [`cond-${cond}`]: true,
        };
    }

    hasToothCondition(tNum) {
        const cond = this.state.teeth[tNum]?.condition;
        return Boolean(cond && cond !== "sound");
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
        if (this.is3DReady) return;
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
        this.scene.background = new THREE.Color(0xe2e8f0); // Clean modern healthcare light neutral background

        // 2. Camera: Centered framing with comfortable reduced default zoom (two steps zoomed out)
        this.camera = new THREE.PerspectiveCamera(36, width / height, 0.1, 1000);
        this.camera.position.set(0, 0.26, 18.8);

        // 3. Renderer with high-quality soft shadows & tone mapping
        this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
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
            if (this.controls) this.controls.update();
            this.updateSelectionBreathingEffect(timestamp);
            if (this.state.viewMode === "chart" && this._needsChartAlign) {
                this.alignChartTeethWithUI();
            }
            this.renderer.render(this.scene, this.camera);
        };
        animate();

        // 11. Load Anatomically Realistic Dental Model
        await this.loadDentalModel(THREE);
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

    createToothOutline(THREE, mesh) {
        if (!mesh || !mesh.geometry) return null;

        const outlineMat = new THREE.ShaderMaterial({
            uniforms: {
                offset: { value: 0.016 },
                color: { value: new THREE.Color(0x334155) }, // Dark slate outline for crisp separation against light background
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

                const chartOutline = this.createToothOutline(THREE, chartMesh);
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

            const toothLastDigit = parseInt(activeNum.slice(-1), 10) || 1;
            const soundColor = toothLastDigit % 2 === 0 ? 0xfbf9f2 : 0xede8dc;

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
                mesh.material.roughness = cond === "caries" ? 0.38 : (isSelected ? 0.18 : 0.28);
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
                mesh.material.emissive.setHex(0x000000);
                mesh.material.emissiveIntensity = 0.0;
                if (toothObj.basePos) mesh.position.copy(toothObj.basePos);
                if (toothObj.baseScale) mesh.scale.copy(toothObj.baseScale);
            }
        }
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
            this.selectTooth(result.toothNumber);
        }
    }

    selectTooth(tNum) {
        if (!tNum) return;
        if (this.lastBreathingMesh) {
            this.resetMeshBreathing(this.lastBreathingMesh);
            this.lastBreathingMesh = null;
        }
        this.state.selectedTooth = String(tNum);
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

    setViewMode(mode) {
        if (this.state.viewMode === mode) return;
        if (this.lastBreathingMesh) {
            this.resetMeshBreathing(this.lastBreathingMesh);
            this.lastBreathingMesh = null;
        }

        this.state.viewMode = mode;

        if (mode === "chart") {
            if (this.modelRoot) this.modelRoot.visible = false;
            if (this.chartRoot) {
                this.chartRoot.visible = true;
                this.chartRoot.updateMatrixWorld(true);
            }
            if (this.controls) {
                this.controls.enabled = false;
            }
            if (this.camera) {
                this.savedJawCameraPos = this.camera.position.clone();
                if (this.controls) this.savedJawTarget = this.controls.target.clone();

                const viewport = this.viewportEl;
                const aspect = viewport && viewport.clientHeight > 0 ? (viewport.clientWidth / viewport.clientHeight) : 1.6;
                const fovRad = ((this.camera.fov || 36) * Math.PI) / 180;
                const halfTan = Math.tan(fovRad / 2);
                // Guaranteed horizontal framing span of 28.5 units to ensure all 16 teeth (18 to 28)
                // have comfortable breathing room on both borders and are NEVER hidden or zoomed out of view
                const chartRequiredWidth = 28.5;
                const chartRequiredHeight = 12.0;
                const zForWidth = chartRequiredWidth / (2 * halfTan * Math.max(aspect, 0.5));
                const zForHeight = chartRequiredHeight / (2 * halfTan);
                const zDist = Math.max(zForWidth, zForHeight, 24.0);
                this.camera.position.set(0, 0, zDist);
                this.camera.lookAt(0, 0, 0);
                if (this.controls) {
                    this.controls.target.set(0, 0, 0);
                }
            }
            this._needsChartAlign = true;
            this.alignChartTeethWithUI();
            requestAnimationFrame(() => this.alignChartTeethWithUI());
        } else {
            // Jaw view
            if (this.modelRoot) this.modelRoot.visible = true;
            if (this.chartRoot) this.chartRoot.visible = false;
            if (this.controls) {
                this.controls.enabled = true;
            }
            if (this.camera) {
                if (this.savedJawCameraPos) {
                    this.camera.position.copy(this.savedJawCameraPos);
                    if (this.controls && this.savedJawTarget) {
                        this.controls.target.copy(this.savedJawTarget);
                    }
                } else {
                    this.setView(this.state.currentView || "front");
                }
            }
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
            this.init3DScene();
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

    setPanelTab(tabName) {
        this.state.activePanelTab = tabName;
    }

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

    async quickApplyCondition(cond) {
        if (!this.state.selectedTooth) return;
        this.setCondition(cond);
        if (cond === "sound") {
            await this.onClearFinding();
        } else {
            await this.onSaveFinding();
        }
    }

    setDiagnosis(val) {
        this.state.newFinding.diagnosis_id = val;
        this.notifyRecordChanged();
    }

    setTreatmentIndicated(val) {
        this.state.newFinding.treatment_indicated = val;
        this.notifyRecordChanged();
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

    async onSaveAll() {
        const caseId = this.caseId || this.getCaseId();
        this.state.isSaving = true;

        try {
            // 1. If a tooth is selected and user edited fields in the recording tab, save finding first
            if (this.state.selectedTooth && this.state.activePanelTab === "record" && this.state.canEdit) {
                if (this.state.newFinding.condition === "sound") {
                    await this.onClearFinding();
                } else {
                    await this.onSaveFinding();
                }
            }

            // 2. Notify Odoo model of the field change so standard Odoo autosave / dirty tracking is active
            await this.notifyRecordChanged();

            // 3. Trigger default Odoo save on the case form record
            if (this.props.record && typeof this.props.record.save === "function") {
                await this.props.record.save();
            }

            this.notification.add(_t("Odontogram & Case saved successfully!"), {
                type: "success",
            });
        } catch (error) {
            console.error("Failed to save odontogram & case:", error);
            this.notification.add(error.message || _t("Failed to save."), {
                type: "danger",
            });
        } finally {
            this.state.isSaving = false;
        }
    }

    async onSaveFinding() {
        if (!this.state.selectedTooth) return;
        const caseId = this.caseId || this.getCaseId();
        if (!caseId) {
            this.notification.add(_t("Please save the dental case before recording findings."), {
                type: "warning",
            });
            return;
        }

        this.state.isSaving = true;

        try {
            const result = await this.orm.call("dental.case", "save_tooth_finding", [caseId], {
                tooth_data: {
                    tooth_number: this.state.selectedTooth,
                    condition: this.state.newFinding.condition,
                    diagnosis_id: this.state.newFinding.diagnosis_id || false,
                    surfaces: this.state.newFinding.surfaces.join(""),
                    severity: this.state.newFinding.severity,
                    treatment_indicated: this.state.newFinding.treatment_indicated,
                    notes: this.state.newFinding.notes,
                },
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
                    _t("Tooth %s condition successfully recorded!", this.state.selectedTooth),
                    { type: "success" }
                );

                // Switch to history tab to show the recorded finding
                this.state.activePanelTab = "history";
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
        }
        if (this.renderer) {
            this.renderer.dispose();
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
