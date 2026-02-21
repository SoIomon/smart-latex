import datetime
import uuid
from datetime import timezone

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.models.database import Base


def generate_uuid() -> str:
    return uuid.uuid4().hex


class Project(Base):
    __tablename__ = "projects"

    id = Column(String(32), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    description = Column(Text, default="")
    template_id = Column(String(64), default="")
    latex_content = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc), onupdate=lambda: datetime.datetime.now(timezone.utc))

    documents = relationship("Document", back_populates="project", cascade="all, delete-orphan")
    chat_messages = relationship("ChatMessage", back_populates="project", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"

    id = Column(String(32), primary_key=True, default=generate_uuid)
    project_id = Column(String(32), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String(255), nullable=False)
    original_name = Column(String(255), nullable=False)
    file_type = Column(String(20), nullable=False)
    parsed_content = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc))

    project = relationship("Project", back_populates="documents")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(String(32), primary_key=True, default=generate_uuid)
    project_id = Column(String(32), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc))

    project = relationship("Project", back_populates="chat_messages")


class LLMConfig(Base):
    __tablename__ = "llm_config"

    id = Column(Integer, primary_key=True, default=1)
    api_key = Column(String, nullable=False, default="")
    base_url = Column(String, nullable=False, default="https://ark.cn-beijing.volces.com/api/v3")
    model = Column(String, nullable=False, default="doubao-pro-32k")
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc),
                        onupdate=lambda: datetime.datetime.now(timezone.utc))
