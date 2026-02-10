require("dotenv").config();
const express = require("express");
const Replicate = require("replicate");
const path = require("path");

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, "public")));

const replicate = new Replicate({
  auth: process.env.REPLICATE_API_TOKEN,
});

// Generate a single comic panel image
app.post("/api/generate-panel", async (req, res) => {
  try {
    const { prompt, panelIndex } = req.body;
    if (!prompt) {
      return res.status(400).json({ error: "prompt is required" });
    }

    const stylePrefix =
      "professional Marvel comic book art style, bold ink lines, dynamic composition, vivid colors, cel-shaded, dramatic lighting, detailed illustration, comic book panel";

    const fullPrompt = `${stylePrefix}, ${prompt}`;

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

    // Flux 1.1 Pro returns a single URL string or a FileOutput
    const imageUrl = typeof output === "string" ? output : output.url?.() ?? String(output);

    res.json({ imageUrl, panelIndex });
  } catch (err) {
    console.error("Generation error:", err);
    res.status(500).json({ error: err.message });
  }
});

// Generate a full comic page (multiple panels)
app.post("/api/generate-page", async (req, res) => {
  try {
    const { panels } = req.body;
    if (!panels || !Array.isArray(panels) || panels.length === 0) {
      return res.status(400).json({ error: "panels array is required" });
    }

    const stylePrefix =
      "professional Marvel comic book art style, bold ink lines, dynamic composition, vivid colors, cel-shaded, dramatic lighting, detailed illustration, comic book panel";

    const results = await Promise.all(
      panels.map(async (panel, index) => {
        const fullPrompt = `${stylePrefix}, ${panel.prompt}`;
        const output = await replicate.run("black-forest-labs/flux-1.1-pro", {
          input: {
            prompt: fullPrompt,
            width: panel.width || 768,
            height: panel.height || 768,
            num_inference_steps: 25,
            guidance_scale: 3.5,
            output_format: "webp",
            output_quality: 90,
          },
        });
        const imageUrl = typeof output === "string" ? output : output.url?.() ?? String(output);
        return { imageUrl, panelIndex: index, prompt: panel.prompt };
      })
    );

    res.json({ panels: results });
  } catch (err) {
    console.error("Page generation error:", err);
    res.status(500).json({ error: err.message });
  }
});

// Break a story into panel descriptions using a simple approach
app.post("/api/story-to-panels", async (req, res) => {
  try {
    const { story, panelCount } = req.body;
    if (!story) {
      return res.status(400).json({ error: "story is required" });
    }

    const count = panelCount || 4;
    // Split the story into visual scene descriptions
    // This is a simple heuristic approach - split by sentences and group them
    const sentences = story
      .split(/[.!?]+/)
      .map((s) => s.trim())
      .filter((s) => s.length > 0);

    const panelsPerGroup = Math.max(1, Math.ceil(sentences.length / count));
    const panels = [];

    for (let i = 0; i < count; i++) {
      const start = i * panelsPerGroup;
      const group = sentences.slice(start, start + panelsPerGroup);
      if (group.length > 0) {
        panels.push({
          prompt: group.join(". "),
          caption: group.join(". ") + ".",
        });
      }
    }

    // Pad with the last description if we don't have enough panels
    while (panels.length < count) {
      panels.push(panels[panels.length - 1]);
    }

    res.json({ panels: panels.slice(0, count) });
  } catch (err) {
    console.error("Story parsing error:", err);
    res.status(500).json({ error: err.message });
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Comic generator running at http://localhost:${PORT}`);
});
