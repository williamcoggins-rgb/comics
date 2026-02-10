const STABILITY_URL =
  "https://api.stability.ai/v2beta/stable-image/generate/core";

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

    const context = [genre, tone, setting].filter(Boolean).join(", ");
    const fullPrompt = `${STYLE_PREFIX}, ${context ? context + ", " : ""}${art}`;

    const formData = new FormData();
    formData.append("prompt", fullPrompt);
    formData.append("output_format", "webp");
    formData.append("aspect_ratio", "1:1");
    formData.append("style_preset", "comic-book");

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
    const imageUrl = `data:image/webp;base64,${data.image}`;
    res.json({ imageUrl, pageIndex, panelIndex });
  } catch (err) {
    console.error("Art generation error:", err);
    res.status(500).json({ error: err.message });
  }
};
