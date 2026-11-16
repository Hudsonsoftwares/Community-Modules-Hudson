(function () {
                "use strict";
                var app = document.getElementById("edu-app");
                var data = JSON.parse(app.dataset.payload || "{}");
                var items = data.items || [];
                var present = data.mode === "present";
                var device = data.device || "screen";
                if (present && device === "screen" && window.matchMedia("(pointer: coarse)").matches) { device = "tablet"; }
                var idx = 0, viewId = null, lastSent = 0, started = false;
                var stage = document.getElementById("stage");
                var icons = { video: "\u25B6", image: "\u25A3", pdf: "\u2630", other: "\u2026" };

                function rpc(params) {
                    if (!present || !data.event_url) { return Promise.resolve({}); }
                    return fetch(data.event_url, {
                        method: "POST", credentials: "same-origin",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ jsonrpc: "2.0", method: "call", params: params })
                    }).then(function (r) { return r.json(); }).then(function (r) { return r.result || {}; })
                      .catch(function () { return {}; });
                }
                function item() { return items[idx]; }
                function version() {
                    var it = item(); if (!it) { return null; }
                    return it.versions.filter(function (v) { return v.id === it.current; })[0] || it.versions[0];
                }
                function send(event, position, duration) {
                    var it = item(), v = version(); if (!it || !v || !it.line_id) { return; }
                    rpc({ event: event, line_id: it.line_id, file_id: v.id, position: position || 0,
                          duration: duration || 0, view_id: viewId, device: device })
                        .then(function (res) { if (res && res.view_id) { viewId = res.view_id; } });
                }
                function markDone() {
                    var it = item(); if (!it) { return; }
                    it.completed = true; renderPlaylist();
                    if (present && items.every(function (i) { return i.completed; }) && !data.acknowledged) {
                        document.getElementById("ack").classList.add("show");
                    }
                }
                function renderPlaylist() {
                    var aside = document.getElementById("playlist");
                    aside.textContent = "";
                    items.forEach(function (it, i) {
                        var v = it.versions.filter(function (x) { return x.id === it.current; })[0] || it.versions[0];
                        var b = document.createElement("button");
                        b.type = "button"; b.className = "item" + (i === idx ? " active" : "");
                        var th = document.createElement("div"); th.className = "thumb";
                        if (v.thumb) { var im = document.createElement("img"); im.src = v.thumb; im.alt = ""; th.appendChild(im); }
                        else { th.textContent = icons[v.kind] || icons.other; }
                        var txt = document.createElement("div");
                        var t = document.createElement("div"); t.className = "t"; t.textContent = v.name;
                        var tp = document.createElement("div"); tp.className = "topic"; tp.textContent = it.topic || "";
                        txt.appendChild(t); txt.appendChild(tp);
                        b.appendChild(th); b.appendChild(txt);
                        if (it.completed) { var d = document.createElement("span"); d.className = "done"; d.textContent = "\u2713"; b.appendChild(d); }
                        b.addEventListener("click", function () { show(i); });
                        aside.appendChild(b);
                    });
                }
                function renderLangs() {
                    var box = document.getElementById("langs"), it = item();
                    box.textContent = "";
                    if (!it || it.versions.length < 2) { return; }
                    it.versions.forEach(function (v) {
                        var b = document.createElement("button"); b.type = "button";
                        b.textContent = v.lang || v.lang_code || "\u2014";
                        b.setAttribute("aria-pressed", v.id === it.current ? "true" : "false");
                        b.addEventListener("click", function () { it.current = v.id; show(idx); });
                        box.appendChild(b);
                    });
                }
                function show(i) {
                    if (!items.length) { return; }
                    idx = Math.max(0, Math.min(i, items.length - 1));
                    viewId = null; lastSent = 0; started = false;
                    var v = version();
                    document.getElementById("media-title").textContent = v.name;
                    document.getElementById("media-desc").textContent = v.description || "";
                    stage.textContent = "";
                    var el;
                    if (v.kind === "video") {
                        el = document.createElement("video");
                        el.controls = true; el.playsInline = true; el.preload = "metadata"; el.src = v.url;
                        if (v.thumb) { el.poster = v.thumb; }
                        el.addEventListener("play", function () { if (!started) { started = true; send("start", el.currentTime, el.duration); } });
                        el.addEventListener("timeupdate", function () {
                            if (el.currentTime - lastSent >= 10) { lastSent = el.currentTime; send("progress", el.currentTime, el.duration); }
                        });
                        el.addEventListener("ended", function () {
                            send("complete", el.duration, el.duration); markDone();
                            if (idx < items.length - 1) { setTimeout(function () { show(idx + 1); var nv = stage.querySelector("video"); if (nv) { nv.play().catch(function () {}); } }, 2500); }
                        });
                    } else if (v.kind === "image") {
                        el = document.createElement("img"); el.src = v.url; el.alt = v.name;
                        send("start", 0, 0);
                    } else if (v.kind === "pdf") {
                        el = document.createElement("iframe"); el.src = v.url; el.title = v.name;
                        send("start", 0, 0);
                    } else {
                        el = document.createElement("a"); el.href = v.url; el.target = "_blank"; el.rel = "noopener";
                        el.textContent = v.name; el.style.color = "var(--accent)"; el.style.fontSize = "22px";
                        send("start", 0, 0);
                    }
                    stage.appendChild(el);
                    renderPlaylist(); renderLangs();
                }
                function next() {
                    var v = version();
                    if (v && v.kind !== "video" && !item().completed) { send("complete", 0, 0); markDone(); }
                    if (idx < items.length - 1) { show(idx + 1); }
                }
                document.getElementById("btn-next").addEventListener("click", next);
                document.getElementById("btn-prev").addEventListener("click", function () { show(idx - 1); });
                document.getElementById("btn-full").addEventListener("click", function () {
                    var d = document.documentElement;
                    if (document.fullscreenElement) { document.exitFullscreen(); } else if (d.requestFullscreen) { d.requestFullscreen(); }
                });
                document.getElementById("btn-ack").addEventListener("click", function () {
                    rpc({ event: "ack", note: document.getElementById("ack-note").value }).then(function () {
                        data.acknowledged = true;
                        document.getElementById("btn-ack").style.display = "none";
                        document.getElementById("ack-note").style.display = "none";
                        document.getElementById("ack-thanks").style.display = "inline";
                    });
                });
                if (!present) {
                    ["btn-prev", "btn-next"].forEach(function (id) { document.getElementById(id).style.display = "none"; });
                    document.getElementById("playlist").style.display = "none";
                    app.style.gridTemplateColumns = "1fr";
                }
                show(0);
            })();
