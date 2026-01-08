## corpApps

`corpApps` 是一个面向**私有/内网部署**的 Streamlit 应用托管平台：把“管理台 / API / 业务应用”统一收敛到**单一对外端口**（默认 `8080`）。你可以在管理台上传 `app.py` + `requirements.txt` 来创建/启动/更新 Streamlit 应用，并查看运行状态与日志。

- **管理台（Streamlit）**：创建/启动/停止/编辑应用、查看日志（通过 `/console/` 访问）
- **托管应用（Streamlit）**：每个应用独立目录与 venv，自动安装依赖并运行（通过 `/apps/<app_id>/` 访问）
- **API（FastAPI）**：应用生命周期管理 + 反向代理（通过 `/api/*` 访问）
- **单端口对外**：外部只需要一个入口端口；内部端口（管理台 `8500` / 应用 `85xx`）不暴露

> **安全提醒**：该系统会执行用户上传的 Python 代码。请仅在受信任的私有环境使用，并结合容器隔离、网络策略、资源限制进一步加固。

### 访问入口（单端口）

假设对外入口为 `PUBLIC_BASE=http://<host>:<port>`：

- **控制台**：`PUBLIC_BASE/console/`
- **API**：`PUBLIC_BASE/api`
- **应用**：`PUBLIC_BASE/apps/<app_id>/`

### 快速开始（Docker，推荐）

在项目根目录执行：

```bash
docker compose up -d --build
```

打开控制台：

- `http://127.0.0.1:8080/console/`

### 快速开始（本机运行，不使用 Docker）

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m streamlit_host.run_all
```

默认数据目录：`./data`（可通过 `STREAMLIT_HOST_DATA` 修改）。

### 对外端口/域名如何配置（只改一个地方）

所有“打开链接 / 启动日志 url=... / API 返回 access_url”都以 **`STREAMLIT_HOST_PUBLIC_BASE`** 为准。

项目提供 `env.example`，推荐复制为 `.env`：

```bash
cp env.example .env
```

常用只需要改两项：

- **`HOST_PORT`**：宿主机对外端口（宿主机端口 → 容器内 `8080`）
- **`STREAMLIT_HOST_PUBLIC_BASE`**：对外基地址（域名/IP + 端口）

例如你希望对外用 `18080`：

- `HOST_PORT=18080`
- `STREAMLIT_HOST_PUBLIC_BASE=http://127.0.0.1:18080`

然后重启：

```bash
docker compose up -d --build
```

### 使用流程（管理台，推荐）

![操作流程](assets/image1.png)

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

![日志展示](assets/image.png)

5) **编辑并重启**

- 在详情页上传新的 `app.py`/`requirements.txt` 或修改应用名
- 保存后会自动重启（后台重新安装依赖并拉起进程）

### API（简要）

所有 API 都在 `/api` 前缀下：

- **`GET /api/apps`**：列出应用
- **`POST /api/apps`**：创建应用（`multipart/form-data`，字段：`name`、`requirements`、`app`）
- **`GET /api/apps/{app_id}`**：查询应用状态
- **`PATCH /api/apps/{app_id}`**：修改应用（可选字段：`name`/`requirements`/`app`，保存后自动重启）
- **`POST /api/apps/{app_id}/start`**：启动
- **`POST /api/apps/{app_id}/stop`**：停止
- **`GET /api/apps/{app_id}/logs?tail=200`**：查看日志尾部
- **`DELETE /api/apps/{app_id}`**：删除

创建应用示例（使用仓库自带 `demo_app`）：

```bash
curl -sS -X POST "http://localhost:8080/api/apps" \
  -F "name=demo" \
  -F "requirements=@demo_app/requirements.txt" \
  -F "app=@demo_app/app.py"
```

### 目录结构（核心）

- **`streamlit_host/`**：平台服务本体（FastAPI 入口 + 管理台 + 反代 + app 管理）
- **`demo_app/`**：用于验证托管链路的示例 Streamlit 应用
- **`data/`**：运行期数据目录（应用文件、venv、日志、元信息等；Docker 默认挂载到 `/data`）
- **`assets/`**：README 截图

### 数据落盘格式

默认在 `./data/apps/<app_id>/`：

- `app.py`
- `requirements.txt`
- `venv/`：每个应用独立虚拟环境
- `run.log`：安装/启动/停止日志
- `meta.json`：状态、端口、pid、name、错误信息等

### 常见问题（FAQ / Troubleshooting）

- **控制台打开是空白或资源加载失败**
  - 检查你访问的是否为 `PUBLIC_BASE/console/`（末尾带 `/` 更稳）
  - 若在反代/域名下部署，务必设置 `STREAMLIT_HOST_PUBLIC_BASE` 为最终外部访问地址（含 https/域名/端口）

- **应用创建后一直是 starting / failed**
  - 进入应用详情查看 `run.log`，通常是依赖安装失败或端口不可用
  - 确认宿主机/容器内允许创建 venv（`data/apps/<id>/venv`）并且磁盘空间足够

- **端口范围冲突**
  - 可通过 `STREAMLIT_HOST_PORT_MIN` / `STREAMLIT_HOST_PORT_MAX` 调整应用端口池（默认 `8501-8999`）

### License

如需对外发布，请在此处补充许可证信息（例如 MIT/Apache-2.0）以及公司内部使用约束。

