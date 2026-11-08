/* News Compiler front end. Vanilla JS, no build step.
   Routes: #            feed (chips: region filters, Saved)
           #/s/<id>     story detail
           #/settings   outlet toggles, smaller stories
           #/health     feed status (not linked from the main UI) */
(() => {
  "use strict";

  const LEANS = ["left", "lean_left", "center", "lean_right", "right"];
  const LEAN_NAME = { left: "Left", lean_left: "Lean left", center: "Center", lean_right: "Lean right", right: "Right" };
  const LEAN_DOT = { left: "dot-l", lean_left: "dot-ll", center: "dot-c", lean_right: "dot-lr", right: "dot-r" };
  const REGIONS = [
    ["all", "All"], ["saved", "Saved"], ["us", "US"], ["europe", "Europe"], ["middle_east", "Middle East"],
    ["asia", "Asia"], ["americas", "Americas"], ["africa", "Africa"], ["oceania", "Oceania"],
  ];
  const STORE = "nc-v1";

  const $ = (s, el = document) => el.querySelector(s);
  const view = $("#view");
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // --- per-device settings (this phone only) ---
  const prefs = load();
  function load() {
    try {
      const p = JSON.parse(localStorage.getItem(STORE) || "{}");
      return { region: p.region || "all", smaller: !!p.smaller, hidden: p.hidden || [], saved: p.saved || [] };
    } catch (e) {
      return { region: "all", smaller: false, hidden: [], saved: [] };
    }
  }
  function save() { try { localStorage.setItem(STORE, JSON.stringify(prefs)); } catch (e) { /* private mode */ } }

  // --- data ---
  let data = null, outlets = {}, loadedAt = 0, query = "";

  async function fetchJSON(path) {
    const r = await fetch(path, { cache: "no-cache" });
    if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
    return r.json();
  }

  async function refresh() {
    try {
      const [stories, outs] = await Promise.all([fetchJSON("data/stories.json"), fetchJSON("data/outlets.json")]);
      data = stories;
      outlets = Object.fromEntries(outs.map((o) => [o.id, o]));
      loadedAt = Date.now();
      route();
    } catch (e) {
      if (!data) {
        view.innerHTML = `<p class="empty">The stories didn't load (${esc(e.message)}). Check your connection, then pull down to try again.</p>`;
      }
    }
  }

  // A story as this phone sees it: hidden outlets removed, counts recomputed.
  function shape(s) {
    const hidden = new Set(prefs.hidden);
    const items = s.items.filter((i) => !hidden.has(i.outlet_id) && outlets[i.outlet_id]);
    const seen = new Set(), counts = Object.fromEntries(LEANS.map((l) => [l, 0]));
    for (const i of items) {
      if (seen.has(i.outlet_id)) continue;
      seen.add(i.outlet_id);
      counts[outlets[i.outlet_id].lean]++;
    }
    return { ...s, items, counts, n: seen.size };
  }

  function visibleStories() {
    if (!data) return [];
    const min = prefs.smaller ? 2 : 3;
    const q = query.trim().toLowerCase();
    return data.stories.map(shape).filter((s) => {
      if (s.n < min && !(prefs.region === "saved" && prefs.saved.includes(s.id))) return false;
      if (prefs.region === "saved" && !prefs.saved.includes(s.id)) return false;
      if (!["all", "saved"].includes(prefs.region) && s.region !== prefs.region) return false;
      if (q) {
        const hay = [s.headline, s.country, s.summary, ...s.items.map((i) => i.title_en + " " + i.title)].join(" ").toLowerCase();
        if (!q.split(/\s+/).every((w) => hay.includes(w))) return false;
      }
      return true;
    });
  }

  // --- formatting ---
  function ago(iso) {
    const mins = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000));
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins} min ago`;
    const h = Math.round(mins / 60);
    if (h < 24) return `${h} h ago`;
    return `${Math.round(h / 24)} d ago`;
  }
  function bar(counts, big = false) {
    const total = LEANS.reduce((a, l) => a + counts[l], 0) || 1;
    const segs = LEANS.filter((l) => counts[l] > 0)
      .map((l) => `<span class="${l}" style="flex:${counts[l]} 1 0"></span>`).join("");
    const label = LEANS.map((l) => `${LEAN_NAME[l]} ${counts[l]}`).join(", ");
    return `<div class="bar${big ? " big" : ""}" role="img" aria-label="Coverage by lean: ${label} of ${total}">${segs}</div>`;
  }
  function blindspotTag(s) {
    if (!s.blindspot) return "";
    return s.blindspot === "right"
      ? `<span class="tag right">Few right-leaning outlets</span>`
      : `<span class="tag left">Few left-leaning outlets</span>`;
  }
  function headlineLabel(s) {
    return s.country ? `<span class="country">${esc(s.country)}</span>` : "";
  }

  // --- views ---
  function renderChips() {
    $("#chips").innerHTML = REGIONS.map(([k, label]) =>
      `<button type="button" class="chip" data-region="${k}" aria-pressed="${prefs.region === k}">${label}</button>`).join("");
  }

  function renderFeed() {
    renderChips();
    $("#chips").hidden = false;
    if (!data) { view.innerHTML = `<p class="empty">Loading stories…</p>`; return; }
    const list = visibleStories();
    const updated = `Updated ${ago(data.generated_at)}`;
    if (!list.length) {
      const why = prefs.region === "saved"
        ? "Nothing saved yet. Open a story and tap Save to keep it here."
        : query ? `No stories match “${esc(query)}”.` : "No stories in this region right now.";
      view.innerHTML = `<p class="status">${updated}</p><p class="empty">${why}</p>`;
      return;
    }
    view.innerHTML = `<p class="status">${updated}, ${list.length} stories</p><ol class="feed">${list.map((s) => `
      <li class="story"><a href="#/s/${esc(s.id)}">
        ${headlineLabel(s)}
        <span class="headline">${esc(s.headline)}</span>
        ${bar(s.counts)}
        <span class="meta"><span>${s.n} outlets</span><span>${ago(s.updated)}</span>${blindspotTag(s)}</span>
      </a></li>`).join("")}</ol>`;
  }

  let detailMode = "lean";
  function renderDetail(id) {
    $("#chips").hidden = true;
    const raw = data && data.stories.find((s) => s.id === id);
    if (!raw) {
      view.innerHTML = `<a class="back" href="#">‹ Stories</a><p class="empty">This story is no longer in the last 48 hours of news.</p>`;
      return;
    }
    const s = shape(raw);
    const saved = prefs.saved.includes(s.id);
    const legend = LEANS.map((l) => `<div class="${s.counts[l] ? "" : "z"}"><b>${s.counts[l]}</b>${LEAN_NAME[l]}</div>`).join("");
    const summary = s.summary
      ? `<p class="summary">${esc(s.summary)}</p>`
      : "";
    const source = s.headline_source === "model" ? "" :
      `<p class="summary-note">Headline from ${esc(s.headline_source.startsWith("wire:") ? (outlets[s.headline_source.slice(5)]?.name || "a wire service") : "one of the outlets")}; a neutral headline is being written.</p>`;

    view.innerHTML = `<article class="detail">
      <a class="back" href="#">‹ Stories</a>
      ${headlineLabel(s)}
      <h1>${esc(s.headline)}</h1>
      ${summary}${source}
      <section class="coverage" aria-label="Coverage">
        <div class="coverage-head"><span>${s.n} outlets covered this</span>${blindspotTag(s)}</div>
        ${bar(s.counts, true)}
        <div class="legend">${legend}</div>
      </section>
      <div class="actions">
        <div class="seg" role="group" aria-label="Order">
          <button type="button" data-mode="lean" aria-pressed="${detailMode === "lean"}">By lean</button>
          <button type="button" data-mode="time" aria-pressed="${detailMode === "time"}">Timeline</button>
        </div>
        <button type="button" class="btn" id="save" aria-pressed="${saved}">${saved ? "Saved" : "Save"}</button>
      </div>
      <div id="rows">${detailMode === "lean" ? byLean(s) : byTime(s)}</div>
    </article>`;
  }

  function row(i, extra = "") {
    const o = outlets[i.outlet_id];
    const translated = i.title_en && i.title_en !== i.title;
    return `<li class="row">
      <span class="tile"><img src="icons/${esc(i.outlet_id)}.png" alt="" loading="lazy" width="24" height="24"></span>
      <div class="row-body">
        <div class="row-top"><span class="name">${esc(o.name)}</span>
          <span class="lean"><i class="${LEAN_DOT[o.lean]}"></i>${LEAN_NAME[o.lean]}</span>
          ${o.paywall ? `<span title="Subscription may be required">Paywall</span>` : ""}
          <span class="when">${extra || ago(i.published)}</span></div>
        <a class="title" href="${esc(i.url)}" target="_blank" rel="noopener">${esc(translated ? i.title_en : i.title)}</a>
        ${translated ? `<button type="button" class="orig-btn">Show original</button><span class="orig" hidden>${esc(i.title)}</span>` : ""}
      </div></li>`;
  }

  function byLean(s) {
    return LEANS.filter((l) => s.items.some((i) => outlets[i.outlet_id].lean === l)).map((l) => {
      const items = s.items.filter((i) => outlets[i.outlet_id].lean === l)
        .sort((a, b) => outlets[a.outlet_id].name.localeCompare(outlets[b.outlet_id].name));
      return `<h2 class="group-title"><i class="${LEAN_DOT[l]}"></i>${LEAN_NAME[l]} (${new Set(items.map((i) => i.outlet_id)).size})</h2>
        <ul class="rows">${items.map((i) => row(i)).join("")}</ul>`;
    }).join("");
  }

  function byTime(s) {
    const items = [...s.items].sort((a, b) => Date.parse(a.published) - Date.parse(b.published));
    const t0 = Date.parse(items[0].published);
    const rel = (i) => {
      const m = Math.round((Date.parse(i.published) - t0) / 60000);
      if (m === 0) return "First";
      return m < 60 ? `+${m} min` : `+${Math.floor(m / 60)} h ${m % 60} min`;
    };
    return `<h2 class="group-title">Who reported first</h2><ul class="rows">${items.map((i) => row(i, rel(i))).join("")}</ul>`;
  }

  function renderSettings() {
    $("#chips").hidden = true;
    const list = Object.values(outlets).sort((a, b) => LEANS.indexOf(a.lean) - LEANS.indexOf(b.lean) || a.name.localeCompare(b.name));
    view.innerHTML = `<section class="page">
      <a class="back" href="#">‹ Stories</a>
      <h1>Settings</h1>
      <p>These apply on this phone only.</p>
      <div class="toggle-row"><label><input type="checkbox" id="smaller" ${prefs.smaller ? "checked" : ""}>
        <span>Show smaller stories<br><small>Include stories only two outlets covered.</small></span></label></div>
      <h2 class="section-h">Outlets</h2>
      <p>Turn an outlet off to drop its headlines from every story. Its lean comes from AllSides or Media Bias/Fact Check.</p>
      ${list.map((o) => `<div class="toggle-row"><label><input type="checkbox" data-outlet="${esc(o.id)}" ${prefs.hidden.includes(o.id) ? "" : "checked"}>
        <span class="tile"><img src="icons/${esc(o.id)}.png" alt="" width="24" height="24" loading="lazy"></span>
        <span>${esc(o.name)}<br><small><span class="lean"><i class="${LEAN_DOT[o.lean]}"></i>${LEAN_NAME[o.lean]}</span>,
        <a href="${esc(o.lean_source_url)}" target="_blank" rel="noopener">${esc(o.lean_source)}</a></small></span></label></div>`).join("")}
    </section>`;
  }

  async function renderHealth() {
    $("#chips").hidden = true;
    view.innerHTML = `<section class="page"><a class="back" href="#">‹ Stories</a><h1>Feed health</h1><p>Loading…</p></section>`;
    try {
      const h = await fetchJSON("data/health.json");
      const by = {};
      for (const f of h.feeds) (by[f.outlet_id] = by[f.outlet_id] || []).push(f);
      const rows = Object.entries(by).sort((a, b) => (outlets[a[0]]?.name || a[0]).localeCompare(outlets[b[0]]?.name || b[0]))
        .map(([id, fs]) => {
          const good = fs.some((f) => f.status === "ok" || f.status === "not_modified");
          const last = fs.map((f) => f.last_success).filter(Boolean).sort().pop();
          const err = fs.filter((f) => f.error).map((f) => f.error).join("; ");
          return `<tr><td>${esc(outlets[id]?.name || id)}</td>
            <td class="${good ? "ok" : "bad"}">${good ? "Working" : "Failing"}</td>
            <td class="n">${fs.reduce((a, f) => a + (f.items || 0), 0)}</td>
            <td>${last ? ago(last) : "never"}${err && !good ? `<br><small>${esc(err)}</small>` : ""}</td></tr>`;
        }).join("");
      const failing = Object.values(by).filter((fs) => !fs.some((f) => f.status === "ok" || f.status === "not_modified")).length;
      view.innerHTML = `<section class="page"><a class="back" href="#">‹ Stories</a><h1>Feed health</h1>
        <p>Last run ${ago(h.generated_at)}. ${failing ? `${failing} outlet${failing > 1 ? "s" : ""} failing.` : "All outlets working."}</p>
        <div class="table-wrap"><table class="health"><thead><tr><th>Outlet</th><th>Status</th><th>New items</th><th>Last success</th></tr></thead>
        <tbody>${rows}</tbody></table></div></section>`;
    } catch (e) {
      view.innerHTML = `<section class="page"><a class="back" href="#">‹ Stories</a><h1>Feed health</h1><p>Couldn't load feed status: ${esc(e.message)}</p></section>`;
    }
  }

  // --- routing ---
  let lastFeedScroll = 0;
  function route() {
    const h = location.hash;
    const m = h.match(/^#\/s\/(.+)$/);
    if (m) renderDetail(decodeURIComponent(m[1]));
    else if (h === "#/settings") renderSettings();
    else if (h === "#/health") renderHealth();
    else { renderFeed(); requestAnimationFrame(() => window.scrollTo(0, lastFeedScroll)); return; }
    window.scrollTo(0, 0);
  }
  window.addEventListener("hashchange", () => {
    route();
  });
  document.addEventListener("click", (e) => {
    if (e.target.closest(".story a")) lastFeedScroll = window.scrollY;
    const chip = e.target.closest(".chip");
    if (chip) { prefs.region = chip.dataset.region; save(); lastFeedScroll = 0; renderFeed(); window.scrollTo(0, 0); return; }
    const mode = e.target.closest("[data-mode]");
    if (mode) { detailMode = mode.dataset.mode; route(); return; }
    if (e.target.id === "save") {
      const id = location.hash.slice(4);
      prefs.saved = prefs.saved.includes(id) ? prefs.saved.filter((x) => x !== id) : [...prefs.saved, id];
      save(); renderDetail(id); return;
    }
    const orig = e.target.closest(".orig-btn");
    if (orig) {
      const span = orig.nextElementSibling; span.hidden = !span.hidden;
      orig.textContent = span.hidden ? "Show original" : "Hide original";
    }
  });
  document.addEventListener("change", (e) => {
    if (e.target.id === "smaller") { prefs.smaller = e.target.checked; save(); }
    if (e.target.dataset.outlet) {
      const id = e.target.dataset.outlet;
      prefs.hidden = e.target.checked ? prefs.hidden.filter((x) => x !== id) : [...new Set([...prefs.hidden, id])];
      save();
    }
  });

  // --- search ---
  const searchBtn = $("#search-btn"), searchForm = $("#search"), q = $("#q");
  searchBtn.addEventListener("click", () => {
    const open = searchForm.hidden;
    searchForm.hidden = !open;
    searchBtn.setAttribute("aria-expanded", String(open));
    if (open) { if (location.hash) location.hash = ""; q.focus(); }
    else { query = ""; q.value = ""; renderFeed(); }
  });
  q.addEventListener("input", () => { query = q.value; if (!location.hash || location.hash === "#") renderFeed(); });
  searchForm.addEventListener("submit", (e) => { e.preventDefault(); q.blur(); });

  // --- pull to refresh (feed only, at the top of the page) ---
  const pull = $("#pull");
  let startY = null;
  window.addEventListener("touchstart", (e) => {
    startY = window.scrollY <= 0 && (!location.hash || location.hash === "#") ? e.touches[0].clientY : null;
  }, { passive: true });
  window.addEventListener("touchmove", (e) => {
    if (startY === null) return;
    pull.classList.toggle("show", e.touches[0].clientY - startY > 70);
  }, { passive: true });
  window.addEventListener("touchend", () => {
    if (startY !== null && pull.classList.contains("show")) {
      pull.textContent = "Refreshing…";
      refresh().finally(() => { pull.classList.remove("show"); pull.textContent = "Release to refresh"; });
    }
    startY = null;
  });
  // Coming back to the app after a while: fetch the latest run.
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && Date.now() - loadedAt > 10 * 60 * 1000) refresh();
  });

  if ("serviceWorker" in navigator && location.protocol === "https:") {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }

  route();
  refresh();
})();
