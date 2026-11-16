/** @odoo-module **/

/**
 * Dental clinic icon library for the floor plan (24 x 24 line icons, drawn with currentColor).
 * Keys match FIXTURE_CATALOG in models/dental_floor_plan.py.
 * Each icon is a list of shapes: a path string, or { d, transform } for a re-used, scaled path.
 */

const circle = (cx, cy, r) => `M${cx - r} ${cy}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0`;
const rect = (x, y, w, h, r = 0) =>
    r
        ? `M${x + r} ${y}h${w - 2 * r}a${r} ${r} 0 0 1 ${r} ${r}v${h - 2 * r}a${r} ${r} 0 0 1 ${-r} ${r}` +
          `h${-(w - 2 * r)}a${r} ${r} 0 0 1 ${-r} ${-r}v${-(h - 2 * r)}a${r} ${r} 0 0 1 ${r} ${-r}z`
        : `M${x} ${y}h${w}v${h}h${-w}z`;

const TOOTH =
    "M7 3C4.8 3 3 4.8 3 7.2c0 2.4.9 4 1.5 6s.8 4.3 1.6 6.3c.4 1 1.7 1 2 0 .5-1.8.9-4.5 3.9-4.5s3.4 2.7 3.9 4.5" +
    "c.3 1 1.6 1 2 0 .8-2 1-4.3 1.6-6.3s1.5-3.6 1.5-6C21 4.8 19.2 3 17 3c-1.9 0-2.9 1-5 1S8.9 3 7 3z";

export const DENTAL_ICONS = {
    // ---- Clinical ----
    dental_chair: [
        "M4.5 6.5 7.2 14H16l4 4",
        "M11.5 14v7M7.5 21h8",
        rect(2.6, 2.6, 3.2, 3.2, 1),
        "M15 14V8.5h6",
        "M18 8.5V6",
    ],
    operating_light: ["M12 2v5", "M4.5 13a7.5 6 0 0 1 15 0z", "M8.5 16.5 7.5 20M12 16.5V21M15.5 16.5l1 3.5"],
    instrument_tray: [rect(2.5, 15, 19, 4.5, 1.2), "M5.5 15 8.5 4.5", "M11 15V4.5", "M14.4 15l1.6-6", circle(16.8, 6.6, 2)],
    handpiece: ["M3 21 13.5 10.5", "M12 9l3 3", "M13.5 10.5 18 6", "M16 4l4 4", "M19.5 2.5 21.5 4.5"],
    dental_mirror: [circle(16.5, 7.5, 4.5), "M13.3 10.7 3.5 20.5", circle(16.5, 7.5, 2)],
    syringe: ["M15 5l4 4L9 19H5v-4z", "M5 19l-3 3", "M17 7l3-3M18.5 2.5l3 3", "M9.5 12.5l2 2M12.5 9.5l2 2"],
    tooth: [TOOTH],
    implant: [
        "M7.5 2.5h9c0 3-1.6 4.5-4.5 4.5S7.5 5.5 7.5 2.5z",
        "M10.5 7v2h3V7",
        "M9.5 9h5l-.6 10.5L12 22l-1.9-2.5z",
        "M9 12.5h6M9.3 15.5h5.4M9.6 18.5h4.8",
    ],

    // ---- Imaging ----
    xray: ["M3 2.5v10", "M3 5.5h6.5l3.5 4", "M12 8.2l4.6-2.4 4.4 7.6-4.6 2.4z", "M16.6 15.8 18 21", "M14 21h8"],
    xray_film: [rect(2, 3.5, 20, 17, 2), { d: TOOTH, transform: "translate(6.6 6.6) scale(0.45)" }],
    monitor: [rect(2.5, 3.5, 19, 13, 1.5), "M9 20.5h6M12 16.5v4", "M6 12.5l3-3 2.5 2.5 3.5-4 3 3"],

    // ---- Sterilization & utilities ----
    autoclave: [rect(2.5, 4.5, 19, 14.5, 2), circle(10, 11.75, 4.2), circle(10, 11.75, 1.8), "M16.5 8.5h2.5M16.5 12h2.5M16.5 15.5h2.5", "M6 19v2.5M18 19v2.5"],
    sink: ["M3 12h18v1a6 6 0 0 1-6 6H9a6 6 0 0 1-6-6z", "M12 12V6.5a2.5 2.5 0 0 1 5 0V8", "M9.5 21.5h5", "M7 9.5h2"],
    compressor: [rect(2.5, 9, 14, 9, 4.5), circle(19.2, 7, 2.3), "M16.5 13.5h2.7V9.3", circle(6.5, 20.3, 1.3), circle(12.5, 20.3, 1.3), "M6.5 13.5h6"],
    waste_bin: ["M4.5 6.5h15", "M9.5 6.5V4h5v2.5", "M6 6.5l1 14h10l1-14", circle(12, 13.5, 1.4), "M12 9.5v2.6M8.8 15.5l2-1.1M15.2 15.5l-2-1.1"],

    // ---- Laboratory ----
    microscope: ["M5 21h14", "M8 18h8", "M9.2 3.4l2.8-1 3.4 8.6-2.8 1z", "M12.6 12l1.4 3", "M15.6 7.8a6 6 0 0 1 1 10.2", "M10 14h3"],
    flask: ["M9 2.5h6", "M10 2.5v6.3L4.4 18.6A1.6 1.6 0 0 0 5.8 21h12.4a1.6 1.6 0 0 0 1.4-2.4L14 8.8V2.5", "M6.8 15h10.4"],

    // ---- Furniture ----
    reception_desk: [circle(12, 5.5, 2.6), "M7.2 13.5a4.8 4 0 0 1 9.6 0", "M2.5 13.5h19", "M3.5 13.5v7h17v-7", "M9 17h6"],
    desk: ["M2 8h20", "M4 8v12M20 8v12", "M14 8v6.5h6", "M16.2 11.2h1.6"],
    sofa: ["M4.5 10.5V8a2 2 0 0 1 2-2h11a2 2 0 0 1 2 2v2.5", "M2 13a2 2 0 0 1 4 0v2h12v-2a2 2 0 0 1 4 0v5H2z", "M12 6v9", "M4.5 18v2M19.5 18v2"],
    chair: [rect(6, 2.5, 12, 8.5, 2), rect(4.5, 12.5, 15, 2.5, 1), "M7 15v6.5M17 15v6.5", "M9 11v1.5M15 11v1.5"],
    cabinet: [rect(4.5, 2.5, 15, 19, 1.5), "M4.5 8.8h15M4.5 15.2h15", "M10.8 5.7h2.4M10.8 12h2.4M10.8 18.4h2.4"],
    water_dispenser: [rect(8, 2, 8, 5.5, 2.5), rect(6.5, 7.5, 11, 14, 1.5), "M10 11.5h4", "M12 11.5v2", "M9 18h6"],
    plant: ["M7 15h10l-1.5 6.5h-7z", "M12 15V8.5", "M12 10.5C12 6.5 9.2 4 5 4c0 4 3 6.5 7 6.5", "M12 12.5c0-3.2 2.4-5.5 6.5-5.5 0 3.2-2.4 5.5-6.5 5.5"],

    // ---- Layout & access ----
    door: ["M2 20.5h3.5M20 20.5h2", "M5.5 20.5V5.5", "M5.5 5.5a15 15 0 0 1 15 15"],
    window: ["M2.5 9h19v6h-19z", "M2.5 12h19", "M2.5 6v12M21.5 6v12"],
    stairs: ["M2.5 21h4.5v-4.5h4.5V12h4.5V7.5h4.5V3h1.5", "M2.5 21V3"],
    exit: ["M10 3H5a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h5", "M15.5 7.5 20 12l-4.5 4.5", "M20 12H9.5"],
    toilet: [rect(5, 2.5, 6.5, 6.5, 1), "M3 9h17v1a7.5 6.5 0 0 1-7.5 6.5h-2A7.5 6.5 0 0 1 3 10z", "M8.5 16.5l-1 5h7l-1-5"],
    wheelchair: [circle(9, 3.8, 1.8), "M9 7v6.5h6l2.5 5.5h2.5", "M9 10h5.5", "M7 10.5a5.6 5.6 0 1 0 7 7.7"],

    // ---- Safety ----
    fire_extinguisher: ["M8 9.5a3.5 3.5 0 0 1 7 0V21.5H8z", "M11.5 6V3h3", "M14.5 3l4.5 1.8", "M9 3h2.5", "M8 14h7"],
    first_aid: [rect(2.5, 6, 19, 14.5, 2), "M8.5 6V3.5h7V6", "M12 9.8v7M8.5 13.3h7"],
    oxygen: ["M8.5 8a3.5 3.5 0 0 1 7 0v13.5h-7z", "M12 4.5V2", "M9.5 2h5", "M8.5 11.5h7", "M10.3 16.5a1.7 1.7 0 1 0 3.4 0 1.7 1.7 0 1 0-3.4 0"],
    ac: [rect(2, 4, 20, 8.5, 2), "M5.5 9.5h13", "M7 15.5l-1 3.5M12 15.5V20M17 15.5l1 3.5"],
};

const FALLBACK = [rect(4, 4, 16, 16, 3)];

/** Shapes of an icon, normalised to { d, transform } objects for the template. */
export function iconShapes(key) {
    return (DENTAL_ICONS[key] || FALLBACK).map((shape) =>
        typeof shape === "string" ? { d: shape, transform: "" } : { d: shape.d, transform: shape.transform || "" }
    );
}
