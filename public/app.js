const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

let generatedSpecs = [];
let selectedSpec = null;
let scriptMode = false; // true when using "My Script" mode

// ---------------------------------------------------------------------------
// Mode Tabs (My Script vs Generate Ideas)
// ---------------------------------------------------------------------------
$$(".mode-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    $$(".mode-tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    const mode = tab.dataset.mode;
    $$("#mode-script, #mode-generate").forEach((p) => p.classList.add("hidden"));
    $(`#mode-${mode}`).classList.remove("hidden");
  });
});

// ---------------------------------------------------------------------------
// Character Builder
// ---------------------------------------------------------------------------
let characterCount = 0;

function addCharacterRow(name, look) {
  characterCount++;
  const id = characterCount;
  const row = document.createElement("div");
  row.className = "character-row";
  row.id = `char-row-${id}`;
  row.innerHTML = `
    <div class="field" style="flex:1">
      <label>Name</label>
      <input type="text" class="char-name" placeholder="e.g. Mara" value="${esc(name || "")}" />
    </div>
    <div class="field" style="flex:3">
      <label>Visual Appearance</label>
      <input type="text" class="char-look" placeholder="e.g. tall woman, short red hair, leather jacket, cyberpunk style, sharp jaw" value="${esc(look || "")}" />
    </div>
    <button class="remove-char" onclick="this.parentElement.remove()">&times;</button>
  `;
  $("#character-list").appendChild(row);
}

$("#btn-add-character").addEventListener("click", () => addCharacterRow("", ""));

// Start with one empty row
addCharacterRow("", "");

function getCharacters() {
  const chars = [];
  $$("#character-list .character-row").forEach((row) => {
    const name = row.querySelector(".char-name").value.trim();
    const look = row.querySelector(".char-look").value.trim();
    if (name) chars.push({ name, look });
  });
  return chars;
}

// ---------------------------------------------------------------------------
// Script Parser
// ---------------------------------------------------------------------------
function parseScript(text) {
  const pages = [];
  // Split into page blocks
  const pageBlocks = text.split(/^PAGE\s+\d+\s*$/im);

  for (const block of pageBlocks) {
    if (!block.trim()) continue;

    const panels = [];
    // Split into panel blocks
    const panelBlocks = block.split(/^Panel\s+\d+\s*:\s*/im);

    for (const panelBlock of panelBlocks) {
      if (!panelBlock.trim()) continue;

      const lines = panelBlock.trim().split("\n");
      // First line is the art direction
      const art = lines[0].trim();
      const textEntries = [];

      for (let i = 1; i < lines.length; i++) {
        const line = lines[i].trim();
        if (!line) continue;

        // CAPTION: text
        const captionMatch = line.match(/^CAPTION\s*:\s*(.+)/i);
        if (captionMatch) {
          textEntries.push({ type: "caption", value: captionMatch[1].trim() });
          continue;
        }
        // SFX: text
        const sfxMatch = line.match(/^SFX\s*:\s*(.+)/i);
        if (sfxMatch) {
          textEntries.push({ type: "sfx", value: sfxMatch[1].trim() });
          continue;
        }
        // CHARACTER: dialogue
        const dialogMatch = line.match(/^([A-Z][A-Z0-9\s.'()-]+)\s*:\s*(.+)/);
        if (dialogMatch) {
          textEntries.push({
            type: "dialogue",
            speaker: dialogMatch[1].trim(),
            value: dialogMatch[2].trim(),
          });
          continue;
        }
      }

      panels.push({ art, text: textEntries });
    }

    if (panels.length > 0) {
      pages.push({
        page_no: pages.length + 1,
        page_type: "normal",
        panels,
      });
    }
  }

  return pages;
}

// ---------------------------------------------------------------------------
// Script Mode: Parse & Generate Art
// ---------------------------------------------------------------------------
$("#btn-parse-script").addEventListener("click", async () => {
  const scriptText = $("#script-input").value.trim();
  if (!scriptText) return alert("Please enter your script first.");

  const pages = parseScript(scriptText);
  if (pages.length === 0) return alert("Could not parse any pages. Make sure to use the PAGE / Panel format.");

  const characters = getCharacters();
  const genre = $("#script-genre").value.trim();
  const tone = $("#script-tone").value.trim();
  const setting = $("#script-setting").value.trim();

  scriptMode = true;
  showStep("#step-art");

  // Build and render panels, then generate art
  generateArtForPages(pages, { characters, genre, tone, setting });
});

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------
function showStep(id) {
  $$(".step").forEach((s) => s.classList.remove("active"));
  $(id).classList.add("active");
}

function setLoading(show, text) {
  if (show) {
    $("#loading").classList.remove("hidden");
    if (text) $("#loading-text").textContent = text;
  } else {
    $("#loading").classList.add("hidden");
  }
}

// ---------------------------------------------------------------------------
// STEP 1 (Generate Mode): Generate specs from seed
// ---------------------------------------------------------------------------
$("#btn-generate").addEventListener("click", async () => {
  const seed = {
    genre: $("#seed-genre").value.trim() || "superhero noir",
    tone: $("#seed-tone").value.trim() || "tense",
    hook: $("#seed-hook").value.trim() || "a stolen secret",
    setting: $("#seed-setting").value.trim() || "a city of hidden power",
    page_count: parseInt($("#seed-pages").value),
    rng_seed: Math.floor(Math.random() * 100000),
  };
  const n = parseInt($("#seed-count").value);

  $("#btn-generate").disabled = true;
  setLoading(true, "Engine is generating structured specs...");
  showStep("#step-seed");

  try {
    const res = await fetch("/api/studio/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ seed, n, applyFixes: "suggest" }),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    generatedSpecs = data.generated_specs || [];
    scriptMode = false;
    renderSpecCards();
    setLoading(false);
    showStep("#step-review");
  } catch (err) {
    alert("Error: " + err.message);
    setLoading(false);
  } finally {
    $("#btn-generate").disabled = false;
  }
});

// ---------------------------------------------------------------------------
// STEP 2: Render spec cards + detail
// ---------------------------------------------------------------------------
function renderSpecCards() {
  const container = $("#spec-cards");
  container.innerHTML = "";
  $("#spec-detail").classList.add("hidden");

  generatedSpecs.forEach((item, idx) => {
    const spec = item.spec;
    const card = document.createElement("div");
    card.className = "spec-card";
    card.innerHTML = `
      <div class="card-title">${esc(spec.title || `Idea ${idx + 1}`)}</div>
      <div class="card-meta">
        ${esc(spec.genre || "")} | ${(spec.pages || []).length} pages |
        <span class="gate-badge gate-${item.summary?.status || "red"}">${item.summary?.status || "?"}</span>
      </div>
      <div class="card-premise">${esc(spec.premise || "")}</div>
    `;
    card.addEventListener("click", () => selectSpec(idx));
    container.appendChild(card);
  });
}

function selectSpec(idx) {
  $$(".spec-card").forEach((c, i) => c.classList.toggle("selected", i === idx));
  selectedSpec = generatedSpecs[idx];
  renderSpecDetail(selectedSpec);
}

function renderSpecDetail(item) {
  const spec = item.spec;
  const detail = $("#spec-detail");
  detail.classList.remove("hidden");

  $("#detail-title").textContent = spec.title || "Untitled";
  const gate = $("#detail-gate");
  const status = item.summary?.status || "red";
  gate.className = `gate-badge gate-${status}`;
  gate.textContent = status === "green" ? "All rules pass" : status === "yellow" ? "Warnings" : "Failures";

  renderRules(item.results || []);

  $("#detail-story").innerHTML = `
    <p><strong>Premise:</strong> ${esc(spec.premise || "")}</p>
    <p><strong>Protagonist:</strong> ${esc(spec.protagonist || "")} — ${esc(spec.protagonist_goal || "")}</p>
    <p><strong>Stakes:</strong> ${esc(spec.stakes || "")}</p>
    <p><strong>Central Conflict:</strong> ${esc(spec.central_conflict || "")}</p>
    <p><strong>Character Change:</strong> ${esc(spec.character_change || "")}</p>
    <p><strong>Internal Conflict:</strong> ${esc(spec.internal_conflict || "")}</p>
    <p><strong>Tone:</strong> ${esc(spec.tone || "")} | <strong>Genre:</strong> ${esc(spec.genre || "")}</p>
  `;

  const chars = spec.characters || [];
  $("#detail-characters").innerHTML = chars
    .map((c) => `<span class="char-item"><span class="char-role">${esc(c.role)}</span> ${esc(c.name)}</span>`)
    .join("");

  const beats = spec.beats || [];
  $("#detail-beats").innerHTML = beats
    .map(
      (b) => `
      <div class="beat-item">
        <div class="beat-name">${esc(b.name || "Beat")}</div>
        <div class="beat-detail">
          ${b.new_problem ? `<strong>Problem:</strong> ${esc(b.new_problem)}<br>` : ""}
          ${b.change ? `<strong>Change:</strong> ${esc(b.change)}<br>` : ""}
          ${b.cost ? `<strong>Cost:</strong> ${esc(b.cost)}` : ""}
        </div>
      </div>`
    )
    .join("");

  const pages = spec.pages || [];
  $("#detail-pages").innerHTML = pages
    .map((page) => {
      const panels = page.panels || [];
      const reveal = page.page_turn_reveal ? `<span style="color:#e63946;font-size:0.75rem;"> [PAGE-TURN REVEAL]</span>` : "";
      return `
        <div class="page-block">
          <div class="page-header">Page ${page.page_no} (${page.page_type || "normal"})${reveal}</div>
          ${panels
            .map(
              (pn, j) => `
              <div class="panel-item">
                Panel ${j + 1}: <span class="panel-art">${esc(pn.art || "")}</span>
                ${(pn.text || []).map((t) => `<br><span class="panel-text">${esc(t.type || "")}: ${esc(t.value || "")}</span>`).join("")}
                ${pn.silent_intent ? `<br><span class="panel-text">silent: ${esc(pn.silent_intent)}</span>` : ""}
              </div>`
            )
            .join("")}
        </div>`;
    })
    .join("");

  const suggestions = spec.suggestions || {};
  const sugKeys = Object.keys(suggestions);
  if (sugKeys.length > 0) {
    $("#detail-suggestions-wrap").classList.remove("hidden");
    $("#detail-suggestions").innerHTML = sugKeys
      .map(
        (key) => `
        <div class="suggestion-group">
          <div class="sg-label">${esc(key)}</div>
          ${(suggestions[key] || []).map((s) => `<div class="sg-item">- ${esc(s)}</div>`).join("")}
        </div>`
      )
      .join("");
  } else {
    $("#detail-suggestions-wrap").classList.add("hidden");
  }
}

function renderRules(results) {
  const panel = $("#detail-rules");
  if (!results || results.length === 0) {
    panel.innerHTML = '<span class="rule-chip rule-note">No rule results</span>';
    return;
  }
  const levelOrder = { FAIL: 0, WARN: 1, NOTE: 2, PASS: 3 };
  const sorted = [...results].sort((a, b) => (levelOrder[a.level] ?? 3) - (levelOrder[b.level] ?? 3));
  panel.innerHTML = sorted
    .map((r) => {
      const lvl = (r.level || "PASS").toLowerCase();
      const cls = `rule-${lvl === "fail" ? "fail" : lvl === "warn" ? "warn" : lvl === "note" ? "note" : "pass"}`;
      return `<span class="rule-chip ${cls}" title="${esc(r.message || "")}">${esc(r.rule_id)}</span>`;
    })
    .join("");
}

// ---------------------------------------------------------------------------
// STEP 3: Generate Art (shared by both modes)
// ---------------------------------------------------------------------------

// From Generate mode: use selected spec
$("#btn-generate-art").addEventListener("click", async () => {
  if (!selectedSpec) return;
  scriptMode = false;
  showStep("#step-art");
  const spec = selectedSpec.spec;
  const characters = (spec.characters || []).map((c) => ({
    name: c.name,
    look: c.look || "",
  }));
  generateArtForPages(spec.pages || [], {
    characters,
    genre: spec.genre || "",
    tone: spec.tone || "",
    setting: spec.setting || "",
  });
});

async function generateArtForPages(pages, { characters, genre, tone, setting }) {
  const container = $("#comic-pages");
  container.innerHTML = "";

  // Build page containers
  pages.forEach((page, pi) => {
    const panels = page.panels || [];
    const pageDiv = document.createElement("div");
    const panelCount = panels.length;
    pageDiv.className = `comic-page panels-${Math.min(panelCount, 6)}`;

    const label = document.createElement("div");
    label.className = "comic-page-label";
    label.textContent = `Page ${page.page_no}${page.page_turn_reveal ? " - PAGE TURN REVEAL" : ""}`;
    pageDiv.appendChild(label);

    panels.forEach((panel, pn) => {
      const panelDiv = document.createElement("div");
      panelDiv.className = "comic-panel";
      panelDiv.id = `panel-${pi}-${pn}`;
      panelDiv.innerHTML = `<div class="panel-loading">Generating panel ${pn + 1}...</div>`;
      pageDiv.appendChild(panelDiv);
    });

    container.appendChild(pageDiv);
  });

  // Use a consistent seed for style cohesion across panels
  const artSeed = Math.floor(Math.random() * 100000);

  // Fire off each panel
  const jobs = [];
  pages.forEach((page, pi) => {
    (page.panels || []).forEach((panel, pn) => {
      const art = (panel.art || "").trim();
      if (!art) return;
      jobs.push({ pageIndex: pi, panelIndex: pn, art, panel, page });
    });
  });

  await Promise.all(
    jobs.map(async (job) => {
      try {
        const res = await fetch("/api/art/panel", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            art: job.art,
            genre,
            tone,
            setting,
            characters,
            seed: artSeed,
            pageIndex: job.pageIndex,
            panelIndex: job.panelIndex,
          }),
        });
        const data = await res.json();
        if (data.error) throw new Error(data.error);

        const panelEl = $(`#panel-${job.pageIndex}-${job.panelIndex}`);
        if (!panelEl) return;
        panelEl.innerHTML = "";

        const img = document.createElement("img");
        img.src = data.imageUrl;
        img.alt = job.art;
        panelEl.appendChild(img);

        // Captions / dialogue
        const texts = job.panel.text || [];
        const captionText = texts
          .filter((t) => t.value)
          .map((t) => {
            if (t.speaker) return `${t.speaker}: "${t.value}"`;
            if (t.type === "sfx") return `[${t.value}]`;
            return t.value;
          })
          .join(" ");
        if (captionText) {
          const caption = document.createElement("div");
          caption.className = "caption";
          caption.textContent = captionText;
          panelEl.appendChild(caption);
        }

        if (job.page.page_turn_reveal) {
          const badge = document.createElement("div");
          badge.className = "reveal-badge";
          badge.textContent = "REVEAL";
          panelEl.appendChild(badge);
        }
      } catch (err) {
        const panelEl = $(`#panel-${job.pageIndex}-${job.panelIndex}`);
        if (panelEl) {
          panelEl.innerHTML = `<div class="panel-loading" style="color:#e63946">Error: ${esc(err.message)}</div>`;
        }
      }
    })
  );
}

// ---------------------------------------------------------------------------
// Navigation buttons
// ---------------------------------------------------------------------------
$("#btn-back-seeds").addEventListener("click", () => {
  showStep("#step-seed");
});

$("#btn-back-start").addEventListener("click", () => {
  if (scriptMode) {
    showStep("#step-seed");
  } else {
    showStep("#step-review");
  }
});

$("#btn-download").addEventListener("click", () => {
  const pages = $("#comic-pages");
  const win = window.open("", "_blank");
  win.document.write(`
    <html><head><title>Comic</title>
    <style>
      body { margin: 0; background: #fff; padding: 20px; }
      .page { display: grid; gap: 6px; padding: 8px; border: 4px solid #111; margin-bottom: 20px; max-width: 800px; margin-left: auto; margin-right: auto; grid-template-columns: 1fr 1fr; }
      .panel { border: 3px solid #111; overflow: hidden; position: relative; }
      .panel img { width: 100%; display: block; }
      .caption { position: absolute; top: 0; left: 0; right: 0; padding: 6px 10px; background: rgba(255,255,50,0.92); color: #111; font-family: "Comic Sans MS", cursive; font-size: 12px; font-weight: 700; border-bottom: 2px solid #111; }
      .reveal { position: absolute; bottom: 4px; right: 4px; background: #e63946; color: #fff; font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 3px; }
      .page-label { grid-column: 1 / -1; text-align: center; color: #666; font-size: 11px; font-weight: 600; text-transform: uppercase; }
    </style></head><body>${pages.innerHTML}
    <script>setTimeout(() => window.print(), 500)<\/script>
    </body></html>
  `);
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function esc(str) {
  const div = document.createElement("div");
  div.textContent = str || "";
  return div.innerHTML;
}
