# 来源、事实与待验证事项

整理日期：2026-11-08。本文区分官方文档口径、设计提案和运行验证；不包含现有私有系统的连接细节或业务数据。

## OpenAI Decisions API

讨论中核对的官方资料：
- [使用指南](https://developers.openai.com/api/docs/guides/decisions)
- [创建接口](https://developers.openai.com/api/reference/resources/decisions/methods/create)
- [发布公告](https://openai.com/index/decisions-api/)
- [定价与可用性](https://developers.openai.com/api/docs/guides/decisions#pricing-and-availability)

记录口径：POST /v1/decisions；文档列出的模型为 gpt-6-luna；支持 predicate、choice、score 等有限答案判断。讨论中读取的价格为未缓存输入每百万 token 0.10 美元、输出 token 不收费，缓存和区域处理另有规则。实施时必须重新核对合同、模型、价格和地区支持，不将本文视为价格承诺。

“最高快 10 倍”为官方特定对比描述，不是本服务端到端承诺。没有实际调用用户 API key，没有验证账户权限、额度、可用模型或延迟。

## Hindsight

参考：[Hindsight recall 文档](https://hindsight.vectorize.io/developer/api/recall)。

设计使用 recall 按需取得带来源的经验；具体应用与结果按原 ID 和引用精确回收，不用 recall 证明找全。reflect 不进入默认快速链路；retain 写回须与真实结果核验和异步完成检查分离。MVP 使用适配器直传及本服务记录，不依赖 Hindsight 写回。具体部署接口、bank 映射和异步操作合同随对应能力接入时在获准环境复核，不在公开仓库暴露项目记忆内容或私有服务细节。

## 既有协调系统的适配原则

本服务不会拥有用户审批或业务状态的权威地位。接入现有协调器、工作流或持久信箱时，应核对它们各自的身份、版本和幂等合同。读取确认不等于批准，批准不等于执行，执行不等于业务验收。

不能将“模型 decision”误作“用户 approval decision”，也不能仅因名称相近就向可信批准入口写入模型结果。模型判断不提供真人身份、批准证明、消息送达或通知能力。

## 按建设阶段补齐的事项

MVP 联调中确认账户调用、入口与 Hindsight 连通、实际可读 bank、候选输出与引用、application/result 自动直传与记录读回、原端恢复补传及错误回退；人工纠正入口继续保留。选择模型/强度时核宿主可用组合，应用动作/计划时核原 workflow 支持的方式。静态范围配置和基本联调属于跑通工作，不要求开发前完成全面调研或收益证明。

MVP 回收已有质量与 usage，沿已有测试和原验收，不逐单增加人工评价；实际使用后再完善频率、任务复杂度分布、人工负担、总 token/耗时、失败返工和模型配置效果。需要正式比较时才建设对应标签协议、基线和保留集。Hindsight webhook、细分混合读写权限和全库补偿在启用该后续链路时解决，不代替 MVP 的原检查点持久留事件与恢复补传，也不阻塞跨 bank 只读 MVP。

## 当前交付边界

只有仓库、文档、看板与规划。没有声称模型准确率、生产 SLA、部署健康或业务验收完成。公开材料已去除凭据、个人信息、内部网络/连接细节和私有来源内容。

## Hindsight webhook 与反馈回收补充（2026-11-08）

用户确认当前部署支持 webhook；这是部署能力说明，不是本项目端到端验证。调研覆盖官方 Webhooks、Documents、Bank strategy、Knowledge Pages、Mental Models、Decision Models 与 Extensions；链接、合同差异及设计取舍见[结果回收方案](outcome-feedback.md)。

初始化调研观察到 MCP 可精确读取文档原文，未暴露 webhook 管理及 Documents API 的时间窗口过滤；官方存在这些能力不代表当前适配已具备。启用 Hindsight webhook 回收前必须验证签名、至少一次投递去重、重试耗尽恢复、并发分页覆盖、不可变修订和所有路由的项目读写隔离。原生删除事件覆盖尚未核验，撤回不能只依赖回调。当前新增交付仍只有文档，没有实现 MVP 直传钩子、配置 webhook、开放跨项目访问、写入运行结果或执行自动评价。

## 本轮评审的复核与缺口（2026-11-08）

### 官方合同复核

- 重新读取 OpenAI [指南](https://developers.openai.com/api/docs/guides/decisions)与[创建接口](https://developers.openai.com/api/reference/resources/decisions/methods/create)：predicate、choice、score 及逐问题 refusal 是不同结果类型；不提供任意新工作流计划、自由文本理由或证据引文。服务从原候选映射动作/模型配置，reason_codes 与输入来源由自身记录。首版可使用简单处置阈值，后续校准分数，不宣传为已证明的准确性。
- 创建接口的返回结构为 answers、model、usage；不能推导“超时后可向 provider 找回原 decision”。[本服务查询草案](architecture.md#超时与查询)仅查询已保存记录；调用方需要首次响应丢失后定位时提供 request_id，未保存的 provider 答案保留未知，可按预算重新推理。
- 重新读取 Hindsight [Webhooks](https://hindsight.vectorize.io/developer/api/webhooks)与[Documents](https://hindsight.vectorize.io/developer/api/documents)：通知去重、原文读取和时间窗口枚举支持该设计方向；它们不自动证明业务正确性或当前部署的全量恢复能力。上述 MCP 能力描述仍是初始化调研观察，本轮未重新连接部署核验。
- 重新读取 Hindsight [OpenAI provider 说明](https://hindsight.vectorize.io/developer/models#openai-decisions)：recall/consolidation 与 reflect/知识页刷新仍有支持范围区别。该页仍称 OpenAI 接口为 public beta，而 OpenAI 自有指南已标 generally available；产品发布状态以 OpenAI 自有来源为准，现有实例兼容性仍需固定版本实测。

### 尚缺的项目价值证据

尚无工作流效率、模型 token 利用率、复杂度选型效果、原规则覆盖率及维护成本的实际数据。跨项目复用与效率提升是已明确的目标，不是已取得的效果；这些缺口不阻塞用户已选择的 MVP 路线。框架、入口、存储与初始策略可按跑通需要选择；外部 API 存在仍不等于本项目账户已调用通过。

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

唯一详细合同为[结果回收与效果验证](outcome-feedback.md)。上述是本轮讨论补充的设计，尚未实现或运行验证；既有源码起点不能证明直传钩子、检查点待回传事件和恢复补传已经具备。双方需沿原仓库核对适配位置与责任，本轮不访问运行服务或 bank、不改代码、不改变权限。
