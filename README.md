# OpenAPI 契约智能生成 Agent

> 把散落在接口文档、curl 抓包、源码注释、SQL 建表语句里的**杂乱素材**，自动整理成可用的 **OpenAPI 3.x** 契约，并如实标注「信息缺失 / 多源冲突 / AI 推断」三类风险。

![python](https://img.shields.io/badge/python-3.10%2B-blue)
![fastapi](https://img.shields.io/badge/FastAPI-0.110%2B-009688)
![openapi](https://img.shields.io/badge/OpenAPI-3.0.3%20%7C%203.1.0-6BA539)
![license](https://img.shields.io/badge/license-MIT-green)

> **当前状态**：可用原型（MVP）。63 个单测 + 36 项端到端 HTTP 冒烟全部通过，零 Agent 框架依赖。
> 实现与 `Agent设计文档.md` 逐条对齐（包结构、类职责、接口契约、错误码、Token 策略、配置项），已知边界见文末[已知限制](#已知限制)。

---

## 这个项目解决什么问题

前后端联调时，接口契约往往不是「没有」，而是「有但不可信」：

- 真实接口信息散落在 Markdown 文档、curl 抓包记录、后端源码注释、SQL 建表语句、甚至截图里；
- 多源之间互相矛盾——同一个 `page_size`，文档写默认 10、源码注释写默认 20；
- 更麻烦的是**无法区分**「素材里真实存在的字段」和「整理者补上去的字段」。前端照文档写完代码跑不通，才发现文档本身是错的。

所以本项目的目标不是「生成一份看起来很完整的文档」，而是**生成一份附带风险标注、可以放心对照的契约**：

- 只提取素材中真实存在的接口，缺失字段**留空不脑补**；
- 多源冲突时**保留双方信息并标记**，而不是让模型自行覆盖；
- 每一处 AI 推断都单独标记出来（`risk_report` + spec 内 `x-ai-inferred`），供人工复核。

## 核心特性

| 能力 | 说明 |
|---|---|
| **支持 34 种格式输入** | 文本类 8 种、源码 16 种（按纯文本读取后交由 LLM 抽取，非语言级解析）、SQL、YAML/JSON、图片（OCR）、zip 递归解包 |
| **两阶段 LLM 抽取** | 逐块抽取 → 按 `(path, method)` 分组融合；内容一致的分组本地去重，不发多余请求 |
| **三层 Token 防护** | 全素材累计上限 → 单分片上限 → 单请求预算预校验；上游上下文超限统一归一为 `10003` |
| **可选截断/摘要** | `ENABLE_CONTEXT_TRUNCATE=True` 时，超长分片先走 LLM 摘要、失败再按 token 尾部截断；默认关闭、超限即失败 |
| **中文分组与接口名** | 抽取阶段由模型按业务语义给出中文 `summary`（如「查询文件列表」）与中文 `tag`（如「商品订单购物车」），组装器写入 `operation.summary` / `operation.tags` 并在文档根节点声明 `tags`；缺失时才回落到 `METHOD /path` 与路径首段，并记入风险报告 |
| **响应结构组装** | 由素材中的返回示例推导 `responses.200.content.schema`，产物可直接给前端做 mock；错误码一并写入 |
| **多源来源打标** | 每段素材标记 `curl` / `code` / `sql` / `markdown` / `testcase`，作为冲突仲裁的优先级依据，并写入 spec 的 `x-source` |
| **风险报告** | 显式输出三类问题：信息缺失、字段冲突、AI 推断 |
| **增量生成** | 传入 `base_openapi` 基线契约，输出 `added / modified / deleted` 变更 diff |
| **两种生成模式** | `strict`（默认，规范校验失败即任务失败）/ `fast`（不中断，校验错误写入风险报告） |
| **4 条降级路径** | 单点失败不中断产出，问题全部写进报告，而不是抛错丢掉结果 |
| **JSON 纠错重试** | 模型输出不符合结构时，把错误输出回灌并要求重新生成，而非简单重试 |
| **异步任务架构** | 提交 / 轮询状态 / 取结果 / 取消 四个端点，11 个中间状态 + 百分比进度，支持任务级超时 |
| **零 Agent 框架依赖** | 自研状态机流水线，流程显式、每层可单测 |

## 工作流程

```
素材（上传文件 / 表单文本）
  │
  ├─[material.FileParser]──── 格式分流 · zip 递归解包 · 图片 OCR
  ├─[material.MaterialPreprocessor]
  │        · 递归切块(1500 字符/150 重叠) · 来源类型打标 · 脏数据过滤
  │        · 全素材累计 token ≤ TOTAL_MATERIAL_TOKEN_LIMIT（超出 → 10003）
  │        · 单分片 token ≤ PER_CHUNK_TOKEN_LIMIT（超出 → 摘要/截断/报错）
  ▼
文本块 × N
  │
  ├─[MetaExtractor 阶段一]─ 逐块 LLM 抽取 ──────▶ RawEndpoint[]
  │                                               （失败则跳过该块，记 warning）
  ├─[MetaExtractor 阶段二]─ 按 (path, method) 分组
  │                   ├─ 内容一致 → 本地去重，不发请求
  │                   └─ 真冲突   → LLM 融合（失败则回退首份素材并标记冲突）
  ▼
ApiIntermediateMeta[]   ← 带 is_conflict / is_ai_infer / source / responses / notes
  │
  ├─[builder.OpenApiAssembler]─ 组装 OpenAPI（可由 base_spec 续写，推导 response schema）
  ├─[builder.OpenApiValidator]─ 规范校验（strict 抛错 / fast 写入风险报告）
  ├─[builder.DiffHelper]────── 基线契约增量对比（传入 base_openapi 时）
  └─[report.RiskReportBuilder] 确定性规则扫描 + LLM 风险扫描
  ▼
结果：{ openapi, diff, risk_report, input_materials }
```

## 目录结构

实现严格按 `Agent设计文档.md` 2.2.1 的包结构：

```
openapi-agent/
├── openapi_agent/
│   ├── main.py                     # FastAPI 入口：路由挂载、临时目录、异常处理器注册
│   ├── config.py                   # 系统配置：LLM 接入、Token 限额、上传限制、默认模式
│   ├── api/                        # 接入层
│   │   ├── routes.py               # 4 个端点 + 请求编排
│   │   ├── schemas.py              # 请求/响应 Pydantic 模型、错误响应模型
│   │   ├── exception_handler.py    # 全局异常捕获，错误码 → HTTP 状态映射
│   │   ├── validators.py           # 入参校验与清洗（指令长度、文件数/大小、基线契约解析）
│   │   └── service.py              # 任务管理器实例、后台执行、进度上报、超时控制
│   ├── core/                       # Agent 核心（自研工作流、状态管理）
│   │   ├── errors.py               # BusinessException 与 5 类错误码
│   │   ├── task.py                 # Task 实体与 11 个 TaskStatus
│   │   ├── task_manager.py         # 任务创建/查询/取消，task_id 生成
│   │   ├── agent_workflow.py       # 自研 Agent 主工作流（状态机编排全部业务步骤）
│   │   ├── llm_client.py           # LLM JSON 调用 + 预算预校验 + 纠错重试
│   │   ├── llm_factory.py          # 客户端装配（测试可替换）
│   │   ├── token_budget.py         # estimate / truncate / summary / 超限识别
│   │   └── prompt_templates.py     # 4 个 prompt 模板常量与变量填充
│   ├── material/                   # 素材预处理层
│   │   ├── file_parser.py          # 多格式解析（含 zip 递归、图片 OCR）
│   │   ├── splitter.py             # 递归切块
│   │   ├── preprocessor.py         # 素材统一预处理、来源打标、Token 校验
│   │   └── extractor.py            # 两阶段抽取与多源融合
│   ├── model/                      # 数据模型
│   │   ├── intermediate_meta.py    # 【核心】接口中间元数据契约
│   │   └── openapi_build_model.py  # 风险报告、diff、风险条目模型
│   ├── builder/                    # OpenAPI 构建 & 校验层
│   │   ├── openapi_assembler.py    # 元数据 → OpenAPI
│   │   ├── schema_builder.py       # 返回示例 → Schema、x-ai-inferred / x-conflict 标记
│   │   ├── validator.py            # OpenAPI 规范校验
│   │   └── diff_helper.py          # 契约增量对比
│   └── report/
│       └── risk_report_builder.py  # 三类风险报告
├── tests/                          # 56 个用例，含 Fake LLM，无需真实模型调用
├── examples/sample_接口文档.md      # 故意做「脏」的演示素材
├── scripts/
│   ├── rerun_sample.py             # 用该素材真实跑一次，覆盖下面的产物快照
│   ├── render_result.py            # 从 res.json 还原 YAML 并打印风险报告
│   ├── mock_llm_server.py          # 本地假的 OpenAI 兼容服务（无密钥也能跑通全链路）
│   └── smoke_http.py               # 端到端 HTTP 冒烟：真实起服务，跑 36 项检查
├── openapi.yaml / res.json         # 由 scripts/rerun_sample.py 生成的产物快照
├── pyproject.toml
├── .gitignore
└── LICENSE
```

## 快速开始

### 1. 环境要求

- Python >= 3.10
- 一个兼容 **OpenAI 协议**的大模型服务（官方 API 或任意兼容网关均可，模型可通过环境变量切换）

### 2. 安装

```bash
pip install -e .

# 可选：图片 OCR 支持
pip install -e ".[ocr]"

# 可选：开发/测试依赖
pip install -e ".[dev]"
```

### 3. 配置

所有配置项都可用环境变量覆盖，默认值见 `openapi_agent/config.py`。

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `OPENAPI_AGENT_BASE_URL` | — | **必填**，大模型服务地址，如 `https://api.openai.com/v1` |
| `OPENAPI_AGENT_API_KEY` | — | **必填**，API Key |
| `OPENAPI_AGENT_MODEL` | `gpt-4o-mini` | 模型名 |
| `OPENAPI_AGENT_LLM_TIMEOUT` | `60` | 单次 LLM 请求超时（秒） |
| `OPENAPI_AGENT_MODEL_MAX_CONTEXT` | `128000` | 模型最大上下文窗口 token |
| `OPENAPI_AGENT_TOTAL_MATERIAL_TOKEN_LIMIT` | `100000` | 全部素材累计 token 上限，超出 → `10003` |
| `OPENAPI_AGENT_PER_CHUNK_TOKEN_LIMIT` | `4000` | 单分片 token 触发阈值 |
| `OPENAPI_AGENT_PROMPT_RESERVE_RATIO` | `0.25` | 单请求预算中留给「输出 + 模板」的比例 |
| `OPENAPI_AGENT_ENABLE_CONTEXT_TRUNCATE` | `false` | 是否开启摘要/截断兜底；默认关闭，超限直接报错 |
| `OPENAPI_AGENT_USER_INSTRUCTION_MAX_LEN` | `1000` | 用户指令最大字符数，超出 → `10001` |
| `OPENAPI_AGENT_MAX_UPLOAD_FILES` | `10` | 单次任务最大上传文件数 |
| `OPENAPI_AGENT_MAX_FILE_SIZE_MB` | `20` | 单文件大小上限 |
| `OPENAPI_AGENT_CHUNK_SIZE` / `OPENAPI_AGENT_CHUNK_OVERLAP` | `1500` / `150` | 分片字符数与重叠 |
| `OPENAPI_AGENT_MIN_CONTENT_LEN` | `20` | 小于该长度的文本块被丢弃 |
| `OPENAPI_AGENT_ASYNC_WORKER_TIMEOUT` | `300` | 异步任务执行超时秒数 |
| `OPENAPI_AGENT_TEMP_ROOT` | 系统临时目录 | 上传素材临时目录根路径（容器部署建议挂载可写卷） |

> `openapi_agent/config.py` 内的 `Settings` 共 19 项配置，全部可用上表同名的环境变量覆盖。

Linux / macOS：

```bash
export OPENAPI_AGENT_BASE_URL="https://api.openai.com/v1"
export OPENAPI_AGENT_API_KEY="sk-xxxxxx"
export OPENAPI_AGENT_MODEL="gpt-4o-mini"
```

Windows PowerShell：

```powershell
$env:OPENAPI_AGENT_BASE_URL = "https://api.openai.com/v1"
$env:OPENAPI_AGENT_API_KEY  = "sk-xxxxxx"
$env:OPENAPI_AGENT_MODEL    = "gpt-4o-mini"
```

> 未配置 `BASE_URL` / `API_KEY` 时，任务会以错误码 `10005`（服务未知内部错误）失败，并提示缺失的配置项。

### 4. 启动服务

```bash
uvicorn openapi_agent.main:app --reload --host 127.0.0.1 --port 8000
# 或
python -m openapi_agent.main
```

- 交互式 API 文档：http://127.0.0.1:8000/docs

## API 使用

服务前缀：`/api/v1/openapi`

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/generate` | 提交生成任务，立即返回 `task_id` |
| GET | `/task/{task_id}/status` | 轮询任务状态与百分比进度 |
| GET | `/task/{task_id}/result` | 获取生成结果 |
| POST | `/task/{task_id}/cancel` | 取消任务 |

### 提交任务

`multipart/form-data` 参数：

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `files` | File[] | 空 | 素材文件，可多选，最多 10 个、单个 ≤ 20MB |
| `text_materials` | string[] | 空 | 直接粘贴的文本素材，可多段（`texts` 为兼容别名） |
| `base_openapi` | string | `""` | 基准 OpenAPI 文档（JSON 或 YAML 字符串），用于增量生成与 diff |
| `user_instruction` | string | `""` | 用户指令，如「过滤内部调试接口」，最长 1000 字符 |
| `generate_mode` | string | `strict` | `strict` / `fast` |
| `output_format` | string | `yaml` | `yaml` / `json` |
| `openapi_version` | string | `3.0.3` | `3.0.3` / `3.1.0` |
| `title` | string | `Generated API` | 契约文档标题 |
| `version` | string | `1.0.0` | 契约文档版本 |

`files` 与 `text_materials` 至少提供一个，否则返回 `10001`。

```bash
# 提交文本素材
curl -X POST http://127.0.0.1:8000/api/v1/openapi/generate \
  -F 'text_materials=获取用户列表接口：GET /users，查询参数 page 为整数，分页返回用户数据。' \
  -F 'user_instruction=过滤内部调试接口' \
  -F 'generate_mode=strict' \
  -F 'output_format=yaml' \
  -F 'title=商城系统 API' \
  -F 'version=1.0.0'

# 提交文件素材（可多个 -F files=...）
curl -X POST http://127.0.0.1:8000/api/v1/openapi/generate \
  -F 'files=@examples/sample_接口文档.md' \
  -F 'files=@docs/order-api.zip' \
  -F 'output_format=json'

# 增量生成：带上基线契约
curl -X POST http://127.0.0.1:8000/api/v1/openapi/generate \
  -F 'files=@docs/new-requirements.md' \
  -F 'base_openapi=@openapi.yaml'
```

响应：

```json
{
  "task_id": "task-8a2f4412-b71e-4c0d-9f31-abc123456789",
  "status": "pending",
  "msg": "任务已提交，开始解析素材"
}
```

### 轮询状态

```bash
curl http://127.0.0.1:8000/api/v1/openapi/task/<task_id>/status
```

```json
{
  "task_id": "task-8a2f4412-b71e-4c0d-9f31-abc123456789",
  "status": "completed",
  "progress": 100,
  "error_info": null
}
```

`status` 取值：`pending` / `preprocessing` / `chunking` / `extracting` / `merging` / `assembling` / `validating` / `diffing` / `completed` / `failed` / `cancelled`。
`progress` 为 0–100 的整数，随状态推进更新（`pending=0 → preprocessing=10 → extracting=40 → merging=60 → assembling=75 → completed=100`）。

### 获取结果

```bash
curl http://127.0.0.1:8000/api/v1/openapi/task/<task_id>/result
```

```json
{
  "task_id": "task-...",
  "status": "completed",
  "openapi": "openapi: 3.0.3\ninfo:\n  title: Generated API\n...",
  "diff": null,
  "risk_report": {
    "conflict_items": [],
    "ai_infer_items": [],
    "missing_info": []
  }
}
```

`openapi` 字段是**字符串**（YAML 或 JSON），需自行解析。任务失败时该接口返回 `10002`；任务尚未完成时返回 `10001`。
传入 `base_openapi` 时 `diff` 为 `{ "added": [...], "modified": {...}, "deleted": [...] }`。

### 取消任务

```bash
curl -X POST http://127.0.0.1:8000/api/v1/openapi/task/<task_id>/cancel
```

```json
{ "task_id": "task-...", "status": "cancelled" }
```

### 错误码

| code | HTTP | 含义 |
|---|---|---|
| `10001` | 400 | 输入参数错误（空素材、枚举非法、指令过长、文件过多） |
| `10002` | 404 | `task_id` 不存在 / 任务无可用结果 / 任务不可取消 |
| `10003` | 422 | 素材解析错误或大小异常（含单文件超限、Token 超限、上下文超限） |
| `10004` | 503 | 大模型服务调用失败或超时 |
| `10005` | 500 | 服务未知内部错误（含规范校验失败） |

错误响应体统一为 `{code, msg, detail}`：

```json
{ "code": 10003, "msg": "素材总量超出 token 上限", "detail": "累计约 120000 token，超出 TOTAL_MATERIAL_TOKEN_LIMIT=100000；请精简素材或调高上限" }
```

## 输出示例

以 `examples/sample_接口文档.md` 为输入（该素材**故意**混合了文档表格、curl 抓包、源码注释，并预埋了字段冲突、默认值不一致和一个需过滤的内部调试接口），一次真实运行的产物如下。

该快照可用下面这条命令一键复现（需要真实模型调用，会覆盖根目录的 `res.json` 与 `openapi.yaml`）：

```bash
python scripts/rerun_sample.py
```

> ⚠️ **产物快照待刷新**：仓库内现有的 `openapi.yaml` / `res.json` 是重构（`app/` → `openapi_agent/`、响应结构组装、`x-source` 标注）之前生成的，
> 结构与上面的示例仍有差异。带模型凭据执行一次 `scripts/rerun_sample.py` 即可覆盖为最新产物。

生成的契约（节选）：

```yaml
openapi: 3.0.3
info:
  title: Generated API
  version: 1.0.0
paths:
  /api/v1/orders:
    post:
      summary: 创建订单
      operationId: post_api_v1_orders
      x-source: markdown,curl
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                type: object
                properties:
                  order_id:
                    type: string
                  status:
                    type: string
      requestBody:
        required: false
        content:
          application/json:
            schema:
              type: object
              properties:
                sku_id:
                  type: string
                  description: 商品 SKU 编号
                quantity:
                  type: integer
                  description: 购买数量，最小为 1
                coupon_code:
                  type: string
                  description: 优惠券码；线上环境传空字符串即可，服务端会自动忽略
                client_tag:
                  type: string
                  description: curl样例字段，文档未列出
```

配套的风险报告（真实输出，有删减）：

```json
{
  "conflict_items": [
    { "path": "/api/v1/orders", "method": "POST", "notes": ["client_tag 仅出现在 curl 样例中，文档字段表未包含"] }
  ],
  "ai_infer_items": [
    { "path": "/api/v1/orders", "method": "POST", "notes": ["client_tag 被标注为 AI推断/curl样例字段，需确认是否正式字段"] }
  ],
  "missing_info": [
    { "path": "/api/v1/products", "method": "GET", "issue": "缺少响应结构定义和错误码" },
    { "scope": "global", "issue": "所有接口均未提取到响应结构与错误码定义" }
  ]
}
```

可以看到，预埋的三类问题全部被命中——这正是本项目要提供的价值：**不只给契约，还给「这份契约哪里不可信」**。

## 支持的文件格式

| 类别 | 扩展名 |
|---|---|
| 文本 | `.md` `.markdown` `.txt` `.rst` `.csv` `.log` `.curl` `.http` |
| 源码 | `.py` `.java` `.go` `.js` `.ts` `.jsx` `.tsx` `.php` `.rb` `.rs` `.c` `.cpp` `.cs` `.kt` `.swift` `.vue` |
| SQL | `.sql` |
| 规范 | `.yaml` `.yml` `.json` |
| 图片 | `.png` `.jpg` `.jpeg` `.bmp` `.webp`（需 `pip install -e ".[ocr]"`） |
| 压缩包 | `.zip`（递归解包，自动跳过包内非文本文件） |

共 34 种。单个素材解析失败会被记录 warning 并**跳过**，只有全部素材都无效时才返回 `10003`。文本块小于 20 字符会被丢弃。

> 源码类文件只做「按纯文本读取 → 交给 LLM 抽取」，不做 AST / 框架级解析，因此新增语言只需往 `CODE_EXTS` 里加扩展名。
> OCR 链路基于 PaddleOCR 2.x 的 API，3.x 已移除相关参数，故依赖锁在 `<3.0`；该链路目前**未被单测覆盖**。

## 可靠性设计

LLM 的输出天然不确定，因此流水线的设计原则是：**产出永远给，问题全部显式标注。**

| 失败点 | 降级行为 |
|---|---|
| 单个文本块抽取失败 | 跳过该块，继续处理其余块（记 warning） |
| 多源融合调用失败 | 回退使用第一份素材内容，强制 `is_conflict = true`，note 提示人工复核 |
| 风险 LLM 扫描失败 | 丢弃 LLM 结果，只保留确定性规则扫描结果 |
| 分片超限且开启截断 | 先尝试 LLM 摘要；摘要也放不下时按 token 尾部截断，记入 `risk_report.preprocess_warnings` |
| `generate_mode=fast` 且规范校验失败 | **不丢弃文档**，把校验错误追加进 `risk_report.validation_errors` |
| `generate_mode=strict` 且规范校验失败 | 任务失败，返回 `10005`，不产出残缺契约 |

## 测试

```bash
python -m pytest -q
# 63 passed
```

测试分布：

| 测试文件 | 覆盖内容 |
|---|---|
| `tests/test_core.py` | 错误码、任务模型与进度默认值、task_id 格式、任务生命周期与取消异常 |
| `tests/test_build.py` | 契约组装与规范校验、中文分组（tag）与中文接口名（summary）及其回落、基准契约 tags 继承、响应结构推导、增量对比、风险规则、递归切块 |
| `tests/test_workflow_flow.py` | 正常流程、来源标签注入、多源冲突融合、抽取失败跳过、融合失败回退、风险扫描降级 |
| `tests/test_api_flow.py` | 提交→轮询→取结果、JSON 输出格式、任务取消、统一错误体字段 |
| `tests/test_api_validation.py` | 枚举/指令长度/文件数/文件大小校验、空输入、基准契约与 diff、生成模式、进度上报 |
| `tests/test_token_control.py` | 三层 Token 防护、截断与摘要、上下文超限归一为 10003、重试策略 |
| `tests/test_validators.py` | 指令清洗、基线契约解析、枚举校验、同名文件防覆盖、路径穿越过滤 |

`tests/fakes.py` 提供按 schema 注入应答的 `FakeLlmClient`（支持异常注入、延迟与纯文本调用），因此**整套流水线无需真实模型调用即可确定性测试**，包括各类异常与降级路径。

### 端到端冒烟（真实起服务，无需模型密钥）

`scripts/mock_llm_server.py` 是一个本地假的 OpenAI 兼容服务，配合 `scripts/smoke_http.py` 可以在没有真实大模型的情况下验证「真实 uvicorn 进程 + 真实 HTTP」全链路：

```bash
# 终端 1：假模型
python scripts/mock_llm_server.py 11434

# 终端 2：真实起服务
export OPENAPI_AGENT_BASE_URL=http://127.0.0.1:11434/v1
export OPENAPI_AGENT_API_KEY=mock
python -m uvicorn openapi_agent.main:app --port 8123

# 终端 3：跑冒烟
python scripts/smoke_http.py http://127.0.0.1:8123
```

覆盖 36 项检查：OpenAPI 文档挂载、提交→轮询→取结果、响应结构组装、`x-source` 标注、基准契约 diff、
文件上传、取消任务、7 类错误码路径、`openapi_version=3.1.0` 产物。

> 沙箱提示：若运行环境禁止写入「运行时新建的目录」，素材暂存会自动退回
> 「已存在目录 + 唯一文件名前缀」模式，并在任务结束后清理，无需额外配置。
> 若连删除也被限制，清理失败会打 `WARNING` 日志而不是静默泄漏。

## 已知限制

这些是当前实现的真实边界，欢迎按需扩展：

1. **错误码语义合并的取舍**：Token/上下文超限按设计文档 2.3.2 统一归入 `10003`（素材/上下文异常），因此无法从错误码单独区分「上游模型超限」与「本地预校验拦截」，区别在 `detail` 文案里。
2. **增量融合不做 LLM 二次融合**：`base_openapi` 仅作为组装基座与 diff 基准，新素材与基线接口的字段级合并仍以新素材为准；设计文档 2.4 只定义了 4 个 Prompt，没有增量融合模板。
3. **切块重叠未完全生效**：`recursive_split` 的 `overlap` 参数仅在没有分隔符的兜底分支生效。
4. **取消是「停止等待」而非「中断请求」**：LLM 调用运行在线程池中，取消无法中断已发出的 HTTP 请求。
5. **任务数据存在进程内存**：服务重启即丢失，无 TTL 清理，无法多实例部署。
6. **OCR 为可选依赖且未经验证**：未安装 `paddleocr` 时，图片素材会被跳过；实现基于 PaddleOCR 2.x 的 API，因此依赖锁在 `<3.0`，该链路也未被单测覆盖。
7. **上传链路的端到端用例依赖真实可写临时目录**：素材暂存已支持「独立临时目录」与「共享目录 + 唯一前缀」两种模式自动切换，注入式测试覆盖了命名冲突与大小校验逻辑。
8. **源码解析是纯文本级**：不做 AST，复杂框架的隐式路由（如装饰器拼路径）可能提取不全。

### 后续规划

- 任务存储持久化（SQLite / Redis），支持多实例与 TTL 清理；
- 多文本块并发抽取，缩短大素材的生成耗时；
- 让取消真正中断已发出的 LLM 请求；
- 补 OCR 链路的单测与 PaddleOCR 3.x 适配；
- 建评测集，量化设计文档 4.1 的准确率 / 覆盖率 / 响应时间指标。

## 许可证

本项目基于 [MIT License](LICENSE) 开源。
