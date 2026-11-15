import os, datetime as dt
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, ForeignKey, Text, DateTime, JSON, func
from pgvector.sqlalchemy import Vector

engine = create_async_engine(os.environ["DATABASE_URL"])
Session = async_sessionmaker(engine, expire_on_commit=False)
class Base(DeclarativeBase): pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True)
    pw_hash: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String, default="owner")  # owner | editor | viewer
class Folder(Base):
    __tablename__ = "folders"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("folders.id"), nullable=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
class File(Base):
    __tablename__ = "files"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    folder_id: Mapped[int | None] = mapped_column(ForeignKey("folders.id"), nullable=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String, default="Uploading")
    sha256: Mapped[str] = mapped_column(String, index=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    flags: Mapped[list] = mapped_column(JSON, default=list)  # PII/secret findings
class FileVersion(Base):
    __tablename__ = "file_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("files.id"))
    version: Mapped[int] = mapped_column(Integer)
    object_key: Mapped[str] = mapped_column(String)
class DocumentChunk(Base):
    __tablename__ = "chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("files.id"))
    idx: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(384))
class Share(Base):
    __tablename__ = "shares"
    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("files.id"))
    token: Mapped[str] = mapped_column(String, unique=True)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime)
class AuditLog(Base):  # append-only: API exposes no update/delete
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String)
    target: Mapped[str] = mapped_column(String)
    at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
