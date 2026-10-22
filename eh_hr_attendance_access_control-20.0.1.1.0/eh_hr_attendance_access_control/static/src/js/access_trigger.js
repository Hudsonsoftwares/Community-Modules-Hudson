/* eslint-disable */
/*
 * Access trigger hook for the EH face kiosk shell. Loaded into
 * eh_hr_face_kiosk.kiosk_assets so it runs alongside the kiosk JS.
 *
 * Behaviour: wraps `window.fetch` for `/eh_hr/kiosk/face/match`. On
 * a successful match response, fires off `/eh_hr/kiosk/access/trigger`
 * with the matched employee_id and forgets about the result. The
 * kiosk's existing success screen continues to show; the access
 * outcome lands in the audit trail and on the access events list.
 *
 * Why fire-and-forget: the unlock is a side effect of the match,
 * not a gate on it. If the door fails to open the user already
 * has the success screen; the manager investigates via the
 * Access events list. This prevents door hardware delays from
 * slowing the visible kiosk flow.
 */
(function (global) {
    'use strict';

    function authHeaders() {
        var token = localStorage.getItem('eh_kiosk_device_token_v1');
        return token ? { 'X-EH-Kiosk-Token': token } : {};
    }

    function fireTrigger(employeeId) {
        return fetch('/eh_hr/kiosk/access/trigger', {
            method: 'POST',
            headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders()),
            body: JSON.stringify({ employee_id: employeeId }),
            keepalive: true,
        }).catch(function () { /* swallow; audit row is created server-side regardless */ });
    }

    function init() {
        var origFetch = global.fetch;
        if (!origFetch) return;
        global.fetch = function (input, opts) {
            var url = (typeof input === 'string') ? input : (input && input.url) || '';
            if (url === '/eh_hr/kiosk/face/match' && opts && opts.method === 'POST') {
                return origFetch(input, opts).then(function (resp) {
                    var clone = resp.clone();
                    clone.json().then(function (body) {
                        if (body && body.match && body.employee_id) {
                            fireTrigger(body.employee_id);
                        }
                    }).catch(function () { });
                    return resp;
                });
            }
            return origFetch(input, opts);
        };
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})(typeof window !== 'undefined' ? window : this);
