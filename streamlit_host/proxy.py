from __future__ import annotations

import asyncio
from typing import Iterable

import httpx
from fastapi import Request, WebSocket
from starlette.background import BackgroundTask
from starlette.responses import Response, StreamingResponse
from starlette.websockets import WebSocketDisconnect
import websockets


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


def _filter_headers(headers: Iterable[tuple[bytes, bytes]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in headers:
        ks = k.decode("latin-1").lower()
        if ks in HOP_BY_HOP_HEADERS:
            continue
        out[k.decode("latin-1")] = v.decode("latin-1")
    return out


async def proxy_http(request: Request, upstream: str) -> Response:
    """
    反向代理 HTTP：把当前 Request 原样转发到 upstream（含 path/query），并流式返回响应。
    upstream 形如: http://127.0.0.1:8500
    """
    url = httpx.URL(upstream).join(request.url.path)
    if request.url.query:
        url = url.copy_with(query=request.url.query.encode("utf-8"))

    async with httpx.AsyncClient(follow_redirects=False, timeout=None) as client:
        req_headers = _filter_headers(request.scope.get("headers", []))
        body = await request.body()
        upstream_req = client.build_request(
            method=request.method,
            url=url,
            headers=req_headers,
            content=body,
        )
        upstream_resp = await client.send(upstream_req, stream=True)

        resp_headers = {
            k: v for k, v in upstream_resp.headers.items() if k.lower() not in HOP_BY_HOP_HEADERS
        }

        async def _aiter():
            async for chunk in upstream_resp.aiter_bytes():
                yield chunk

        return StreamingResponse(
            _aiter(),
            status_code=upstream_resp.status_code,
            headers=resp_headers,
            background=BackgroundTask(upstream_resp.aclose),
        )


async def proxy_ws(websocket: WebSocket, upstream_ws_url: str) -> None:
    """
    反向代理 WebSocket：客户端 <-> 上游 ws 双向转发。
    upstream_ws_url 形如: ws://127.0.0.1:8500/console/_stcore/stream?xxx
    """
    await websocket.accept()

    # 过滤一下 header，避免带上 host 等
    headers = _filter_headers(websocket.scope.get("headers", []))

    async with websockets.connect(upstream_ws_url, extra_headers=headers) as upstream:
        async def _client_to_upstream():
            try:
                while True:
                    msg = await websocket.receive()
                    if msg.get("type") == "websocket.disconnect":
                        break
                    if "text" in msg and msg["text"] is not None:
                        await upstream.send(msg["text"])
                    elif "bytes" in msg and msg["bytes"] is not None:
                        await upstream.send(msg["bytes"])
            except WebSocketDisconnect:
                pass
            except Exception:
                pass

        async def _upstream_to_client():
            try:
                async for m in upstream:
                    if isinstance(m, (bytes, bytearray)):
                        await websocket.send_bytes(bytes(m))
                    else:
                        await websocket.send_text(str(m))
            except Exception:
                pass

        t1 = asyncio.create_task(_client_to_upstream())
        t2 = asyncio.create_task(_upstream_to_client())
        done, pending = await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()

