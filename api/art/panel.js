const Replicate = require("replicate");

const STYLE_PREFIX =
  "comic book art in the style of Joe Quesada, heavy black ink areas, bold graphic compositions, " +
  "high contrast noir lighting, organic expressive linework, dramatic shadows with large solid black shapes, " +
  "dynamic exaggerated perspectives, fluid action poses, Art Nouveau decorative influences, " +
  "detailed ink rendering with brush strokes, Marvel Knights aesthetic, professional comic book panel";

module.exports = async (req, res) => {
  if (req.method !== "POST") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  try {
    const { art, genre, tone, setting, pageIndex, panelIndex } = req.body;
    if (!art) return res.status(400).json({ error: "art direction is required" });

    const replicate = new Replicate({ auth: process.env.REPLICATE_API_TOKEN });
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

    const imageUrl =
      typeof output === "string" ? output : output.url?.() ?? String(output);
    res.json({ imageUrl, pageIndex, panelIndex });
  } catch (err) {
    console.error("Art generation error:", err);
    res.status(500).json({ error: err.message });
  }
};
