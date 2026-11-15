import os, uuid, hashlib, secrets, asyncio, datetime as dt, jwt
from fastapi import FastAPI, Depends, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select, text
from minio import Minio
import redis.asyncio as aioredis
from .models import *
from .embed import embed
from .worker import ingest
from .agent import ask_copilot, propose_folders

SECRET = os.environ["JWT_SECRET"]
mc = Minio(os.environ["MINIO_ENDPOINT"], os.environ["MINIO_USER"], os.environ["MINIO_PASS"], secure=False)
app = FastAPI(title="AetherDrive API")
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("CORS", "http://localhost:5173").split(","), allow_methods=["*"], allow_headers=["*"])
bearer = HTTPBearer()
hits: dict = {}

def pw(p, salt=b"aether"): return hashlib.pbkdf2_hmac("sha256", p.encode(), salt, 200_000).hex()

async def me(c=Depends(bearer)) -> int:
    try: uid = jwt.decode(c.credentials, SECRET, algorithms=["HS256"])["sub"]
    except jwt.PyJWTError: raise HTTPException(401, "Invalid token")
    now = dt.datetime.utcnow().timestamp()
    hits[uid] = [t for t in hits.get(uid, []) if now - t < 60] + [now]
    if len(hits[uid]) > 120: raise HTTPException(429, "Rate limit: 120 req/min")
    return int(uid)

async def audit(s, uid, action, target): s.add(AuditLog(user_id=uid, action=action, target=target))

@app.on_event("startup")
async def init():
    async with engine.begin() as c:
        await c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await c.run_sync(Base.metadata.create_all)
        await c.execute(text("CREATE INDEX IF NOT EXISTS chunks_hnsw ON chunks USING hnsw (embedding vector_cosine_ops)"))
    if not mc.bucket_exists("drive"): mc.make_bucket("drive")

class Cred(BaseModel): email: str; password: str
@app.post("/auth/register")
async def register(c: Cred):
    async with Session() as s:
        u = User(email=c.email, pw_hash=pw(c.password)); s.add(u)
        try: await s.commit()
        except Exception: raise HTTPException(409, "Email exists")
        return {"id": u.id}
@app.post("/auth/login")
async def login(c: Cred):
    async with Session() as s:
        u = (await s.execute(select(User).where(User.email == c.email))).scalar_one_or_none()
        if not u or not secrets.compare_digest(u.pw_hash, pw(c.password)): raise HTTPException(401, "Bad credentials")
        exp = dt.datetime.utcnow() + dt.timedelta(hours=8)
        return {"token": jwt.encode({"sub": str(u.id), "exp": exp}, SECRET)}

class Up(BaseModel): name: str; sha256: str; folder_id: int | None = None
@app.post("/files/presign")  # step 1: dedup check + presigned PUT (direct-to-MinIO)
async def presign(b: Up, uid=Depends(me)):
    async with Session() as s:
        dup = (await s.execute(select(File).where(File.owner_id == uid, File.sha256 == b.sha256))).scalars().first()
        if dup: return {"duplicate": True, "file_id": dup.id}
        f = (await s.execute(select(File).where(File.owner_id == uid, File.name == b.name, File.folder_id == b.folder_id))).scalars().first()
        if not f: f = File(name=b.name, folder_id=b.folder_id, owner_id=uid, sha256=b.sha256); s.add(f); await s.flush()
        n = len((await s.execute(select(FileVersion).where(FileVersion.file_id == f.id))).scalars().all()) + 1
        key = f"{uid}/{uuid.uuid4()}/{b.name}"; f.sha256 = b.sha256; f.status = "Uploading"
        s.add(FileVersion(file_id=f.id, version=n, object_key=key)); await audit(s, uid, "upload", b.name); await s.commit()
        return {"file_id": f.id, "version": n, "url": mc.presigned_put_object("drive", key, dt.timedelta(minutes=10))}
@app.post("/files/{fid}/complete")  # step 2: kick off the AI pipeline
async def complete(fid: int, uid=Depends(me)):
    ingest.delay(fid); return {"queued": True}
@app.get("/files")
async def files(uid=Depends(me)):
    async with Session() as s:
        return [dict(id=f.id, name=f.name, status=f.status, tags=f.tags, flags=f.flags) for f in (await s.execute(select(File).where(File.owner_id == uid))).scalars()]

@app.get("/search")  # hybrid: 0.7 cosine + 0.3 keyword
async def search(q: str, uid=Depends(me)):
    async with Session() as s:
        r = await s.execute(text("""SELECT f.name, c.idx, left(c.content,200),
            0.7*(1-(c.embedding <=> CAST(:v AS vector))) + 0.3*(c.content ILIKE :k)::int AS score
            FROM chunks c JOIN files f ON f.id=c.file_id WHERE f.owner_id=:u ORDER BY score DESC LIMIT 8"""),
            {"v": str(embed(q)), "k": f"%{q}%", "u": uid})
        return [dict(file=n, chunk=i, snippet=t, score=round(float(sc), 3)) for n, i, t, sc in r]

class Q(BaseModel): question: str
@app.post("/copilot")
async def copilot(b: Q, uid=Depends(me)): return await ask_copilot(b.question, uid)
@app.get("/copilot/organize")
async def organize(uid=Depends(me)): return await propose_folders(uid)

@app.post("/files/{fid}/share")  # time-expiring link
async def share(fid: int, hours: int = 24, uid=Depends(me)):
    async with Session() as s:
        f = await s.get(File, fid)
        if not f or f.owner_id != uid: raise HTTPException(404)
        t = secrets.token_urlsafe(24); s.add(Share(file_id=fid, token=t, expires_at=dt.datetime.utcnow() + dt.timedelta(hours=min(hours, 720))))
        await audit(s, uid, "share", f.name); await s.commit(); return {"token": t}

@app.websocket("/ws/{token}")  # live status badges
async def ws(sock: WebSocket, token: str):
    try: uid = jwt.decode(token, SECRET, algorithms=["HS256"])["sub"]
    except jwt.PyJWTError: return await sock.close(4401)
    await sock.accept(); ps = aioredis.from_url(os.environ["REDIS_URL"]).pubsub(); await ps.subscribe(f"u:{uid}")
    async for m in ps.listen():
        if m["type"] == "message": await sock.send_text(m["data"].decode())
