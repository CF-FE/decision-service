# Hindsight Decision Models 与 OpenAI Decisions

文档版本：**v1.1**。资料核验时间：**2026-11-09 07:40 UTC / 北京时间 15:40**。这是本仓说明的维护版本，不是上游 API 版本；线上文档未标独立合同版本号，以下用固定提交、Issue/PR 和取证时间区分证据。

当前记录：据[本项目 #6 的运行收口](https://github.com/CF-FE/decision-service/issues/6)，Win 局部拒答补丁已于北京时间 15:29 部署，唯一一次真实双 bank 与最终 Luna 判断通过，仍使用 OpenAI / gpt-6-luna。Q8 备选试验先前未通过且已恢复；拒答**传播缺陷**已处理，拒答**触发原因**及此前是否曾有限流仍 UNKNOWN。本轮只核对公开文档、固定源码和已有运行记录，没有重新探测生产或追加模型调用。

| 文档版本 | 时间 | 变化 |
| --- | --- | --- |
| v1.0 | 2026-11-09，随 [PR #7](https://github.com/CF-FE/decision-service/pull/7) 合入 | 四种返回与逐题拒答说明，当时本地修复仍在进行。 |
| v1.1 | 2026-11-09 07:40 UTC / 北京时间 15:40 | 补充上游 #6242 复现、#6389 默认关闭的整批回退与本地方案区别，并引用 #6 更新生产状态边界。 |

## 2026-11-09：保留 Luna，跳过明确拒答候选

安装版没有局部拒答跳过开关，原解析器遇到任一题 refusal 会让整次 recall 失败。现已采用 [Herdr 固定补丁 49e48b5c](https://github.com/CF-FE/herdr-4-codexcloud/commit/49e48b5c6a8a23d90d68a53dafbe9a37b680c6b3)：只在 OpenAI 候选排序路径保留明确拒答标记、排除该候选，再排名其余正常答案。正常零概率、全部拒答、缺答、非法答案和 HTTP 错误分别处理；其他 Decision Model 调用及去重题仍使用严格拒答行为。

原有批量继续使用：同一 bank 的多个候选组成 questions，按容量拆批。当前 Win 配置的候选上限为 100；OpenAI 当前接口上限为每请求 1–400 问题，不能把 Hindsight 的通用拆批上限当作 OpenAI 限额。官方 response 的 refusal 只有 name/type，没有具体原因字段；“证据不足”“安全原因”“并发限流”均不是这次故障已确认的根因。

15:29（Asia/Shanghai）完成 API 单独重载和源码/ACL/健康读回，原配置、PG/BGE 保留。唯一一次真实 evaluate 用时 14.873 秒，两 bank 各返回 3 个有 memory 引用的片段；最终 complete/suggested，原生 predicate probability=1.0，同 ID 读回一致。测试窗口中有 1/100 和 10/100 两条部分拒答告警，但不带 bank/request 标签，不能逐条归属。详见 [Issue #6](https://github.com/CF-FE/decision-service/issues/6) 和[完整证据边界](evidence-and-open-questions.md#luna-局部拒答补丁与真实验证2026-11-09)。

上游 [Issue #6242](https://github.com/vectorize-io/hindsight/issues/6242) 已由 [PR #6389](https://github.com/vectorize-io/hindsight/pull/6389) 关闭。其新增选项默认关闭，启用后会在 Decision Model 失败时用配置的备用 reranker 从头重排。本轮固定安装版使用候选级补丁，保留 Luna 已给出的正常答案；没有启用整批备用重排或切换 Q8。

## 2026-11-09：Q8 备选验证与恢复

真实跨库请求在 Hindsight 的 Decision Model 精排阶段遇到拒答，补丁应用前的安装版将其传播为整次 recall 的 HTTP 500。接口没有受支持的请求级关闭精排参数；rerank 对象的 prune/dedup 不能替代该能力。

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

## 上游复现：共同路径与未知原因

[Hindsight #6242](https://github.com/vectorize-io/hindsight/issues/6242) 是报告者在 1.1.0-slim/Linux 上的公开复现，另核对固定主线 `bc5ea195`。它与本项目 Win 1.2.0 的共同点是逐题拒答被排序链传播成整次 recall 失败，不代表输入、模型快照或拒答触发原因相同。

- **公开输入的 provider 对照**：报告者用机器人转向题观察到原生 OpenAI 返回 HTTP 200，其中 choice 题 refusal、控制 predicate 正常；经 OpenRouter/System One 的同类请求则返回 HTTP 502，不带部分答案。缩短指令后两端均选到正确候选。这是特定输入的已报告现象，不是安全原因、证据不足或限流的根因证明；本次未重放该请求。
- **排序链的离线复现**：另用合成 predicate 正常答案加 refusal，确认 `_from_openai()` → `DecisionModelReranker` 抛异常。报告中的生产排序为 Noul（映射到 OpenAI predicate），公开 Choice 题只复现 provider/适配器结果，不能当作同一生产候选池。
- **重试放大是另一条路径**：报告的合成 System One 502 测试在默认 4 次重试下共尝试 5 次，直接 `DecisionRefusedError` 为 1 次。不能把这个计数套到本项目原生 OpenAI 请求；换成直连只能避开该 502 包装，并不单独消除拒答传播。
- **限制反推**：报告者的中性 1/20/100/200 题对照通过，只能排除这些样例的一般批量不兼容。原生返回型号为 `gpt-6-luna`，OpenRouter 成功对照为带日期的型号名，未证明两路使用相同快照；不能据此断言所有生产输入或当前版本必然复现。

结论是“有独立报告支持相同的异常传播机制”，不是“已找到 Luna 为什么拒答”。模型拒答触发原因仍未公开，本项目此前 429/峰值并发也仍缺少逐次可关联证据。[本地证据 #6](https://github.com/CF-FE/decision-service/issues/6)

## 上游整批回退与本地局部拒答方案

上游 [PR #6389](https://github.com/vectorize-io/hindsight/pull/6389) 于 **2026-11-06 11:45:21 UTC** 合并，合并提交为 [3d7d084](https://github.com/vectorize-io/hindsight/commit/3d7d084dd67ab27a5d3bda58aaa97dffe9fac554)，#6242 随之关闭。本次核对了实际 diff 与[维护者答复](https://github.com/vectorize-io/hindsight/issues/6242#issuecomment-6684062624)，不是仅按 Issue 已关闭推断功能。[7][8]

| 边界 | 上游 #6389：整批 reranker fallback | 本地 #6：局部拒答隔离 |
| --- | --- | --- |
| 启用与触发 | 服务级 `HINDSIGHT_API_RECALL_DECISION_MODEL_FALLBACK`，**默认 false**。显式开启后，Decision Model 排序失败/拒答且原重试结束，才回退。 | 固定 Win 1.2.0 补丁，仅对 OpenAI recall 候选排序识别明确的逐题 refusal。 |
| 候选与模型 | 配置的 `HINDSIGHT_API_RERANKER_*`（含 failover chain）从头重新排序该次整批候选；不是只跳过被拒题。 | 继续使用 Luna，保留正常答案，仅移除明确拒答候选；真实零概率仍按正常答案处理。 |
| 排序语义 | 使用 fallback 自己的输入对与每条记忆上下文，并记录实际 serving provider；cross-encoder 的 recency/temporal/proof-count boosts 恢复，Decision Model 的 prune/dedup 不用于该 fallback。 | 保留存活候选的原排序/筛选语义及原索引；dedup 仅看存活池，去重题拒答仍严格失败。 |
| 初始化与重试 | fallback 在启动时初始化，避免失败请求中才下载本地模型；**502 重试保持不变**。 | HTTP 错误、超时、原重试与窗口二分沿既有路径处理；不把失败或缺答当部分成功。 |
| 全拒答与其他调用 | 开启后可进入整个 reranker 回退；回退本身仍可能失败，不保证成功。 | 跨批汇总后全拒答仍明确失败；普通 predict、consolidation 等调用保留原严格拒答行为。 |

本地固定交付为 [Herdr 49e48b5](https://github.com/CF-FE/herdr-4-codexcloud/commit/49e48b5c6a8a23d90d68a53dafbe9a37b680c6b3)，补丁、源哈希锁、14 个合成回归与部署/回退说明均归 [decision-reranker 目录](https://github.com/CF-FE/herdr-4-codexcloud/tree/49e48b5c6a8a23d90d68a53dafbe9a37b680c6b3/mcp/hindsight-memory/decision-reranker)。其目标是保住有明确正常判断的候选，不是移植 #6389 或自动采用 Q8。

**发布与安装不能混推。** #6389 合入上游不证明某个包或当前 Win 已包含它。固定 `34a1386` 的 [reranker 构造](https://github.com/vectorize-io/hindsight/blob/34a138684a899b6ec34175f7a2b633860466d289/hindsight-api-slim/hindsight_api/engine/search/reranking.py#L320-L342)仍是 Decision Model 直接替换普通 reranker，没有该 fallback 接线；本地补丁也没有引入整批 fallback。以后评估上游升级时须核版本、源码与实际配置，不能只补一个环境变量就宣称启用，更不能把两方案混称“官方单条跳过”。

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

故障语义需带版本和配置：consolidation 的 Decision Model 失败可退回原 LLM；recall 默认仍显露排序失败。上游 #6389 仅在显式启用新服务级开关后使用配置的 reranker 回退，本地当前采用的是上述局部拒答补丁，不能承诺自动退回 Q8。[1][7] 原精排配置保留用于显式恢复。

## 与反馈回收设计的关系

MVP 由适配器直接回传应用与工作单元结果，保存在服务记录中。以后采用 Hindsight 回收时保留“项目 bank 存结果、服务按授权回收”的方向；该链路不是首版前置。Webhook 通知、记忆抽取完成和 consolidation 完成均不等于业务完成，更不等于决策正确。

Decision Models 可优化记忆处理成本，但不是 ground truth、审批或自动验收。Knowledge Pages/Mental Models 可以辅助汇总经验；纠错、修订、撤回、幂等及来源验证仍按[反馈方案](outcome-feedback.md)处理。

## 证据边界与来源

已核对：官方在线合同；现有 Hindsight API Slim 1.2.0 的 provider 默认表、实际 OpenAI 请求适配和操作级继承；一次 Luna 样例、配置写入/解析、原入口重载、新 API 健康及 PG/BGE 保全。秘密值不进入文档。
后续运行证据：#6 已记录局部补丁部署及一次真实双库 recall/最终判断通过，见上文；尚未完成自然业务质量、consolidation 效果、长期延迟和 token 收益验证。单次调用不证明长期额度、稳定性或其他模型权限，也未据此确定最低兼容版本。

1. [Hindsight Decision Models](https://hindsight.vectorize.io/developer/decision-models)
2. [Hindsight Models：OpenAI Decisions](https://hindsight.vectorize.io/developer/models#openai-decisions)
3. [Hindsight Configuration：Decision model](https://hindsight.vectorize.io/developer/configuration#decision-model)
4. [OpenAI Decisions API 指南](https://developers.openai.com/api/docs/guides/decisions)
5. [OpenAI Decisions 请求与返回 schema](https://developers.openai.com/api/reference/resources/decisions/methods/create)
6. [Hindsight 固定版本 `_from_openai` 拒答处理](https://github.com/vectorize-io/hindsight/blob/34a138684a899b6ec34175f7a2b633860466d289/hindsight-api-slim/hindsight_api/engine/decision_model.py#L162-L178)
7. [Hindsight PR #6389：默认关闭的整批 reranker fallback](https://github.com/vectorize-io/hindsight/pull/6389)
8. [Hindsight #6242：公开复现与维护者处理说明](https://github.com/vectorize-io/hindsight/issues/6242)
