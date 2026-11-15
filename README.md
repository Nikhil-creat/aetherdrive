# AetherDrive v2
Static showcase + Vercel serverless Copilot (/api/chat).
Env vars (Vercel > Settings > Environment Variables): GROQ_API_KEY and/or GEMINI_API_KEY. Model auto-detected.
Local Docker: docker compose up --build -> http://localhost:8080
Designed & engineered by Nikhil Chary Sriramoju.

## Full platform (platform/)
cd platform && cp .env.example .env  (edit secrets) && docker compose up --build
API docs: http://localhost:8000/docs  ·  MinIO console: http://localhost:9001
Flow: register -> login -> POST /files/presign -> PUT to MinIO -> POST /files/{id}/complete -> /search, /copilot

## v3
Guard (prompt-injection + secret redaction), in-browser RAG with sources, voice input, command palette (Ctrl/Cmd+K), PWA offline shell, live GitHub stats, resume download.
Run the guard eval: npm run eval (results in evals/RESULTS.md).
