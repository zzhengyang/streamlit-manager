from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from typing import Optional


def _env(name: str, default: str) -> str:
    v = os.getenv(name)
    return v if v is not None and v != "" else default


def _popen(cmd: list[str]) -> subprocess.Popen:
    return subprocess.Popen(cmd, stdout=sys.stdout, stderr=sys.stderr, text=True)


def main() -> int:
    api_host = _env("STREAMLIT_HOST_API_BIND", "0.0.0.0")
    api_port = int(_env("STREAMLIT_HOST_API_PORT", "8080"))
    admin_host = _env("STREAMLIT_HOST_ADMIN_BIND", "0.0.0.0")
    admin_port = int(_env("STREAMLIT_HOST_ADMIN_PORT", "8500"))

    # 启动 API
    api_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "streamlit_host.main:app",
        "--host",
        api_host,
        "--port",
        str(api_port),
    ]
    api_proc = _popen(api_cmd)

    # 启动管理台（Streamlit）
    # 注意：Streamlit 自身会处理静态资源等，建议单独端口（默认 8500）
    admin_cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        os.path.join(os.path.dirname(__file__), "admin_ui.py"),
        "--server.address",
        admin_host,
        "--server.port",
        str(admin_port),
        "--server.baseUrlPath",
        "console",
        "--server.headless",
        "true",
        "--server.enableCORS",
        "false",
        "--server.enableXsrfProtection",
        "false",
        "--browser.gatherUsageStats",
        "false",
    ]
    admin_proc = _popen(admin_cmd)

    procs = [api_proc, admin_proc]

    def _terminate(sig: int, _frame: Optional[object] = None) -> None:
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        # 给一点时间优雅退出
        deadline = time.time() + 5
        for p in procs:
            try:
                while time.time() < deadline and p.poll() is None:
                    time.sleep(0.1)
            except Exception:
                pass
        for p in procs:
            if p.poll() is None:
                try:
                    p.kill()
                except Exception:
                    pass

    signal.signal(signal.SIGTERM, _terminate)
    signal.signal(signal.SIGINT, _terminate)

    # 任一进程退出则整体退出
    while True:
        for p in procs:
            code = p.poll()
            if code is not None:
                _terminate(signal.SIGTERM)
                return int(code)
        time.sleep(0.5)


if __name__ == "__main__":
    raise SystemExit(main())


