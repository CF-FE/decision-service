# 来源、事实与待验证事项

整理日期：2026-11-08；运行证据记录于 **2026-11-09 07:40 UTC / 北京时间 15:40**，任务状态于 2026-11-09 再按实际交付收口。拒答资料及版本历史见 [Hindsight 说明](hindsight-decision-models.md)。本文区分官方文档口径、设计提案和运行验证；任务记录更新不表示重新探测运行服务，不包含现有私有系统的连接细节或业务数据。

## OpenAI Decisions API

讨论中核对的官方资料：
- [使用指南](https://developers.openai.com/api/docs/guides/decisions)
- [创建接口](https://developers.openai.com/api/reference/resources/decisions/methods/create)
- [发布公告](https://openai.com/index/decisions-api/)
- [定价与可用性](https://developers.openai.com/api/docs/guides/decisions#pricing-and-availability)

记录口径：POST /v1/decisions；文档列出的模型为 gpt-6-luna；支持 predicate、choice、score 等有限答案判断。讨论中读取的价格为未缓存输入每百万 token 0.10 美元、输出 token 不收费，缓存和区域处理另有规则。实施时必须重新核对合同、模型、价格和地区支持，不将本文视为价格承诺。

“最高快 10 倍”为官方特定对比描述，不是本服务端到端承诺。2026-11-08 初始调研时尚未实际调用用户 API key，也未验证账户权限、额度、可用模型或延迟；后续实际调用结果见下方“当前交付边界”。

## Hindsight

参考：[Hindsight recall 文档](https://hindsight.vectorize.io/developer/api/recall)。

设计使用 recall 按需取得带来源的经验；具体应用与结果按原 ID 和引用精确回收，不用 recall 证明找全。reflect 不进入默认快速链路；retain 写回须与真实结果核验和异步完成检查分离。MVP 使用适配器直传及本服务记录，不依赖 Hindsight 写回。具体部署接口、bank 映射和异步操作合同随对应能力接入时在获准环境复核，不在公开仓库暴露项目记忆内容或私有服务细节。

## 既有协调系统的适配原则

本服务不会拥有用户审批或业务状态的权威地位。接入现有协调器、工作流或持久信箱时，应核对它们各自的身份、版本和幂等合同。读取确认不等于批准，批准不等于执行，执行不等于业务验收。

不能将“模型 decision”误作“用户 approval decision”，也不能仅因名称相近就向可信批准入口写入模型结果。模型判断不提供真人身份、批准证明、消息送达或通知能力。

## 按建设阶段补齐的事项

MVP 联调中确认账户调用、入口与 Hindsight 连通、实际可读 bank、候选输出与引用、application/result 自动直传与记录读回、原端恢复补传及错误回退；人工纠正入口继续保留。选择模型/强度时核宿主可用组合，应用动作/计划时核原 workflow 支持的方式。静态范围配置和基本联调属于跑通工作，不要求开发前完成全面调研或收益证明。

MVP 回收已有质量与 usage，沿已有测试和原验收，不逐单增加人工评价；实际使用后再完善频率、任务复杂度分布、人工负担、总 token/耗时、失败返工和模型配置效果。需要正式比较时才建设对应标签协议、基线和保留集。Hindsight webhook、细分混合读写权限和全库补偿在启用该后续链路时解决，不代替 MVP 的原检查点持久留事件与恢复补传，也不阻塞跨 bank 只读 MVP。

最新用户取舍优先：消耗只记直接可得值，缺失留缺省（省略/null，非零），不追补计量；现金费用不记录。模型类型/型号和推理强度必须留记录，推荐与实际采用分别标明，实际无法确认时如实标记。官方有 usage 接口不意味着首版必须为它新增采集适配；本页历史价格调研不作为现金费用采集需求。

## 当前交付边界

2026-11-09，服务、MCP、插件包和消费者代码已提交，部署与安装分别取证。两原会话负责审查和文档互审，实现、修复及部署由执行会话和临时子代理完成。

| 范围 | 已取得的证据 | 尚不代表 |
| --- | --- | --- |
| 工程实现 | 服务全量基线 54 项、后续插件专项 8 项通过；Herdr 359 项通过、4 项既有条件跳过；两条隔离跨仓入口可复跑 | 自然任务的业务验收 |
| 云端服务 | 独立 systemd/持久 SQLite；公网 HTTP/MCP 同记录和反馈回执；真实 Luna predicate 返回并持久读回 | 长期稳定性、效率或模型准确率 |
| OAuth | 独立 GitHub App；公网发现、DCR、S256；登记跨重启；异常不回显、存储拒写边界已回归 | 所有客户端都已授权 |
| Mac 原生工作流与模型 | 固定版本消费者；真实 Luna 选择分支、原 runner 采用；一次原生 Codex 回合确认 gpt-6.1-sol/low；两个决策共一个结果第 2 修订，FINISHED、待传 0 | 生产角色迁移或一般任务质量 |
| 本地插件 | 默认用户 catalog 已安装启用；原生 OAuth 登录及不注入 Bearer 的工具读回通过 | 所有在途桌面会话均已刷新技能目录 |
| 云端 App | Decision Service Cloud 原生私有 App 已安装/授权，三个工具可发现；原生 get_decision 与本地/REST 的 decision_id 一致；v1.0.2 Skill 与仓库原文逐字节一致，App 绑定和名称保留；用户已在云端显式加载 Skill 并查回同一测试记录，未创建决策或反馈 | 一次显式加载不证明所有旧会话已自动刷新 |
| 真实跨 bank | Win 已应用 Luna 候选拒答补丁；原 45 秒预算下一次 evaluate 用时 14.873 秒，两库各返回 3 个带 memory 引用的片段，最终判断 complete/suggested，同记录读回一致 | 一次工程验证不代表长期相关性、吞吐或业务验收；拒答原因仍未知 |

### Q8 备选试验与恢复（2026-11-09）

本次切换的目的是测试备选方案，不是决定长期替换 Luna。只将 Hindsight 的 recall Decision Model provider 从 openai 改为 none，使用已保留的 ONNX Q8 排序；没有调整候选、阈值、45 秒服务总预算或其他模型配置。只发送一次双 bank evaluate，并按原 request_id 查询同一记录。

- Decision Service bank 成功：35 条片段均有 memory 引用，29 条有 document 引用；现有网关日志显示单次约 32.58 秒。
- Herdr bank 失败：单次约 44.40 秒，分类为 TIMEOUT/api_relay_roundtrip。Win 内部耗时未确认，不能据此断言是网络或 CPU 故障。
- 最终决策为 unknown/openai_timeout，没有可用答案；客户端端到端墙钟约 53.76 秒。总预算配置仍为 45 秒，墙钟差异原因未定位，不能宣称在预算内完成。
- 试验与清理前均核对原生 API 列出的 4 个 bank 无等待或处理中异步操作；不据此宣称没有同步请求。配置备份及访问权限已核验，两次均只重载 API，PG/BGE 原进程保留。
- 14:27（Asia/Shanghai）已恢复 recall=openai，配置文件哈希与试验前完全一致，新 API 健康。清理没有追加 recall、evaluate 或模型请求。Q8 未采纳为长期方案，原 Luna 拒答原因仍未知。

### Luna 局部拒答补丁与真实验证（2026-11-09）

本节按 [#6](https://github.com/CF-FE/decision-service/issues/6) 截至上述时间的收口记录整理；本次文档核对未重新部署、重放公开复现或追加真实模型请求。

[Issue #6](https://github.com/CF-FE/decision-service/issues/6) 记录故障与后续验证。[Herdr 固定提交 49e48b5c](https://github.com/CF-FE/herdr-4-codexcloud/commit/49e48b5c6a8a23d90d68a53dafbe9a37b680c6b3) 维护 Hindsight API Slim 1.2.0 的三个文件补丁、前后哈希、回归与回退说明。15:29（Asia/Shanghai）沿原 SYSTEM 入口完成 API 单独重载；原文件备份、部署源码、ACL、模块导入和新进程健康均已读回，PG/BGE 进程及原配置保持不变。

补丁只对 OpenAI recall 候选排序允许局部拒答：显式拒答项在排名前排除，正常零概率仍是有效答案；全部拒答仍失败，缺答或非法答案不降成零。普通调用及去重题保留严格拒答行为，trace 保留逐题拒答标记和已有 usage。原版同组离线用例失败，补丁版 14 项全部通过，主审独立复跑；Herdr 结构检查及 363 项全套检查通过（359 通过、4 跳过）。离线 HTTP 和分词计数使用替身，真实采用另以下列回执为准。

- 运行中服务配置读回：总预算 45 秒、并发 bank 数 2。只发送一次 evaluate；`request_id=s2-recall-luna-partial-20261109-01`，`decision_id=b864e553-c1e3-4675-be45-5a55fac318fa`，attempts=1。
- POST 用时 14.873 秒；初次同 ID GET 用时 0.355 秒，决策、答案、检索和模型记录一致。后续仅为核对原生字段再 GET 同记录，耗时 14.816 秒，未重复 evaluate，不能将两次 GET 混成一个延迟指标。
- 两库均为 ok，各 3 个带 memory 引用的片段；Decision Service 另有 2 个 document 引用，Herdr 另有 1 个。匹配冻结实参哈希和时间窗口的网关记录分别为 11.95153 秒、8.43272 秒，各一次尝试；Win 内部独立耗时仍缺省。
- 最终状态 complete、处置 suggested，模型 openai/gpt-6-luna、类型 decision；原生 predicate probability=1.0。这是该次模型的输出，不是业务正确性证明。
- POST 时间窗口内，Win 日志有两条匹配本题前缀的 recall-start，以及明确的 1/100、10/100 部分拒答告警。告警没有 bank/request 标签，不能将两条拒答数逐一指定给某库；该窗口没有其他可见的外部 recall-start。
- 本轮没有 retain、反馈或业务工作流写入。原始拒答原因、是否曾限流仍未知；接口没有将 refusal 定义为“证据不足”。上游 [#6242](https://github.com/vectorize-io/hindsight/issues/6242) 与 [#6389](https://github.com/vectorize-io/hindsight/pull/6389) 已记录整次改用备用 reranker 的方案，本轮采用的是用户指定的 Luna 候选级处理。

上游 [#6242](https://github.com/vectorize-io/hindsight/issues/6242) 的公开复现和 [#6389](https://github.com/vectorize-io/hindsight/pull/6389) 的合并记录证明另一种默认关闭的整批 reranker fallback 已进入上游源码；不证明本机安装、开关启用或本地根因。两方案的具体差异与固定版本见[对照说明](hindsight-decision-models.md#上游整批回退与本地局部拒答方案)。#6 已于 2026-11-09 按技术修复和部署验证完成关闭；拒答原因及历史限流证据缺口作为 UNKNOWN 留档，不为此继续发起请求。剩余工作见[当前优先级](roadmap.md#当前优先级与-issue-状态)。

两条仓内隔离入口使用真实本地 HTTP/SQLite、生成 runner 和上游/宿主替身，覆盖回执丢失、部分 recall 失败、进程中断、配置读回、联合结果及质量修订，见[可复跑命令](development.md)。真实工程样例另有原生回执，不能混用两类证据。模型准确率、整单效率和 token 收益尚无实测结论；Hindsight webhook 仍后置。公开材料不包含凭据、内部连接细节或私有来源内容。下文带 2026-11-08 日期的章节保留当时调研事实，不代表当前实现状态。

## Hindsight webhook 与反馈回收补充（2026-11-08）

用户确认当前部署支持 webhook；这是部署能力说明，不是本项目端到端验证。调研覆盖官方 Webhooks、Documents、Bank strategy、Knowledge Pages、Mental Models、Decision Models 与 Extensions；链接、合同差异及设计取舍见[结果回收方案](outcome-feedback.md)。

初始化调研观察到 MCP 可精确读取文档原文，未暴露 webhook 管理及 Documents API 的时间窗口过滤；官方存在这些能力不代表当前适配已具备。启用 Hindsight webhook 回收前必须验证签名、至少一次投递去重、重试耗尽恢复、并发分页覆盖、不可变修订和所有路由的项目读写隔离。原生删除事件覆盖尚未核验，撤回不能只依赖回调。2026-11-08 当时只交付文档；2026-11-09 已实现 MVP 直传，仍未配置 webhook 或写入生产结果；本次专用只读主体的两 bank 授权见当前交付边界。

## 本轮评审的复核与缺口（2026-11-08）

### 官方合同复核

- 重新读取 OpenAI [指南](https://developers.openai.com/api/docs/guides/decisions)与[创建接口](https://developers.openai.com/api/reference/resources/decisions/methods/create)：predicate、choice、score 及逐问题 refusal 是不同结果类型；不提供任意新工作流计划、自由文本理由或证据引文。服务从原候选映射动作/模型配置，reason_codes 与输入来源由自身记录。首版可使用简单处置阈值，后续校准分数，不宣传为已证明的准确性。
- 创建接口的返回结构为 answers、model、usage；不能推导“超时后可向 provider 找回原 decision”。[本服务查询草案](architecture.md#超时与查询)仅查询已保存记录；调用方需要首次响应丢失后定位时提供 request_id，未保存的 provider 答案保留未知，可按预算重新推理。
- 重新读取 Hindsight [Webhooks](https://hindsight.vectorize.io/developer/api/webhooks)与[Documents](https://hindsight.vectorize.io/developer/api/documents)：通知去重、原文读取和时间窗口枚举支持该设计方向；它们不自动证明业务正确性或当前部署的全量恢复能力。上述 MCP 能力描述仍是初始化调研观察，本轮未重新连接部署核验。
- 重新读取 Hindsight [OpenAI provider 说明](https://hindsight.vectorize.io/developer/models#openai-decisions)：recall/consolidation 与 reflect/知识页刷新仍有支持范围区别。该页仍称 OpenAI 接口为 public beta，而 OpenAI 自有指南已标 generally available；产品发布状态以 OpenAI 自有来源为准，现有实例兼容性仍需固定版本实测。

### 尚缺的项目价值证据

尚无工作流效率、模型 token 利用率、复杂度选型效果、原规则覆盖率及维护成本的实际数据。跨项目复用与效率提升是已明确的目标，不是已取得的效果；这些缺口不阻塞用户已选择的 MVP 路线。用户已确定 HTTP 首版程序入口、按 Agent 需求提供 MCP、轻量 Skill 与 SQLite 存储，插件分发后置，见 [ADR-002](decisions/002-mvp-deliverables-and-sqlite.md)；框架、路由、表结构与初始策略按实现需要选择。外部 API 存在仍不等于本项目账户已调用通过。

[路线图](roadmap.md)现为先跑通跨 bank MVP，再在真实任务中观察、纠正与改善。评测和消融不再前置；后续正式报告效果时仍保留样本范围与不确定性，不把局部 API 速度、较短输出或较低单价冒充整段任务更高效。

### 全局边界的源码核对

关联全局评审协助定位后，本轮复核了 `CF-FE/herdr-4-codexcloud` 的 `e43f6427` 和实际 owner 为 `ghyghoo8/create-network-sh` 的 `ebbf6d5`：

- [协调器](https://github.com/CF-FE/herdr-4-codexcloud/blob/e43f6427dde563e08bdd0183a014b60f236f452c/scripts/project_coordinator.py#L507)已有项目、主体、原任务、代次与任职检查；[项目 workflow](https://github.com/CF-FE/herdr-4-codexcloud/blob/e43f6427dde563e08bdd0183a014b60f236f452c/docs/project-workflow-development.md#自定义项目操作)已有程序/决定/交接/结束边界，不需要本服务另建状态和派发系统。
- [审批设计](https://github.com/CF-FE/herdr-4-codexcloud/blob/e43f6427dde563e08bdd0183a014b60f236f452c/docs/approval-workflow.md#1-目标与已确认缺口)所记录的缺口是实际投递、答复回流和接续，不是缺分类模型；不能以 Decisions 接入宣称修复审批链。
- [共享记忆规范](https://github.com/CF-FE/herdr-4-codexcloud/blob/e43f6427dde563e08bdd0183a014b60f236f452c/docs/hindsight-memory-integration.md#4-角色使用规则)允许权限内直接贡献带来源的普通经验；不应将本服务的策略发布评审扩成每条经验的人工批准。
- 网关已有按主体限制 bank 集合的源码路径；混合“多项目只读、服务 bank 可写”、结果发布者证明、webhook 管理和枚举接入仍有具体缺口，见[回收方案](outcome-feedback.md#当前网关的具体适配缺口)。这些后续写回/同步缺口不等于跨 bank 只读不能做。本轮未调用网关、读取私有项目记忆或核验运行部署。

### 动态推进与角色选型的设计边界

本轮补充明确两类用途：选择 workflow 下一动作/具体调整方案，以及按任务需求与复杂度选择实际可用的模型/强度组合。现有固定决定点、检查点和组织宿主记录是接入起点，不能据此声称任意运行中改图、跨宿主热切模型或完整模型能力目录已经存在。

双方复核的具体源码起点：公共 [workflow 模板](https://github.com/CF-FE/herdr-4-codexcloud/blob/e43f6427dde563e08bdd0183a014b60f236f452c/scripts/project_workflow_template.py#L196)只向当前 WAITING_DECISION 导入合法 choice，单活动步骤且拒绝回已完成步骤；[Worker 候选与启动准备](https://github.com/CF-FE/herdr-4-codexcloud/blob/e43f6427dde563e08bdd0183a014b60f236f452c/scripts/worker_library.py#L215)列 provider/model，准备端透传 backend.agent_args，尚无统一 reasoning/context/cost 候选合同。这是源码观察，不是实际角色创建或模型切换验收。

这些合同由本仓与 Herdr/项目 workflow 侧互审：本仓拥有判断、候选选择和来源记录，原组件拥有候选生成、能力信息、计划应用及角色生命周期。实际可用接口与需补充的文档/实现由对应仓库维护；本轮只更新设计，不启动相关实现。

### 应用、结果回收与效果验证的补充设计

MVP 由适配器自动直传 application（实际采用动作/模型配置或未采用原因）与 result（原工作单元/执行 attempt 的结果引用及已有质量、usage），人工纠正保留。decision_id 沿原任务/工作单元及可得执行引用关联，不虚构 run/action/attempt；原检查点持久留待回传事件，恢复或后续检查点先只读核实，再独立补原事件。服务端按同事件/同 revision 幂等接收，质量更新用新 revision。补传不阻塞业务、不重跑业务，不另建消息总线。角色跨任务按任务单元回收，不等待角色退出。

评价沿已有测试与原验收，缺少 token、质量或结果保留 UNKNOWN；应用事实、执行结果与业务验收分别记录。多项决策关联同一执行 attempt 时成本只计一次，服务判断 attempt 另计，并发墙钟时间不能相加。应用回收率与已知结束单元的结果回收率分别统计，在途、未知与缺口另列；这些关联与统计不自动证明某次决策带来的因果收益。

唯一详细语义合同为[结果回收与效果验证](outcome-feedback.md)，序列化归[v1 合同](api-contract.md)。上述在 2026-11-08 为讨论设计；2026-11-09 的实现、隔离验证及尚缺真实运行证据见本页“当前交付边界”，不能用旧源码调研或局部测试代替生产验收。
