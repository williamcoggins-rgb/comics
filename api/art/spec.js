const STABILITY_URL =
  "https://api.stability.ai/v2beta/stable-image/generate/core";

const STYLE_PREFIX =
  "comic book art in the style of Joe Quesada, heavy black ink areas, bold graphic compositions, " +
  "high contrast noir lighting, organic expressive linework, dramatic shadows with large solid black shapes, " +
  "dynamic exaggerated perspectives, fluid action poses, Art Nouveau decorative influences, " +
  "detailed ink rendering with brush strokes, Marvel Knights aesthetic, professional comic book panel";

function buildPrompt({ art, genre, tone, setting, characters }) {
  const context = [genre, tone, setting].filter(Boolean).join(", ");
  const artLower = art.toLowerCase();
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
      authorization: `Bearer ${process.env.STABILITY_API_KEY}`,
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

module.exports = async (req, res) => {
  if (req.method !== "POST") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  try {
    const { spec, characters, seed } = req.body;
    if (!spec || !spec.pages)
      return res.status(400).json({ error: "spec with pages is required" });

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
};
