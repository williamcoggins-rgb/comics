const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// Mode switching
$$(".mode-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    $$(".mode-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    $$(".mode-content").forEach((c) => c.classList.remove("active"));
    $(`#${btn.dataset.mode}-mode`).classList.add("active");
  });
});

// Add panel button
$("#add-panel-btn").addEventListener("click", () => {
  const container = $("#panel-inputs");
  const count = container.children.length + 1;
  const row = document.createElement("div");
  row.className = "panel-input-row";
  row.innerHTML = `
    <label>Panel ${count}:</label>
    <input type="text" class="panel-prompt" placeholder="Describe panel ${count}..." />
  `;
  container.appendChild(row);
});

// Generate from story mode
$("#generate-story-btn").addEventListener("click", async () => {
  const story = $("#story-input").value.trim();
  if (!story) return;

  const panelCount = parseInt($("#panel-count").value);
  const layout = $("#layout-select").value;

  setLoading(true, "Breaking story into panels...");

  try {
    // Split story into panel descriptions
    const storyRes = await fetch("/api/story-to-panels", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ story, panelCount }),
    });
    const storyData = await storyRes.json();
    if (storyData.error) throw new Error(storyData.error);

    setLoading(true, "Generating comic art... this may take a minute");

    // Generate all panels
    const panels = storyData.panels.map((p) => ({
      prompt: p.prompt,
      caption: p.caption,
    }));

    await generateComic(panels, layout);
  } catch (err) {
    alert("Error: " + err.message);
    setLoading(false);
  }
});

// Generate from panel mode
$("#generate-panels-btn").addEventListener("click", async () => {
  const prompts = [...$$(".panel-prompt")]
    .map((el) => el.value.trim())
    .filter((v) => v.length > 0);

  if (prompts.length === 0) return;

  const layout = $("#layout-select-panel").value;
  setLoading(true, "Generating comic art... this may take a minute");

  try {
    const panels = prompts.map((prompt) => ({ prompt, caption: "" }));
    await generateComic(panels, layout);
  } catch (err) {
    alert("Error: " + err.message);
    setLoading(false);
  }
});

let lastPanels = null;
let lastLayout = null;

async function generateComic(panels, layout) {
  lastPanels = panels;
  lastLayout = layout;

  const comicPage = $("#comic-page");
  comicPage.className = `comic-page ${layout}`;
  comicPage.innerHTML = "";

  // Create placeholder panels
  panels.forEach((panel, i) => {
    const div = document.createElement("div");
    div.className = "comic-panel";
    div.id = `panel-${i}`;
    div.innerHTML = `<div class="panel-loading">Generating panel ${i + 1}...</div>`;
    comicPage.appendChild(div);
  });

  setLoading(false);
  $("#comic-display").classList.remove("hidden");

  // Generate each panel individually so they appear as they complete
  const promises = panels.map(async (panel, i) => {
    try {
      const res = await fetch("/api/generate-panel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: panel.prompt, panelIndex: i }),
      });
      const data = await res.json();
      if (data.error) throw new Error(data.error);

      const panelEl = $(`#panel-${i}`);
      panelEl.innerHTML = "";

      const img = document.createElement("img");
      img.src = data.imageUrl;
      img.alt = panel.prompt;
      panelEl.appendChild(img);

      if (panel.caption) {
        const caption = document.createElement("div");
        caption.className = "caption";
        caption.textContent = panel.caption;
        panelEl.appendChild(caption);
      }
    } catch (err) {
      const panelEl = $(`#panel-${i}`);
      panelEl.innerHTML = `<div class="panel-loading" style="color:#e63946">Error: ${err.message}</div>`;
    }
  });

  await Promise.all(promises);
}

function setLoading(show, text) {
  const el = $("#loading");
  if (show) {
    el.classList.remove("hidden");
    $("#comic-display").classList.add("hidden");
    if (text) $("#loading-text").textContent = text;
  } else {
    el.classList.add("hidden");
  }

  // Disable/enable generate buttons
  $$(".generate-btn").forEach((btn) => (btn.disabled = show));
}

// Regenerate
$("#regenerate-btn").addEventListener("click", () => {
  if (lastPanels && lastLayout) {
    setLoading(true, "Regenerating comic...");
    generateComic(lastPanels, lastLayout);
  }
});

// Download as image
$("#download-btn").addEventListener("click", async () => {
  const comicPage = $("#comic-page");

  // Simple approach: open print dialog for the comic
  const win = window.open("", "_blank");
  win.document.write(`
    <html>
    <head><title>Comic Page</title>
    <style>
      body { margin: 0; background: #fff; display: flex; justify-content: center; padding: 20px; }
      .page { display: grid; gap: 6px; padding: 8px; border: 4px solid #111; max-width: 800px; width: 100%; }
      .page.grid-2x2 { grid-template-columns: 1fr 1fr; }
      .page.grid-2x3 { grid-template-columns: 1fr 1fr; }
      .page.vertical { grid-template-columns: 1fr; }
      .page.dynamic { grid-template-columns: 1fr 1fr; }
      .page.dynamic .panel:first-child, .page.dynamic .panel:last-child { grid-column: 1 / -1; }
      .panel { border: 3px solid #111; overflow: hidden; position: relative; }
      .panel img { width: 100%; display: block; }
      .caption { position: absolute; top: 0; left: 0; right: 0; padding: 6px 10px;
        background: rgba(255,255,50,0.92); color: #111; font-family: "Comic Sans MS", cursive;
        font-size: 12px; font-weight: 700; border-bottom: 2px solid #111; }
    </style></head>
    <body>
    <div class="page ${lastLayout}">
      ${[...comicPage.children]
        .map((p) => `<div class="panel">${p.innerHTML}</div>`)
        .join("")}
    </div>
    <script>setTimeout(() => window.print(), 500)<\/script>
    </body></html>
  `);
});
