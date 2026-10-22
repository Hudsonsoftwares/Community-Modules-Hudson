/* eslint-disable */
/*
 * Kiosk shell controller for the EH face kiosk.
 *
 * Vanilla JS, no Odoo web framework dependency, so the page can run on
 * locked-down corporate browsers. State machine:
 *
 *   pair -> welcome <-> tracking -> matching -> success | fail -> welcome
 *
 * The welcome screen runs a continuous detect-only loop and draws a
 * Face-ID-style tracking box on the overlay canvas while the user
 * gets ready. When the face is held stable for a few frames the loop
 * pauses and a full embedding capture runs against the server.
 *
 * The page is served by /eh_hr/kiosk/<site_code>. The body element
 * carries data-site-code, which is the only piece of context this
 * script reads from the DOM.
 */
(function (global) {
    'use strict';

    var TOKEN_KEY = 'eh_kiosk_device_token_v1';
    var HEARTBEAT_MS = 30000;
    var CAPTURE_TIMEOUT_MS = 5000;
    var STABLE_FRAMES_REQUIRED = 3;
    var TRACK_INTERVAL_MS = 180;
    // Time the success / fail card stays visible before the kiosk
    // bounces back to the welcome tracking screen. Long enough to
    // read the name and action, short enough not to block the next
    // person in the queue.
    var RESULT_DWELL_MS = 3000;

    var state = {
        siteCode: null,
        siteName: null,
        token: null,
        idleSeconds: 30,
        matchThreshold: 0.55,
        geofence: null,
        capturing: false,
        idleTimer: null,
        stopDetectionLoop: null,
        stableHits: 0,
        lastStatus: '',
    };

    function $(sel) { return document.querySelector(sel); }
    function show(screen) {
        document.querySelectorAll('.eh-screen').forEach(function (el) {
            el.classList.add('eh-hidden');
        });
        var el = document.querySelector('.eh-screen[data-screen="' + screen + '"]');
        if (el) el.classList.remove('eh-hidden');
    }
    function setStatus(msg) {
        var el = $('#eh-status');
        if (!el) return;
        if (msg === state.lastStatus) return;
        state.lastStatus = msg || '';
        el.textContent = msg || '';
    }
    function setFrameClass(cls) {
        var frame = $('#eh-camera-frame');
        if (!frame) return;
        frame.classList.remove('is-searching', 'is-tracking', 'is-locked', 'is-success', 'is-fail');
        if (cls) frame.classList.add(cls);
    }
    function clearOverlay() {
        var canvas = $('#eh-overlay');
        if (canvas) {
            var ctx = canvas.getContext('2d');
            ctx.clearRect(0, 0, canvas.width, canvas.height);
        }
    }
    function getToken() { return localStorage.getItem(TOKEN_KEY); }
    function setToken(t) { localStorage.setItem(TOKEN_KEY, t); }
    function clearToken() { localStorage.removeItem(TOKEN_KEY); }

    function postJson(url, body, headers) {
        var hdrs = Object.assign({ 'Content-Type': 'application/json' }, headers || {});
        return fetch(url, {
            method: 'POST',
            headers: hdrs,
            body: JSON.stringify(body || {}),
        }).then(function (r) {
            return r.json().then(function (j) { return { status: r.status, body: j }; });
        });
    }
    function getJson(url, headers) {
        return fetch(url, { method: 'GET', headers: headers || {} })
            .then(function (r) { return r.json().then(function (j) { return { status: r.status, body: j }; }); });
    }

    function authHeaders() {
        return { 'X-EH-Kiosk-Token': state.token };
    }

    function doPair() {
        var nameEl = $('#eh-pair-name');
        var pinEl = $('#eh-pair-pin');
        var errEl = $('#eh-pair-error');
        errEl.textContent = '';
        var deviceName = (nameEl.value || '').trim() || 'Unnamed kiosk';
        var pin = (pinEl.value || '').trim();
        if (!pin) { errEl.textContent = 'Enter the pairing PIN.'; return; }
        postJson('/eh_hr/kiosk/pair', {
            site_code: state.siteCode,
            pin: pin,
            device_name: deviceName,
        }).then(function (res) {
            if (res.status !== 200) {
                errEl.textContent = (res.body && res.body.error) || ('Pairing failed (' + res.status + ').');
                return;
            }
            state.token = res.body.device_token;
            state.siteName = res.body.site_name;
            setToken(state.token);
            bootstrap();
        }).catch(function (e) {
            errEl.textContent = 'Network error: ' + e.message;
        });
    }

    function heartbeat() {
        if (!state.token) return;
        postJson('/eh_hr/kiosk/heartbeat', {}, authHeaders()).then(function (res) {
            if (res.status === 401) {
                clearToken();
                state.token = null;
                stopTracking();
                show('pair');
                return;
            }
            if (res.status === 200 && res.body) {
                state.idleSeconds = res.body.idle_seconds || state.idleSeconds;
                state.matchThreshold = res.body.match_threshold || state.matchThreshold;
                state.geofence = res.body.geofence || null;
            }
        }).catch(function () { /* ignore transient */ });
    }

    function getGeofencePosition() {
        if (!state.geofence || !state.geofence.enabled) {
            return Promise.resolve(null);
        }
        if (!navigator.geolocation) {
            return Promise.resolve(null);
        }
        return new Promise(function (resolve) {
            navigator.geolocation.getCurrentPosition(
                function (pos) {
                    resolve({ lat: pos.coords.latitude, lng: pos.coords.longitude, accuracy: pos.coords.accuracy });
                },
                function () { resolve(null); },
                { enableHighAccuracy: true, timeout: 4000, maximumAge: 60000 }
            );
        });
    }

    /**
     * Continuous tracking loop on the welcome screen. Every ~180ms we
     * run a fast detect-only pass, draw a Face-ID-style bracket on the
     * overlay, and update the status text contextually. After
     * STABLE_FRAMES_REQUIRED consecutive hits, we stop the loop and
     * trigger a real match attempt with the full descriptor.
     */
    function startTracking() {
        if (state.stopDetectionLoop) return;
        state.stableHits = 0;
        setFrameClass('is-searching');
        setStatus('Looking for you...');
        var video = $('#eh-camera');
        var canvas = $('#eh-overlay');
        state.stopDetectionLoop = global.ehFace.runDetectionLoop(function (result) {
            if (state.capturing) return;
            if (result && result.box) {
                state.stableHits += 1;
                global.ehFace.drawTrackingBox(canvas, video, result.box, { color: '#7ee8b8' });
                if (state.stableHits >= STABLE_FRAMES_REQUIRED) {
                    setFrameClass('is-locked');
                    setStatus('Got you, identifying...');
                    stopTracking();
                    attemptMatch();
                } else {
                    setFrameClass('is-tracking');
                    setStatus('Hold still...');
                }
            } else {
                state.stableHits = 0;
                clearOverlay();
                setFrameClass('is-searching');
                setStatus('Looking for you...');
            }
        }, { intervalMs: TRACK_INTERVAL_MS });
    }

    function stopTracking() {
        if (state.stopDetectionLoop) {
            try { state.stopDetectionLoop(); } catch (e) { /* ignore */ }
            state.stopDetectionLoop = null;
        }
    }

    function attemptMatch() {
        if (state.capturing) return;
        state.capturing = true;
        setStatus('Identifying...');
        Promise.all([
            global.ehFace.captureEmbedding({ timeoutMs: CAPTURE_TIMEOUT_MS }),
            getGeofencePosition(),
        ]).then(function (results) {
            var capture = results[0];
            var geo = results[1];
            if (!capture) {
                state.capturing = false;
                setFrameClass('is-searching');
                setStatus('No face captured. Step closer and look at the camera.');
                clearOverlay();
                // Resume the tracking loop after a beat so the user can try again.
                setTimeout(startTracking, 500);
                return;
            }
            return postJson('/eh_hr/kiosk/face/match', {
                embedding: capture.embedding,
                geofence: geo,
            }, authHeaders()).then(function (res) {
                state.capturing = false;
                if (res.status === 401) {
                    clearToken();
                    state.token = null;
                    show('pair');
                    return;
                }
                if (res.status !== 200) {
                    setStatus('Server error: ' + res.status);
                    setFrameClass('is-fail');
                    setTimeout(function () { show('welcome'); startTracking(); }, 1500);
                    return;
                }
                if (res.body && res.body.match) {
                    setFrameClass('is-success');
                    showSuccess(res.body);
                } else {
                    showFail(res.body || {});
                }
            });
        }).catch(function (err) {
            state.capturing = false;
            setStatus('Error: ' + err.message);
            setFrameClass('is-fail');
            setTimeout(function () { show('welcome'); startTracking(); }, 1500);
        });
    }

    function showSuccess(body) {
        $('#eh-success-name').textContent = body.employee_name || 'Welcome';
        $('#eh-success-action').textContent = body.action === 'check_in' ? 'Checked in' : 'Checked out';
        $('#eh-success-time').textContent = new Date().toLocaleTimeString();
        show('success');
        scheduleIdleReset();
    }
    function showFail(body) {
        var reason = body.reason || 'no_match';
        // Extension modules (jobcost picker, future hooks) may synthesise a
        // non-match response to take over the post-match flow themselves.
        // Bail early so we do not stomp the screen they just opened.
        if (reason === 'job_picker_pending') {
            return;
        }
        var msg = {
            'no_templates': 'No employees enrolled for this company.',
            'below_threshold': 'Could not confirm identity. Try again, or use a fallback PIN.',
            'geofence_required': 'Location is required for this site.',
            'geofence_violation': 'You are outside this kiosk\'s permitted area.',
        }[reason] || 'Match failed.';
        $('#eh-fail-reason').textContent = msg;
        setFrameClass('is-fail');
        show('fail');
        scheduleIdleReset();
    }
    function scheduleIdleReset() {
        if (state.idleTimer) clearTimeout(state.idleTimer);
        state.idleTimer = setTimeout(function () {
            show('welcome');
            setStatus('');
            clearOverlay();
            startTracking();
        }, RESULT_DWELL_MS);
    }

    function bootstrap() {
        show('welcome');
        $('#eh-welcome-site').textContent = state.siteName ? ('Site: ' + state.siteName) : ('Site code: ' + state.siteCode);
        var video = $('#eh-camera');
        var canvas = $('#eh-overlay');
        setStatus('Loading models...');
        global.ehFace.loadModels().then(function () {
            return global.ehFace.startCamera(video, canvas);
        }).then(function () {
            heartbeat();
            setInterval(heartbeat, HEARTBEAT_MS);
            // Give the camera a moment to settle, then start the live
            // tracking loop. Capture only fires once a face is held
            // stably for a few frames in a row.
            setTimeout(startTracking, 600);
        }).catch(function (err) {
            if (err && err.ehSetupRequired) {
                // Models unreachable both locally and via CDN. Camera is
                // fine; this is a server setup problem, so say so.
                setStatus('Face models are not installed on this server. ' +
                    'Administrator: run eh_hr_face_kiosk/tools/fetch_face_api.sh ' +
                    '(see static/lib/face-api/README.md in the module).');
                return;
            }
            setStatus('Camera or model load failed: ' + err.message);
        });
    }

    function init() {
        if (document.body.getAttribute('data-faceapi-blocked') === 'true') {
            // Server rendered the setup-required panel: the face-api
            // bundle is missing and the CDN fallback is disabled by
            // policy. Nothing the kiosk JS can do until an operator
            // vendors the files.
            return;
        }
        state.siteCode = document.body.getAttribute('data-site-code');
        var siteFound = document.body.getAttribute('data-site-found') === 'true';
        if (!siteFound) {
            show('error');
            return;
        }
        state.token = getToken();
        if (!state.token) {
            show('pair');
            $('#eh-pair-submit').addEventListener('click', doPair);
            $('#eh-pair-pin').addEventListener('keydown', function (e) {
                if (e.key === 'Enter') doPair();
            });
            return;
        }
        // We have a token: fetch whoami to validate, then bootstrap.
        getJson('/eh_hr/kiosk/whoami', authHeaders()).then(function (res) {
            if (res.status !== 200) {
                clearToken();
                state.token = null;
                show('pair');
                $('#eh-pair-submit').addEventListener('click', doPair);
                return;
            }
            state.siteName = res.body.site_name;
            state.idleSeconds = res.body.idle_seconds || 30;
            bootstrap();
        });
    }

    /*
     * Public hook surface for extension modules.
     *
     * Extensions like jobcost intercept the match response with a
     * monkey-patched fetch and then call show('success') themselves
     * after their own picker flow. They do not have access to the
     * private scheduleIdleReset() inside this IIFE, so without this
     * hook the success card would sit on the screen forever after a
     * picker selection. bounceToWelcome() makes that re-arm explicit.
     */
    global.ehKiosk = global.ehKiosk || {};
    global.ehKiosk.bounceToWelcome = function () { scheduleIdleReset(); };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})(typeof window !== 'undefined' ? window : this);
