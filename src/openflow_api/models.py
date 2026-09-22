from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def generate_uuid() -> str:
    return str(uuid.uuid4())


class Organization(Base):
    """Multi-tenant organization (Tenant) root entity."""
    __tablename__ = "organizations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    projects = relationship("Project", back_populates="organization", cascade="all, delete-orphan")
    users = relationship("User", back_populates="organization", cascade="all, delete-orphan")


class Project(Base):
    """Project entity scoped strictly within an Organization."""
    __tablename__ = "projects"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    org_id = Column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    organization = relationship("Organization", back_populates="projects")
    pipelines = relationship("Pipeline", back_populates="project", cascade="all, delete-orphan")


class User(Base):
    """User belonging to an organization with role-based permissions."""
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    org_id = Column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    role = Column(String(50), default="member", nullable=False)  # admin, member, viewer
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    organization = relationship("Organization", back_populates="users")


class Pipeline(Base):
    """DAG Pipeline definition storing nodes, edges, and configuration."""
    __tablename__ = "pipelines"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    org_id = Column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    graph_json = Column(JSON, nullable=False, default=dict)  # nodes & edges definition
    version = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    project = relationship("Project", back_populates="pipelines")
    executions = relationship("Execution", back_populates="pipeline", cascade="all, delete-orphan")


class Execution(Base):
    """Pipeline execution run record with tenant scoping, status, and telemetry."""
    __tablename__ = "executions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    org_id = Column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    pipeline_id = Column(String(36), ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False, index=True)

    status = Column(
        Enum("pending", "running", "succeeded", "failed", name="execution_status_type"),
        default="pending",
        nullable=False,
        index=True,
    )
    engine = Column(String(50), default="pandas", nullable=False)  # "pandas" or "spark"
    logs = Column(JSON, nullable=False, default=list)  # List of NodeLogs
    duration_ms = Column(Float, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)

    pipeline = relationship("Pipeline", back_populates="executions")

