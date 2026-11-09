# MVP 公共合同 v1

状态：2026-11-09 两仓审查会话已互审通过，冻结为并行实施合同 v1.0；由本仓维护，三个实现会话共用。细化[架构](architecture.md)和[反馈语义](outcome-feedback.md#最小反馈合同)，不改变它们的数据归属与业务授权。实现状态、会话和回执归本地任务队列，不以本文存在宣称接口上线。

## 范围与共同约定

- 一个 HTTP 核心与 SQLite；消费者通过 HTTP 调用，不直接读服务数据库。JSON 使用 UTF-8，`schema_version` 固定为 `1`（整数）。时间为带时区的 ISO 8601 字符串。
- 静态 Bearer 凭据映射受信 `caller_scope`、允许的项目及 bank。调用者正文中的 project/producer 不授予权限；默认监听 loopback，正式入口沿部署配置接入。测试使用隔离凭据，不读取或复制原 Win 密钥。
- Herdr 两种预设要求 `project_id`、`subject_ref` 和稳定 `request_id`；普通有限问题可省略项目/执行关联。无原生 ID 的字段可空或省略，不能制造原生 run/action/attempt。
- 对需要摘要的 JSON，递归排序对象键、紧凑分隔、UTF-8、保留数组顺序、禁止 NaN/Infinity，计算 SHA-256。服务计算实际输入/候选摘要；调用方保存请求并核对回显，不用本地推测替代服务摘要。
- 秘密只在配置/传输边界使用，不进请求快照、反馈、错误正文或日志。现金费用不作为消耗计量采集；usage 可省略/null，缺省不是 0。此约束不禁止普通 question/context 中原本属于业务事实的财务内容，不对整个请求做财务关键词黑名单；现成 usage 附带费用/估价时，在计量边界忽略这些字段，保留有效执行/质量反馈，不因可选现金字段拒收整条结果。

## HTTP 操作

| 方法与路径 | 核心操作 | 结果 |
| --- | --- | --- |
| `POST /v1/decisions/evaluate` | evaluate_decision | 创建或重放同一决策请求 |
| `GET /v1/decisions/{decision_id}` | get_decision | 按决策 ID 只读查询记录及关联反馈 |
| `GET /v1/decisions?request_id=...` | get_decision | 同一受信作用域按调用者请求 ID 找回记录，覆盖首次响应丢失 |
| `POST /v1/decision-feedback` | record_decision_feedback | 持久接收应用、结果和带来源纠正 |
| `GET /health` | 运行检查 | 不暴露凭据、项目或 bank 清单，可不鉴权 |

MCP 若接入，映射相同三个核心操作；不复制模型逻辑、SQLite 或幂等命名空间。具体 SDK/框架不改变本合同。

## evaluate 请求与响应

| 请求字段 | 语义 |
| --- | --- |
| `schema_version`, `request_id` | 版本和调用者请求标识；通用问题未给 ID 时由服务生成，但不承诺客户端丢失响应后可定位 |
| `preset` | 可省略，或 `workflow_next_action` / `role_model_selection` |
| `kind`, `question`, `context` | `choice` / `predicate` / `score`；问题为字符串，context 为 JSON 对象 |
| `choices` | choice 的候选数组；每项含唯一 `candidate_id`、`description`、JSON 对象 `parameters`，可带 `metadata`；冻结 ID 到参数的完整映射 |
| `levels` | score 的有序等级数组，每项为 label/description；predicate/score 按 OpenAI 有限回答语义处理，不冒充可执行动作 |
| `project_id`, `subject_ref`, `snapshot` | 来源项目、原任务/工作单元引用、原状态/候选快照；subject_ref 为原系统字段对象，snapshot 为其版本/摘要对象，不能把这些字段冒称原模板已有字段 |
| `bank_ids`, `recall` | bank 选择可省略；`recall` 为 `auto`（默认）或 `skip`。只能取有效可读集合；越界不悄悄裁剪为成功 |
| `expects_application` | 布尔值，默认 false；两种执行预设由消费者明确声明，以形成应用反馈的预期范围 |

bank 选择由 S 负责：显式 bank_ids 按有效范围校验；省略且 recall=auto 时，只取配置的 project→默认 bank 映射，无映射则跳过并报告 `no_default_banks`，不把全部允许集合自动传给 P。跨项目 bank 可显式选择或列入该项目的已配置默认集合；P 只检索收到的解析后列表。

Herdr 集成的 subject_ref 使用字符串 `task_id`、`unit_id`，以及 `unit_id_source=native/adapter`；workflow 另带字符串 `step`、`source_sha256`、`input_sha256`，workflow_id 可选。task_id 是源端原任务的稳定定位引用，不冒称模板原生 run_id。snapshot 使用字符串 `state_digest` 与 `candidate_digest`；前者只覆盖会影响本次选择的业务状态，排除 decision/outbox 等适配记账字段，后者对应本次完整 choices。来源已有 state_version 可附带，不能捏造。

execution_ref 固定为可空对象 `{"source":"herdr","ids":{"session_id":"...","turn_id":"..."}}`：source 为来源系统名，ids 仅保留实际可得的字符串原生引用（如 action_id/attempt_id/pane_id/session_id/thread_id/turn_id）。没有这些原生引用就省略对象或留 null，不能拿稳定 unit_id 填成原生 attempt_id。scope_ref、evidence_refs 和 result_refs 中的引用是源端提供的字符串，服务不自动访问其指向位置。

输入摘要包含完整实际请求、候选参数及解析后的预设版本/内容，不只是 question。相同受信作用域内，同 request_id 不同输入返回冲突；已完成请求重放返回原记录，不再调用 provider。正在处理的同 ID 不并行启动第二次判断。进程中断导致 provider 结果不可确认时保留 unknown；不宣称可向 OpenAI 找回未保存答案。重算若实施，按[超时合同](architecture.md#超时与查询)保留尝试及总预算，不另建后台恢复平台。

决策记录统一包含：`schema_version`、`request_id`、`decision_id`、`status`、`disposition`、`answer`、`candidate_id`、`parameters`、原 `project_id/subject_ref/snapshot`、`input_digest`、`candidate_digest`、`evidence_refs`、`retrieval`、`decision_model`、`attempts`，以及可选 `usage`。查询另外返回关联反馈、质量修订及 coverage；不因查询发送反馈或推进业务。

- `status` 为 `processing` / `complete` / `unknown`。只有有有效建议的完整记录才能应用；processing/unknown 不提供可执行参数。
- `disposition` 为 `suggested` / `abstain` / `needs_review` / `needs_replan` / `unavailable`，处理中或状态未知可为空。完整响应也可能是 unavailable，不代表业务成功。
- `answer` 保留 choice/predicate/score/refusal 的不同类型。两种执行预设使用 choice；`candidate_id/parameters` 只从本次冻结候选取回，不接受模型生成的命令。
- workflow 的“候选均不适合”在 metadata 中固定 `executable=false`、`disposition=needs_replan`，被选中时映射到 needs_replan；角色能力筛选为空返回 unavailable。只有一个明确合法候选或确定规则足够时可跳过模型，记录 `decision_model.status=not_invoked`，不伪造调用量。
- `retrieval` 保存每个已选 bank 的 ok/empty/failed/skipped 状态及必要来源片段，部分失败可利用现有上下文继续。输入充分可 skip，不默认扫全部 bank。
- `evidence_refs` 至少含可经 get_decision 定位的记录引用；它是判断来源，不是用户批准或业务验收证据。

模型配置记录使用 `provider`、`model_type`、`model`、`reasoning_effort`；类型/型号沿实际候选和宿主声明，不预设统一类型枚举。实际配置另附 `configuration_status=confirmed/unconfirmed`，强度另附 `effort_status=set/not_applicable/unconfirmed`。未知值留 null，不拿推荐值补成实际值。服务判断模型与候选的执行模型分开；原生接口无强度参数时记 not_applicable。

## 反馈及来源观察

反馈外壳包含 `schema_version`、`project_id`、`event_id`、正整数 `revision`、`kind`、非空 `decision_ids`、`subject_ref`、`observed_at`、`payload`；`execution_ref` 可省略。程序反馈另需 `execution_state`（not_started/running/ended/unknown）；引用为空不自动推出 not_started。producer 身份由认证作用域绑定，正文来源标签仅用于说明。

application/result 的 project_id 必须是获准来源项目。通用问题原本没有 project_id 时，correction 可以显式使用 null，但只能关联同 caller_scope 下同为 null 项目的决策，不得因此读写其他项目；不要为了纠正普通问题伪造项目。服务存储需使 null 项目下的事件幂等键同样唯一。

首版 application 每条绑定一个 decision_id，分别表达该候选的实际采用；同一执行的 result 可以关联多个 decision_ids。避免一条只有单个 recommended_candidate_id 的 application 冒称同时应用了不同的工作流与模型候选。

| kind | payload 的必要内容 |
| --- | --- |
| `application` | `application_status`（applied/not_applied/stale/failed/unknown）、推荐候选与实际动作/配置及原因；模型选择保存 recommended/launch/effective 三层，只有 effective 已确认才算配置采用 |
| `result` | `execution_status`（completed/failed/cancelled/unknown）、原结果/产物引用、`quality_status`（passed/failed/pending/unknown）及 `evidence_refs`；取消请求不冒充 cancelled；现成 usage 可附带 |
| `correction` | 带来源的纠正文本、目标引用和理由；人工意见不自动成为执行事实或验收结论，不计入两类程序反馈回收数量 |

程序反馈须带来源端单元观察 `coverage_observation`：`scope_ref`、`observed_at`、`scope_complete` 和 `units`。units 每项保存原稳定单元/执行引用、最后观察状态（pending/ended/unknown）及是否应回传 result；最小可只观察当前单元，并明确范围不完整。result 缺失时可随 application 的新修订回传已知终态，不能只从已收 result 反推分母。这是原端清单的观察，不复制其状态机；没有可靠引用或完整范围时明确 UNKNOWN。后续质量结论用新 revision，不增加执行或结果计数。

去重键为受信产生端作用域、project_id、event_id、revision。同键同内容重投返回原接收结果；同键不同内容冲突。修订保留替代关系，迟到旧版本不覆盖新结论。多个 decision_ids 可关联同一执行；所有被引用决策须在相同获准项目范围，原用量按执行引用去重。具体质量/覆盖率语义仍以[反馈文档](outcome-feedback.md)为准。

revision 从 1 开始；后续修订是完整快照，外壳增加 `supersedes_revision`（小于当前 revision）。前序暂未到达时可接收并保留修订缺口，最新修订按 revision 确定，迟到旧版不回滚当前结果。event_id 固定同一语义事件/原单元，不能通过修订把它挪给另一执行。

服务将事件、修订、必要关联和接收状态在同一短事务中提交后，返回 `receipt_id`、`event_id`、`revision`、`received=true`、`duplicate`。HTTP 成功表示已收回，不表示业务或质量通过。原端收到确认后才更新待传状态；响应丢失使用原 ID/修订补传，不重新执行业务。

### 字面字段与最小样例

以下仅为协议样例，不是运行数据。`coverage_observation` 和 `execution_state` 均在反馈外壳。units 的固定字段是 `unit_id`、`state`、`expects_result`、可选 `execution_ref`；unit_id 沿源端稳定单元键，适配器生成时在 subject_ref 中以 `unit_id_source=adapter` 标明并持久保留，不冒充原生 ID。

application 的固定 payload 键为 `application_status`、`recommended_candidate_id`、`effective_candidate_id`、`reason_codes`、`evidence_refs`；模型任务另带 `recommended_model`、`launch_model`、`effective_model`，沿前文模型配置对象。result 的固定 payload 键为 `execution_status`、`quality_status`、`result_refs`、`evidence_refs`，模型任务另带 `effective_model`；纯程序单元不要求捏造模型。correction 使用 `target_ref`、`text`、`reason_codes`、`evidence_refs`，不直接改写事实计数。

```json
{
  "schema_version": 1, "project_id": "example", "event_id": "unit-1.application",
  "revision": 1, "kind": "application", "decision_ids": ["d-workflow"],
  "subject_ref": {"task_id": "task-1", "step": "review", "unit_id": "unit-1", "unit_id_source": "adapter"},
  "observed_at": "2026-11-09T10:00:00+08:00", "execution_state": "running",
  "coverage_observation": {"scope_ref": "task-1", "observed_at": "2026-11-09T10:00:00+08:00", "scope_complete": false,
    "units": [{"unit_id": "unit-1", "state": "pending", "expects_result": true}]},
  "payload": {"application_status": "applied", "recommended_candidate_id": "continue", "effective_candidate_id": "continue",
    "reason_codes": [], "evidence_refs": ["decision://d-workflow"]}
}
```

同一单元的 result 使用新的稳定事件 ID；下面示例为不涉及模型的程序执行。模型配置应用单独保留其 application 事件，后续实际同一执行的 result 可把 decision_ids 扩为多个关联决策，不重复生成执行结果。

```json
{
  "schema_version": 1, "project_id": "example", "event_id": "unit-1.result",
  "revision": 1, "kind": "result", "decision_ids": ["d-workflow"],
  "subject_ref": {"task_id": "task-1", "step": "review", "unit_id": "unit-1", "unit_id_source": "adapter"},
  "observed_at": "2026-11-09T10:01:00+08:00", "execution_state": "ended",
  "coverage_observation": {"scope_ref": "task-1", "observed_at": "2026-11-09T10:01:00+08:00", "scope_complete": false,
    "units": [{"unit_id": "unit-1", "state": "ended", "expects_result": true}]},
  "payload": {"execution_status": "completed", "quality_status": "pending", "result_refs": ["artifact://result-1"], "evidence_refs": []}
}
```

质量补齐时仍用 `unit-1.result`，发送完整外壳和 payload：`revision=2`、`supersedes_revision=1`、新 observed_at、`quality_status=passed` 及实际 `evidence_refs`，其他事实保持原单元。不是另造一个执行事件，也不是只发上述差异字段。

get 的 `feedback` 为所关联事件的完整已收修订数组，每项回显原外壳并增加 `receipt_id` 和 `is_current`。`coverage` 固定结构如下；只统计本次查询可见且关联的原端观察范围，计数不可确认时用 null，零分母的 rate 为 null。scope_complete=false 时不得将局部率宣传为全部回收。

覆盖单元按 `(caller_scope, project_id, scope_ref, unit_id)` 定位。同一事件先按 revision 取有效修订，再按 coverage_observation.observed_at 选择该单元的最新观察；不同范围的观察不得直接合并为全量。旧 revision 或更早观察不能把已知 ended 退回 pending；显式新修订纠正保留来源和替代关系。同时间的来源观察互相矛盾时该单元保留 unknown，不以接收先后当业务顺序。没有可靠观察时，无法确认的分母/数量保持 null，不默认填 0。

```json
{"coverage": {
  "application": {"expected": 1, "received": 1, "rate": 1.0},
  "result": {"expected_ended": 1, "received": 1, "rate": 1.0},
  "pending": 0, "missing": 0, "unknown": 0, "quality_pending": 0,
  "scope_complete": false, "observed_at": "2026-11-09T10:02:00+08:00"
}}
```

## 错误与消费者行为

| 情况 | HTTP / error.code | 消费者行为 |
| --- | --- | --- |
| JSON/字段不合法 | 400 / invalid_request | 修正请求；不把解析失败当默认候选 |
| 未鉴权 | 401 / unauthenticated | 停止该调用，沿原配置处理 |
| 项目或检索范围越界 | 403 / forbidden_scope | 不扩大身份/权限，不尝试其他项目凭据 |
| 记录不存在或不可见 | 404 / not_found | 保留未知，不据此重执行业务 |
| request_id 或事件修订内容冲突 | 409 / input_conflict 或 revision_conflict | 查询原记录、核对原输入 |
| 同请求仍处理中 | 409 / request_in_progress | 用 get_decision 查询，不再并行推理 |
| provider 失败/拒绝/无有效选择 | 有记录时返回带 disposition 的决策；无法受理时 503 / unavailable | 交原回退路径；不默认通过，不让它阻断独立工作 |

错误对象包含 `error.code`、非秘密 `message`，可带已知 request_id/decision_id。网络断开或超时没有接收证明；只读查询和独立补传仍分开。服务查询不会执行原 workflow、角色创建、shell 或审批操作。

## 服务内部并行实现接缝

这部分只约束 S/P 两个实现会话，不向消费者公开 Python 实现类型。P 独占 `src/decision_service/providers.py`，提供两个同步函数；S 负责调度、认证、持久化与 HTTP：

- `retrieve_evidence(request, bank_ids, settings)`：输入为 S 已校验的请求、已解析的有效 bank 列表和运行配置；返回 JSON 对象，含 `evidence` 数组及 `banks` 状态数组。每个片段保留实际可得的 bank/document/memory 引用，不补造来源。P 可在一次调用内并行检索这些 bank。
- `call_decisions(request, evidence, settings)`：输入为冻结问题/候选与必要证据；返回 JSON 对象，含 `status`（ok/refused/unavailable）、有类型 `answer`、`model`、可选 `usage` 和 `reason_codes`。只处理 provider 判断，不生成执行命令、不写 SQLite。

settings 是仅在进程内使用的映射：openai_base_url/openai_api_key/openai_model、hindsight_base_url/hindsight_api_key、timeout_seconds、evidence_max_chars、max_parallel_banks。openai_base_url 默认为 `https://api.openai.com`（不带 `/v1`），P 追加 `/v1/decisions`；hindsight_base_url 是原生 REST API 根地址（不带 `/v1`，不是 MCP URL），P 使用官方 recall 路径，生产网关若非此合同须明确另配适用入口，不能猜 URL。timeout_seconds 为单次上游调用截止时间，S 可传剩余预算以约束整次请求；P 不隐含无限重试。默认模型为 gpt-6-luna；真实地址与凭据由运行配置注入，不能从原 Win 配置自动复制。P 使用 httpx；依赖与版本由 S 统一写入 pyproject，P 不改项目清单。两函数在普通请求失败时返回上述状态；编程错误保留异常，由 S 转为不泄密的内部错误并记录失败，不吞掉诊断。

两函数的 request 就是前文经 S 校验/解析的 evaluate 请求；evidence 是检索返回的片段数组。字面返回样例：

```json
{"evidence": [{"bank_id": "example-bank", "document_id": null, "memory_id": "m-1", "text": "相关事实"}],
 "banks": [{"bank_id": "example-bank", "status": "ok", "reason_code": null}]}
```

```json
{"status": "ok", "answer": {"type": "choice", "choice": "continue", "probabilities": [{"value": "continue", "probability": 1.0}]},
 "model": {"provider": "openai", "model_type": "decision", "model": "gpt-6-luna", "requested_model": "gpt-6-luna",
   "configuration_status": "confirmed", "reasoning_effort": null, "effort_status": "not_applicable"},
 "usage": null, "reason_codes": []}
```

其中 model 的实际型号以 provider 可读回值为准；未返回实际型号时 `model=null`、configuration_status=unconfirmed，requested_model 保留请求型号。S 将此对象保存为 decision_model。answer 的四种规范形状为：choice 使用上例（choice 的值就是 candidate_id）；predicate 为 `{"type":"predicate","probability":0.8}`；score 为 `{"type":"score","score":0.8,"probabilities":[{"value":0,"probability":0.2},{"value":1,"probability":0.8}]}`，value 是输入 levels 的零基索引；refusal 为 `{"type":"refusal","reason":"provider_refusal"}`。这是本服务规范化输出，P 对官方返回做转换；refusal 对应 status=refused，普通上游失败对应 status=unavailable、answer=null。不能把 score 的加权索引改成候选选择或可靠性保证。

P 不承担调用者授权、业务状态或存储；S 不再次实现网络 provider。内部结构如需调整，两个实现者先向审查会话说明影响并同步此处，禁止在不同会话悄悄维持两套函数合同。
