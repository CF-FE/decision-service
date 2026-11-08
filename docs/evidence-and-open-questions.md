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

设计使用 recall 按需取得带来源的经验；reflect 不进入默认快速链路；retain 写回须与真实结果核验和异步完成检查分离。具体部署接口、bank 映射和异步操作合同，实施前在获准环境复核，不在公开仓库暴露项目记忆内容或私有服务细节。

## 既有协调系统的适配原则

本服务不会拥有用户审批或业务状态的权威地位。接入现有协调器、工作流或持久信箱时，应核对它们各自的身份、版本和幂等合同。读取确认不等于批准，批准不等于执行，执行不等于业务验收。

不能将“模型 decision”误作“用户 approval decision”，也不能仅因名称相近就向可信批准入口写入模型结果。模型判断不提供真人身份、批准证明、消息送达或通知能力。

## 上线前必须回答

1. 账户是否可实际调用 Decisions，精确请求/响应与拒绝语义是什么？
2. 3–5 个候选中，哪个首验场景确有语义缺口、足够高频且误判代价可控？
3. 实时状态与规则的权威来源、版本和有效期是什么？
4. 各身份可访问哪些项目、bank、场景与预算？
5. Hindsight 何时检索，何时允许写回，如何验证结果来源？
6. 选定运行形态的容量、网络与端到端延迟是否满足目标？采用 VPS 时再核其具体资源。
7. 何种情况下 abstain/review，如何退回既有负责人流程？
8. 灰度前有哪些测试、监控、成本预算和回滚标准？

## 当前交付边界

只有仓库、文档、看板与规划。没有声称模型准确率、生产 SLA、部署健康或业务验收完成。公开材料已去除凭据、个人信息、内部网络/连接细节和私有来源内容。

## Hindsight webhook 与反馈回收补充（2026-11-08）

用户确认当前部署支持 webhook；这是部署能力说明，不是本项目端到端验证。调研覆盖官方 Webhooks、Documents、Bank strategy、Knowledge Pages、Mental Models、Decision Models 与 Extensions；链接、合同差异及设计取舍见[结果回收方案](outcome-feedback.md)。

初始化调研观察到 MCP 可精确读取文档原文，未暴露 webhook 管理及 Documents API 的时间窗口过滤；官方存在这些能力不代表当前适配已具备。启用自动回收前必须验证签名、至少一次投递去重、重试耗尽恢复、并发分页覆盖、不可变修订和所有路由的项目读写隔离。原生删除事件覆盖尚未核验，撤回不能只依赖回调。当前新增交付仍只有文档，没有配置 webhook、开放跨项目访问、写入运行结果或执行自动评价。

## 本轮评审的复核与缺口（2026-11-08）

### 官方合同复核

- 重新读取 OpenAI [指南](https://developers.openai.com/api/docs/guides/decisions)与[创建接口](https://developers.openai.com/api/reference/resources/decisions/methods/create)：predicate、choice、score 及逐问题 refusal 是不同结果类型；不提供本服务自定义的自由文本理由或证据引文。模型分数仍需用场景标签校准。服务的 reason_codes 与输入引用由自身确定性逻辑记录。
- 创建接口的返回结构为 answers、model、usage；不能从该合同推导“超时后可向 provider 找回原 decision”。[本服务查询草案](architecture.md#超时与查询)仅承诺查询已保存的受理与结果记录，首次响应丢失用原 request_id 定位，未保存的 provider 答案保留未知。
- 重新读取 Hindsight [Webhooks](https://hindsight.vectorize.io/developer/api/webhooks)与[Documents](https://hindsight.vectorize.io/developer/api/documents)：通知去重、原文读取和时间窗口枚举支持该设计方向；它们不自动证明业务正确性或当前部署的全量恢复能力。上述 MCP 能力描述仍是初始化调研观察，本轮未重新连接部署核验。
- 重新读取 Hindsight [OpenAI provider 说明](https://hindsight.vectorize.io/developer/models#openai-decisions)：recall/consolidation 与 reflect/知识页刷新仍有支持范围区别。该页仍称 OpenAI 接口为 public beta，而 OpenAI 自有指南已标 generally available；产品发布状态以 OpenAI 自有来源为准，现有实例兼容性仍需固定版本实测。

### 尚缺的项目价值证据

尚无首验场景的频率、原规则覆盖率、人工负担、误判成本、独立标签、模型增益和维护成本数据。跨项目共同需求是设计目标，不是已证明的复用收益。当前不据此选定框架、部署形态或阈值，也不将外部 API 可用性等同于本项目账户可用。

因此[路线图](roadmap.md)把有限对照前移，把 recall 和自动结果回收分开验证。小样本可帮助淘汰方向，不能作为生产准确率承诺；业务标签、运行结果和设计接受状态继续分别记录。

### 全局边界的源码核对

关联全局评审协助定位后，本轮复核了 `CF-FE/herdr-4-codexcloud` 的 `e43f6427` 和实际 owner 为 `ghyghoo8/create-network-sh` 的 `ebbf6d5`：

- [协调器](https://github.com/CF-FE/herdr-4-codexcloud/blob/e43f6427dde563e08bdd0183a014b60f236f452c/scripts/project_coordinator.py#L507)已有项目、主体、原任务、代次与任职检查；[项目 workflow](https://github.com/CF-FE/herdr-4-codexcloud/blob/e43f6427dde563e08bdd0183a014b60f236f452c/docs/project-workflow-development.md#自定义项目操作)已有程序/决定/交接/结束边界，不需要本服务另建状态和派发系统。
- [审批设计](https://github.com/CF-FE/herdr-4-codexcloud/blob/e43f6427dde563e08bdd0183a014b60f236f452c/docs/approval-workflow.md#1-目标与已确认缺口)所记录的缺口是实际投递、答复回流和接续，不是缺分类模型；不能以 Decisions 接入宣称修复审批链。
- [共享记忆规范](https://github.com/CF-FE/herdr-4-codexcloud/blob/e43f6427dde563e08bdd0183a014b60f236f452c/docs/hindsight-memory-integration.md#4-角色使用规则)允许权限内直接贡献带来源的普通经验；不应将本服务的策略发布评审扩成每条经验的人工批准。
- 网关存在按 bank 区分读写、结果发布者证明、webhook 管理与枚举接入的具体缺口，已写入[回收方案](outcome-feedback.md#当前网关的具体适配缺口)。本轮未调用网关、读取私有项目记忆或核验运行部署；源码检查不能证明这些链路已上线。
