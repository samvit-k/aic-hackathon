/* FixItSanDiego client: wizard state, Leaflet map, and calls to the FastAPI backend.
 * All model/geocoder text is inserted with textContent (never innerHTML).
 * Report freshness is handled by ReportSync (static/report-sync.js).
 */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const TITLES = {
    1: "Add a photo",
    2: "AI analysis",
    3: "Where is it?",
    4: "Review your report",
    5: "Send it",
  };
  const NON_REPORTABLE = new Set(["no_visible_issue", "uncertain"]);
  const EXPORT_BUTTONS = ["copy-btn", "dl-json", "dl-txt", "dl-photo"];
  const SOURCE_LABELS = {
    gps: "device GPS (your position — move the pin if the defect is elsewhere)",
    map_click: "map pin",
    search: "place search (OpenStreetMap) — drag the pin to refine",
    manual: "typed coordinates",
    demo_test_coordinate: "DEMO TEST COORDINATE — not a real location",
  };
  const MOBILE = window.matchMedia("(max-width: 47.99em)");

  const state = {
    step: 1,
    config: null,
    photo: { file: null, previewUrl: null },
    analysis: null, // /api/analyze response
    edits: {},
    loc: { lat: null, lon: null, accuracy: null, source: null, address: null, confirmed: false },
    destination: null,
    searchResults: [],
  };

  // ------------------------------------------------------------------ helpers
  async function api(path, options = {}) {
    let res;
    try {
      res = await fetch(path, options);
    } catch (_) {
      throw new Error("Network error — check your connection and try again.");
    }
    let body = null;
    try { body = await res.json(); } catch (_) { /* non-JSON */ }
    if (!res.ok) throw new Error((body && body.detail) || `Request failed (${res.status}).`);
    return body;
  }
  const postJSON = (path, data) =>
    api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });

  function setAlert(el, kind, text) {
    el.className = kind ? `alert alert--${kind}` : "alert";
    el.textContent = text || "";
    el.hidden = !text;
  }
  function fillList(ul, items) {
    const rows = items && items.length ? items : ["(none listed)"];
    ul.replaceChildren(...rows.map((t) => {
      const li = document.createElement("li");
      li.textContent = t;
      return li;
    }));
  }
  const round6 = (n) => Math.round(n * 1e6) / 1e6;
  const validCoords = (lat, lon) =>
    Number.isFinite(lat) && Number.isFinite(lon) && lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180;
  const typeLabel = (t) => {
    const hit = (state.config?.issue_types || []).find((x) => x.value === t);
    return hit ? hit.label : t;
  };
  function makeRadio(name, value, label, checked) {
    const wrap = document.createElement("label");
    wrap.className = "radio";
    const input = document.createElement("input");
    input.type = "radio";
    input.name = name;
    input.value = value;
    input.checked = !!checked;
    const span = document.createElement("span");
    span.textContent = label;
    wrap.append(input, span);
    return wrap;
  }
  // Decode locally: fetch() of a data: URL is blocked by the CSP (connect-src 'self').
  function dataUrlToBlob(dataUrl) {
    const [meta, b64] = dataUrl.split(",", 2);
    const mime = (meta.match(/^data:([^;]+)/) || [])[1] || "application/octet-stream";
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
    return new Blob([bytes], { type: mime });
  }
  function downloadBlob(name, blob) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  // ------------------------------------------------------------ report sync
  function buildReportPayload() {
    const d = state.analysis;
    const l = state.loc;
    return {
      analysis: d.analysis,
      edits: { ...state.edits },
      location: l.lat === null ? {} : {
        latitude: l.lat, longitude: l.lon, accuracy_meters: l.accuracy,
        source: l.source, address: l.address, user_confirmed: l.confirmed,
      },
      destination: state.destination === "unsure" ? null : state.destination,
      photo: { filename: d.photo.filename, original_format: d.photo.original_format, sha256: d.photo.sha256 },
      report_id: d.report_id,
      created_at: d.created_at,
    };
  }
  const sync = new window.FixItReportSync.ReportSync({
    // The payload is built when the request fires, so it always reflects the latest edits.
    request: () => postJSON("/api/report", buildReportPayload()),
    onChange: () => { renderReport(); updateContinue(); },
  });
  /** Call on every edit: drops the old report at once and rebuilds it. */
  function invalidateReport({ immediate = false } = {}) {
    if (!state.analysis) return;
    sync.invalidate({ immediate });
  }

  // --------------------------------------------------------------- navigation
  function canContinue() {
    switch (state.step) {
      case 1: return state.photo.file ? null : "Add a photo to continue.";
      case 2: return state.analysis ? null : "Analyze the photo to continue.";
      case 3: return state.loc.confirmed ? null
        : "Set the pin, then tick “Confirm this is the issue location” to continue.";
      case 4:
        if (sync.pending) return "Updating your report…";
        if (sync.error) return "Fix the problem shown above to continue.";
        return sync.ready ? null : "Preparing your report…";
      default: return null;
    }
  }
  function updateContinue() {
    const btn = $("continue-btn");
    const last = state.step === 5;
    const reason = last ? null : canContinue();
    btn.textContent = last ? "Start a new report" : "Continue";
    btn.disabled = !!reason;
    $("continue-hint").textContent = reason || "";
  }
  function goTo(step) {
    state.step = step;
    document.querySelectorAll(".step").forEach((s) => { s.hidden = Number(s.dataset.step) !== step; });
    $("step-title").textContent = TITLES[step];
    $("step-count").textContent = `Step ${step} of 5`;
    $("back-btn").classList.toggle("is-hidden", step === 1);
    document.body.dataset.step = String(step);
    $("sidebar-body").scrollTop = 0;
    if (MOBILE.matches) window.scrollTo(0, 0);
    if (step >= 4 && state.analysis && !sync.ready && !sync.pending) invalidateReport({ immediate: true });
    setTimeout(() => map && map.invalidateSize(), 60);
    updateContinue();
    $("step-title").focus({ preventScroll: true });
  }

  // -------------------------------------------------------------------- photo
  function resetAnalysis() {
    state.analysis = null;
    state.edits = {};
    sync.reset();
    $("analysis-result").hidden = true;
    setAlert($("analyze-error"), "error", "");
    $("analyze-btn").textContent = "Analyze photo";
  }
  function onPhotoChosen(file) {
    if (!file) return;
    const err = $("photo-error");
    const maxMb = state.config?.max_upload_mb || 10;
    if (/hei[cf]/i.test(file.type) || /\.hei[cf]$/i.test(file.name || "")) {
      setAlert(err, "error", "iPhone HEIC photos aren't supported. Use “Take a photo”, or set Camera › Formats › Most Compatible.");
      return;
    }
    if (file.size > maxMb * 1024 * 1024) {
      setAlert(err, "error", `That photo is ${(file.size / 1048576).toFixed(1)} MB; the limit is ${maxMb} MB.`);
      return;
    }
    if (file.type && !file.type.startsWith("image/")) {
      setAlert(err, "error", "That file isn't an image. Use a JPEG, PNG or WebP photo.");
      return;
    }
    setAlert(err, "error", "");
    if (state.photo.previewUrl) URL.revokeObjectURL(state.photo.previewUrl);
    state.photo = { file, previewUrl: URL.createObjectURL(file) };
    resetAnalysis();
    $("photo-img").src = state.photo.previewUrl;
    $("analyze-thumb").src = state.photo.previewUrl;
    $("photo-caption").textContent = `${file.name || "Photo"} — to replace it, take or upload another.`;
    $("photo-preview").hidden = false;
    updateContinue();
  }

  // ----------------------------------------------------------------- analysis
  async function analyze() {
    if (!state.photo.file) return;
    const btn = $("analyze-btn");
    const file = state.photo.file;
    btn.disabled = true;
    $("analyze-spinner").hidden = false;
    setAlert($("analyze-error"), "error", "");
    const form = new FormData();
    form.append("photo", file, file.name || "photo.jpg");
    try {
      const data = await api("/api/analyze", { method: "POST", body: form });
      if (state.photo.file !== file) return; // photo replaced while analyzing
      state.analysis = data;
      const a = data.analysis;
      state.edits = {
        issue_type: a.issue_type,
        description: a.description,
        visible_evidence: a.visible_evidence.join("\n"),
        possible_root_causes: a.possible_root_causes.join("\n"),
        urgency: data.suggested_urgency,
      };
      renderAnalysis();
      populateReviewForm();
      $("photo-img").src = data.photo.data_url;
      $("analyze-thumb").src = data.photo.data_url;
      invalidateReport({ immediate: true });
    } catch (e) {
      setAlert($("analyze-error"), "error", e.message);
    } finally {
      btn.disabled = !state.config?.analysis_enabled;
      $("analyze-spinner").hidden = true;
      btn.textContent = state.analysis ? "Analyze again" : "Analyze photo";
      updateContinue();
    }
  }
  function renderAnalysis() {
    const a = state.analysis.analysis;
    const banner = $("analysis-banner");
    if (a.issue_type === "no_visible_issue") {
      setAlert(banner, "success", "Gemini did not see a visible issue in this photo.");
    } else if (a.issue_type === "uncertain") {
      setAlert(banner, "warning", "Gemini couldn't tell from this photo. Try a clearer, closer, well-lit shot — or continue and set the details yourself.");
    } else {
      setAlert(banner, "success", `Draft ready: ${typeLabel(a.issue_type)}. You can review and edit it in step 4.`);
    }
    $("r-type").textContent = typeLabel(a.issue_type);
    $("r-desc").textContent = a.description;
    fillList($("r-evidence"), a.visible_evidence);
    fillList($("r-causes"), a.possible_root_causes);
    $("r-quality").textContent = a.image_quality + (a.uncertainty_notes ? ` — ${a.uncertainty_notes}` : "");
    $("r-model").textContent = `Analyzed with ${state.analysis.model}. AI output is a draft — please review it.`;
    $("analysis-result").hidden = false;
  }

  // ------------------------------------------------------------------- review
  function populateReviewForm() {
    const e = state.edits;
    document.querySelectorAll('input[name="issue_type"]').forEach((r) => { r.checked = r.value === e.issue_type; });
    $("desc-input").value = e.description || "";
    $("evidence-input").value = e.visible_evidence || "";
    $("causes-input").value = e.possible_root_causes || "";
    $("urgency-select").value = e.urgency || "uncertain";
    updateCausesWarning();
    const a = state.analysis.analysis;
    $("quality-note").textContent = `Photo quality: ${a.image_quality}` + (a.uncertainty_notes ? ` — ${a.uncertainty_notes}` : "");
  }
  function updateCausesWarning() {
    const n = ($("causes-input").value || "").split("\n").filter((l) => l.trim()).length;
    $("causes-warning").hidden = n <= 3;
  }

  function renderDestLinks(targets, enabled) {
    const dests = state.config.destinations;
    $("dest-links").replaceChildren(...targets.map((key) => {
      const label = `Open ${dests[key].name} ↗`;
      if (!enabled) {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "btn btn--primary btn--block";
        b.disabled = true;
        b.textContent = label;
        return b;
      }
      const a = document.createElement("a");
      a.className = "btn btn--primary btn--block";
      a.href = dests[key].url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.textContent = label;
      return a;
    }));
  }

  function renderReport() {
    const ready = sync.ready;
    EXPORT_BUTTONS.forEach((id) => { $(id).disabled = !ready; });
    setAlert($("report-error"), "error", sync.error ? `The report has a problem: ${sync.error}` : "");
    const chosen = state.destination === "unsure" ? null : state.destination;
    const targets = chosen ? [chosen] : ["ucsd", "city"];
    $("jurisdiction-note").hidden = !!chosen;

    if (!ready) {
      // Previous report is invalid: show nothing that could be copied or exported.
      const msg = sync.pending ? "Updating your report…"
        : sync.error ? "The report can't be generated until the problem in step 4 is fixed."
        : "Preparing your report…";
      setAlert($("status-banner"), sync.error ? "error" : "info", msg);
      $("report-text").textContent = sync.pending ? "Updating your report…" : "";
      $("urgency-suggestion").textContent = sync.pending ? "Updating suggestion…" : "";
      $("urgency-reason").textContent = "";
      $("copy-status").textContent = "";
      renderDestLinks(targets, false);
      return;
    }

    const r = sync.report;
    const rep = r.report;
    const level = rep.urgency.level;
    $("cost-text").textContent = r.cost_text;
    $("active-time").textContent = r.active_time_text;
    $("agency-time").textContent = r.agency_time_text;
    $("urgency-suggestion").textContent =
      `FixItSanDiego suggests ${rep.urgency.suggested_level} — not an official City/UCSD priority.`;
    $("urgency-reason").textContent = `Reason: ${rep.urgency.reason}`;
    $("p0-banner").hidden = level !== "P0";
    $("p1-banner").hidden = level !== "P1";
    $("uncertain-banner").hidden = level !== "uncertain";

    const isReady = r.status === "ready_for_manual_submission";
    setAlert($("status-banner"), isReady ? "success" : "warning",
      isReady ? "Ready for manual submission. You still need to submit it on the official site."
              : `Draft — ${r.blocker}.`);
    $("report-text").textContent = r.text;
    const type = rep.issue.type;
    $("nodamage-note").hidden = !NON_REPORTABLE.has(type);
    renderDestLinks(targets, true);
    $("category-hint").hidden = !(targets.includes("city") && ["pothole", "curb_damage", "other_damage"].includes(type));
  }

  // --------------------------------------------------------------------- map
  let map = null;
  let marker = null;
  let accuracyCircle = null;
  let kbdMode = "idle";
  const PIN_SVG =
    '<svg viewBox="0 0 36 48" width="36" height="48" aria-hidden="true">' +
    '<path d="M18 1.5C8.9 1.5 1.5 8.7 1.5 17.6 1.5 30 18 46.5 18 46.5S34.5 30 34.5 17.6C34.5 8.7 27.1 1.5 18 1.5z" fill="#1f1f1f" stroke="#fff" stroke-width="2"/>' +
    '<circle cx="18" cy="17.5" r="7" fill="#FFD000"/></svg>';

  const PanZoom = L.Control.extend({
    options: { position: "topright" },
    onAdd(m) {
      const box = L.DomUtil.create("div", "panzoom");
      const add = (cls, label, glyph, fn) => {
        const b = L.DomUtil.create("button", `panzoom__btn panzoom__${cls}`, box);
        b.type = "button";
        b.title = label;
        b.setAttribute("aria-label", label);
        b.textContent = glyph;
        L.DomEvent.on(b, "click", (e) => { L.DomEvent.stop(e); fn(); });
      };
      add("up", "Move map up", "▲", () => m.panBy([0, -160]));
      add("left", "Move map left", "◀", () => m.panBy([-160, 0]));
      L.DomUtil.create("div", "panzoom__hub", box);
      add("right", "Move map right", "▶", () => m.panBy([160, 0]));
      add("down", "Move map down", "▼", () => m.panBy([0, 160]));
      add("in", "Zoom in", "+", () => m.zoomIn());
      add("out", "Zoom out", "−", () => m.zoomOut());
      L.DomEvent.disableClickPropagation(box);
      L.DomEvent.disableScrollPropagation(box);
      return box;
    },
  });

  function initMap(center) {
    map = L.map("map", { zoomControl: false, keyboard: true, keyboardPanDelta: 120 }).setView(center, 15);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);
    new PanZoom().addTo(map);
    map.on("click", (e) => setPin(e.latlng.lat, e.latlng.lng, "map_click", { keepAddress: true }));

    const el = map.getContainer();
    el.addEventListener("focus", () => { if (el.matches(":focus-visible")) setKbd(marker ? "placed" : "drop"); });
    el.addEventListener("blur", () => setKbd("idle"));
    el.addEventListener("keydown", (e) => {
      if (e.key !== " " && e.code !== "Space") return;
      e.preventDefault();
      if (kbdMode === "placed") {
        if (marker) map.panTo(marker.getLatLng());
        setKbd("drop");
      } else {
        const c = map.getCenter();
        setPin(c.lat, c.lng, "map_click", { keepAddress: true });
        setKbd("placed");
      }
    });
    $("kbd-banner").addEventListener("click", () => { el.focus(); setKbd(marker ? "placed" : "drop"); });
    // On phones the map starts hidden (zero size); refit whenever its box changes size.
    if ("ResizeObserver" in window) {
      new ResizeObserver(() => map.invalidateSize()).observe(el); // default keeps the centre
    }
    MOBILE.addEventListener("change", () => setTimeout(() => map.invalidateSize(), 60));
  }
  function setKbd(mode) {
    kbdMode = mode;
    $("mapbox").classList.toggle("kbd-drop", mode === "drop");
    document.querySelectorAll(".kbd-state").forEach((s) => { s.hidden = s.dataset.kbd !== mode; });
  }

  function setPin(lat, lon, source, { accuracy = null, address = null, keepAddress = false, zoom = null } = {}) {
    if (!validCoords(lat, lon)) return false;
    const l = state.loc;
    l.lat = round6(lat);
    l.lon = round6(lon);
    l.source = source;
    l.accuracy = accuracy;
    if (!keepAddress) l.address = address;
    l.confirmed = false; // every move needs re-confirmation
    const ll = [l.lat, l.lon];
    if (!marker) {
      marker = L.marker(ll, {
        icon: L.divIcon({ className: "pin", html: PIN_SVG, iconSize: [36, 48], iconAnchor: [18, 47] }),
        draggable: true,
        keyboard: false,
        title: "Issue location — drag to adjust",
        autoPan: true,
      }).addTo(map);
      marker.on("dragend", () => {
        const p = marker.getLatLng();
        setPin(p.lat, p.lng, "map_click", { keepAddress: true });
      });
    } else {
      marker.setLatLng(ll);
    }
    if (accuracyCircle) { accuracyCircle.remove(); accuracyCircle = null; }
    if (accuracy) {
      accuracyCircle = L.circle(ll, { radius: accuracy, color: "#3b7dd8", weight: 1, fillOpacity: 0.08, interactive: false }).addTo(map);
    }
    if (zoom) map.setView(ll, zoom);
    renderLocation();
    invalidateReport({ immediate: true });
    updateContinue();
    return true;
  }
  function clearPin() {
    Object.assign(state.loc, { lat: null, lon: null, accuracy: null, source: null, address: null, confirmed: false });
    if (marker) { marker.remove(); marker = null; }
    if (accuracyCircle) { accuracyCircle.remove(); accuracyCircle = null; }
    $("lat-input").value = "";
    $("lon-input").value = "";
    renderLocation();
    invalidateReport({ immediate: true });
    updateContinue();
  }
  function renderLocation() {
    const l = state.loc;
    const has = l.lat !== null;
    if (has) {
      $("lat-input").value = l.lat.toFixed(6);
      $("lon-input").value = l.lon.toFixed(6);
    }
    const summary = $("pin-summary");
    if (!has) {
      const p = document.createElement("p");
      p.className = "form-hint";
      p.textContent = "No location set yet. Search, use GPS, click the map, or type coordinates.";
      summary.replaceChildren(p);
    } else {
      const p1 = document.createElement("p");
      const acc = l.accuracy ? ` · accuracy ±${Math.round(l.accuracy)} m` : "";
      p1.textContent = `Pin: ${l.lat.toFixed(6)}, ${l.lon.toFixed(6)} · source: ${SOURCE_LABELS[l.source] || l.source}${acc}`;
      const rows = [p1];
      if (l.address) {
        const p2 = document.createElement("p");
        p2.textContent = `Near: ${l.address}`;
        rows.push(p2);
      }
      summary.replaceChildren(...rows);
    }
    $("demo-warning").hidden = l.source !== "demo_test_coordinate";
    const box = $("confirm-loc");
    box.disabled = !has;
    box.checked = has && l.confirmed;
    $("mobile-place-btn").textContent = has ? "Move pin here" : "Place pin here";
  }

  // ------------------------------------------------------------ search / GPS
  async function doSearch(event) {
    event.preventDefault();
    const status = $("search-status");
    const q = $("search-input").value.trim();
    $("search-results").hidden = true;
    if (!q) { setAlert(status, "warning", "Enter a place or address to search."); return; }
    setAlert(status, "info", "Searching OpenStreetMap…");
    $("search-btn").disabled = true;
    try {
      const { results } = await postJSON("/api/geocode", { q });
      state.searchResults = results;
      if (!results.length) {
        setAlert(status, "info", "No match found. Try a nearby landmark or street address, or click the map.");
        return;
      }
      setAlert(status, "", "");
      $("search-legend").textContent = results.length > 1
        ? `${results.length} possible matches — pick the right one` : "Match";
      $("search-options").replaceChildren(...results.map((r, i) => makeRadio("search_choice", String(i), r.label, i === 0)));
      $("search-results").hidden = false;
      map.setView([results[0].lat, results[0].lon], 17);
    } catch (e) {
      setAlert(status, "warning", e.message);
    } finally {
      $("search-btn").disabled = false;
    }
  }
  function useSearchResult() {
    const checked = document.querySelector('input[name="search_choice"]:checked');
    const r = checked && state.searchResults[Number(checked.value)];
    if (!r) return;
    setPin(r.lat, r.lon, "search", { address: r.label, zoom: 18 });
    setAlert($("search-status"), "info", "Pin placed at the match. Drag it or click the map onto the exact defect, then confirm below.");
    $("search-results").hidden = true;
  }
  function useGPS() {
    const status = $("gps-status");
    if (!("geolocation" in navigator)) {
      setAlert(status, "warning", "This browser can't share its location. Use search, the map, or coordinates.");
      return;
    }
    if (!window.isSecureContext) {
      setAlert(status, "warning", "Location needs a secure (HTTPS) page. Use search, the map, or coordinates.");
      return;
    }
    setAlert(status, "info", "Requesting your location…");
    $("gps-btn").disabled = true;
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        $("gps-btn").disabled = false;
        const { latitude, longitude, accuracy } = pos.coords;
        const acc = Number.isFinite(accuracy) ? Math.round(accuracy) : null;
        if (!setPin(latitude, longitude, "gps", { accuracy: acc, zoom: 18 })) {
          setAlert(status, "warning", "Your browser returned an invalid position. Use search, the map, or coordinates.");
          return;
        }
        setAlert(status, "info", `Using your device's position${acc ? ` (±${acc} m)` : ""}. That's where you are — drag the pin onto the defect if it's elsewhere.`);
      },
      (err) => {
        $("gps-btn").disabled = false;
        const messages = {
          1: "Location permission was denied. You can still search, click the map, or enter coordinates.",
          2: "Your position is unavailable right now. Try again, or use search, the map, or coordinates.",
          3: "Getting your location timed out. Try again, or use search, the map, or coordinates.",
        };
        setAlert(status, "warning", messages[err.code] || "Could not get your location.");
      },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 },
    );
  }
  function onCoordsChange() {
    const lat = $("lat-input").valueAsNumber;
    const lon = $("lon-input").valueAsNumber;
    const err = $("coords-error");
    if (Number.isNaN(lat) || Number.isNaN(lon)) { setAlert(err, "warning", ""); return; }
    if (!validCoords(lat, lon)) {
      setAlert(err, "warning", "Latitude must be between -90 and 90, longitude between -180 and 180.");
      return;
    }
    setAlert(err, "warning", "");
    setPin(lat, lon, "manual", { zoom: 18 });
  }

  // ------------------------------------------------------------- copy & files
  async function copyReport() {
    if (!sync.ready) return;
    const text = sync.report.text;
    const status = $("copy-status");
    try {
      await navigator.clipboard.writeText(text);
      status.textContent = "Copied to clipboard.";
    } catch (_) {
      const range = document.createRange();
      range.selectNodeContents($("report-text"));
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      status.textContent = "Text selected — press Ctrl+C (⌘+C on Mac) to copy.";
    }
  }

  // ---------------------------------------------------------------------- init
  function wire() {
    $("pick-camera").addEventListener("click", () => $("photo-camera").click());
    $("pick-upload").addEventListener("click", () => $("photo-upload").click());
    ["photo-camera", "photo-upload"].forEach((id) => $(id).addEventListener("change", (e) => {
      onPhotoChosen(e.target.files && e.target.files[0]);
      e.target.value = "";
    }));
    $("analyze-btn").addEventListener("click", analyze);

    $("focus-search").addEventListener("click", () => $("search-input").focus());
    $("search-form").addEventListener("submit", doSearch);
    $("search-options").addEventListener("change", (e) => {
      const r = state.searchResults[Number(e.target.value)];
      if (r) map.setView([r.lat, r.lon], 17);
    });
    $("use-place-btn").addEventListener("click", useSearchResult);
    $("gps-btn").addEventListener("click", useGPS);
    $("lat-input").addEventListener("change", onCoordsChange);
    $("lon-input").addEventListener("change", onCoordsChange);
    $("demo-btn").addEventListener("click", () => {
      const [lat, lon] = state.config.demo_coordinate;
      setPin(lat, lon, "demo_test_coordinate", { zoom: 18 });
    });
    $("clear-btn").addEventListener("click", clearPin);
    $("confirm-loc").addEventListener("change", (e) => {
      state.loc.confirmed = e.target.checked && state.loc.lat !== null;
      invalidateReport({ immediate: true });
      updateContinue();
    });
    $("mobile-place-btn").addEventListener("click", () => {
      const c = map.getCenter();
      setPin(c.lat, c.lng, "map_click", { keepAddress: true });
    });

    // Every report field invalidates the previous report immediately.
    $("type-options").addEventListener("change", (e) => {
      state.edits.issue_type = e.target.value;
      invalidateReport({ immediate: true });
    });
    const bindText = (id, key) => $(id).addEventListener("input", (e) => {
      state.edits[key] = e.target.value;
      if (id === "causes-input") updateCausesWarning();
      invalidateReport(); // debounced rebuild; old report is dropped now
    });
    bindText("desc-input", "description");
    bindText("evidence-input", "visible_evidence");
    bindText("causes-input", "possible_root_causes");
    $("urgency-select").addEventListener("change", (e) => {
      state.edits.urgency = e.target.value;
      invalidateReport({ immediate: true });
    });
    document.querySelectorAll('input[name="destination"]').forEach((r) => r.addEventListener("change", (e) => {
      state.destination = e.target.value;
      invalidateReport({ immediate: true });
    }));

    $("copy-btn").addEventListener("click", copyReport);
    $("dl-json").addEventListener("click", () => {
      if (!sync.ready) return;
      downloadBlob(`${sync.report.file_stem}.json`,
        new Blob([JSON.stringify(sync.report.report, null, 2)], { type: "application/json" }));
    });
    $("dl-txt").addEventListener("click", () => {
      if (!sync.ready) return;
      downloadBlob(`${sync.report.file_stem}.txt`, new Blob([sync.report.text], { type: "text/plain" }));
    });
    $("dl-photo").addEventListener("click", () => {
      if (!sync.ready || !state.analysis) return;
      downloadBlob(`${sync.report.file_stem}.jpg`, dataUrlToBlob(state.analysis.photo.data_url));
    });

    $("back-btn").addEventListener("click", () => { if (state.step > 1) goTo(state.step - 1); });
    $("continue-btn").addEventListener("click", () => {
      if (state.step === 5) {
        if (window.confirm("Start a new report? This clears the current draft.")) window.location.reload();
        return;
      }
      if (!canContinue()) goTo(state.step + 1);
    });
  }

  function buildConfigWidgets() {
    const c = state.config;
    $("type-options").replaceChildren(...c.issue_types.map((t) => makeRadio("issue_type", t.value, t.label, false)));
    $("urgency-select").replaceChildren(...c.urgency_levels.map((u) => {
      const o = document.createElement("option");
      o.value = u.value;
      o.textContent = u.label;
      return o;
    }));
    if (!c.search_enabled) {
      $("search-form").hidden = true;
      $("search-off").hidden = false;
      $("focus-search").disabled = true;
    }
    if (!c.analysis_enabled) {
      $("analyze-btn").disabled = true;
      setAlert($("analyze-error"), "warning",
        "Gemini isn't configured on this server. Ask the administrator to set GEMINI_API_KEY.");
    }
  }

  async function init() {
    try {
      state.config = await api("/api/config");
    } catch (e) {
      setAlert($("fatal-error"), "error", `Couldn't load the app configuration: ${e.message}`);
      return;
    }
    if (typeof L === "undefined") {
      setAlert($("fatal-error"), "error", "The map library failed to load. Check your connection and reload.");
      return;
    }
    buildConfigWidgets();
    initMap(state.config.map_center);
    wire();
    renderLocation();
    renderReport();
    goTo(1);
  }

  init();
})();
