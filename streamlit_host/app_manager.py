from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import psutil

from .config import Settings
from .models import AppMeta, AppStatus
from .utils import is_port_free, sha256_file


class AppManager:
    """
    负责：
    - 每个应用独立目录：data/apps/<app_id>/
    - 创建 venv、pip install
    - 分配端口并启动 streamlit 子进程
    - 读写 meta.json、写入 run.log
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.apps_dir = (settings.data_dir / "apps").resolve()
        self.apps_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _app_dir(self, app_id: str) -> Path:
        return (self.apps_dir / app_id).resolve()

    def _meta_path(self, app_id: str) -> Path:
        return self._app_dir(app_id) / "meta.json"

    def _log_path(self, app_id: str) -> Path:
        return self._app_dir(app_id) / "run.log"

    def _load_meta(self, app_id: str) -> AppMeta:
        meta_path = self._meta_path(app_id)
        if not meta_path.exists():
            raise FileNotFoundError(f"app not found: {app_id}")
        return AppMeta.model_validate_json(meta_path.read_text(encoding="utf-8"))

    def _save_meta(self, meta: AppMeta) -> None:
        meta.updated_at = datetime.utcnow()
        meta_path = self._meta_path(meta.app_id)
        meta_path.write_text(meta.model_dump_json(indent=2), encoding="utf-8")

    def list_apps(self) -> list[AppMeta]:
        metas: list[AppMeta] = []
        for p in self.apps_dir.iterdir():
            if not p.is_dir():
                continue
            meta_path = p / "meta.json"
            if not meta_path.exists():
                continue
            try:
                meta = AppMeta.model_validate_json(meta_path.read_text(encoding="utf-8"))
                metas.append(self._refresh_status(meta))
            except Exception:
                continue
        metas.sort(key=lambda m: m.created_at, reverse=True)
        return metas

    def get_app(self, app_id: str) -> AppMeta:
        meta = self._load_meta(app_id)
        return self._refresh_status(meta)

    def _refresh_status(self, meta: AppMeta) -> AppMeta:
        if meta.pid:
            if psutil.pid_exists(meta.pid):
                try:
                    p = psutil.Process(meta.pid)
                    if p.is_running() and p.status() != psutil.STATUS_ZOMBIE:
                        if meta.status not in (AppStatus.running, AppStatus.starting):
                            meta.status = AppStatus.running
                            self._save_meta(meta)
                        return meta
                except Exception:
                    pass
            # pid 不存在或不可用
            if meta.status in (AppStatus.running, AppStatus.starting):
                meta.status = AppStatus.stopped
                meta.pid = None
                self._save_meta(meta)
        return meta

    def create_app(
        self,
        name: str,
        requirements_path: Path,
        app_py_path: Path,
    ) -> AppMeta:
        app_id = uuid.uuid4().hex[:16]
        app_dir = self._app_dir(app_id)
        app_dir.mkdir(parents=True, exist_ok=False)

        # 保存用户文件
        req_dst = app_dir / "requirements.txt"
        app_dst = app_dir / "app.py"
        shutil.copyfile(requirements_path, req_dst)
        shutil.copyfile(app_py_path, app_dst)

        port = self._alloc_port()
        meta = AppMeta(
            app_id=app_id,
            name=name,
            status=AppStatus.starting,
            port=port,
            requirements_sha256=sha256_file(req_dst),
            app_sha256=sha256_file(app_dst),
        )
        self._save_meta(meta)

        # 异步启动（后台线程）
        t = threading.Thread(target=self._provision_and_start, args=(app_id,), daemon=True)
        t.start()
        return meta

    def update_app(
        self,
        app_id: str,
        name: Optional[str] = None,
        requirements_path: Optional[Path] = None,
        app_py_path: Optional[Path] = None,
    ) -> AppMeta:
        """
        修改应用后自动重启：
        - 可改名
        - 可替换 requirements.txt / app.py（任意组合）
        - 会停止旧进程，重新分配端口并启动
        """
        meta = self._load_meta(app_id)

        # 先停掉旧进程
        try:
            self.stop_app(app_id)
        except Exception:
            pass

        app_dir = self._app_dir(app_id)
        req_dst = app_dir / "requirements.txt"
        app_dst = app_dir / "app.py"

        if name is not None and name.strip() != "":
            meta.name = name.strip()

        if requirements_path is not None:
            shutil.copyfile(requirements_path, req_dst)
            meta.requirements_sha256 = sha256_file(req_dst)

        if app_py_path is not None:
            shutil.copyfile(app_py_path, app_dst)
            meta.app_sha256 = sha256_file(app_dst)

        # 清理错误并重启
        meta.error = None
        meta.pid = None
        meta.status = AppStatus.starting
        meta.port = self._alloc_port()
        self._save_meta(meta)

        t = threading.Thread(target=self._provision_and_start, args=(app_id,), daemon=True)
        t.start()
        return meta

    def stop_app(self, app_id: str) -> AppMeta:
        meta = self._load_meta(app_id)
        meta = self._refresh_status(meta)
        if meta.pid:
            self._append_log(app_id, f"stopping pid={meta.pid}")
            self._kill_pid_tree(meta.pid)
            meta.pid = None
        meta.status = AppStatus.stopped
        self._save_meta(meta)
        self._append_log(app_id, "stopped")
        return meta

    def start_app(self, app_id: str) -> AppMeta:
        """
        已停止/失败的应用可再次启动：
        - 尽量复用现有 port（若空闲）
        - 否则重新分配 port
        """
        meta = self._load_meta(app_id)
        meta = self._refresh_status(meta)
        if meta.status == AppStatus.running and meta.pid:
            return meta

        meta.pid = None
        meta.error = None
        port = meta.port
        if port is None or not is_port_free(self.settings.host, int(port)):
            port = self._alloc_port()
        meta.port = int(port)
        meta.status = AppStatus.starting
        self._save_meta(meta)
        self._append_log(app_id, f"starting (manual) port={meta.port}")

        t = threading.Thread(target=self._provision_and_start, args=(app_id,), daemon=True)
        t.start()
        return meta

    def delete_app(self, app_id: str) -> None:
        try:
            self.stop_app(app_id)
        except FileNotFoundError:
            return
        shutil.rmtree(self._app_dir(app_id), ignore_errors=True)

    def tail_logs(self, app_id: str, tail: int = 200) -> str:
        log_path = self._log_path(app_id)
        if not log_path.exists():
            return ""
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-tail:])

    def _alloc_port(self) -> int:
        with self._lock:
            for port in range(self.settings.port_min, self.settings.port_max + 1):
                if is_port_free(self.settings.host, port):
                    return port
        raise RuntimeError("no free ports available")

    def _venv_paths(self, app_id: str) -> tuple[Path, Path, Path]:
        app_dir = self._app_dir(app_id)
        venv_dir = app_dir / "venv"
        if os.name == "nt":
            python_bin = venv_dir / "Scripts" / "python.exe"
            pip_bin = venv_dir / "Scripts" / "pip.exe"
        else:
            python_bin = venv_dir / "bin" / "python"
            pip_bin = venv_dir / "bin" / "pip"
        return venv_dir, python_bin, pip_bin

    def _append_log(self, app_id: str, msg: str) -> None:
        log_path = self._log_path(app_id)
        ts = datetime.utcnow().isoformat()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")

    def _run_cmd(
        self,
        app_id: str,
        cmd: list[str],
        cwd: Optional[Path] = None,
        env: Optional[dict[str, str]] = None,
        timeout: Optional[int] = None,
    ) -> None:
        self._append_log(app_id, f"$ {' '.join(cmd)}")
        p = subprocess.Popen(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        try:
            start = time.time()
            assert p.stdout is not None
            for line in p.stdout:
                self._append_log(app_id, line.rstrip("\n"))
                if timeout is not None and (time.time() - start) > timeout:
                    raise TimeoutError(f"command timeout after {timeout}s")
            code = p.wait()
            if code != 0:
                raise RuntimeError(f"command failed (exit {code}): {' '.join(cmd)}")
        finally:
            try:
                p.kill()
            except Exception:
                pass

    def _provision_and_start(self, app_id: str) -> None:
        meta = self._load_meta(app_id)
        try:
            # 如果 create/update 已经分配过端口，尽量复用；否则再分配
            port = meta.port
            if port is None or not is_port_free(self.settings.host, int(port)):
                port = self._alloc_port()
                meta.port = port
            meta.status = AppStatus.starting
            self._save_meta(meta)

            app_dir = self._app_dir(app_id)
            req_path = app_dir / "requirements.txt"
            app_path = app_dir / "app.py"

            venv_dir, python_bin, pip_bin = self._venv_paths(app_id)

            # 创建 venv
            if not venv_dir.exists():
                self._run_cmd(app_id, [os.sys.executable, "-m", "venv", str(venv_dir)], cwd=app_dir)

            # 升级 pip & 安装依赖
            self._run_cmd(app_id, [str(pip_bin), "install", "--upgrade", "pip"], cwd=app_dir, timeout=15 * 60)
            # 确保 streamlit 存在（即使用户 requirements.txt 为空）
            if not self._requirements_has_streamlit(req_path):
                self._run_cmd(app_id, [str(pip_bin), "install", "streamlit"], cwd=app_dir, timeout=20 * 60)

            if req_path.exists() and req_path.read_text(encoding="utf-8", errors="ignore").strip():
                self._run_cmd(
                    app_id,
                    [str(pip_bin), "install", "-r", str(req_path)],
                    cwd=app_dir,
                    timeout=30 * 60,
                )

            # 启动 streamlit（独立进程组，便于 stop）
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"

            cmd = [
                str(python_bin),
                "-m",
                "streamlit",
                "run",
                str(app_path),
                "--server.address",
                self.settings.host,
                "--server.port",
                str(port),
                "--server.baseUrlPath",
                f"apps/{app_id}",
                "--server.headless",
                "true",
                "--server.enableCORS",
                "false",
                "--server.enableXsrfProtection",
                "false",
            ]

            log_f = self._log_path(app_id).open("a", encoding="utf-8")
            try:
                if os.name == "nt":
                    proc = subprocess.Popen(
                        cmd,
                        cwd=str(app_dir),
                        env=env,
                        stdout=log_f,
                        stderr=subprocess.STDOUT,
                        text=True,
                    )
                else:
                    proc = subprocess.Popen(
                        cmd,
                        cwd=str(app_dir),
                        env=env,
                        stdout=log_f,
                        stderr=subprocess.STDOUT,
                        text=True,
                        preexec_fn=os.setsid,
                    )
            finally:
                # 子进程已继承 fd，父进程可关闭句柄避免泄漏
                try:
                    log_f.close()
                except Exception:
                    pass

            meta.pid = proc.pid
            meta.status = AppStatus.running
            self._save_meta(meta)
            self._append_log(app_id, f"streamlit started pid={proc.pid} port={port}")
        except Exception as e:
            meta.status = AppStatus.failed
            meta.error = str(e)
            self._save_meta(meta)
            self._append_log(app_id, f"FAILED: {e}")

    def _kill_pid_tree(self, pid: int) -> None:
        try:
            parent = psutil.Process(pid)
        except Exception:
            return
        children = parent.children(recursive=True)
        for c in children:
            try:
                c.kill()
            except Exception:
                pass
        try:
            parent.kill()
        except Exception:
            pass

        _, alive = psutil.wait_procs([parent, *children], timeout=5)
        for p in alive:
            try:
                p.kill()
            except Exception:
                pass

    def _requirements_has_streamlit(self, req_path: Path) -> bool:
        if not req_path.exists():
            return False
        try:
            txt = req_path.read_text(encoding="utf-8", errors="ignore").lower()
        except Exception:
            return False
        # 粗略判断：包含 "streamlit" 即认为用户显式指定/依赖了
        for line in txt.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith("streamlit") or " streamlit" in s or "streamlit" in s:
                return True
        return False


