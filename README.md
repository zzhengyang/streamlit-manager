## Streamlit 私有托管服务（单端口 8080/自定义端口）

在私有环境部署一个“Streamlit 托管平台”：

- **控制台（Streamlit）**：创建/启动/停止/编辑应用、查看日志
- **托管应用（Streamlit）**：每个应用独立目录与 venv，自动安装依赖并运行
- **单端口暴露**：对外只暴露一个端口（默认 `8080`），通过路径区分控制台/API/应用

> 安全提醒：该系统会执行用户上传的 Python 代码。请仅在受信任的私有环境使用，并结合容器隔离、网络策略、资源限制进一步加固。

## 访问入口（单端口）

假设对外入口为 `PUBLIC_BASE=http://<host>:<port>`：

- **控制台**：`PUBLIC_BASE/console/`
- **API**：`PUBLIC_BASE/api`
- **应用**：`PUBLIC_BASE/apps/<app_id>/`

## 快速开始（Docker，推荐）

在项目根目录执行：

```bash
docker compose up -d --build
```

打开控制台：

- `http://127.0.0.1:8080/console/`

## 对外端口/域名如何配置（只改一个地方）

所有“打开链接 / 启动日志 url=... / API 返回 access_url”都以 **`STREAMLIT_HOST_PUBLIC_BASE`** 为准。

### 推荐做法：使用 `.env`

项目提供 `env.example`，你可以复制为 `.env`：

```bash
cp env.example .env
```

然后只需要改两项：

- `HOST_PORT`: 对外暴露端口（宿主机端口 → 容器内 8080）
- `STREAMLIT_HOST_PUBLIC_BASE`: 对外基地址（包含端口）

例如你希望对外用 `18080`：

- `HOST_PORT=18080`
- `STREAMLIT_HOST_PUBLIC_BASE=http://127.0.0.1:18080`

然后重启：

```bash
docker compose up -d --build
```

## 本机运行（不使用 Docker）

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m streamlit_host.run_all
```

默认数据目录：`./data`（可通过 `STREAMLIT_HOST_DATA` 修改）。

## 使用流程（推荐）

1) **打开控制台**

- `PUBLIC_BASE/console/`

2) **创建应用**

- 填写应用名
- 上传 `requirements.txt` 与 `app.py`
- 创建成功后控制台会给出访问地址：`PUBLIC_BASE/apps/<app_id>/`

3) **启动/停止**

- 在应用列表点击【查看】进入详情
- 使用【启动】/【停止】控制进程

4) **查看日志**

- 进入应用详情后，可查看 `run.log`（支持自动刷新与自动滚动到底部）

5) **编辑并重启**

- 在详情页上传新的 `app.py`/`requirements.txt` 或修改应用名
- 保存后会自动重启

## API（简要）

所有 API 都在 `/api` 前缀下：

- `GET /api/apps`：列出应用
- `POST /api/apps`：创建应用（`multipart/form-data`，字段：`name`、`requirements`、`app`）
- `GET /api/apps/{app_id}`：查询应用状态
- `PATCH /api/apps/{app_id}`：修改应用（可选字段：`name`/`requirements`/`app`，自动重启）
- `POST /api/apps/{app_id}/start`：启动
- `POST /api/apps/{app_id}/stop`：停止
- `GET /api/apps/{app_id}/logs?tail=200`：查看日志尾部
- `DELETE /api/apps/{app_id}`：删除

创建应用示例：

```bash
curl -sS -X POST "http://localhost:8080/api/apps" \
  -F "name=demo" \
  -F "requirements=@demo_app/requirements.txt" \
  -F "app=@demo_app/app.py"
```

## 存储位置

默认在 `./data/apps/<app_id>/`：

- `app.py`
- `requirements.txt`
- `venv/`（每个应用独立虚拟环境）
- `run.log`（安装/启动/停止日志）
- `meta.json`（状态、端口、pid、name 等）


