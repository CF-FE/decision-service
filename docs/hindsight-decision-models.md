# Hindsight Decision Models 与 OpenAI Decisions

更新日期：2026-11-09。当前继续使用 Luna；Win Hindsight API Slim 1.2.0 已应用候选级拒答补丁，一次真实双库检索、最终判断及持久读回在原 45 秒预算下通过。此前 Q8 备选试验未通过完整链路，已恢复原配置。拒答触发原因仍未知，以下分别记录部署、工程验证和历史试验，不声称长期质量或效率收益已验证。

## 2026-11-09：保留 Luna，跳过明确拒答候选

安装版没有局部拒答跳过开关，原解析器遇到任一题 refusal 会让整次 recall 失败。现已采用 [Herdr 固定补丁 49e48b5c](https://github.com/CF-FE/herdr-4-codexcloud/commit/49e48b5c6a8a23d90d68a53dafbe9a37b680c6b3)：只在 OpenAI 候选排序路径保留明确拒答标记、排除该候选，再排名其余正常答案。正常零概率、全部拒答、缺答、非法答案和 HTTP 错误分别处理；其他 Decision Model 调用及去重题仍使用严格拒答行为。

原有批量继续使用：同一 bank 的多个候选组成 questions，按容量拆批。当前 Win 配置的候选上限为 100；OpenAI 当前接口上限为每请求 1–400 问题，不能把 Hindsight 的通用拆批上限当作 OpenAI 限额。官方 response 的 refusal 只有 name/type，没有具体原因字段；“证据不足”“安全原因”“并发限流”均不是这次故障已确认的根因。

15:29（Asia/Shanghai）完成 API 单独重载和源码/ACL/健康读回，原配置、PG/BGE 保留。唯一一次真实 evaluate 用时 14.873 秒，两 bank 各返回 3 个有 memory 引用的片段；最终 complete/suggested，原生 predicate probability=1.0，同 ID 读回一致。测试窗口中有 1/100 和 10/100 两条部分拒答告警，但不带 bank/request 标签，不能逐条归属。详见 [Issue #6](https://github.com/CF-FE/decision-service/issues/6) 和[完整证据边界](evidence-and-open-questions.md#luna-局部拒答补丁与真实验证2026-11-09)。

上游 [Issue #6242](https://github.com/vectorize-io/hindsight/issues/6242) 已由 [PR #6389](https://github.com/vectorize-io/hindsight/pull/6389) 关闭。其新增选项默认关闭，启用后会在 Decision Model 失败时用配置的备用 reranker 从头重排。本轮固定安装版使用候选级补丁，保留 Luna 已给出的正常答案；没有启用整批备用重排或切换 Q8。

## 2026-11-09：Q8 备选验证与恢复

真实跨库请求在 Hindsight 的 Decision Model 精排阶段遇到拒答，安装版将其传播为整次 recall 的 HTTP 500。接口没有受支持的请求级关闭精排参数；rerank 对象的 prune/dedup 不能替代该能力。

公子批准仅为测试备选方案，将 `HINDSIGHT_API_RECALL_DECISION_MODEL_PROVIDER` 从 openai 改为 none，让 recall 使用已保留的 ONNX Q8。Q8 实际加载成功，但唯一一次双 bank 测试只有一库返回 35 条片段，另一库中继等待超时，最终判断为 unknown/openai_timeout；不能把加载成功当成备选通过。

试验结束按同一回退路径恢复 recall=openai，配置文件与试验前逐字节一致。仅重载 API，PG/BGE 保留；清理没有追加召回或模型请求。业务 Decision Service、consolidation 和其他原配置保留。Q8 没有成为长期选型，详细耗时及证据边界见[交付记录](evidence-and-open-questions.md#q8-备选试验与恢复2026-11-09)。

## 结论与职责边界

可以使用 OpenAI，但不是将 Hindsight 整体换成一个 OpenAI 模型。

Hindsight Decision Models 是可选的内部判断层：辅助筛选记忆、辨别重复事实、判断证据是否足够、判断知识页是否需要更新；需要生成文字的工作仍由普通 LLM 完成。[1] 它不是本项目面向协调员、负责人和工作流的业务决策服务。

三类模型用途应分开：

- **记忆内部优化**：Hindsight → 原生 Decision Model provider。
- **业务有限判断**：decision-service → OpenAI Decisions API；按授权向 Hindsight 检索背景。
- **角色执行模型**：decision-service 按任务需求与复杂度选择宿主实际可用的模型/推理强度组合，原创建者应用。被选择的执行模型不要求与本服务的判断模型、Hindsight 内部模型相同。

结果与纠正沿原任务、服务反馈记录或后续自动回收取得，不能由上述模型输出自行证明正确。MVP 不等待项目 bank 写回，详见[结果回收方案](outcome-feedback.md)。

本次复用 Hindsight 原生 provider 直接接入 OpenAI，内部记忆判断不绕经 decision-service，减少依赖环和额外延迟；该次配置未涉及业务服务开发，业务服务的当前进展见[项目说明](../README.md)。

## 当前官方支持范围

| Hindsight 环节 | 使用 OpenAI Decision Model |
| --- | --- |
| Recall 判断/排序 | 支持；本次配置显式指定 provider，继承行为以安装版本为准 |
| Consolidation 判断 | 支持；需要改写的内容仍交给 LLM |
| Reflect | 当前不支持此 provider；本次显式配置为 none，保留原 LLM 路径 |
| Knowledge-page refresh | 当前不支持此 provider，保留 LLM-only 路径并告警 |

官方列出 provider `openai`，默认 `gpt-6-luna`。Reflect 与知识页刷新目前只支持 `hindsight`、`typesafe` 的 Decision Model。[2] 因此，“支持 OpenAI”不代表四个环节全部替换，也不意味着普通 LLM、embedding 或其他组件不再需要。

OpenAI 官方指南当前使用 `POST /v1/decisions`、`gpt-6-luna`，提供 predicate、choice、score 等有限答案类型；SDK 使用 `client.decisions.create(...)`。[4] 实施时锁定 SDK/服务版本，再核对合同与账户可用性。

## 逐题拒答与 Hindsight 安装版行为

2026-11-09 核对的 OpenAI 原生 `answers[]` 有 **predicate、choice、score、refusal** 四种返回类型。任一题可返回 `{"type":"refusal","name":"问题名"}`，其他题仍可有正常答案；未命名时 `name=null`。官方只定义拒答分支的 `name/type`，未给出原因字段或触发规则。完整字段、概率/评分语义、批量限制及 Decision Service 的规范化映射见[官方返回类型说明](provider-integration.md#openai-decisions-官方返回类型)。[5]

补丁前安装版所对应的固定上游源码 `34a138684a899b6ec34175f7a2b633860466d289` 中，`_from_openai()` 遍历答案，遇到任一 refusal 就抛 `DecisionRefusedError`，没有返回已解析的正常答案。[6] 因此此前 recall 整体 500 是已确认的 **Hindsight 适配/排序链路传播行为**，不能表述为 OpenAI 要求整批失败。HTTP 错误、超时、明确拒答和合法低分必须分别诊断；当前证据仍不能确认拒答的原始原因或是否曾有限流。

[Issue #6](https://github.com/CF-FE/decision-service/issues/6) 跟踪的修复是在 **recall 排序责任边界** 显式保留拒答状态并排除对应候选，其余正常答案继续使用；全部拒答仍失败/未知，不伪造为零分或有效空结果。不能仅吞掉异常后让未评分候选继续获得名次分，也不改变 consolidation/reflect 的严格拒答语义。该候选级补丁已于 2026-11-09 15:29（Asia/Shanghai）应用到 Win；源码版本、实际验证和局限见上方“保留 Luna，跳过明确拒答候选”。

源码仍属 `vectorize-io/hindsight`；Win 补丁、部署和回退材料归 `CF-FE/herdr-4-codexcloud` 的 `mcp/hindsight-memory`，VPS 网关归 `ghyghoo8/create-network-sh`。本仓记录消费端现象、合同与验收，不复制 Hindsight 排序器。此文档补充不改变 provider、模型、并发、权限或运行配置。

## 2026-11-08 首次启用配置

本次在原实例选用以下非秘密配置，普通 LLM、embedding 及原 Q8 精排配置保留：

```dotenv
HINDSIGHT_API_DECISION_MODEL_PROVIDER=openai
HINDSIGHT_API_DECISION_MODEL_MODEL=gpt-6-luna
HINDSIGHT_API_DECISION_MODEL_BASE_URL=https://api.openai.com
HINDSIGHT_API_RECALL_DECISION_MODEL_PROVIDER=openai
HINDSIGHT_API_CONSOLIDATION_DECISION_MODEL_PROVIDER=openai
HINDSIGHT_API_REFLECT_DECISION_MODEL_PROVIDER=none
```

通过受控秘密注入提供 `HINDSIGHT_API_DECISION_MODEL_API_KEY`；不要把实际值提交到仓库、日志、记忆或文档。

本次公子指定的新密钥仅授权 Luna，限用于 Decision Models 的 `gpt-6-luna`；普通 LLM `gpt-4.1-mini` 继续使用原密钥。两把密钥分离，不合并、不用新密钥调用其他型号；以后确需合并时，先告知公子调整权限。

安装版 1.2.0 的 `decision_model_config()` 在操作未覆盖时继承全局 provider；仅对 `hindsight` provider 特判 recall 默认继续使用原 reranker。全局 `openai` 会被 recall 继承，因此不能把“所有 provider 都要另开 recall”当作通则。本次配置显式指定 recall，以消除继承歧义；若只开 consolidation 而保留原精排，应让 recall 显式为 none，或仅设置 consolidation 的操作级配置。此处使用的是 `DECISION_MODEL` 配置族，不是修改普通 `LLM_PROVIDER`。

如果确有 reflect 加速需求，可以单独选择 `HINDSIGHT_API_REFLECT_DECISION_MODEL_PROVIDER=hindsight` 或 `typesafe`，并提供对应的独立 API key；跨 provider 不能假定继承全局 OpenAI key。[2][3] 也可先保持已有 LLM 路径。不要仅为统一供应商牺牲受支持的功能。

本次记录分别证明：

- **账户与原生适配可调用**：一次 `gpt-6-luna` 原生 Decisions 样例通过，使用固定非项目输入；未追加其他型号或真实召回测试。
- **配置已写入并重载**：原配置已备份；安装版配置解析确认 recall/consolidation 为 openai + gpt-6-luna、reflect 为 none，专用密钥正确绑定且与保留的普通 LLM 密钥分离。原启动入口完成一次 API 重载，新进程健康检查通过，原 PG/BGE 进程保留。
- **验证边界**：重载前两次观察的 4 个 bank 均无 pending/running 异步操作；未枚举同步请求，不宣称全系统空闲。配置解析、加载顺序和新进程健康共同支持本次配置采用，不代替真实 recall/consolidation 业务效果验证。

脱敏 setup/apply/restart 回执由原维护入口保留，关联会话已同步；秘密值、私有备份内容和连接信息不写入本仓。本次没有升级 Hindsight、创建 bank 或开发业务 Decision Service。

## 最小启用与后续观察

用户已提出先配置 Hindsight Decision Models。本节针对现有记忆服务的配置，不要求先开发业务 Decision Service，也不将完整收益评测设为启用前置。

1. 核实际版本、原生 provider 和配置加载顺序。现有 1.2.0 已包含 openai 分支及 `/v1/decisions` 调用；本次新密钥的 Luna 调用已确认，不据此推断其他模型权限。
2. 在原机受控配置内使用本次指定的 Luna 专用凭据，以不含项目私密信息的一条最小样例确认账户和接口可用；失败则保留原配置，处理具体错误，不先启用失效 provider。
3. 保存原配置、明确操作级启用范围，核对在途工作后沿既有入口重载，确认配置读回与服务可用。保留原 LLM、embedding 和原精排配置；恢复原配置不等于撤回已发生的记忆整合。
4. 实际使用后再观察 recall 遗漏、错误合并及直接可得的 token/耗时；有明确问题或需要量化主张时再做针对性对照，不为此增加常驻采集链路。

provider、模型类型/型号及适用强度按各自调用链记录；原生不提供强度参数时标不适用。消耗只记录现成数据，缺失留缺省，不记录现金费用。身份/数据权限继续由服务端控制；共享供应商不意味着共享所有 bank 或扩大数据传输范围。

当前官方故障语义有一项区别：consolidation 的 Decision Model 失败可退回原 LLM；recall 将它作为 ranker，远程调用重试后仍失败会导致 recall 失败，不能承诺自动退回 Q8 精排。[1] 原精排配置保留用于显式恢复。

## 与反馈回收设计的关系

MVP 由适配器直接回传应用与工作单元结果，保存在服务记录中。以后采用 Hindsight 回收时保留“项目 bank 存结果、服务按授权回收”的方向；该链路不是首版前置。Webhook 通知、记忆抽取完成和 consolidation 完成均不等于业务完成，更不等于决策正确。

Decision Models 可优化记忆处理成本，但不是 ground truth、审批或自动验收。Knowledge Pages/Mental Models 可以辅助汇总经验；纠错、修订、撤回、幂等及来源验证仍按[反馈方案](outcome-feedback.md)处理。

## 证据边界与来源

已核对：官方在线合同；现有 Hindsight API Slim 1.2.0 的 provider 默认表、实际 OpenAI 请求适配和操作级继承；一次 Luna 样例、配置写入/解析、原入口重载、新 API 健康及 PG/BGE 保全。秘密值不进入文档。
尚未完成：真实业务 recall/consolidation 与端到端质量、延迟、token 收益验证；单次调用不证明长期额度、稳定性或其他模型权限，也未据此确定最低兼容版本。

1. [Hindsight Decision Models](https://hindsight.vectorize.io/developer/decision-models)
2. [Hindsight Models：OpenAI Decisions](https://hindsight.vectorize.io/developer/models#openai-decisions)
3. [Hindsight Configuration：Decision model](https://hindsight.vectorize.io/developer/configuration#decision-model)
4. [OpenAI Decisions API 指南](https://developers.openai.com/api/docs/guides/decisions)
5. [OpenAI Decisions 请求与返回 schema](https://developers.openai.com/api/reference/resources/decisions/methods/create)
6. [Hindsight 固定版本 `_from_openai` 拒答处理](https://github.com/vectorize-io/hindsight/blob/34a138684a899b6ec34175f7a2b633860466d289/hindsight-api-slim/hindsight_api/engine/decision_model.py#L162-L178)
