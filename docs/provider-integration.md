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
