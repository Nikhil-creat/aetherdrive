// Vercel serverless Copilot proxy: keys live in env vars, never in the browser.
const hits = new Map();
const SYS = "You are Aether Copilot for AetherDrive, an AI-native cloud workspace (FastAPI, React, LangGraph, pgvector hybrid RAG, PyTorch CNN, MinIO, Celery, Docker, zero-trust security), designed by Nikhil Chary Sriramoju, final-year B.Tech CSE student at Vaagdevi College of Engineering, ML Engineer Intern at Yuva Intern (NSDC) and Data Analytics Intern at Thiranex. Be concise.";
module.exports = async (req, res) => {
  if (req.method !== "POST") return res.status(405).json({ error: "POST only" });
  const ip = String(req.headers["x-forwarded-for"] || "x").split(",")[0];
  const now = Date.now();
  const hit = (hits.get(ip) || []).filter(t => now - t < 60000);
  if (hit.length >= 20) return res.status(429).json({ error: "Rate limit: 20 req/min" });
  hit.push(now); hits.set(ip, hit);
  const msgs = ((req.body && req.body.messages) || []).slice(-10).map(m => ({
    role: m.role === "assistant" ? "assistant" : "user", content: String(m.content || "").slice(0, 2000) }));
  if (!msgs.length) return res.status(400).json({ error: "No messages" });
  try {
    if (process.env.GROQ_API_KEY) {
      const H = { Authorization: "Bearer " + process.env.GROQ_API_KEY, "Content-Type": "application/json" };
      const ids = (await (await fetch("https://api.groq.com/openai/v1/models", { headers: H })).json()).data
        .map(m => m.id).filter(i => !/whisper|guard|tts|embed|playai/i.test(i));
      const model = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"].find(x => ids.includes(x)) || ids[0];
      const r = await fetch("https://api.groq.com/openai/v1/chat/completions", { method: "POST", headers: H,
        body: JSON.stringify({ model, messages: [{ role: "system", content: SYS }, ...msgs] }) });
      if (!r.ok) throw new Error("groq " + r.status);
      return res.json({ reply: (await r.json()).choices[0].message.content, model: "groq · " + model });
    }
    if (process.env.GEMINI_API_KEY) {
      const k = process.env.GEMINI_API_KEY;
      const ms = (await (await fetch("https://generativelanguage.googleapis.com/v1beta/models?key=" + k)).json()).models
        .filter(m => (m.supportedGenerationMethods || []).includes("generateContent")).map(m => m.name.replace("models/", ""));
      const model = ms.find(x => /flash/.test(x) && !/lite|exp|preview|thinking/.test(x)) || ms[0];
      const r = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${k}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ systemInstruction: { parts: [{ text: SYS }] },
          contents: msgs.map(m => ({ role: m.role === "user" ? "user" : "model", parts: [{ text: m.content }] })) }) });
      if (!r.ok) throw new Error("gemini " + r.status);
      return res.json({ reply: (await r.json()).candidates[0].content.parts.map(p => p.text).join(""), model: "gemini · " + model });
    }
    return res.status(503).json({ error: "No server key configured" });
  } catch (e) { return res.status(502).json({ error: "Upstream error" }); }
};
