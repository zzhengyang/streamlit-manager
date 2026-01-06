from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from .app_manager import AppManager
from .config import get_settings
from .models import AppMeta, CreateAppResponse, StartAppResponse, StopAppResponse
from .proxy import proxy_http, proxy_ws


settings = get_settings()
manager = AppManager(settings)

app = FastAPI(title="Streamlit Host", version="0.1.0")
api = APIRouter(prefix="/api")

# 私有部署场景通常不需要 CORS；为了便于对接内部面板，默认放开（也可自行移除/收紧）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"ok": True}

@api.get("/health")
def api_health() -> dict:
    return {"ok": True}

@api.api_route("/apps", methods=["GET", "HEAD"], response_model=list[AppMeta])
def list_apps() -> list[AppMeta]:
    return manager.list_apps()


@api.api_route("/apps/{app_id}", methods=["GET", "HEAD"], response_model=AppMeta)
def get_app(app_id: str) -> AppMeta:
    try:
        return manager.get_app(app_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="app not found")


@api.get("/apps/{app_id}/logs")
def get_logs(app_id: str, tail: int = 200) -> dict:
    try:
        _ = manager.get_app(app_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="app not found")
    return {"app_id": app_id, "logs": manager.tail_logs(app_id, tail=tail)}


def _public_access_url(app_id: str) -> str | None:
    """
    单端口方案：对外访问地址是 {PUBLIC_BASE}/apps/{app_id}/
    例如 PUBLIC_BASE=http://my-host:8080
    """
    base = os.getenv("STREAMLIT_HOST_PUBLIC_BASE")
    if not base:
        return None
    return base.rstrip("/") + f"/apps/{app_id}/"


@api.post("/apps", response_model=CreateAppResponse)
async def create_app(
    name: str = Form(...),
    requirements: UploadFile = File(...),
    app_file: UploadFile = File(..., alias="app"),
) -> CreateAppResponse:
    # 保存到临时目录，再交给 manager 复制进 app_dir
    tmp_dir = Path(settings.data_dir / "tmp")
    tmp_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=str(tmp_dir)) as td:
        td_path = Path(td)
        req_path = td_path / "requirements.txt"
        app_path = td_path / "app.py"

        req_path.write_bytes(await requirements.read())
        app_path.write_bytes(await app_file.read())

        try:
            meta = manager.create_app(name=name, requirements_path=req_path, app_py_path=app_path)
        except FileExistsError:
            raise HTTPException(status_code=500, detail="id collision, retry")

    return CreateAppResponse(
        app_id=meta.app_id,
        name=meta.name,
        port=meta.port,
        access_url=_public_access_url(meta.app_id),
        status=meta.status,
    )


@api.patch("/apps/{app_id}", response_model=AppMeta)
async def update_app(
    app_id: str,
    name: str | None = Form(None),
    requirements: UploadFile | None = File(None),
    app_file: UploadFile | None = File(None, alias="app"),
) -> AppMeta:
    tmp_dir = Path(settings.data_dir / "tmp")
    tmp_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=str(tmp_dir)) as td:
        td_path = Path(td)
        req_path = td_path / "requirements.txt"
        app_path = td_path / "app.py"

        req_in: Path | None = None
        app_in: Path | None = None

        if requirements is not None:
            req_path.write_bytes(await requirements.read())
            req_in = req_path

        if app_file is not None:
            app_path.write_bytes(await app_file.read())
            app_in = app_path

        try:
            return manager.update_app(app_id=app_id, name=name, requirements_path=req_in, app_py_path=app_in)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="app not found")


@api.post("/apps/{app_id}/stop", response_model=StopAppResponse)
def stop_app(app_id: str) -> StopAppResponse:
    try:
        meta = manager.stop_app(app_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="app not found")
    return StopAppResponse(app_id=meta.app_id, status=meta.status)


@api.post("/apps/{app_id}/start", response_model=StartAppResponse)
def start_app(app_id: str) -> StartAppResponse:
    try:
        meta = manager.start_app(app_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="app not found")
    return StartAppResponse(app_id=meta.app_id, status=meta.status, port=meta.port)


@api.delete("/apps/{app_id}")
def delete_app(app_id: str) -> dict:
    manager.delete_app(app_id)
    return {"deleted": True, "app_id": app_id}


app.include_router(api)


@app.api_route("/console", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def console_http_root(request: Request):
    return await proxy_http(request, upstream=f"http://127.0.0.1:{int(os.getenv('STREAMLIT_HOST_ADMIN_PORT', '8500'))}")


@app.api_route("/console/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def console_http(path: str, request: Request):
    return await proxy_http(request, upstream=f"http://127.0.0.1:{int(os.getenv('STREAMLIT_HOST_ADMIN_PORT', '8500'))}")


@app.websocket("/console/{path:path}")
async def console_ws(path: str, websocket: WebSocket):
    q = websocket.url.query
    qs = f"?{q}" if q else ""
    upstream = f"ws://127.0.0.1:{int(os.getenv('STREAMLIT_HOST_ADMIN_PORT', '8500'))}{websocket.url.path}{qs}"
    await proxy_ws(websocket, upstream)


@app.api_route("/apps/{app_id}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def app_http_root(app_id: str, request: Request):
    port = _app_port(app_id)
    return await proxy_http(request, upstream=f"http://127.0.0.1:{port}")


def _app_port(app_id: str) -> int:
    meta = manager.get_app(app_id)
    if not meta.port:
        raise HTTPException(status_code=404, detail="app port not assigned yet")
    return int(meta.port)


@app.api_route("/apps/{app_id}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def app_http(app_id: str, path: str, request: Request):
    port = _app_port(app_id)
    return await proxy_http(request, upstream=f"http://127.0.0.1:{port}")


@app.websocket("/apps/{app_id}/{path:path}")
async def app_ws(app_id: str, path: str, websocket: WebSocket):
    port = _app_port(app_id)
    q = websocket.url.query
    qs = f"?{q}" if q else ""
    upstream = f"ws://127.0.0.1:{port}{websocket.url.path}{qs}"
    await proxy_ws(websocket, upstream)


