import os, io, re, json, asyncio, redis
from celery import Celery
from minio import Minio
from sqlalchemy import select
from .models import Session, File, FileVersion, DocumentChunk
from .embed import embed

app = Celery("worker", broker=os.environ["REDIS_URL"])
mc = Minio(os.environ["MINIO_ENDPOINT"], os.environ["MINIO_USER"], os.environ["MINIO_PASS"], secure=False)
rd = redis.from_url(os.environ["REDIS_URL"])
PII = re.compile(r"(AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|gsk_[A-Za-z0-9]{20,}|\b\d{12}\b)")

def chunks(t, n=800, o=100):
    w = t.split()
    return [" ".join(w[i:i + n]) for i in range(0, max(len(w), 1), n - o)]

def extract(name, b):
    if name.lower().endswith(".pdf"):
        from pypdf import PdfReader
        return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(b)).pages)
    return b.decode("utf-8", "ignore")

def image_tags(b):  # CNN: torchvision ResNet-50 top-3 (install torch/torchvision in worker image to enable)
    try:
        import torch, torchvision as tv
        from PIL import Image
        m = tv.models.resnet50(weights="DEFAULT").eval()
        w = tv.models.ResNet50_Weights.DEFAULT
        x = w.transforms()(Image.open(io.BytesIO(b)).convert("RGB")).unsqueeze(0)
        top = m(x).softmax(1)[0].topk(3)
        return [f"{w.meta['categories'][i]}:{p:.2f}" for p, i in zip(top.values.tolist(), top.indices.tolist())]
    except Exception:
        return []

def push(uid, fid, status):
    rd.publish(f"u:{uid}", json.dumps({"file": fid, "status": status}))

async def run(fid):
    async with Session() as s:
        f = await s.get(File, fid)
        v = (await s.execute(select(FileVersion).where(FileVersion.file_id == fid).order_by(FileVersion.version.desc()))).scalars().first()
        push(f.owner_id, fid, "Extracting")
        b = mc.get_object("drive", v.object_key).read()
        if f.name.lower().endswith((".png", ".jpg", ".jpeg")):
            f.tags = image_tags(b); text = ""
        else:
            text = extract(f.name, b)
        f.flags = sorted(set(PII.findall(text)))[:5] and ["pii-or-secret-detected"]
        push(f.owner_id, fid, "Indexing AI")
        for i, c in enumerate(chunks(text) if text.strip() else []):
            s.add(DocumentChunk(file_id=fid, idx=i, content=c, embedding=embed(c)))
        f.status = "Ready"; await s.commit()
        push(f.owner_id, fid, "Ready")

@app.task
def ingest(fid): asyncio.run(run(fid))
