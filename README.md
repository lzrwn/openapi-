# OpenAPI 契约智能生成 Agent

> 把散落在接口文档、curl 抓包、源码注释、SQL 建表语句里的**杂乱素材**，自动整理成可用的 **OpenAPI 3.0.3** 契约，并如实标注「信息缺失 / 多源冲突 / AI 推断」三类风险。

![python](https://img.shields.io/badge/python-3.10%2B-blue)
![fastapi](https://img.shields.io/badge/FastAPI-0.110%2B-009688)
![openapi](https://img.shields.io/badge/OpenAPI-3.0.3-6BA539)
![license](https://img.shields.io/badge/license-MIT-green)

> **当前状态**：可用原型（MVP）。15 个测试全部通过，核心链路无 Agent 框架依赖。已知限制见文末[已知限制](#已知限制)。

---

## 这个项目解决什么问题

前后端联调时，接口契约往往不是「没有」，而是「有但不可信」：

- 真实接口信息散落在 Markdown 文档、curl 抓包记录、后端源码注释、SQL 建表语句、甚至截图里；
- 多源之间互相矛盾——同一个 `page_size`，文档写默认 10、源码注释写默认 20；
- 更麻烦的是**无法区分**「素材里真实存在的字段」和「整理者补上去的字段」。前端照文档写完代码跑不通，才发现文档本身是错的。

所以本项目的目标不是「生成一份看起来很完整的文档」，而是**生成一份附带风险标注、可以放心对照的契约**：

- 只提取素材中真实存在的接口，缺失字段**留空不脑补**；
- 多源冲突时**保留双方信息并标记**，而不是让模型自行覆盖；
- 每一处 AI 推断都单独标记出来，供人工复核。

## 核心特性

| 能力 | 说明 |
|---|---|
| **支持 34 种格式输入** | 文本类 8 种、源码 16 种（按纯文本读取后交由 LLM 抽取，非语言级解析）、SQL、YAML/JSON、图片（OCR）、zip 递归解包 |
| **两阶段 LLM 抽取** | 逐块抽取 → 按 `(path, method)` 分组融合；内容一致的分组本地去重，不发多余请求 |
| **多源来源打标** | 每段素材标记 `curl` / `code` / `sql` / `markdown` / `testcase`，作为冲突仲裁的优先级依据 |
| **风险报告** | 显式输出三类问题：信息缺失、字段冲突、AI 推断 |
| **4 条降级路径** | 单点失败不中断产出，问题全部写进报告，而不是抛错丢掉结果 |
| **JSON 纠错重试** | 模型输出不符合结构时，把错误输出回灌并要求重新生成，而非简单重试 |
| **异步任务架构** | 提交 / 轮询状态 / 取结果 / 取消 四个端点，LLM 调用不阻塞事件循环 |
| **零 Agent 框架依赖** | 自研状态机流水线，流程显式、每层可单测 |

## 工作流程

```
素材（上传文件 / 表单文本）
  │
  ├─[Preprocessing]─ 格式分流 · 递归切块(1500 字符/150 重叠) · 来源类型打标
  ▼
文本块 × N
  │
  ├─[Agent 阶段一]─ 逐块 LLM 抽取 ──────────────▶ RawEndpoint[]
  │                                               （失败则跳过该块，不中断）
  ├─[Agent 阶段二]─ 按 (path, method) 分组
  │                   ├─ 内容一致 → 本地去重，不发请求
  │                   └─ 真冲突   → LLM 融合（失败则回退首份素材并标记冲突）
  ▼
ApiIntermediateMeta[]   ← 带 is_conflict / is_ai_infer / source / notes
  │
  ├─[OpenAPI Build]─ 组装 OpenAPI 3.0.3 → 规范校验（失败不丢弃文档，写入风险报告）
  │
  └─[Reporting]──── 确定性规则扫描 + LLM 风险扫描
  ▼
结果：{ openapi, diff, risk_report }
```

## 目录结构

```
openapi-agent/
├── app/
│   ├── main.py                  # FastAPI 入口：路由挂载、错误码 → HTTP 状态映射
│   ├── api/routes.py            # 4 个端点 + 后台任务编排
│   ├── core/
│   │   ├── errors.py            # 业务异常与 5 类错误码
│   │   ├── task.py              # 任务模型与状态枚举
│   │   └── task_manager.py      # 进程内任务表
│   ├── preprocessing/
│   │   ├── file_parser.py       # 多格式解析（含 zip 递归、图片 OCR）
│   │   ├── splitter.py          # 递归切块
│   │   └── preprocessor.py      # 素材统一预处理与来源打标
│   ├── agent/
│   │   ├── llm_client.py        # LLM JSON 调用 + 纠错重试
│   │   ├── extractor.py         # 两阶段抽取与多源融合
│   │   ├── workflow.py          # 流水线编排
│   │   ├── models.py            # 中间元数据契约
│   │   ├── prompts.py           # prompt 加载与渲染
│   │   └── prompts/             # system / extract / fuse / risk_scan 模板
│   ├── openapi_build/
│   │   ├── assembler.py         # 元数据 → OpenAPI 3.0.3
│   │   ├── validator.py         # OpenAPI 规范校验
│   │   └── diff.py              # 契约增量对比（尚未接通 API，见已知限制）
│   └── reporting/risk_report.py # 三类风险报告
├── tests/                       # 15 个用例，含 Fake LLM，无需真实模型调用
├── examples/sample_接口文档.md   # 故意做「脏」的演示素材
├── scripts/
│   ├── rerun_sample.py          # 用该素材真实跑一次，覆盖下面的产物快照
│   └── render_result.py         # 从 res.json 还原 YAML 并打印风险报告
├── openapi.yaml / res.json      # 由 scripts/rerun_sample.py 生成的产物快照
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

### 3. 配置大模型

| 环境变量 | 必填 | 说明 |
|---|---|---|
| `OPENAPI_AGENT_BASE_URL` | 是 | 大模型服务地址，如 `https://api.openai.com/v1` |
| `OPENAPI_AGENT_API_KEY` | 是 | API Key |
| `OPENAPI_AGENT_MODEL` | 否 | 模型名，默认 `gpt-4o-mini` |

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
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
# 或
python app/main.py
```

- 交互式 API 文档：http://127.0.0.1:8000/docs

## API 使用

服务前缀：`/api/v1/openapi`

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/generate` | 提交生成任务，立即返回 `task_id` |
| GET | `/task/{task_id}/status` | 轮询任务状态 |
| GET | `/task/{task_id}/result` | 获取生成结果 |
| POST | `/task/{task_id}/cancel` | 取消任务 |

### 提交任务

`multipart/form-data` 参数：

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `files` | File[] | 空 | 素材文件，可多选 |
| `texts` | string[] | 空 | 直接粘贴的文本素材，可多段 |
| `user_instruction` | string | `""` | 用户指令，如「过滤内部调试接口」 |
| `output_format` | string | `yaml` | 仅支持 `yaml` / `json` |
| `title` | string | `Generated API` | 契约文档标题 |
| `version` | string | `1.0.0` | 契约文档版本 |

`files` 与 `texts` 至少提供一个，否则返回 `10001`。

```bash
# 提交文本素材
curl -X POST http://127.0.0.1:8000/api/v1/openapi/generate \
  -F 'texts=获取用户列表接口：GET /users，查询参数 page 为整数，分页返回用户数据。' \
  -F 'user_instruction=过滤内部调试接口' \
  -F 'output_format=yaml' \
  -F 'title=商城系统 API' \
  -F 'version=1.0.0'

# 提交文件素材（可多个 -F files=...）
curl -X POST http://127.0.0.1:8000/api/v1/openapi/generate \
  -F 'files=@examples/sample_接口文档.md' \
  -F 'files=@docs/order-api.zip' \
  -F 'output_format=json'
```

响应：

```json
{ "task_id": "469a477f8f654bd5a1b84cb7f1b6766b" }
```

### 轮询状态

```bash
curl http://127.0.0.1:8000/api/v1/openapi/task/<task_id>/status
```

```json
{
  "task_id": "e57ac0da27444cab9daf98faebecad28",
  "status": "completed",
  "progress": "",
  "error_info": null
}
```

`status` 取值：`pending` / `preprocessing` / `chunking` / `extracting` / `merging` / `assembling` / `validating` / `diffing` / `completed` / `failed` / `cancelled`。
> 当前实现只上报 `preprocessing` 与 `extracting`，其余中间态尚未接入（见[已知限制](#已知限制)）。

### 获取结果

```bash
curl http://127.0.0.1:8000/api/v1/openapi/task/<task_id>/result
```

```json
{
  "task_id": "...",
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

### 取消任务

```bash
curl -X POST http://127.0.0.1:8000/api/v1/openapi/task/<task_id>/cancel
```

```json
{ "task_id": "...", "status": "cancelled" }
```

### 错误码

| code | HTTP | 含义 |
|---|---|---|
| `10001` | 400 | 输入参数错误 |
| `10002` | 404 | `task_id` 不存在 / 任务无可用结果 |
| `10003` | 422 | 素材解析错误或大小异常 |
| `10004` | 503 | 大模型服务调用失败或超时 |
| `10005` | 500 | 服务未知内部错误 |

错误响应体统一为：

```json
{ "code": 10002, "message": "task_id不存在", "detail": "deadbeef" }
```

## 输出示例

以 `examples/sample_接口文档.md` 为输入（该素材**故意**混合了文档表格、curl 抓包、源码注释，并预埋了字段冲突、默认值不一致和一个需过滤的内部调试接口），一次真实运行的产物如下。

该快照可用下面这条命令一键复现（需要真实模型调用，会覆盖根目录的 `res.json` 与 `openapi.yaml`）：

```bash
python scripts/rerun_sample.py
```

生成的契约（节选）：

```yaml
openapi: 3.0.3
info:
  title: Generated API
  version: 1.0.0
paths:
  /api/v1/orders:
    post:
      summary: POST /api/v1/orders
      operationId: post_api_v1_orders
      responses:
        '200':
          description: OK
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
                  description: AI推断/curl样例字段，文档未列出；出现在抓包样例中
```

配套的风险报告（真实输出，有删减）：

```json
{
  "conflict_items": [
    { "issue": "POST /api/v1/orders 请求体字段 client_tag：文档字段表未包含，但 curl 样例包含，存在字段冲突" },
    { "issue": "GET /api/v1/orders 的 page_size 默认值：素材标注为 20，与产品文档不一致，待确认" }
  ],
  "ai_infer_items": [
    { "issue": "POST /api/v1/orders 的 client_tag 被标注为 AI推断/curl样例字段，文档未列出，需确认是否正式字段" }
  ],
  "missing_info": [
    { "path": "/api/v1/products", "method": "GET", "issue": "缺少响应结构定义和错误码" },
    { "scope": "global", "issue": "所有接口均未提取到响应结构与错误码定义" },
    { "issue": "GET /api/v1/orders 的 status 参数仅写“订单状态”，缺少可选值/枚举说明" }
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
| OpenAPI 规范校验失败 | **不丢弃文档**，把校验错误追加进 `risk_report.validation_errors` |

## 测试

```bash
python -m pytest -q
# 15 passed
```

15 个用例分布：

| 测试文件 | 用例数 | 覆盖内容 |
|---|---|---|
| `tests/test_core.py` | 3 | 错误码、任务模型、任务生命周期 |
| `tests/test_build.py` | 4 | 契约组装与规范校验、增量对比、风险规则、递归切块 |
| `tests/test_workflow_flow.py` | 5 | 正常流程、多源冲突融合、抽取失败跳过、融合失败回退、风险扫描降级 |
| `tests/test_api_flow.py` | 3 | 提交→轮询→取结果、JSON 输出格式、任务取消 |

`tests/fakes.py` 提供按 schema 注入应答的 `FakeLlmClient`，因此**整套流水线无需真实模型调用即可确定性测试**，包括各类异常与降级路径。

## 已知限制

这些是当前实现的真实边界，欢迎按需扩展：

1. **契约增量对比未接通 API**：`DiffHelper` 与 `Assembler(base_spec=...)` 已实现，但 `/generate` 不接收基线契约，`diff` 字段恒为 `null`。
2. **响应结构缺失**：`response_examples` 已从素材抽取，但组装器未使用它，生成的 `responses` 只有 `200 OK`，没有响应 schema 与错误码；风险报告会如实提示这一点。
3. **中间状态未上报**：`TaskStatus` 定义了 11 个状态，实际只写入 `preprocessing` 与 `extracting`，`progress` 恒为空字符串。
4. **取消是「停止等待」而非「中断请求」**：LLM 调用运行在线程池中，取消无法中断已发出的 HTTP 请求。
5. **任务数据存在进程内存**：服务重启即丢失，无 TTL 清理，无法多实例部署。
6. **切块重叠未完全生效**：`recursive_split` 的 `overlap` 参数仅在没有分隔符的兜底分支生效。
7. **上传无大小与数量限制**：同名文件会在临时目录相互覆盖。
8. **OCR 为可选依赖且未经验证**：未安装 `paddleocr` 时，图片素材会被跳过；实现基于 PaddleOCR 2.x 的 API，因此依赖锁在 `<3.0`，该链路也未被单测覆盖。

### 后续规划

- 接通基线契约，输出真实的接口增量变更报告；
- 把 `response_examples` 组装进 `responses`，让产物可直接用于联调；
- 上报真实进度与中间状态；
- 任务存储持久化，支持多实例；
- 多文本块并发抽取，缩短大素材的生成耗时。

## 许可证

本项目基于 [MIT License](LICENSE) 开源。
