require("dotenv").config();
const express = require("express");
const Replicate = require("replicate");
const path = require("path");
const { generateSpecs, evaluateSpec } = require("./engine/bridge");

const app = express();
app.use(express.json({ limit: "2mb" }));
app.use(express.static(path.join(__dirname, "public")));

const replicate = new Replicate({
  auth: process.env.REPLICATE_API_TOKEN,
});

const STYLE_PREFIX =
  "comic book art in the style of Joe Quesada, heavy black ink areas, bold graphic compositions, " +
  "high contrast noir lighting, organic expressive linework, dramatic shadows with large solid black shapes, " +
  "dynamic exaggerated perspectives, fluid action poses, Art Nouveau decorative influences, " +
  "detailed ink rendering with brush strokes, Marvel Knights aesthetic, professional comic book panel";

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
    const { art, genre, tone, setting, pageIndex, panelIndex } = req.body;
    if (!art) return res.status(400).json({ error: "art direction is required" });

    // Build a rich prompt from the spec's art field + context
    const context = [genre, tone, setting].filter(Boolean).join(", ");
    const fullPrompt = `${STYLE_PREFIX}, ${context ? context + ", " : ""}${art}`;

    const output = await replicate.run("black-forest-labs/flux-1.1-pro", {
      input: {
        prompt: fullPrompt,
        width: 768,
        height: 768,
        num_inference_steps: 25,
        guidance_scale: 3.5,
        output_format: "webp",
        output_quality: 90,
      },
    });

    const imageUrl = typeof output === "string" ? output : output.url?.() ?? String(output);
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
    const { spec } = req.body;
    if (!spec || !spec.pages) return res.status(400).json({ error: "spec with pages is required" });

    const genre = spec.genre || "";
    const tone = spec.tone || "";
    const setting = spec.setting || "";
    const context = [genre, tone, setting].filter(Boolean).join(", ");

    // Build flat list of generation jobs
    const jobs = [];
    for (let pi = 0; pi < spec.pages.length; pi++) {
      const page = spec.pages[pi];
      const panels = page.panels || [];
      for (let pn = 0; pn < panels.length; pn++) {
        const panel = panels[pn];
        const art = (panel.art || "").trim();
        if (!art) continue;
        jobs.push({ pageIndex: pi, panelIndex: pn, art, context });
      }
    }

    // Generate all in parallel (Replicate handles concurrency)
    const results = await Promise.all(
      jobs.map(async (job) => {
        const fullPrompt = `${STYLE_PREFIX}, ${job.context ? job.context + ", " : ""}${job.art}`;
        const output = await replicate.run("black-forest-labs/flux-1.1-pro", {
          input: {
            prompt: fullPrompt,
            width: 768,
            height: 768,
            num_inference_steps: 25,
            guidance_scale: 3.5,
            output_format: "webp",
            output_quality: 90,
          },
        });
        const imageUrl = typeof output === "string" ? output : output.url?.() ?? String(output);
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
