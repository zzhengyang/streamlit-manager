from __future__ import annotations

import os
from datetime import datetime
import html as _html
from typing import Any, Optional
from urllib.parse import urlparse

import requests
import streamlit as st
import streamlit.components.v1 as components
try:
    from streamlit_autorefresh import st_autorefresh
except Exception:  # 依赖未安装时降级为手动刷新
    st_autorefresh = None


def _default_api_base() -> str:
    return os.getenv("STREAMLIT_HOST_API_URL", "http://localhost:8080/api").rstrip("/")


def _guess_public_host_from_api(api_base: str) -> str:
    """
    用于拼接 http://<host>:<port> 访问链接（尽量友好显示）。
    若在容器里，通过 STREAMLIT_HOST_PUBLIC_HOST 显式指定更稳。
    """
    explicit = os.getenv("STREAMLIT_HOST_PUBLIC_HOST")
    if explicit:
        return explicit
    p = urlparse(api_base)
    return p.hostname or "localhost"


def _http(method: str, url: str, **kwargs) -> requests.Response:
    timeout = kwargs.pop("timeout", 30)
    return requests.request(method, url, timeout=timeout, **kwargs)


def _fmt_ts(ts: Any) -> str:
    if not ts:
        return ""
    try:
        # API 返回是 ISO8601
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


st.set_page_config(page_title="Streamlit 托管管理台", layout="wide")
st.title("Streamlit 托管管理台")

with st.sidebar:
    st.subheader("连接设置")
    api_base = st.text_input("API Base URL", value=_default_api_base(), help="例如 http://127.0.0.1:8080")
    public_host = st.text_input(
        "对外访问 Host（用于生成应用访问链接）",
        value=_guess_public_host_from_api(api_base),
        help="如在容器/内网环境建议显式填域名或 IP",
    )
    public_port = st.number_input("对外访问端口", min_value=1, max_value=65535, value=8080, step=1)
    st.divider()
    if st.button("刷新列表", use_container_width=True):
        st.session_state.pop("apps_cache", None)


def fetch_apps() -> list[dict[str, Any]]:
    if "apps_cache" in st.session_state:
        return st.session_state["apps_cache"]
    r = _http("GET", f"{api_base}/apps")
    r.raise_for_status()
    apps = r.json()
    st.session_state["apps_cache"] = apps
    return apps


st.subheader("创建应用（提交应用名 + 上传文件）")
with st.form("create_app_form", clear_on_submit=False):
    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        name = st.text_input("应用名", value="", placeholder="例如：销售看板")
    with c2:
        req = st.file_uploader("requirements.txt", type=["txt"], key="req")
    with c3:
        app_py = st.file_uploader("app.py", type=["py"], key="app")

    # 注意：st.form 内的控件交互不会触发 rerun，submit_button 的 disabled 状态不会动态更新，
    # 会导致按钮一直灰。这里保持按钮可点击，提交后再做校验与提示。
    submitted = st.form_submit_button("创建并启动", type="primary")

if submitted:
    if not name.strip():
        st.error("请先填写应用名")
        st.stop()
    if req is None or app_py is None:
        st.error("请同时上传 requirements.txt 与 app.py")
        st.stop()
    files = {
        "requirements": ("requirements.txt", req.getvalue(), "text/plain"),
        "app": ("app.py", app_py.getvalue(), "text/x-python"),
    }
    data = {"name": name.strip()}
    try:
        r = _http("POST", f"{api_base}/apps", data=data, files=files, timeout=120)
        r.raise_for_status()
        resp = r.json()
        st.success(f"已创建：{resp.get('name') or ''} ({resp.get('app_id')})")
        app_id = resp.get("app_id")
        url = f"http://{public_host}:{int(public_port)}/apps/{app_id}/" if app_id else None
        st.markdown(f"**访问地址**：`{url}`" if url else "**访问地址**：创建成功但 app_id 缺失")
        st.session_state["last_created_app_id"] = resp.get("app_id")
        st.session_state.pop("apps_cache", None)
    except Exception as e:
        st.error(f"创建失败：{e}")

st.divider()
st.subheader("应用列表（含状态）")
try:
    apps = fetch_apps()
except Exception as e:
    st.error(f"无法获取应用列表：{e}")
    st.stop()

rows: list[dict[str, Any]] = []
for a in apps:
    rows.append(
        {
            "app_id": a.get("app_id"),
            "name": a.get("name") or "",
            "status": a.get("status"),
            "port": a.get("port"),
            "pid": a.get("pid"),
            "created_at": _fmt_ts(a.get("created_at")),
            "updated_at": _fmt_ts(a.get("updated_at")),
        }
    )

def _status_badge(status: str | None) -> str:
    s = (status or "").lower()
    if s == "running":
        return "🟢 running"
    if s == "starting":
        return "🟡 starting"
    if s == "stopped":
        return "⚪ stopped"
    if s == "failed":
        return "🔴 failed"
    if s == "created":
        return "⚫ created"
    return status or ""

rows_badged: list[dict[str, Any]] = []
for r in rows:
    rr = dict(r)
    rr["status"] = _status_badge(str(r.get("status")) if r.get("status") is not None else None)
    rows_badged.append(rr)

st.dataframe(rows_badged, use_container_width=True, hide_index=True)

if not apps:
    st.info("暂无应用。")
    st.stop()

# 选择应用（默认优先选择刚创建的）
options = {a["app_id"]: a for a in apps}
default_id: str = (
    st.session_state.get("last_created_app_id")
    or st.session_state.get("selected_app_id")
    or apps[0]["app_id"]
)
if default_id not in options:
    default_id = apps[0]["app_id"]

label_map: dict[str, str] = {}
for a in apps:
    aid = a["app_id"]
    nm = a.get("name") or aid
    stt = a.get("status") or ""
    label_map[aid] = f"{nm}  [{stt}]  ({aid})"

selected_app_id = st.selectbox(
    "选择要管理的应用",
    options=list(label_map.keys()),
    index=list(label_map.keys()).index(default_id),
    format_func=lambda x: label_map.get(x, x),
)
st.session_state["selected_app_id"] = selected_app_id

left, right = st.columns([1, 2], gap="large")

with left:
    a = options[selected_app_id]
    st.caption("概要")
    st.write(
        {
            "name": a.get("name"),
            "status": a.get("status"),
            "port": a.get("port"),
            "pid": a.get("pid"),
            "created_at": _fmt_ts(a.get("created_at")),
            "updated_at": _fmt_ts(a.get("updated_at")),
        }
    )

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("停止", use_container_width=True):
            try:
                r = _http("POST", f"{api_base}/apps/{selected_app_id}/stop")
                r.raise_for_status()
                st.success(f"已停止：{a.get('name') or selected_app_id}")
                st.session_state.pop("apps_cache", None)
            except Exception as e:
                st.error(f"停止失败：{e}")
    with col_b:
        if st.button("删除", use_container_width=True, type="secondary"):
            try:
                r = _http("DELETE", f"{api_base}/apps/{selected_app_id}")
                r.raise_for_status()
                st.success(f"已删除：{a.get('name') or selected_app_id}")
                st.session_state.pop("apps_cache", None)
                st.session_state.pop("selected_app_id", None)
                st.rerun()
            except Exception as e:
                st.error(f"删除失败：{e}")

    # 启动按钮（停止后可再启动）
    if st.button("启动", use_container_width=True, type="primary"):
        try:
            r = _http("POST", f"{api_base}/apps/{selected_app_id}/start")
            r.raise_for_status()
            st.success(f"已启动：{a.get('name') or selected_app_id}")
            st.session_state.pop("apps_cache", None)
        except Exception as e:
            st.error(f"启动失败：{e}")

    with st.expander("修改应用（保存后自动重启）", expanded=False):
        st.session_state["show_details"] = True
        new_name = st.text_input("应用名", value=a.get("name") or "", key=f"edit_name_{selected_app_id}")
        c1, c2 = st.columns(2)
        with c1:
            new_req = st.file_uploader(
                "替换 requirements.txt（可选）",
                type=["txt"],
                key=f"edit_req_{selected_app_id}",
            )
        with c2:
            new_app = st.file_uploader(
                "替换 app.py（可选）",
                type=["py"],
                key=f"edit_app_{selected_app_id}",
            )

        if st.button("保存并重启", type="primary", use_container_width=True):
            data = {"name": new_name.strip()} if new_name.strip() else {}
            files = {}
            if new_req is not None:
                files["requirements"] = ("requirements.txt", new_req.getvalue(), "text/plain")
            if new_app is not None:
                files["app"] = ("app.py", new_app.getvalue(), "text/x-python")
            try:
                r = _http("PATCH", f"{api_base}/apps/{selected_app_id}", data=data, files=files or None, timeout=180)
                r.raise_for_status()
                meta = r.json()
                st.success("已提交修改并重启（后台安装依赖中）")
                app_id = meta.get("app_id")
                if app_id:
                    url = f"http://{public_host}:{int(public_port)}/apps/{app_id}/"
                    st.markdown(f"**新访问地址**：`{url}`")
                st.session_state.pop("apps_cache", None)
            except Exception as e:
                st.error(f"修改失败：{e}")

with right:
    # 只有“编辑”场景才展示详情
    if not st.session_state.get("show_details"):
        st.info("点击左侧“修改应用（保存后自动重启）”后，这里才会展示应用详情与日志。")
        st.stop()

    st.subheader("详情 / 日志")
    try:
        r = _http("GET", f"{api_base}/apps/{selected_app_id}")
        r.raise_for_status()
        meta = r.json()
    except Exception as e:
        st.error(f"无法获取详情：{e}")
        st.stop()

    status = meta.get("status")
    if meta.get("app_id") and status in ("running", "starting", "stopped", "failed", "created"):
        url = f"http://{public_host}:{int(public_port)}/apps/{meta.get('app_id')}/"
        st.markdown(f"**访问地址**：`{url}`")

    if meta.get("error"):
        st.error(f"错误：{meta.get('error')}")

    with st.expander("meta.json", expanded=False):
        st.json(meta)

    st.caption("日志")
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        tail = st.number_input("尾部行数", min_value=50, max_value=5000, value=300, step=50)
    with c2:
        auto = st.checkbox("自动刷新", value=True)
    with c3:
        interval = st.number_input("刷新间隔(秒)", min_value=1, max_value=60, value=2, step=1)

    if auto and st_autorefresh is not None:
        st_autorefresh(interval=int(interval) * 1000, key=f"logs_autorefresh_{selected_app_id}")
    elif auto and st_autorefresh is None:
        st.info("未安装自动刷新组件（streamlit-autorefresh），请先安装依赖或使用手动刷新。")

    try:
        r = _http("GET", f"{api_base}/apps/{selected_app_id}/logs", params={"tail": int(tail)}, timeout=30)
        r.raise_for_status()
        logs = r.json().get("logs", "")
    except Exception as e:
        logs = f"获取日志失败：{e}"

    # 固定高度，可滚动；每次刷新后自动滚动到最底部
    def _render_logs_autoscroll(text: str, height_px: int = 420) -> None:
        safe = _html.escape(text or "(暂无日志)")
        # 用 app_id 做容器 id，避免页面上多个组件冲突
        dom_id = f"logbox-{selected_app_id}"
        components.html(
            f"""
            <div id="{dom_id}" style="
                height: {height_px}px;
                overflow-y: auto;
                border: 1px solid rgba(49, 51, 63, 0.2);
                border-radius: 6px;
                padding: 12px;
                background: rgba(240, 242, 246, 0.6);
                font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
                font-size: 12px;
                white-space: pre;
            ">{safe}</div>
            <script>
              (function() {{
                const el = document.getElementById("{dom_id}");
                if (el) {{
                  el.scrollTop = el.scrollHeight;
                }}
              }})();
            </script>
            """,
            height=height_px + 30,
        )

    _render_logs_autoscroll(logs)


