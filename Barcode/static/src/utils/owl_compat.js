/** @odoo-module **/

import * as owl from "@odoo/owl";

// Polyfill global owl.useState and owl.useRef for Owl 3 backward compatibility
if (typeof globalThis !== "undefined" && globalThis.owl) {
    if (!globalThis.owl.useState && globalThis.owl.proxy) {
        globalThis.owl.useState = globalThis.owl.proxy;
    }
    if (!globalThis.owl.useRef && globalThis.owl.signal && globalThis.owl.signal.ref) {
        globalThis.owl.useRef = function (name) {
            const r = globalThis.owl.signal.ref();
            Object.defineProperty(r, "el", {
                get() {
                    return r();
                },
                configurable: true,
            });
            return r;
        };
    }
}

// Polyfill Component.prototype.props for Owl 3 components so this.props works seamlessly everywhere
const targetComponent = owl.Component || (typeof globalThis !== "undefined" && globalThis.owl?.Component);
if (targetComponent && !Object.getOwnPropertyDescriptor(targetComponent.prototype, "props")) {
    Object.defineProperty(targetComponent.prototype, "props", {
        get() {
            return this.__props_val || this.__owl__?.props || {};
        },
        set(val) {
            this.__props_val = val;
            Object.defineProperty(this, "props", {
                value: val,
                writable: true,
                configurable: true,
                enumerable: true,
            });
        },
        configurable: true,
    });
}

// Polyfill template context so that legacy expressions (e.g. `state.xyz`, `props.xyz`, `myMethod`)
// in templates can resolve without needing `this.` everywhere.
const targetApp = owl.App || (typeof globalThis !== "undefined" && globalThis.owl?.App);
if (targetApp && !targetApp.prototype._isCompatGetTemplatePatched) {
    const origGetTemplate = targetApp.prototype.getTemplate;
    targetApp.prototype.getTemplate = function (name) {
        const fn = origGetTemplate.apply(this, arguments);
        if (typeof fn === "function" && !fn._isCompatWrapped) {
            const wrapped = function (ctx, node, key) {
                let actualCtx = ctx;
                if (ctx && ctx.this && !ctx.__isCompatProxy__) {
                    actualCtx = new Proxy(ctx, {
                        get(target, prop, receiver) {
                            if (prop in target) {
                                return Reflect.get(target, prop, receiver);
                            }
                            const comp = target.this;
                            if (comp && prop in comp) {
                                const val = comp[prop];
                                return typeof val === "function" ? val.bind(comp) : val;
                            }
                            return Reflect.get(target, prop, receiver);
                        },
                        has(target, prop) {
                            return (prop in target) || (Boolean(target.this) && prop in target.this);
                        },
                    });
                }
                return fn.call(this, actualCtx, node, key);
            };
            wrapped._isCompatWrapped = true;
            return wrapped;
        }
        return fn;
    };
    targetApp.prototype._isCompatGetTemplatePatched = true;
}

/**
 * Creates a reactive proxy in Owl 3 (equivalent to useState in Owl 2).
 */
export function useState(initialState) {
    return owl.proxy ? owl.proxy(initialState) : initialState;
}

/**
 * Creates a signal ref in Owl 3 with an .el getter for backward compatibility.
 */
export function useRef(name) {
    const r = (owl.signal && owl.signal.ref) ? owl.signal.ref() : (() => null);
    Object.defineProperty(r, "el", {
        get() {
            return r();
        },
        configurable: true,
    });
    return r;
}

/**
 * useProps helper for Owl 3.
 */
export function useProps(schema) {
    return owl.useProps ? owl.useProps(schema) : {};
}
