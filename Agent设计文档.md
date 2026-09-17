# Agent 设计文档 - 通用模板



---

## 一、总体设计

### 1.1 Agent 定位

**Agent名称**：OpenAPI生成Agent

**核心功能**：多源素材解析与标准 OpenAPI 文档自动生成

**解决的问题**：接口文档手写费时费力；存量项目缺少接口文档；人工文档格式不规范；团队协作缺少标准接口契约。

**目标用户**：后端开发者、前端开发者、测试工作者

### 1.2 使用场景

| 场景 | 触发时机 | 输入 | 输出 |
|------|----------|------|------|
| 【场景1:接口发生变更】 | 版本迭代，新增 / 修改 / 废弃部分接口 | 旧版 OpenAPI 文件和变更素材 | 新版本OpenAPI以及新旧版本差异 |
| 【场景2:接口文档格式等不统一】 | 历史 wiki、Markdown 接口笔记，需要迁移标准化|Markdown/Word/wiki 文本，非结构化接口描述 |标准化 OpenAPI；对识别模糊、冲突的地方给出告警提示 |
| 【场景3:新项目开发阶段，根据零散需求素材，预生成 OpenAPI契约】 |需求评审完成，接口还未编码 | 产品需求文档 markdown；口头 和 文本接口描述| OpenAPI 3.x yaml/json 契约文档；可直接交给前端做 mock、后端做编码参考|


### 1.3 功能模块划分

| 模块 | 职责 | 说明 |
|------|------|------|
| 【多源素材接入和预处理模块】 | 接收各类文件、文本、截图输入，做清洗、解压、分片、格式处理 | 原始素材格式化 |
| 【多源元信息解析提取模块】 | 从清洗后素材提取接口基础元数据 | 结构化素材用规则解析，非结构化靠 AI 解析；输出中间接口元数据，识别冲突 |
| 【Agent核心推理与业务决策模块】 | 识别用户意图，多源信息融合、增量更新、过滤接口、识别缺失 / 歧义信息，处理用户指令 | 决定怎么合并不同来源信息，标记需要人工确认的内容 |
| 【OpenAPI文档构建和标准化校验模块】 | 把中间元数据组装成标准 OpenAPI3.x YAML/JSON，构建 Schema，做规范校验 | 完成最终文档组装，提供严谨 / 快速两种生成模式，标记 AI 推测内容 |
| 【结果输出、差异对比和风险报告模块】 | 文档导出、新旧文档 diff 对比，输出风险复核报告、接口概览 | 产出最终文件，提示哪些地方可能不准，提醒人工核对|
| 【系统配置与会话管理模块】 | 管理 Agent 参数配置，维护会话上下文，支持接口分组 | 保存本次任务上下文，控制生成规则，支持迭代调整文档 |

### 1.4 明确不做的功能

- ❌ 【功能1 不会调用用户本地服务，不会发 http 请求去真实业务接口抓接口信息】
- ❌ 【功能2 不会执行接口请求；不会生成 pytest/postman 自动化测试脚本】
- ❌ 【功能3 不能填写数据库 ip 账号密码直连库读取表结构】

### 1.5 技术选型

| 层级 | 技术 | 选型理由 |
|------|------|----------|
| 接入层 | 【FastAPI；UI：Streamlit (MVP)/Vue3 (正式)；本地临时文件】 | 异步接口，支持文件上传；快速搭建原型，素材只临时存放 |
| 素材预处理层 | 【PyYAML、json、zipfile、RecursiveCharacterTextSplitter；PaddleOCR】 |解析各类文件、压缩包；大文本分片规避 LLM 上下文超限；只做文本处理，不运行 / 编译代码 |
| Agent核心层 | 【兼容 OpenAI 协议 LLM、Pydantic（结构化模型）、LLM JSON Mode、本地 Prompt 模板、手写状态机控制流程】 | Agent 逻辑是自己写的业务状态流转，只是调用大模型做推理，不套现成 Agent 组件 |
| OpenAPI构建校验层 | 【pydantic‑openapi、openapi‑spec‑validator、orjson、PyYAML、deepdiff】 |代码组装 OpenAPI 对象，不全靠大模型输出完整 yaml；做 OpenAPI 规范校验；新旧文档 diff 对比 |
| 输出与会话管理层 | 【内存存储【MVP】/ Sqlite；文件流导出】 | 保存会话中间状态；直接文件下载，不做云端文档托管 |


---

## 二、详细设计

### 2.1 接口设计

#### 2.1.1 Agent对外接口

| 接口 | 方法 | URL | 输入 | 输出 | 说明 |
|------|------|-----|------|------|------|
| 【提交OpenAPI生成任务】 | POST | /api/v1/openapi/generate | Request Body，multipart/form‑data，支持上传文件 + 文本参数 | 200 JSON | 接收多源素材，创建异步 Agent 任务 |
| 【查询任务状态】 | GET |/api/v1/openapi/task/{task_id}/status | 路径参数 `task_id`| 200 JSON | 轮询 Agent 任务执行状态 |
| 【获取任务生成结果】 | GET | /api/v1/openapi/task/{task_id}/result | 路径参数 `task_id`| 200 JSON |返回完整 OpenAPI 文档字符串、变更 diff、风险复核报告 |
| 【取消执行中任务】 | POST | /api/v1/openapi/task/{task_id}/cancel | 路径参数 `task_id`| 200 JSON | 止正在运行的 Agent 任务，释放资源 |

提交OpenAPI生成任务接口：
**输入参数示例**（以OpenAPI生成为例）：

```json
{
 "files": ["demo_api.md", "postman_collection.json"],
  "text_materials": "curl -X GET /api/user/list -H \"token:xxx\"",
  "base_openapi": null,
  "user_instruction": "忽略调试接口，OpenAPI 版本使用 3.1",
  "generate_mode": "strict"
}
```

**输出示例**：

```json
{
  "task_id": "task-8a2f-4412-b71e-abc123456789",
  "status": "pending",
  "msg": "任务已提交，开始解析素材"
}
```

> **字段裁决（原文档自相矛盾处，统一如下）**
> - 文本素材入参字段名统一为 **`text_materials`**（2.8.2 的 `text_material` 为笔误）。
> - `files` 在 multipart/form-data 下为文件流，在 JSON 下为文件名字符串数组；`files` 与 `text_materials` 至少提供一个。
> - `generate_mode`：`strict`（默认，规范校验失败即任务失败）/ `fast`（校验失败不中断，写入风险报告）。
> - 可选参数 `openapi_version`：`3.0.3`（默认）/ `3.1.0`。
> - 可选参数 `output_format`：`yaml`（默认）/ `json`。

#### 2.1.2 错误码

| 错误码 | 说明 | HTTP状态码 |
|--------|------|------------|
| 10001 | 输入参数错误 | 400 |
| 10002 | task_id不存在 | 404 |
| 10003 | 素材解析错误或者大小异常 | 422 |
| 10004 | 大模型服务调用失败或超时 | 503 |
| 10005 | 服务未知内部错误 | 500 |

---

### 2.2 类设计

#### 2.2.1 包结构

```
openapi_agent/
├── main.py                     # FastAPI入口，注册路由
├── api/                        # 接入层：http接口
│   ├── __init__.py
│   ├── routes.py               # 接口路由：generate、task/status、task/result、task/cancel
│   ├── schemas.py              # http请求/响应Pydantic模型，错误响应模型
│   ├── validators.py           # 入参校验与清洗（指令长度、文件数/大小、base_openapi 解析）
│   ├── service.py              # 接入层编排辅助：临时目录、运行中任务句柄
│   └── exception_handler.py    # 全局异常捕获，错误码统一封装
├── core/                       # Agent核心（自研工作流、状态管理）
│   ├── __init__.py
│   ├── errors.py               # 业务异常 BusinessException 与错误码枚举
│   ├── task.py                 # 任务实体 Task 与状态枚举 TaskStatus
│   ├── task_manager.py         # 任务管理器：任务创建、状态维护、取消、内存任务存储
│   ├── agent_workflow.py       # 自研Agent主工作流（状态机编排全部业务步骤 + run_task 后台执行与超时）
│   ├── llm_client.py           # LLM通用调用客户端，JSON‑Mode封装 + 单请求token预校验
│   ├── llm_factory.py          # LLM 客户端装配（便于测试替换）
│   ├── token_budget.py         # token 估算、尾部截断、分片摘要、上下文超限识别
│   └── prompt_templates.py     # prompt模板常量与变量填充
├── material/                   # 素材预处理层
│   ├── __init__.py
│   ├── preprocessor.py         # 素材预处理：解压、分片、脏数据过滤、token 统计与超限校验
│   ├── file_parser.py          # 文件解析：md/json/yaml/zip/sql/postman解析
│   ├── splitter.py             # 递归切块（内部工具）
│   └── extractor.py            # 元信息提取：规则解析 + LLM提取中间元数据（extract(): 入参 llm_client，chunks 由构造/上游注入）
├── model/                      # 数据模型（核心结构体）
│   ├── __init__.py
│   ├── intermediate_meta.py    # 【核心】接口中间元数据模型（不是OpenAPI）
│   └── openapi_build_model.py  # OpenAPI构建相关模型，风险报告、diff模型
├── builder/                    # OpenAPI构建&校验层
│   ├── __init__.py
│   ├── openapi_assembler.py    # 根据中间元数据组装OpenAPI对象
│   ├── schema_builder.py       # 返回示例→Schema 推导，x-ai-inferred / x-conflict 标注
│   ├── validator.py            # OpenAPI规范校验
│   └── diff_helper.py          # 新旧openapi对比diff生成
├── report/                     # 输出报告模块
│   ├── __init__.py
│   └── risk_report_builder.py  # 风险报告构建：冲突、缺失、AI推测项
└── config.py                   # 系统配置：LLM地址、默认模式、文件大小限制等
```

#### 2.2.2 核心类说明

**BusinessException**

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| 【构造函数】 | 【code:int，message:str，detail:str|None】 | 【异常实例】 | 【自定义业务异常，全局抛出，输出统一错误 JSON】 |

```python
// 示例代码骨架
class BusinessException(Exception):
    """自定义业务异常，全局捕获后输出统一错误JSON"""
    code: int
    message: str
    detail: Optional[str]

    def __init__(self, code: int, message: str, detail: Optional[str] = None):
        self.code = code
        self.message = message
        self.detail = detail
        super().__init__(message)

```
**Task**

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| 【数据类】 | 【task_id，status，progress，input_materials，result，error_info】  | 【-】 | 【内存任务实体，存储任务状态、输入输出数据】 |

```python
// 示例代码骨架
class Task:
    """任务数据实体，内存保存任务信息"""
    task_id: str
    status: str  # pending/preprocessing/chunking/extracting/merging/assembling/validating/diffing/completed/failed/cancelled
    progress: int  # 0-100 百分比
    input_materials: dict
    result: Optional[dict] = None
    error_info: Optional[dict] = None
```
**TaskManager**

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| create_task() | `task_id: str`、`input_materials: dict` | `Task` | 【任务管理器，管理任务创建、查询、取消生命周期；`_tasks`：内存字典存储全部 Task 对象】 |
| get_task() | `task_id: str` | `Task` / `None` | 【按 id 查询任务，不存在返回 None】 |
| cancel_task() | `task_id: str` | `None` | 【任务不存在或已处于终态时抛 BusinessException(10002)】 |

```python
// 示例代码骨架
class TaskManager:
    """任务管理器：负责任务创建、查询、取消，内存存储任务"""
    def __init__(self):
        # 类属性：内存字典存放所有任务
        self._tasks: Dict[str, Task] = {}

    def create_task(self, task_id: str, input_materials: dict) -> Task:
        # task_id 由调用方生成并传入（形如 task-8a2f-4412-b71e-abc123456789）
        """
        创建任务
        :param task_id: 任务唯一id
        :param input_materials: 用户输入素材与配置参数
        :return: Task 任务实例
        """
        task = Task(
            task_id=task_id,
            status="pending",
            progress=0,
            input_materials=input_materials
        )
        self._tasks[task_id] = task
        return task

    def get_task(self, task_id: str) -> Optional[Task]:
        """
        获取任务
        :param task_id: 任务id
        :return: Task实例，不存在返回None
        """
        return self._tasks.get(task_id)

    def cancel_task(self, task_id: str) -> None:
        """
        取消执行中的任务
        :param task_id: 任务id
        :raises BusinessException: 任务不存在、不可取消
        """
        task = self.get_task(task_id)
        if not task:
            raise BusinessException(code=10002, message="task_id不存在", detail=f"task_id:{task_id}")
        # 修改任务状态逻辑
```
**AgentWorkflow**

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| run() | llm_client：LLM 客户端实例；preprocessor：素材预处理实例；extractor：元数据提取实例；base_spec：基准 OpenAPI dict 或 None；title/version：文档标题与版本；generate_mode：strict/fast；openapi_version：3.0.3/3.1.0 | 【(List[ApiIntermediateMeta], dict)】 | 【自研 Agent 主工作流，串联全流程，产出中间元数据；dict 含 openapi/diff/risk_report】 |

**LlmClient**

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| 【chat_json()】 | 【system:str，user:str，schema:type[BaseModel]】 | 【Pydantic 模型实例】 | 【封装 LLM 调用，开启 JSON Mode，调用前做单请求 token 预校验，输出不符合 schema 时回灌纠错重试，捕获上下文超限转 10003】 |
| 【chat_raw()】 | 【prompt:str】 | 【str 纯文本】 | 【不带 JSON Mode 的纯文本调用，仅用于输入摘要 summary_fragment】 |


**MaterialPreprocessor**

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| 【process()】 | 【无（files/texts 由构造函数注入）】 | 【list[dict]】 | 【完成素材清洗、分片、来源标记、脏数据过滤、全素材 token 统计与超限校验】 |


**FileParser**

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| 【parse()】 | 【path：素材文件路径】 | 【list[str]】 | 【解析各类文件，输出文本片段，不编译运行代码】 |


**MetaExtractor**

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| 【extract()】 | 【llm_client：大模型客户端实例】 | 【List[ApiIntermediateMeta]】 | 【规则 + LLM 提取接口中间元数据】 |


**ApiIntermediateMeta**

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| 【Pydantic 模型】 | 【path，method，summary，tag，parameters，request_body，response_examples，error_codes，source，is_conflict，is_ai_infer】 | 【-】 | 【核心内部流转模型，非 OpenAPI 文档结构】 |


**OpenApiAssembler**

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| 【assemble()】 | 【无】 | 【dict】 | 【基于中间元数据，代码组装 OpenAPI 字典对象；summary 优先用元数据中的中文功能名，tag 优先用元数据中的中文业务分组名（缺失时回落路径首段），并在文档根节点声明 tags】 |


**OpenApiValidator**

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| 【validate()】 | 【无】 | 【无】 | 【校验 OpenAPI 文档规范，失败抛出业务异常】 |


**DiffHelper**

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| 【diff()】 | 【无】 | 【dict{added,modified,deleted}】 | 【对比新旧 OpenAPI，输出变更信息】 |


**RiskReportBuilder**

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| 【build()】 | 【无】 | 【dict{conflict_items,missing_info,ai_infer_items}】 | 【构建风险报告，标记冲突、缺失、AI 推测项】 |



### 2.3 核心流程

#### 2.3.1 主流程

```
用户请求POST /generate
        ↓
参数校验 → 失败返回错误
        ↓
TaskManager 创建Task(pending)，返回task_id
        ↓
后台异步执行，task状态改为running
        ↓
AgentWorkflow.run()
    ├─ FileParser：解析各类文件得到文本片段
    ├─ MaterialPreprocessor：清洗、分片、标记来源
    ├─ MetaExtractor：规则+LLM提取得到初步中间元数据
    └─ 自研逻辑：多源合并、冲突检测、用户指令处理、增量融合
        ↓
OpenApiAssembler 组装OpenAPI dict
        ↓
OpenApiValidator 规范校验
        ↓
DiffHelper 计算变更diff（增量场景）
        ↓
RiskReportBuilder 生成风险报告
        ↓
结果写入Task，状态置success
        ↓
前端轮询status接口，完成后拉取result接口返回全部数据
        ↓
释放临时素材内存资源

```

#### 2.3.2 Token控制流程

```
素材输入
    ↓
MaterialPreprocessor：统计全部素材总token
    ↓
总素材是否超限？→是→抛出10003，任务失败
    ↓否
对大文本分片，控制单分片token上限
    ↓
循环每个分片
    ↓
LlmClient：预估本次请求总token(prompt+分片+指令)
    ↓
单请求token是否超限？→是→抛出10003，任务失败
    ↓否
调用LLM提取该分片元数据
    ↓
收集ApiIntermediateMeta，代码做合并融合（无LLM调用）
    ↓
后续OpenAPI构建流程

```
---

### 2.4 Prompt设计

#### 2.4.1 Prompt模板

**【功能1】通用基础Prompt**：

```
你是 专业 OpenAPI 契约智能解析 Agent，专注从各类杂乱技术素材中精准提取接口元数据。
你具备后端接口、前端联调、接口文档标准化能力。

**永久固定规则**

1. 只提取真实存在的接口，禁止编造不存在接口、禁止脑补字段
2. 输出必须严格 JSON，禁止解释、禁止 markdown、禁止多余文字
3. 识别不确定内容，标记为 AI 推断，不瞎填
4. 识别冲突内容，标记冲突，不自行覆盖
5. 严格区分：真实素材内容 / AI 推测内容 / 冲突内容
```

**【功能2】接口元数据提取Prompt**：

```

任务：从用户提供的技术素材中，精准提取所有HTTP接口完整元数据。

要求：
你需要识别并输出以下字段：
- path：接口路径
- method：GET/POST/PUT/DELETE
- summary：接口功能名称，必须用**通俗易懂的简体中文**概括这个接口做什么（例如「查询文件列表」「创建订单」「删除购物车商品」），禁止直接照抄 path 或写成「GET /xxx」
- tag：业务分组名，用**简体中文**表示该接口属于哪个业务模块（例如「商品订单购物车」「用户管理」）；同一业务模块的接口必须使用完全相同的 tag
- parameters：路径参数、查询参数列表
- request_body：请求体结构、字段、类型
- response_examples：返回示例
- error_codes：素材中出现的错误码定义（如 "400: 参数错误"），没有就留空
- source_type：当前素材来源（curl/markdown/code/sql/testcase）

输入内容：
1. 技术素材片段：{{material_content}}
2. 用户指令：{{user_instruction}}
3. 素材来源提示：{{source_hint}}

只输出 JSON，格式：{"endpoints": [{"path": "...", "method": "...", "summary": "...", "tag": "...", "parameters": [], "request_body": {}, "response_examples": null, "error_codes": [], "source_type": "..."}]}，没有接口时 endpoints 为空数组。
```

> **命名与回落约定（2.4.1 功能2）**
> - `source_hint` 由 `MaterialPreprocessor` 用确定性规则（扩展名 / 文件名 / curl 特征）给出，形如 `sql（文件: schema.sql）`，避免模型自行猜测来源。
> - `summary` 缺失或与 `METHOD /path` 相同时，组装器回落为 `METHOD /path`，并在风险报告中记为「缺少接口功能名称」。
> - `tag` 缺失时组装器回落为路径首段（如 `/api/v1/products` → `api`），并在风险报告中记为「未识别出业务分组」。

**【功能3】多源素材融合 & 冲突修正Prompt**：

```

任务：对多份素材提取的同一接口元数据进行智能融合、去重、冲突修正。

要求：
1. 相同 path+method 判定为同一个接口，自动合并
2. 真实请求样例（curl、日志）优先级最高
3. 源码注释、SQL表结构次之
4. 文档描述优先级最低
5. 多源字段不一致自动标记 conflict，保留双方信息
6. 缺失字段不脑补，保留空缺
7. 用户指定忽略内部接口、调试接口需要过滤
8. summary 用通俗易懂的简体中文功能名称，tag 用简体中文业务分组名，冲突时优先采信高优先级来源的取名

输入内容：
1. 多源接口原始元数据列表：{{raw_meta_list}}
2. 用户过滤指令：{{user_instruction}}

只输出 JSON，字段：path、method、summary、tag、parameters、request_body、response_examples、error_codes、source、is_conflict、is_ai_infer、notes（冲突或推断说明放 notes）。
```

**【功能3.5】分组与命名回落规则（代码确定性实现，不依赖模型）**：

| 场景 | 行为 |
|------|------|
| 模型给出中文 `summary` | 原样写入 `operation.summary` |
| `summary` 缺失或等于 `METHOD /path` | 回落为 `METHOD /path`，并在 `risk_report.missing_info` 记「缺少接口功能名称（summary）」 |
| 模型给出中文 `tag` | 写入 `operation.tags`，并在文档根节点 `tags` 按首次出现顺序声明 |
| `tag` 缺失 | 回落为路径首段（`/api/v1/products` → `api`），并在 `risk_report.missing_info` 记「未识别出业务分组（tag）」 |
| 传入 `base_openapi` 且其中已声明同名 tag | 继承基准契约里的 `description`，不覆盖为裸 name |

**【功能4】风险识别 & 缺失检测Prompt**：

```

任务：对已提取的接口元数据进行风险扫描，识别三类问题：
1. 信息缺失项（缺少响应、缺少参数说明、缺少错误码）
2. 字段冲突项（多素材定义不一致）
3. AI推断项（无原始素材依据，AI补全内容）

输入内容：
接口中间元数据列表：{{final_meta_list}}
```
#### 2.4.2 变量填充规则

| 变量 | 来源 | 处理方式 |
|------|------|----------|
| {{material_content}} | `MaterialPreprocessor`输出的单个素材分片文本片段 | 1. 取单分片清洗后文本；2. 去除首尾空白；3. 不做自动截断；4. 转义 JSON 特殊字符（换行、双引号），避免破坏 prompt 结构；5. token 在 LlmClient 层提前校验超限抛异常 |
|{{user_instruction}} | HTTP 入参 `user_instruction` | 1. 获取用户传入的自定义指令字符串；2. 空值填充：`无特殊指令`；3. 过滤高危控制字符；4. 原样嵌入 prompt，不做语义修改 |
|{{raw_meta_list}}| MetaExtractor 输出，多个分片提取得到的 `List[ApiIntermediateMeta]` | 1. 将 Pydantic 模型列表调用`.model_dump()`转为字典；2. 序列化为 JSON 字符串填入变量；3. 不做字段删减，完整保留 path、method、summary、tag、conflict、is_ai_infer 等标记 |
| {{final_meta_list}} | 融合完成后的中间元数据列表 `List[ApiIntermediateMeta]` | 1. Pydantic 模型`.model_dump()`导出字典；2. 序列化为 JSON 字符串；3. 原样传入风险识别 prompt |

---

### 2.5 Token控制策略

| 策略 | 实现位置 | 说明 |
|------|----------|------|
| 全局素材总 token 上限校验 | `MaterialPreprocessor.process()`素材预处理阶段 |文件解析完成得到全部文本片段；统计**全部素材累计 token**。超过`TOTAL_MATERIAL_TOKEN_LIMIT`直接失败任务，不进入后续流程。|
| 素材分片，控制单分片 token 大小 |MaterialPreprocessor.process() | 分片保留来源信息；不在分片内部做文本裁剪丢弃业务内容，仅在边界切分。后续循环逐个分片调用 LLM，禁止把全部素材一次性塞入单次 Prompt。 |
| 单 LLM 请求 token 预校验 | `LlmClient.chat_json()`LLM 调用前| Prompt 模板 + 填充变量完成之后，估算本次完整请求总 token。 |
| LLM 侧返回超限异常兜底|`LlmClient.chat_json()`捕获大模型返回错误 | 捕获上游 LLM 返回的上下文溢出、max_context exceed 类错误；统一转换为业务异常。 |
| 控制元数据送入 LLM，避免二次 token 膨胀| `AgentWorkflow.run()`多源融合、风险报告环节 | 默认优先代码完成合并、冲突检测、风险识别，不把大量元数据序列化送入 LLM。 |


**上下文截断代码示例**：

```python
def estimate_token(text:str)->int:
    return len(text)//4

def truncate_text_by_token(text:str, max_token:int) -> tuple[str,bool]:
    if estimate_token(text) <= max_token:
        return text,False
    out = text[:max_token*4] + "\n【警告：文本已截断，内容可能丢失】"
    return out,True
```

**输入摘要示例**（以代码生成为例）：

```python
# 不传整个文件，只传类签名+方法签名

def summary_fragment(llm_client, fragment_text: str) -> tuple[str, bool]:
    prompt = (
        "对技术素材压缩摘要，完整保留HTTP接口路径、method、参数、示例；"
        "删除无关描述；不要编造；只输出摘要文本。\n"
        "原始素材：" + fragment_text
    )
    if estimate_token(prompt) >= MODEL_MAX_CONTEXT:
        raise BusinessException(10003, "分片过大无法摘要，请精简素材")
    text = llm_client.chat_raw(prompt)
    return text, True
```

> **说明**：摘要仅在 `ENABLE_CONTEXT_TRUNCATE=True` 时启用；默认关闭，超限直接报 10003。
> `chat_raw` 与 `chat_json` 共用同一份 `MODEL_MAX_CONTEXT` 预算。

---

### 2.6 结果解析

#### 2.6.1 返回格式规范

**成功返回示例**：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "task_id": "tsk‑20260827‑0001"
  }
}
```

**错误返回示例**：

```json
{
  "code": 10001,
  "msg": "参数非法，user_instruction过长",
  "detail": "用户指令不能超过1000字符"
}
```

#### 2.6.2 解析逻辑

```python
def agent_run(inputs):
    # 1.解析文件+预处理分片token校验
    frags = MaterialPreprocessor().process(inputs["files"], inputs["text"])
    # 2.逐分片LLM提取接口元数据
    meta_list = MetaExtractor(llm).extract(frags, inputs["user_instruction"])
    # 3.代码合并、冲突标记、过滤接口
    merged_meta = merge_meta(meta_list)
    # 4.组装OpenAPI文档
    openapi = OpenApiAssembler.assemble(merged_meta, inputs["base_openapi"])
    # 5.校验、计算diff、生成风险报告
    OpenApiValidator.validate(openapi)
    diff = DiffHelper.diff(inputs["base_openapi"], openapi)
    risk_report = RiskReportBuilder.build(merged_meta, frags)
    return {"openapi_json":openapi, "diff_info":diff, "risk_report":risk_report}

```

---

### 2.7 测试策略

| 测试类型 | 测试内容 | 预期结果 |
|----------|----------|----------|
| 功能测试‑基础提取 | 输入 curl、markdown、postman 样例，包含正常 GET/POST 接口 | 正确输出接口 path、method、参数、响应示例；openapi 结构合法；risk_report 无异常告警 |
| 功能测试‑用户指令 | 传入指令：忽略调试接口、只输出查询类接口 | 匹配指令过滤对应接口，无关接口不出现在结果 |
| 功能测试‑增量生成 | 传入 base_openapi 基准文档 + 新素材| diff_info 正确识别 added/modified/deleted；原有接口保留，新增接口合并 |
| 边界测试‑token 超限| 输入超大素材，超过 token 阈值 | 返回错误码 **10003**，提示上下文超限，任务失败，不生成残缺文档 |
| 边界测试‑空输入 | files、text_materials 同时为空 | 参数校验失败，错误码 **10001**，拒绝创建任务|
| 边界测试‑无有效接口 | 上传素材不含任何 HTTP 接口| openapi paths 为空，risk_report 提示未识别到接口，任务成功不报错 |

---

### 2.8 部署与使用

#### 2.8.1 配置项

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| OPENAI_BASE_URL | - | 兼容 OpenAI 协议的大模型服务地址 |
| OPENAI_API_KEY | - | API Key（原文档写的 `claude.api-key` 与 1.5「兼容 OpenAI 协议」矛盾，统一为 OpenAI 协议） |
| MODEL_NAME | gpt-4o-mini | 模型名 |
| MODEL_MAX_CONTEXT | 128000 | 大模型最大上下文窗口 token |
| TOTAL_MATERIAL_TOKEN_LIMIT | 100000 | 全部输入素材累计 token 上限 |
| ENABLE_CONTEXT_TRUNCATE | False | 是否开启文本尾部自动截断；默认关闭，超限直接报错 10003 |
| USER_INSTRUCTION_MAX_LEN | 1000 | 用户自定义指令最大字符长度，超限报 10001 |
| ASYNC_WORKER_TIMEOUT | 300 | 异步任务执行超时秒数 |
| MAX_UPLOAD_FILES | 10 | 单次任务最大上传文件数，超限报 10001 |
| MAX_FILE_SIZE_MB | 20 | 单个上传文件大小上限，超限报 10003 |
| CHUNK_SIZE / CHUNK_OVERLAP | 1500 / 150 | 素材分片字符数与重叠字符数 |

#### 2.8.2 使用方式

**方式一：HTTP API**

| 集成点 | 调用时机 | 具体操作 |
|--------|----------|----------|
| 【集成点1：提交生成任务】 | 需求评审完成 / 版本迭代开始 | `POST /api/v1/openapi/generate`，携带 files + text_materials + user_instruction，返回 task_id |
| 【集成点2：轮询任务状态】 | 提交后每 1s 轮询 | `GET /api/v1/openapi/task/{task_id}/status`，直到 status 为 completed/failed/cancelled |
| 【集成点3：拉取生成结果】 | 状态为 completed | `GET /api/v1/openapi/task/{task_id}/result`，取 openapi/diff/risk_report |
| 【集成点4：接入 CI / 文档站】 | 结果落库后 | 将 openapi 字符串写入接口文档站或 openapi.json，risk_report 推送人工复核工单 |

**方式二：嵌入项目**

```python
from openapi_agent.core.agent_workflow import AgentWorkflow
from openapi_agent.core.llm_client import LlmClient
from openapi_agent.material.extractor import MetaExtractor
from openapi_agent.material.preprocessor import MaterialPreprocessor

llm = LlmClient(base_url="xxx", api_key="xxx", model="gpt-4o-mini")

input_materials = {
    "files": ["demo_api.md", "postman_collection.json"],
    "text_materials": "curl -X GET /api/user/list -H \"token:xxx\"",
    "user_instruction": "过滤调试接口",
    "base_openapi": None,
}

pre = MaterialPreprocessor(files=input_materials["files"], texts=[input_materials["text_materials"]])
extractor = MetaExtractor(user_instruction=input_materials["user_instruction"])
metas, result = AgentWorkflow().run(
    llm,
    pre,
    extractor,
    base_spec=input_materials["base_openapi"],
    generate_mode="strict",
)
# result: {"openapi": dict, "diff": dict|None, "risk_report": dict}

```



---

## 三、与业务系统集成

### 3.1 在简历系统中使用（示例）

| 参数 | 说明| 
|--------|----------|
| files | 上传文件，支持 md/json/postman/zip，最多 10 个 | 
| text_materials | 文本素材，curl、接口描述文本 | 
| user_instruction | 用户指令：过滤接口、生成要求等 | 
| base_openapi | json 字符串，基准 OpenAPI 文档，用于增量生成 | 

---

## 四、评估与验证

### 4.1 成功标准

| 维度 | 指标 | 目标 |
|------|------|------|
| agent成功标准 | 生成结果准确率 | ≥90% |
| agent成功标准| 接口提取覆盖率 | 100% |
| Token稳定性维度 | 超限容错率 | 100% |
| 任务稳定性 | 认为成功率 | ≥90% |
| 响应速度 | 平均响应时间 | ≤10秒 |

### 4.2 验证方法

- 人工抽查：随机选取生成结果，人工校验正确性
- 对比验证：与手工结果对比
- 监控指标：记录Token消耗、响应时间

---

## 五、总结

### 5.1 核心亮点

1. 【亮点1：不依赖 LangChain/LangGraph，纯手工流程可控，无黑盒逻辑、无冗余依赖、性能高、可完全私有化部署。】
2. 【亮点2：支持基准 OpenAPI 对比生成变更 diff，可持续迭代更新接口文档，适配日常迭代场景。】
3. 【亮点3：任务管理、超时控制、取消机制、异常兜底、内存资源自动回收，适配线上服务。】

### 5.2 简历描述示例

```

基于ClaudeCode自研OpenAPI生成 Agent，实现从 curl、Markdown、Postman 等多源技术素材自动生成合规 OpenAPI3.x 接口文档。
采用LLM 仅做语义提取，业务逻辑代码实现的架构，完成素材解析分片、多层 Token 防护、元数据提取融合、冲突识别、增量生成、风险报告输出；支持异步任务管理、任务取消与超时回收。解决大模型幻觉编造问题，对冲突、AI 推断、信息缺失做标记告警，输出结果可人工复核，满足生产使用要求。
```

---

## 附录

### A. 完整Prompt模板示例

模板以外置常量文件形式维护（实现位于 `openapi_agent/core/prompt_templates.py`），共 4 个：

**A.1 通用基础 Prompt（base_system）**

```text
你是 专业 OpenAPI 契约智能解析 Agent，专注从各类杂乱技术素材中精准提取接口元数据。
你具备后端接口、前端联调、接口文档标准化能力。

**永久固定规则**

1. 只提取真实存在的接口，禁止编造不存在接口、禁止脑补字段
2. 输出必须严格 JSON，禁止解释、禁止 markdown、禁止多余文字
3. 识别不确定内容，标记为 AI 推断，不瞎填
4. 识别冲突内容，标记冲突，不自行覆盖
5. 严格区分：真实素材内容 / AI 推测内容 / 冲突内容
```

**A.2 元数据提取 Prompt（extract）**

```text
任务：从用户提供的技术素材中，精准提取所有HTTP接口完整元数据。

要求：
你需要识别并输出以下字段：
- path：接口路径
- method：GET/POST/PUT/DELETE
- summary：接口简要说明
- parameters：路径参数、查询参数列表
- request_body：请求体结构、字段、类型
- response_examples：返回示例
- source_type：当前素材来源（curl/markdown/code/sql/testcase）

输入内容：
1. 技术素材片段：{{material_content}}
2. 用户指令：{{user_instruction}}

只输出 JSON，格式：{"endpoints": [{"path": "...", "method": "...", "summary": "...", "parameters": [], "request_body": {}, "response_examples": null, "source_type": "..."}]}，没有接口时 endpoints 为空数组。
```

**A.3 多源融合 Prompt（fuse）**

```text
任务：对多份素材提取的同一接口元数据进行智能融合、去重、冲突修正。

要求：
1. 相同 path+method 判定为同一个接口，自动合并
2. 真实请求样例（curl、日志）优先级最高
3. 源码注释、SQL表结构次之
4. 文档描述优先级最低
5. 多源字段不一致自动标记 conflict，保留双方信息
6. 缺失字段不脑补，保留空缺
7. 用户指定忽略内部接口、调试接口需要过滤

输入内容：
1. 多源接口原始元数据列表：{{raw_meta_list}}
2. 用户过滤指令：{{user_instruction}}

只输出 JSON，字段：path、method、summary、tag、parameters、request_body、response_examples、error_codes、source、is_conflict、is_ai_infer、notes。
```

**A.4 风险扫描 Prompt（risk_scan）**

```text
任务：对已提取的接口元数据进行风险扫描，识别三类问题：
1. 信息缺失项（缺少响应、缺少参数说明、缺少错误码）
2. 字段冲突项（多素材定义不一致）
3. AI推断项（无原始素材依据，AI补全内容）

输入内容：
接口中间元数据列表：{{final_meta_list}}

只输出 JSON：{"missing_info": [], "conflict_items": [], "ai_infer_items": []}，数组元素用简洁中文描述字符串。
```

### B. 测试用例

| 用例ID | 输入 | 预期输出 |
|--------|------|----------|
| TC001 | curl + markdown 样例，含 GET/POST 正常接口 | path/method/参数/响应示例正确提取，openapi 结构合法 |
| TC002 | `user_instruction="忽略调试接口"` | 调试接口被过滤，不出现在 paths |
| TC003 | `base_openapi` + 新素材 | diff 正确识别 added/modified/deleted，原有接口保留 |
| TC004 | 超大素材超过 `TOTAL_MATERIAL_TOKEN_LIMIT` | 错误码 10003，任务失败，不产出残缺文档 |
| TC005 | `files` 与 `text_materials` 同时为空 | 错误码 10001，拒绝创建任务 |
| TC006 | 素材不含任何 HTTP 接口 | paths 为空，risk_report 提示未识别到接口，任务成功 |
| TC007 | `user_instruction` 超过 1000 字符 | 错误码 10001 |
| TC008 | 上传 11 个文件 | 错误码 10001，超出 `MAX_UPLOAD_FILES` |
| TC009 | 单文件超过 20MB | 错误码 10003 |
| TC010 | `generate_mode=strict` 且产物不合规范 | 任务失败，返回规范校验错误 |
| TC011 | `generate_mode=fast` 且产物不合规范 | 任务成功，校验错误写入 risk_report.validation_errors |
| TC012 | 单文本块抽取失败 | 跳过该块，其余块正常产出（降级） |
| TC013 | 多源融合调用失败 | 回退首份素材，强制 is_conflict=true（降级） |
| TC014 | 风险 LLM 扫描失败 | 保留确定性规则扫描结果（降级） |
| TC015 | 任务执行中调用 cancel | status 置 cancelled，取结果返回错误 |

### C. 参考文档

- OpenAI 兼容 API 文档（Chat Completions / JSON Mode）
- OpenAPI 3.0.3 与 3.1.0 规范
- openapi-spec-validator、deepdiff、Pydantic v2 官方文档

### D. 设计 ↔ 实现对照表

本设计文档与仓库实现（`openapi_agent/`）逐条对齐，对照如下：

| 设计条目 | 实现位置 |
|---|---|
| 2.1.1 四个对外接口 | `api/routes.py`（`/api/v1/openapi/generate`、`task/{id}/status`、`task/{id}/result`、`task/{id}/cancel`） |
| 2.1.2 错误码 | `core/errors.py` 的 `ErrorCode`；HTTP 映射见 `api/exception_handler.py` |
| 2.2.1 包结构 | `openapi_agent/` 完整目录，与本文档一致（额外新增 `core/llm_factory.py`、`api/validators.py`、`api/service.py`） |
| 2.2.2 `BusinessException` | `core/errors.py` |
| 2.2.2 `Task` / `TaskStatus` | `core/task.py`（`progress: int`，11 个状态） |
| 2.2.2 `TaskManager` | `core/task_manager.py`（`create_task(task_id, dict)` / `cancel_task` 抛 10002 / `new_task_id()`） |
| 2.2.2 `AgentWorkflow` | `core/agent_workflow.py`（`run()` 返回 `(metas, {openapi, diff, risk_report})`，另含 `run_task()` / `run_with_timeout()`） |
| 2.2.2 `LlmClient` | `core/llm_client.py`（`chat_json` 预算预校验 + 纠错重试，`chat_raw` 供摘要使用） |
| 2.2.2 `MaterialPreprocessor` | `material/preprocessor.py`（`process()` 无参，构造注入 files/texts） |
| 2.2.2 `FileParser` | `material/file_parser.py`（`parse(path)`） |
| 2.2.2 `MetaExtractor` | `material/extractor.py`（`extract(llm_client)`，两阶段抽取+融合） |
| 2.2.2 `ApiIntermediateMeta` | `model/intermediate_meta.py`（新增 `summary` / `response_examples` / `error_codes`） |
| 2.2.2 `OpenApiAssembler` | `builder/openapi_assembler.py` +「返回示例→Schema」推导 `builder/schema_builder.py` |
| 2.2.2 `OpenApiValidator` | `builder/validator.py`（失败抛业务异常，由 `generate_mode` 决定是否中断） |
| 2.2.2 `DiffHelper` | `builder/diff_helper.py` |
| 2.2.2 `RiskReportBuilder` | `report/risk_report_builder.py`，模型见 `model/openapi_build_model.py` |
| 2.3.1 主流程 | `core/agent_workflow.py::run_task()` |
| 2.3.2 / 2.5 Token 控制 | `core/token_budget.py` + `material/preprocessor.py` + `core/llm_client.py` |
| 2.4 Prompt 设计 | `core/prompt_templates.py`（4 个模板常量 + `render`） |
| 2.6 结果解析 | `api/schemas.py`（`{code, msg, detail}` 与 `{task_id, status, openapi, diff, risk_report}`） |
| 2.8.1 配置项 | `config.py`（`Settings`，全部支持环境变量覆盖） |
| 2.7 测试策略 | `tests/`（63 个单测，TC001–TC015 已覆盖）+ `scripts/smoke_http.py`（36 项端到端 HTTP 冒烟，配合 `scripts/mock_llm_server.py` 无需真实模型） |

**实现中与本文档的已知差异**（均已在此处定稿）：

1. 校验失败行为由 `generate_mode` 决定：`strict` 抛错、`fast` 写入 `risk_report.validation_errors`。
2. Token/上下文超限统一为 `10003`，不再使用 `10004`。
3. 「系统配置与会话管理模块」目前只落地了配置（`config.py`），会话上下文与迭代调整尚未实现。
4. 用户指令过滤（如「忽略调试接口」）通过 Prompt 交给 LLM 完成，尚无确定性规则预过滤。
