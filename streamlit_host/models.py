from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AppStatus(str, Enum):
    created = "created"
    starting = "starting"
    running = "running"
    failed = "failed"
    stopped = "stopped"


class AppMeta(BaseModel):
    app_id: str
    name: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    status: AppStatus = AppStatus.created
    port: Optional[int] = None
    pid: Optional[int] = None
    error: Optional[str] = None

    requirements_sha256: Optional[str] = None
    app_sha256: Optional[str] = None


class CreateAppResponse(BaseModel):
    app_id: str
    name: Optional[str] = None
    port: Optional[int] = None
    access_url: Optional[str] = None
    status: AppStatus


class StopAppResponse(BaseModel):
    app_id: str
    status: AppStatus


class StartAppResponse(BaseModel):
    app_id: str
    status: AppStatus
    port: Optional[int] = None


