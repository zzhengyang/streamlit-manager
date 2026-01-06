# Streamlit 私有托管服务（上传 requirements.txt + app.py 自动部署）

这是一个可在**私有环境**部署的 Streamlit 托管服务：

- 用户上传 `requirements.txt` 与 `app.py`
- 服务端为每个应用创建独立目录与虚拟环境（venv）
- 自动安装依赖、分配空闲端口并启动 Streamlit
- 提供查询状态、查看日志、停止/删除应用的 API

> 注意：该系统会执行用户上传的 Python 代码。请仅在**受信任的私有环境**使用，并结合容器隔离、网络策略与资源限制（cgroup/ulimit）进一步加固。

## 运行方式（本机 / 服务器）

### 1) Python 方式运行控制面

```bash
cd /Users/zhengyang/Documents/zy/streamlit-app
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m streamlit_host.run_all
```

默认数据目录：`./data`（可通过环境变量 `STREAMLIT_HOST_DATA` 修改）。

启动后：

- 管理台（Streamlit）：`http://localhost:8080/console/`
- API（FastAPI）：`http://localhost:8080/api`
- 应用访问：`http://localhost:8080/apps/<app_id>/`

## 对外端口/域名如何配置（单一入口）

单端口方案下，所有“打开链接 / 启动日志 url=... / API 返回 access_url”都以 **`STREAMLIT_HOST_PUBLIC_BASE`** 为准。

- 例如你想对外用 `18080`：把 `STREAMLIT_HOST_PUBLIC_BASE` 设为 `http://<host>:18080`
- `docker-compose.yml` 已支持用 `HOST_PORT` 改对外端口（宿主机端口映射到容器内 8080）

建议做法：

- 复制 `env.example` 为 `.env`，然后修改：
  - `HOST_PORT=18080`
  - `STREAMLIT_HOST_PUBLIC_BASE=http://127.0.0.1:18080`

### 2) Docker 方式运行（推荐私有部署）

```bash
cd /Users/zhengyang/Documents/zy/streamlit-app
docker compose up -d --build
```

控制面默认监听 `8080`，应用会占用动态端口（默认在 `8501-8999` 范围内分配）。
但在“单端口方案A”下，这些内部端口不会对外暴露，对外统一走 `8080` 反代。

## API 使用示例

### 创建应用（上传 requirements.txt + app.py）

```bash
curl -sS -X POST "http://localhost:8080/apps" \
  -F "requirements=@requirements.txt" \
  -F "app=@app.py"
```

> 注意：单端口方案下 API 路径是 `/api`，所以上面命令需要改成：
>
> `POST http://localhost:8080/api/apps`

返回示例（简化）：

```json
{
  "app_id": "a7c1e0f2b9f84a62",
  "port": 8501,
  "status": "starting"
}
```

### 查询状态

```bash
curl -sS "http://localhost:8080/apps/a7c1e0f2b9f84a62"
```

### 查看日志（默认返回尾部）

```bash
curl -sS "http://localhost:8080/apps/a7c1e0f2b9f84a62/logs?tail=200"
```

### 停止应用

```bash
curl -sS -X POST "http://localhost:8080/apps/a7c1e0f2b9f84a62/stop"
```

### 删除应用（停止并删除目录）

```bash
curl -sS -X DELETE "http://localhost:8080/apps/a7c1e0f2b9f84a62"
```

## 目录结构

- `streamlit_host/`：控制面服务代码（FastAPI + 进程管理）
- `data/apps/<app_id>/`：每个应用的隔离目录
  - `app.py`
  - `requirements.txt`
  - `venv/`
  - `run.log`
  - `meta.json`


