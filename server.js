require("dotenv").config();
const express = require("express");
const path = require("path");
const { generateSpecs, evaluateSpec } = require("./engine/bridge");

const app = express();
app.use(express.json({ limit: "2mb" }));
app.use(express.static(path.join(__dirname, "public")));

const STABILITY_API_KEY = process.env.STABILITY_API_KEY;
const STABILITY_URL =
  "https://api.stability.ai/v2beta/stable-image/generate/core";

const STYLE_PREFIX =
  "comic book art in the style of Joe Quesada, heavy black ink areas, bold graphic compositions, " +
  "high contrast noir lighting, organic expressive linework, dramatic shadows with large solid black shapes, " +
  "dynamic exaggerated perspectives, fluid action poses, Art Nouveau decorative influences, " +
  "detailed ink rendering with brush strokes, Marvel Knights aesthetic, professional comic book panel";

// Build a prompt that includes character visual descriptions for consistency
function buildPrompt({ art, genre, tone, setting, characters }) {
  const context = [genre, tone, setting].filter(Boolean).join(", ");
  const artLower = art.toLowerCase();

  // Find which characters are mentioned in this panel's art direction
  const charDescs = (characters || [])
    .filter((c) => c.look && artLower.includes(c.name.toLowerCase()))
    .map((c) => `${c.name}: ${c.look}`)
    .join("; ");

  const parts = [STYLE_PREFIX];
  if (context) parts.push(context);
  if (charDescs) parts.push(`characters in this panel: ${charDescs}`);
  parts.push(art);

  return parts.join(", ");
}

async function generateImage(prompt, seed) {
  const formData = new FormData();
  formData.append("prompt", prompt);
  formData.append("output_format", "webp");
  formData.append("aspect_ratio", "1:1");
  formData.append("style_preset", "comic-book");
  if (seed != null) formData.append("seed", String(seed));

  const response = await fetch(STABILITY_URL, {
    method: "POST",
    headers: {
      authorization: `Bearer ${STABILITY_API_KEY}`,
      accept: "application/json",
    },
    body: formData,
  });

  if (!response.ok) {
    const err = await response.text();
    throw new Error(`Stability AI API error (${response.status}): ${err}`);
  }

  const data = await response.json();
  return `data:image/webp;base64,${data.image}`;
}

// ---------------------------------------------------------------------------
// STUDIO: Generate structured comic specs from a seed
// ---------------------------------------------------------------------------
app.post("/api/studio/generate", async (req, res) => {
  try {
    const { seed = {}, n = 3, applyFixes = "suggest" } = req.body;
    const result = await generateSpecs({ seed, n, applyFixes, includeResults: true });
    res.json(result);
  } catch (err) {
    console.error("Studio generate error:", err);
    res.status(500).json({ error: err.message });
  }
});

// ---------------------------------------------------------------------------
// CRITIC: Evaluate / validate an existing spec
// ---------------------------------------------------------------------------
app.post("/api/critic/evaluate", async (req, res) => {
  try {
    const { spec, applyFixes = "suggest", fullReport = false } = req.body;
    if (!spec) return res.status(400).json({ error: "spec is required" });
    const result = await evaluateSpec({ spec, applyFixes, fullReport });
    res.json(result);
  } catch (err) {
    console.error("Critic evaluate error:", err);
    res.status(500).json({ error: err.message });
  }
});

// ---------------------------------------------------------------------------
// ART: Generate image for a single panel from its art direction
// ---------------------------------------------------------------------------
app.post("/api/art/panel", async (req, res) => {
  try {
    const { art, genre, tone, setting, characters, seed, pageIndex, panelIndex } = req.body;
    if (!art) return res.status(400).json({ error: "art direction is required" });

    const fullPrompt = buildPrompt({ art, genre, tone, setting, characters });
    const imageUrl = await generateImage(fullPrompt, seed);
    res.json({ imageUrl, pageIndex, panelIndex });
  } catch (err) {
    console.error("Art generation error:", err);
    res.status(500).json({ error: err.message });
  }
});

// ---------------------------------------------------------------------------
// ART: Generate images for an entire spec (all pages/panels)
// ---------------------------------------------------------------------------
app.post("/api/art/spec", async (req, res) => {
  try {
    const { spec, characters, seed } = req.body;
    if (!spec || !spec.pages) return res.status(400).json({ error: "spec with pages is required" });

    const genre = spec.genre || "";
    const tone = spec.tone || "";
    const setting = spec.setting || "";

    const jobs = [];
    for (let pi = 0; pi < spec.pages.length; pi++) {
      const page = spec.pages[pi];
      const panels = page.panels || [];
      for (let pn = 0; pn < panels.length; pn++) {
        const panel = panels[pn];
        const art = (panel.art || "").trim();
        if (!art) continue;
        jobs.push({ pageIndex: pi, panelIndex: pn, art });
      }
    }

    const results = await Promise.all(
      jobs.map(async (job) => {
        const fullPrompt = buildPrompt({ art: job.art, genre, tone, setting, characters });
        const imageUrl = await generateImage(fullPrompt, seed);
        return { pageIndex: job.pageIndex, panelIndex: job.panelIndex, imageUrl };
      })
    );

    res.json({ images: results });
  } catch (err) {
    console.error("Spec art generation error:", err);
    res.status(500).json({ error: err.message });
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Comic Creator running at http://localhost:${PORT}`);
  console.log("  Studio API:  POST /api/studio/generate");
  console.log("  Critic API:  POST /api/critic/evaluate");
  console.log("  Art API:     POST /api/art/panel | /api/art/spec");
});
