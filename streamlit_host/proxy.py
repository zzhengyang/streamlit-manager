from __future__ import annotations

import asyncio
from typing import Iterable

import httpx
from fastapi import Request, WebSocket
from starlette.responses import PlainTextResponse, Response
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
    # 反代时 Host 由 httpx 基于 URL 生成；若同时透传原始 host 会触发重复 Host 头（h11/httpcore 直接报错）
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


def _rewrite_location(location: str, upstream_base: str, public_base: str) -> str:
    """
    把上游返回的绝对 Location（可能带内部端口，如 8500/85xx）重写成 public_base（通常是 8080）。
    """
    try:
        up = httpx.URL(upstream_base)
        pub = httpx.URL(public_base)
        loc = httpx.URL(location)
        if loc.scheme and loc.host and loc.host == up.host and loc.port == up.port:
            loc = loc.copy_with(scheme=pub.scheme, host=pub.host, port=pub.port)
            return str(loc)
    except Exception:
        pass
    return location


def _select_ws_forward_headers(headers: dict[str, str]) -> list[tuple[str, str]]:
    """
    WebSocket 反代时不要透传客户端握手头（Sec-WebSocket-* 等），否则容易导致上游握手失败。
    通常只需要透传 cookie / authorization 等鉴权上下文。
    """
    out: list[tuple[str, str]] = []
    for k, v in headers.items():
        kl = k.lower()
        if kl in ("cookie", "authorization"):
            out.append((k, v))
    return out


async def proxy_http(request: Request, upstream: str) -> Response:
    """
    反向代理 HTTP：把当前 Request 原样转发到 upstream（含 path/query），并返回响应。
    upstream 形如: http://127.0.0.1:8500
    """
    url = httpx.URL(upstream).join(request.url.path)
    if request.url.query:
        url = url.copy_with(query=request.url.query.encode("utf-8"))

    async with httpx.AsyncClient(follow_redirects=False, timeout=httpx.Timeout(30.0, read=30.0)) as client:
        try:
            req_headers = _filter_headers(request.scope.get("headers", []))
            # 关键：把外部 Host / X-Forwarded-* 传给上游，让 Streamlit 生成正确的资源/WS 地址
            external_host = request.headers.get("host")
            if external_host:
                # 防御：避免意外残留 host 导致重复
                req_headers.pop("host", None)
                req_headers.pop("Host", None)
                req_headers["Host"] = external_host
                req_headers["X-Forwarded-Host"] = external_host
                if ":" in external_host:
                    req_headers["X-Forwarded-Port"] = external_host.split(":", 1)[1]
            req_headers["X-Forwarded-Proto"] = request.url.scheme
            # 避免压缩带来的 Content-Encoding/解压不一致问题
            req_headers["Accept-Encoding"] = "identity"

            body = await request.body()
            upstream_resp = await client.request(
                method=request.method,
                url=url,
                headers=req_headers,
                content=body,
            )
        except httpx.ReadError as e:
            return PlainTextResponse(f"upstream read error: {e}", status_code=502)
        except httpx.ConnectError as e:
            return PlainTextResponse(f"upstream connect error: {e}", status_code=502)

        # httpx 会自动解压 gzip/br，但 header 可能仍带 Content-Encoding；透传会导致浏览器二次解压 → 白屏
        resp_headers = {
            k: v
            for k, v in upstream_resp.headers.items()
            if k.lower() not in HOP_BY_HOP_HEADERS and k.lower() not in ("content-encoding",)
        }

        # 避免浏览器跟随跳转到内部端口
        for k in list(resp_headers.keys()):
            if k.lower() == "location":
                resp_headers[k] = _rewrite_location(
                    resp_headers[k],
                    upstream_base=upstream,
                    public_base=str(request.base_url).rstrip("/"),
                )
        return Response(content=upstream_resp.content, status_code=upstream_resp.status_code, headers=resp_headers)


async def proxy_ws(websocket: WebSocket, upstream_ws_url: str) -> None:
    """
    反向代理 WebSocket：客户端 <-> 上游 ws 双向转发。
    upstream_ws_url 形如: ws://127.0.0.1:8500/console/_stcore/stream?xxx
    """
    # 只透传必要上下文（避免把 Sec-WebSocket-* 握手头带给上游）
    headers = _filter_headers(websocket.scope.get("headers", []))
    extra_headers = _select_ws_forward_headers(headers)

    # 透传浏览器的 origin / subprotocol（Streamlit 前端会用 subprotocol；若代理端未 accept 该 subprotocol，浏览器会立刻断开）
    h_lower = {k.lower(): v for k, v in headers.items()}
    origin = h_lower.get("origin")
    subp = h_lower.get("sec-websocket-protocol")
    offered_subprotocols = [s.strip() for s in subp.split(",")] if subp else []

    async with websockets.connect(
        upstream_ws_url,
        extra_headers=extra_headers,
        origin=origin,
        subprotocols=offered_subprotocols or None,
        ping_interval=None,
    ) as upstream:
        chosen = upstream.subprotocol
        # 先 accept 客户端，并返回与上游一致的 subprotocol，避免浏览器握手后秒断
        if chosen and chosen in offered_subprotocols:
            await websocket.accept(subprotocol=chosen)
        else:
            await websocket.accept()

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

