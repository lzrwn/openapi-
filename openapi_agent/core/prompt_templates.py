"""Prompt 模板常量与变量填充。

设计文档 2.2.1 / 2.4.1 要求模板以常量形式维护在本模块，共 4 个：
BASE_SYSTEM / EXTRACT / FUSE / RISK_SCAN。
"""

BASE_SYSTEM = """你是 专业 OpenAPI 契约智能解析 Agent，专注从各类杂乱技术素材中精准提取接口元数据。
你具备后端接口、前端联调、接口文档标准化能力。

**永久固定规则**

1. 只提取真实存在的接口，禁止编造不存在接口、禁止脑补字段
2. 输出必须严格 JSON，禁止解释、禁止 markdown、禁止多余文字
3. 识别不确定内容，标记为 AI 推断，不瞎填
4. 识别冲突内容，标记冲突，不自行覆盖
5. 严格区分：真实素材内容 / AI 推测内容 / 冲突内容"""

EXTRACT = """任务：从用户提供的技术素材中，精准提取所有HTTP接口完整元数据。

要求：
你需要识别并输出以下字段：
- path：接口路径
- method：GET/POST/PUT/DELETE
- summary：接口功能名称，必须用**通俗易懂的简体中文**概括这个接口做什么（例如「查询商品列表」「创建订单」「删除购物车商品」），禁止直接照抄 path 或写成「GET /xxx」
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

只输出 JSON，格式：{"endpoints": [{"path": "...", "method": "...", "summary": "...", "tag": "...", "parameters": [], "request_body": {}, "response_examples": null, "error_codes": [], "source_type": "..."}]}，没有接口时 endpoints 为空数组。"""

FUSE = """任务：对多份素材提取的同一接口元数据进行智能融合、去重、冲突修正。

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

只输出 JSON，字段：path、method、summary、tag、parameters、request_body、response_examples、error_codes、source、is_conflict、is_ai_infer、notes（冲突或推断说明放 notes）。
summary 用通俗易懂的简体中文功能名称，tag 用简体中文业务分组名，二者不要照抄 path。"""

RISK_SCAN = """任务：对已提取的接口元数据进行风险扫描，识别三类问题：
1. 信息缺失项（缺少响应、缺少参数说明、缺少错误码）
2. 字段冲突项（多素材定义不一致）
3. AI推断项（无原始素材依据，AI补全内容）

输入内容：
接口中间元数据列表：{{final_meta_list}}

只输出 JSON：{"missing_info": [], "conflict_items": [], "ai_infer_items": []}，数组元素用简洁中文描述字符串。"""

SUMMARY = """对技术素材压缩摘要，完整保留HTTP接口路径、method、参数、示例；删除无关描述；不要编造；只输出摘要文本。
原始素材：{{fragment_content}}"""


def render(template: str, **variables: str) -> str:
    for key, value in variables.items():
        template = template.replace("{{" + key + "}}", value)
    return template
