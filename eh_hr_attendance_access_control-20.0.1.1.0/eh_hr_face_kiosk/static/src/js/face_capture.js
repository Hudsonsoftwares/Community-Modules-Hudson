/* eslint-disable */
/*
 * Face capture module for the EH face kiosk.
 *
 * Wraps face-api.js into a small, single-instance API used by the
 * kiosk shell. Loads the recognition models once on module bootstrap,
 * exposes startCamera / stopCamera, and provides:
 *
 *   - detectOnce()   : one fast detection without descriptor
 *                      (returns box + score, no embedding)
 *   - captureEmbedding(): full detect + landmarks + descriptor
 *                      (returns 128-dim embedding)
 *   - runDetectionLoop(onTick, onStop)
 *                    : continuous detect-only loop for live tracking;
 *                      caller draws feedback and decides when to capture.
 *   - drawTrackingBox(canvas, video, box)
 *                    : draws Face-ID-style corner brackets around the
 *                      detected face onto the overlay canvas.
 *
 * Privacy: nothing in this module ever sends a frame, image, or
 * descriptor anywhere. The caller (kiosk_shell.js) chooses what to
 * post to the server, and posts only the numeric embedding.
 */
(function (global) {
    'use strict';

    if (!global.ehFace) {
        global.ehFace = {};
    }

    // Model sources, tried in order. The first entry is whatever the
    // server selected (the locally vendored copy when present, else the
    // pinned CDN build); the others are appended as fallbacks so a
    // half-installed local bundle still recovers via the CDN. The CDN
    // entries are dropped when the operator disabled the fallback via
    // the eh_hr_face_kiosk.disable_cdn_fallback system parameter (the
    // kiosk page carries data-faceapi-cdn="off" in that case).
    var LOCAL_MODEL_URL = '/eh_hr_face_kiosk/static/lib/face-api/models';
    var CDN_LIB_URL = 'https://cdn.jsdelivr.net/gh/justadudewhohacks/face-api.js@0.22.2/dist/face-api.min.js';
    var CDN_MODEL_URL = 'https://cdn.jsdelivr.net/gh/justadudewhohacks/face-api.js@0.22.2/weights';
    var DETECTOR_OPTIONS = null;
    var modelsLoaded = false;
    var loadPromise = null;
    var stream = null;
    var videoEl = null;
    var canvasEl = null;

    function setupError(detail) {
        var err = new Error(
            'face-api.js model files could not be loaded (' + detail + '). ' +
            'Run eh_hr_face_kiosk/tools/fetch_face_api.sh on the server; ' +
            'see static/lib/face-api/README.md.');
        err.ehSetupRequired = true;
        return err;
    }

    function cdnAllowed() {
        return !(document.body && document.body.getAttribute('data-faceapi-cdn') === 'off');
    }

    function modelUrlCandidates() {
        var urls = [];
        var fromPage = document.body && document.body.getAttribute('data-faceapi-models');
        if (fromPage) {
            urls.push(fromPage);
        }
        if (urls.indexOf(LOCAL_MODEL_URL) === -1) {
            urls.push(LOCAL_MODEL_URL);
        }
        if (cdnAllowed() && urls.indexOf(CDN_MODEL_URL) === -1) {
            urls.push(CDN_MODEL_URL);
        }
        return urls;
    }

    /*
     * Make sure window.faceapi exists. The page normally loads the
     * library via its own <script> tag (local or CDN, server-selected),
     * but if that file 404ed or was corrupted we inject the pinned CDN
     * build as a late fallback, unless the operator disabled it.
     */
    function ensureLibrary() {
        if (global.faceapi) {
            return Promise.resolve();
        }
        if (!cdnAllowed()) {
            return Promise.reject(setupError('library missing, CDN fallback disabled'));
        }
        return new Promise(function (resolve, reject) {
            var s = document.createElement('script');
            s.src = CDN_LIB_URL;
            s.onload = function () {
                if (global.faceapi) {
                    resolve();
                } else {
                    reject(setupError('CDN library loaded but faceapi global missing'));
                }
            };
            s.onerror = function () {
                reject(setupError('library missing locally and CDN unreachable'));
            };
            document.head.appendChild(s);
        });
    }

    function loadNetsFrom(url) {
        return Promise.all([
            global.faceapi.nets.tinyFaceDetector.loadFromUri(url),
            global.faceapi.nets.faceLandmark68Net.loadFromUri(url),
            global.faceapi.nets.faceRecognitionNet.loadFromUri(url),
        ]);
    }

    function loadModels() {
        if (modelsLoaded) {
            return Promise.resolve();
        }
        if (loadPromise) {
            return loadPromise;
        }
        loadPromise = ensureLibrary().then(function () {
            var urls = modelUrlCandidates();
            function tryNext(i) {
                if (i >= urls.length) {
                    return Promise.reject(setupError(
                        'tried ' + urls.join(', ')));
                }
                return loadNetsFrom(urls[i]).catch(function () {
                    return tryNext(i + 1);
                });
            }
            return tryNext(0);
        }).then(function () {
            modelsLoaded = true;
            DETECTOR_OPTIONS = new global.faceapi.TinyFaceDetectorOptions({
                inputSize: 320,
                scoreThreshold: 0.5,
            });
        }).catch(function (err) {
            // Allow a retry on the next call instead of caching the
            // rejection forever (the operator may fix the files while
            // the kiosk page stays open).
            loadPromise = null;
            throw err;
        });
        return loadPromise;
    }

    function startCamera(video, canvas) {
        videoEl = video;
        canvasEl = canvas || null;
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            return Promise.reject(new Error('Camera not supported by this browser.'));
        }
        return navigator.mediaDevices.getUserMedia({
            video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } },
            audio: false,
        }).then(function (s) {
            stream = s;
            video.srcObject = s;
            return new Promise(function (resolve) {
                video.onloadedmetadata = function () { resolve(); };
            });
        });
    }

    function stopCamera() {
        if (stream) {
            stream.getTracks().forEach(function (t) { t.stop(); });
            stream = null;
        }
        if (videoEl) {
            videoEl.srcObject = null;
        }
    }

    function l2norm(arr) {
        var s = 0;
        for (var i = 0; i < arr.length; i++) { s += arr[i] * arr[i]; }
        var n = Math.sqrt(s);
        if (n === 0) return arr.slice();
        var out = new Array(arr.length);
        for (var j = 0; j < arr.length; j++) { out[j] = arr[j] / n; }
        return out;
    }

    /**
     * One fast detection from the live stream. Just box + confidence,
     * no landmarks, no descriptor. Cheap enough to call at ~5 FPS in a
     * detection loop for live tracking feedback.
     */
    function detectOnce() {
        if (!modelsLoaded || !videoEl) {
            return Promise.resolve(null);
        }
        return global.faceapi
            .detectSingleFace(videoEl, DETECTOR_OPTIONS)
            .then(function (result) {
                if (!result) return null;
                return {
                    box: { x: result.box.x, y: result.box.y, width: result.box.width, height: result.box.height },
                    score: result.score,
                };
            })
            .catch(function () { return null; });
    }

    /**
     * Capture a single full embedding from the live stream.
     *
     * Returns {embedding: float[128], quality: float, box: {...}} on
     * success, or null if no face is detected within the timeout window.
     * Heavier than detectOnce because it includes landmarks + descriptor.
     */
    function captureEmbedding(opts) {
        opts = opts || {};
        var timeoutMs = opts.timeoutMs || 4000;
        if (!modelsLoaded) {
            return loadModels().then(function () { return captureEmbedding(opts); });
        }
        if (!videoEl) {
            return Promise.reject(new Error('Camera not started.'));
        }
        var deadline = Date.now() + timeoutMs;

        function tick() {
            return global.faceapi
                .detectSingleFace(videoEl, DETECTOR_OPTIONS)
                .withFaceLandmarks()
                .withFaceDescriptor()
                .then(function (result) {
                    if (result && result.descriptor) {
                        var arr = Array.from(result.descriptor);
                        return {
                            embedding: l2norm(arr),
                            quality: result.detection ? result.detection.score : null,
                            box: result.detection ? result.detection.box : null,
                        };
                    }
                    if (Date.now() > deadline) {
                        return null;
                    }
                    return new Promise(function (resolve) {
                        setTimeout(function () { resolve(tick()); }, 200);
                    });
                });
        }
        return tick();
    }

    /**
     * Run a continuous detect-only loop. Calls onTick({box, score} or null)
     * every intervalMs. Returns a stop function. Use this for live
     * tracking feedback while the user gets ready; switch to
     * captureEmbedding when ready to identify.
     */
    function runDetectionLoop(onTick, opts) {
        opts = opts || {};
        var intervalMs = opts.intervalMs || 180;
        if (!modelsLoaded || !videoEl) {
            return function () {};
        }
        var stopped = false;
        function loop() {
            if (stopped) return;
            detectOnce().then(function (result) {
                if (stopped) return;
                try { onTick(result); } catch (e) { /* swallow per tick errors */ }
                setTimeout(loop, intervalMs);
            });
        }
        loop();
        return function () { stopped = true; };
    }

    /**
     * Draw Face-ID-style corner brackets around a detected face on the
     * overlay canvas. canvas is sized to match the video element.
     * box coordinates are in the video's intrinsic coordinate space.
     */
    function drawTrackingBox(canvas, video, box, opts) {
        opts = opts || {};
        var color = opts.color || '#7ee8b8';
        var width = opts.width || 4;
        var armRatio = opts.armRatio || 0.18;

        if (!canvas || !video) return;
        if (canvas.width !== video.clientWidth || canvas.height !== video.clientHeight) {
            canvas.width = video.clientWidth;
            canvas.height = video.clientHeight;
        }
        var ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        if (!box) return;

        var sx = canvas.width / (video.videoWidth || 640);
        var sy = canvas.height / (video.videoHeight || 480);

        // Mirror the X axis because the video is displayed mirrored
        // (front-facing camera convention) but the detector reports
        // unmirrored coordinates.
        var x = canvas.width - (box.x + box.width) * sx;
        var y = box.y * sy;
        var w = box.width * sx;
        var h = box.height * sy;

        var arm = Math.min(w, h) * armRatio;
        ctx.strokeStyle = color;
        ctx.lineWidth = width;
        ctx.lineCap = 'round';

        // Corner brackets only, no full rectangle, for the Face-ID look.
        function corner(cx, cy, dx, dy) {
            ctx.beginPath();
            ctx.moveTo(cx + dx * arm, cy);
            ctx.lineTo(cx, cy);
            ctx.lineTo(cx, cy + dy * arm);
            ctx.stroke();
        }
        corner(x,         y,         +1, +1);
        corner(x + w,     y,         -1, +1);
        corner(x,         y + h,     +1, -1);
        corner(x + w,     y + h,     -1, -1);
    }

    /**
     * Capture N samples in series. Used by the enrolment flow.
     */
    function captureSamples(count, opts) {
        opts = opts || {};
        var samples = [];
        function next() {
            if (samples.length >= count) {
                return Promise.resolve(samples);
            }
            return captureEmbedding(opts).then(function (s) {
                if (s) samples.push(s);
                if (samples.length < count) {
                    return new Promise(function (r) { setTimeout(r, opts.delayMs || 800); }).then(next);
                }
                return samples;
            });
        }
        return next();
    }

    global.ehFace.loadModels = loadModels;
    global.ehFace.startCamera = startCamera;
    global.ehFace.stopCamera = stopCamera;
    global.ehFace.detectOnce = detectOnce;
    global.ehFace.captureEmbedding = captureEmbedding;
    global.ehFace.captureSamples = captureSamples;
    global.ehFace.runDetectionLoop = runDetectionLoop;
    global.ehFace.drawTrackingBox = drawTrackingBox;

})(typeof window !== 'undefined' ? window : this);
