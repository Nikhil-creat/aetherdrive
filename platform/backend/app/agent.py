import os, httpx
from typing import TypedDict
from langgraph.graph import StateGraph, END
from sqlalchemy import text, select
from .models import Session, File
from .embed import embed

class S(TypedDict):
    q: str; uid: int; ctx: list; answer: str

async def retrieve(st: S):
    async with Session() as s:
        r = await s.execute(text("""SELECT f.name, c.idx, c.content FROM chunks c JOIN files f ON f.id=c.file_id
            WHERE f.owner_id=:u ORDER BY c.embedding <=> CAST(:v AS vector) LIMIT 5"""), {"u": st["uid"], "v": str(embed(st["q"]))})
        return {"ctx": [dict(name=n, chunk=i, text=t) for n, i, t in r]}

async def answer(st: S):
    ctx = "\n".join(f"[{c['name']}#{c['chunk']}] {c['text'][:700]}" for c in st["ctx"])
    key = os.environ.get("GROQ_API_KEY")
    if not key: return {"answer": "Set GROQ_API_KEY.\n" + ctx}
    async with httpx.AsyncClient(timeout=30) as h:
        r = await h.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
            json={"model": "llama-3.3-70b-versatile", "messages": [
              {"role": "system", "content": "Answer ONLY from the context. Cite sources as [file#chunk]. If missing, say so."},
              {"role": "user", "content": f"Context:\n{ctx}\n\nQuestion: {st['q']}"}]})
    return {"answer": r.json()["choices"][0]["message"]["content"]}

g = StateGraph(S)
g.add_node("retrieve", retrieve); g.add_node("answer", answer)
g.set_entry_point("retrieve"); g.add_edge("retrieve", "answer"); g.add_edge("answer", END)
graph = g.compile()

async def ask_copilot(q: str, uid: int):
    out = await graph.ainvoke({"q": q, "uid": uid, "ctx": [], "answer": ""})
    return {"answer": out["answer"], "sources": [f"{c['name']}#{c['chunk']}" for c in out["ctx"]]}

async def propose_folders(uid: int):  # human-in-the-loop: proposal only, nothing is moved
    async with Session() as s:
        files = (await s.execute(select(File).where(File.owner_id == uid))).scalars().all()
    plan = {}
    for f in files: plan.setdefault((f.tags or ["Unsorted"])[0].split(":")[0], []).append(f.name)
    return {"proposal": plan, "requires_confirmation": True}
