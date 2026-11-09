# 决策服务上游适配

服务核心从同步入口调用 `decision_service.providers`。两函数的 JSON 形状见 [v1 合同](api-contract.md#服务内部并行实现接缝)。

```python
from decision_service.providers import call_decisions, retrieve_evidence

provider_settings = settings.provider_settings()
retrieval = retrieve_evidence(validated_request, resolved_bank_ids, provider_settings)
decision = call_decisions(validated_request, retrieval["evidence"], provider_settings)
```

核心在调用前解析并校验 bank 范围，保留 `retrieval["banks"]` 的逐 bank 状态，并按本次冻结候选解析模型返回的 ID。适配器内部使用 HTTPX 异步传输。同步函数从普通线程调用，异步入口需将同步调用调度到线程。

架构分流为 `BOUNDARY_NOTE`。服务设置向现有 provider 接缝增加可选的 `hindsight_api_mode`，默认走原生 REST。S 持有授权和持久化，P 持有只读召回适配，VPS 网关持有上游重试。用两种协议的 HTTP 替身核对原请求、片段来源和失败状态。

## 原生协议

- Hindsight 以 `POST /v1/default/banks/{bank_id}/memories/recall` 检索解析后列表中的每个 bank。请求使用 `question` 作为 `query`，不附加完整决策上下文。建议让问题本身包含检索所需主题。原生响应的 `results[].id` 映射为 `memory_id`，可得的 `document_id` 原样保留。bank 来源来自本次实际请求路径。参见 [原生 Recall API](https://hindsight.vectorize.io/developer/api/recall) 与 [鉴权和路径](https://docs.hindsight.vectorize.io/api-reference/recall-memories/)。
- 片段可附带 recall 响应中的 `occurred_start`、`occurred_end` 和 `mentioned_at`。前两项是 Hindsight 从内容提取的事件时间范围，后一项是事实写入 bank 的时间。保留原始时间字符串，缺失时省略对应字段。参见 [Recall 结果字段](https://hindsight.vectorize.io/developer/api/recall#occurred_start--occurred_end)。
- OpenAI 以 `POST /v1/decisions` 请求 `gpt-6-luna`，每次传一个问题。choice 传候选 ID 和描述，score 按输入顺序传等级，predicate 传待判断命题。共享输入包含当前上下文、候选参数和必要记忆片段。返回按 v1 形状规范化，score 保留原生概率加权值和零基等级索引。refusal 单独返回。参见 [Decisions API 参考](https://developers.openai.com/api/reference/resources/decisions/methods/create) 和 [等级与评分语义](https://developers.openai.com/api/docs/guides/decisions#score-against-a-rubric)。
- `decision_model.model` 取自响应中的 `model`，缺失时留空并记为 `unconfirmed`。`requested_model` 单独保存。usage 保留原生可得的输入、输出、总 token 计数以及缓存和推理 token 明细。缺失的计数留缺省。

## OpenAI Decisions 官方返回类型

以下为 OpenAI 原生合同；本服务的规范化输出另见下节，不把两者混用。

| 版本与时间 | 记录 |
| --- | --- |
| 本节文档版本 | **v1.0**；仅为本仓说明的维护版本，不是 OpenAI API 或模型版本。 |
| 更新时间 | **2026-11-09 07:05 UTC / 北京时间 2026-11-09 15:05**。 |
| 官方资料核验日期 | **2026-11-09**；[Decisions 指南](https://developers.openai.com/api/docs/guides/decisions)、[Create decision 参考](https://developers.openai.com/api/reference/resources/decisions/methods/create)和[错误码指南](https://developers.openai.com/api/docs/guides/error-codes)为在线文档，核对页面未标明独立的合同/schema 版本号。不要把本节版本或核验日期当作上游版本号。 |
| 实现对照基线 | Decision Service [45bf3a9](https://github.com/CF-FE/decision-service/tree/45bf3a99423fe4e5618febe56badccf170eaf126)；Hindsight API Slim **1.2.0** 对照固定上游提交 [34a1386](https://github.com/vectorize-io/hindsight/tree/34a138684a899b6ec34175f7a2b633860466d289)。运行中的安装/补丁状态须另行读回，不能仅凭本文判定。 |

后续变更本节时递增文档版本，更新上述时间、资料核验日期与实现基线，并在下表记录变化；历史内容可按对应 Git 提交追溯。

| 文档版本 | 更新时间 | 变更 |
| --- | --- | --- |
| v1.0 | 2026-11-09 07:05 UTC / 北京时间 15:05 | 首次整理四种答案、逐题拒答、批量限制、服务映射和证据边界；增加版本、时间与固定实现基线。 |

### 请求与响应外壳

Decisions 用于有限类型判断，不负责生成任意 JSON、文字解释或执行动作。当前官方指南使用 `POST /v1/decisions`（SDK 为 `client.decisions.create(...)`），支持模型为 `gpt-6-luna`。`input` 提供共享证据，`questions` 定义问题、候选或有序等级。官方支持文本、图像和 JSON 输入；本服务当前适配器将上下文与片段序列化为文本，不因此自动获得新的多模态入口。[官方指南](https://developers.openai.com/api/docs/guides/decisions#how-decisions-work)

原生响应顶层为 `answers`、`model`、`usage`。`answers` 按问题顺序返回，逐项用 `type` 区分答案；`name` 回显问题名，未命名时为 `null`。建议为多题请求提供唯一名称，同时核对数量、顺序与对应类型，不能只取第一项或跳过拒答后错配候选。`model` 是返回型号，`usage` 是整次请求的 token 用量，不是每个答案各自的用量。[响应 schema](https://developers.openai.com/api/reference/resources/decisions/methods/create)

### 四种答案

| `answers[].type` | 原生字段（除 `type` 外） | 解释 |
| --- | --- | --- |
| `predicate` | `name`、`probability` | 判断一个条件是否成立，例如“该片段是否有助于回答问题”。返回成立的估计概率，范围 0–1；不是布尔值，也没有该类型的独立 `confidence` 字段。 |
| `choice` | `name`、`choice`、`confidence`、`probabilities` | 从给定的无序候选中选一项，例如把工单分到售后/技术支持；分布元素为 `{value, probability}`。原生 `choice`/`value` 可以是字符串或布尔值，`true` 与 `"true"` 不同。 |
| `score` | `name`、`score`、`confidence`、`probabilities` | 对有序等级评分，例如故障严重程度；分布元素为 `{label, value, probability}`，`value` 为等级的零基整数索引。`score` 是索引的概率加权平均，不是必然为整数的等级选择。 |
| `refusal` | `name` | 模型拒绝回答这一题，调用方应进入该业务允许的拒答/回退处理，而非据此作肯定或否定判断。当前 schema 只定义 `name` 和 `type`，没有答案值、概率、置信度或拒答原因字段。 |

字段依据[官方返回 schema](https://developers.openai.com/api/reference/resources/decisions/methods/create)；概率及评分语义依据[问题类型](https://developers.openai.com/api/docs/guides/decisions#choose-a-question-type)和[有序评分](https://developers.openai.com/api/docs/guides/decisions#score-against-a-rubric)。例如三级的概率依次为 0.2、0.5、0.3，`score = 0×0.2 + 1×0.5 + 2×0.3 = 1.1`；不能把 1.1 当作“110% 置信度”或直接当候选 ID。

官方将 `confidence` 与概率分布分别列出；本次核对的指南和 schema 没有给出它的计算公式，不能自行认定它等于最大概率或校准后的正确率。路由、过滤和人工复核阈值应根据应用的标注样例与误判代价确定，不将任一数值当作事实保证、授权或执行回执。[Interpret the answers](https://developers.openai.com/api/docs/guides/decisions#interpret-the-answers)

### `type=refusal` 与批量处理

**拒答是逐题的答案分支，不是第四种可提交的问题类型。** `questions[].type` 为 predicate、choice 或 score；任一问题都可能返回 refusal，同一请求中的其他题仍可返回正常答案。下列为自拟的 `answers` 片段，省略顶层 `model`/`usage`，不是生产请求证据：

```json
{
  "answers": [
    {"type": "predicate", "name": "candidate_a", "probability": 0.8},
    {"type": "refusal", "name": "candidate_b"}
  ]
}
```

读取时先检查每项 `type`，再访问该类型字段。上例第二题没有 `probability`，不能补成 0、false、确定无关或成功判断。是否保留其他答案由调用方的业务边界决定；全部拒答不等于有效空结果。[官方 per-question refusal 定义](https://developers.openai.com/api/reference/resources/decisions/methods/create)

截至核验日，官方没有在上述 Decisions 文档中说明具体拒答触发规则，也没有给出“证据不足即拒答”的约定。仅见 `type=refusal` 无法断定是安全原因、证据不足、限流或并发过高；低概率/低置信度也不等同拒答。

请求级 HTTP 错误与逐题 refusal 分开处理。HTTP 429 还需检查错误类别/代码及相关响应头，区分请求速率、额度等原因；超时只说明本次未取得可确认结果。不能从 Hindsight 外层 500 或末次 refusal 反推曾发生 429，也不能由异常文本中的重复行计算请求次数。[OpenAI 错误码](https://developers.openai.com/api/docs/guides/error-codes)、[本次故障证据边界 #6](https://github.com/CF-FE/decision-service/issues/6)

当前 `questions` 每请求为 **1–400 题**。独立问题可共享输入放入一次请求；依赖前一题答案的问题应分开请求。这是同步 Decisions 多题调用，不是另建 Batch API 作业；服务本身仍一次只提交一题。请求容量应读取 `questions` 限制，不能把返回数组 schema 的上界或 Hindsight 通用分批常量当作可提交题数。[多题指南](https://developers.openai.com/api/docs/guides/decisions#ask-multiple-questions)、[请求 schema](https://developers.openai.com/api/reference/resources/decisions/methods/create)

### 本服务的映射与状态

以下依据本仓 [provider 实现](../src/decision_service/providers.py)与[核心映射](../src/decision_service/app.py)，不是 OpenAI 原生字段：

| 原生结果/传输结果 | provider 返回 | 对外决策记录 |
| --- | --- | --- |
| 合法 predicate/choice/score | `status=ok`，规范化 `answer` | 核心再核对冻结候选及其 metadata；可建议，也可要求复核/重规划。 |
| `type=refusal` | `status=refused`，`answer={"type":"refusal","reason":"provider_refusal"}` | `status=complete`、`disposition=abstain`，无可执行参数。`provider_refusal` 是本地分类码，不是上游披露的拒答原因。 |
| HTTP 429 等普通上游失败 | `status=unavailable`、`answer=null`，例如 `openai_http_429` | `status=complete`、`disposition=unavailable`；完整记录不等于业务成功。 |
| OpenAI 超时 | `status=unavailable`、`answer=null`、`openai_timeout` | `status=unknown`、`disposition=null`，不伪造答案。 |
| 数量、类型或值校验失败 | `status=unavailable`、`answer=null`、`openai_invalid_response` | 与明确 refusal 分开，不能当作否定答案。 |

规范化只保留合同约定字段：choice 使用字符串 `candidate_id`，不接受原生布尔候选；score 保留加权数值和整数索引分布；当前不透传原生 `name`、`confidence` 或 score 分布的 `label`。调用方须读 [v1 合同](api-contract.md#服务内部并行实现接缝)，不能假定原生字段都会出现。Hindsight 自己的 OpenAI provider 不经过这个映射，其拒答传播问题见 [Hindsight 说明](hindsight-decision-models.md#逐题拒答与-hindsight-安装版行为)。

## Hindsight VPS 网关

设置 `hindsight_api_mode=gateway` 时，`hindsight_base_url` 使用网关带部署前缀的根地址，适配器追加 `/api`。使用专用于该网关的只读 Bearer 凭据。每个获准 bank 发送一个 `recall` 请求，其 arguments 为 `bank_id`、`query` 和 `max_tokens`。请求取得并行名额后才计算剩余网络预算，向网关传递的 `timeout_seconds` 最多为 180 秒。网关管理自身的上游尝试。

逐层核对 HTTP 状态、工具错误、relay 状态、原生 HTTP 状态、动作和 bank 引用，通过后才读取 `body.results`。正常返回的空数组记为 `empty`。失败或无法核实的回执记为 `failed`，原因码不带上游正文。来源和字符预算沿原生模式的处理。参见 [VPS 网关合同](https://github.com/ghyghoo8/create-network-sh/blob/main/fastmcp/hindsight-memory/README.md) 和 [Win API relay 实现](https://github.com/CF-FE/herdr-4-codexcloud/blob/main/mcp/hindsight-memory/api_relay.py)。

## 运行边界

| 配置 | 用法 |
| --- | --- |
| `hindsight_api_mode`、`hindsight_base_url`、`hindsight_api_key` | 默认 `native`，base URL 是原生 REST 根地址，允许部署前缀。显式 `gateway` 使用上述网关路径和专用凭据。缺少地址或网关凭据时逐 bank 返回 skipped。原生无鉴权实例可省略密钥。 |
| `openai_base_url`、`openai_api_key`、`openai_model` | REST 根地址默认 `https://api.openai.com`，密钥单独注入，型号默认 `gpt-6-luna`。缺少密钥或配置其他型号时返回 unavailable。 |
| `timeout_seconds`、`max_parallel_banks` | recall 批次共用一个网络截止时间，等待并行名额也计入。保留截止前返回的各 bank 结果。Decisions 单次调用另用一个截止时间，核心可分别传剩余预算。 |
| `evidence_max_chars` | 全批次片段文本的字符上限。各 bank 按自身结果顺序交错取片段，尾片段按剩余字符截取。来源 ID 和 JSON 结构另计。recall 每 bank 的原生 `max_tokens` 最多 4096，并受配置的字符预算限制。 |

两种根地址均不带适配器将追加的 `/v1`。传输使用独立 Bearer 凭据，不跟随重定向，不读取环境代理。错误只暴露简短的原因码。普通 HTTP、网络、超时和响应格式错误按函数合同返回，调用链异常交给核心记录。Hindsight 状态 `ok` 表示该 bank 有可用结果，最终片段仍受全批次预算限制。

## 隔离验证

```sh
rtk proxy .venv/bin/python -m pytest tests/test_providers.py -q
```

在项目共用环境的 Python 3.11.15、HTTPX 0.28.1 上验证。专项用例通过 `MockTransport` 检查请求、跨 bank 部分失败、字符预算、截止时间、类型映射和消耗读回。另使用当前服务入口、临时 SQLite 与同类上游替身验证了检索部分失败时的判断持久化、重新打开后按请求 ID 查询和重放。正式入口的连通性、凭据和真实判断效果待独立验收。
