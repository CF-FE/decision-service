# Decision Service · 快速决策公共服务

跨项目、跨 Agent 与工作流复用的快速决策服务，通过 OpenAI Decisions API 和 Hindsight 跨 bank 检索，为动态工作流选择推进/调整方案，并按任务需求与复杂度选择角色使用的模型及推理强度。

> 当前阶段：云端服务与 Mac 消费者已部署（2026-11-09），真实 Luna 判断及 Herdr 独立工程闭环通过。服务全量基线 54 项、后续插件专项 8 项通过；Herdr 359 项通过、4 项既有条件跳过。云端 Decision Service Cloud 与本地插件均已 OAuth 连接，云端 Skill 的显式加载和只读查询也已确认。真实跨 bank 尚未通过：Luna 精排拒答后，Q8 备选试验只恢复一库，另一库及最终判断超时；试验结束已恢复原 Luna 召回配置。三个实现会话负责编码，两个原会话只审计复核。工程回执不等于自然业务验收或效率收益证明。

- [GitHub Project #7](https://github.com/orgs/CF-FE/projects/7)
- [讨论与决策记录](docs/discussion-record.md)
- [总体架构与接口草案](docs/architecture.md)
- [MVP 公共合同 v1](docs/api-contract.md)
- [并行实施与审计安排](docs/implementation-plan.md)
- [本地运行与隔离验证](docs/development.md)
- [OpenAI/Hindsight 接入配置](docs/provider-integration.md)
- [本地与云端插件安装](docs/plugin-installation.md)
- [Hindsight 集成与经验闭环](docs/hindsight-integration.md)
- [Hindsight Decision Models 与 OpenAI 支持边界](docs/hindsight-decision-models.md)
- [决策结果回收与验证方案](docs/outcome-feedback.md)
- [部署、安全与故障边界](docs/deployment.md)
- [阶段路线图与验收](docs/roadmap.md)
- [ADR-001：独立公共服务与接入层](docs/decisions/001-shared-decision-service.md)
- [ADR-002：首版交付物与 SQLite 存储](docs/decisions/002-mvp-deliverables-and-sqlite.md)
- [来源、事实与待验证事项](docs/evidence-and-open-questions.md)

## 定位

核心目标是提升工作流执行效率和模型 token 利用率：减少等待、重复整理上下文、无效模型回合与返工，让相同质量的任务消耗更少 token，或用相同预算取得更多有效进展。

记录重点为模型类型、具体型号及推理强度，推荐与实际采用分别保存。消耗计量优先级低，现成可得就附带记录，缺失留缺省、不补零、不为此扩展采集；现金费用不记录。缺少消耗数据不阻塞 MVP、结果回收或质量评价。

“公共”指获准项目共享，不是匿名开放。MVP 支持两类核心预设：workflow_next_action 选择下一动作或具体调整方案，role_model_selection 按能力需求与复杂度选择模型/强度组合；通用 evaluate 同时支持项目路由、分类等有限答案问题。已有结构化状态和程序规则直接复用，不为每个节点或无变化轮询增加模型调用。

先跑通再完善，不等待收益证明、完整标签集、基线对照或 recall 消融。受信调用方可直接提供问题、候选与上下文，常用问题存成预设，不逐场景审批。跨 bank 检索直接入首版：静态配置可读范围，按问题取相关项目经验，无需先复制到共享库或逐次批准；输入充分时也可跳过检索。

三个消费方：

1. Router/协调器：选择可见目标项目和推进方案，沿既有路径派发。
2. 项目负责人及角色创建者：按任务能力需求、复杂度与预算选择模型和推理强度，交 Herdr 原入口创建或接续。
3. 项目工作流：提供当前状态及具体动作/计划候选，消费选择结果，在原授权内自动推进；复杂计划仍由原规划者产生。

## 对外交付物

| 产物 | 职责与首版安排 |
| --- | --- |
| 核心 Decision Service | 一个服务进程，提供判断、跨 bank 检索、模型配置选择与反馈记录 |
| HTTP API | 首版程序入口，供工作流调用决策、查询记录和回传结果 |
| MCP | 已实现 Streamable HTTP，与 HTTP 共用核心、身份作用域及记录 |
| Skill | 首版轻量使用规范：调用时机、事实与候选准备、应用、回退和反馈 |
| 插件 | 本地 Codex 包及云端原生私有 App 的 Skill 更新包；两端分别安装和授权 |
| Herdr／项目工作流适配器 | 首版配套交付，在关联仓库维护候选、原动作/配置应用及反馈补传 |

HTTP 与 MCP 已实现 evaluate_decision、get_decision 和 record_decision_feedback 三项核心能力，路由与字段归[v1 合同](docs/api-contract.md)。[Skill](skill/decision-service/SKILL.md) 说明怎样使用这些能力，不另实现决策逻辑；安装及原生授权见[插件说明](docs/plugin-installation.md)。详见[交付边界](docs/architecture.md#对外交付物)。

## 内部存储

首版已确定使用 **SQLite**，数据库位于服务主机的持久数据目录，调用方通过 HTTP/MCP 访问服务。保存决策与输入快照、反馈事件及修订、决策与原工作单元的关联和回收缺口；记录服务判断模型，以及推荐/实际执行模型的类型、型号和强度。消耗仅附带现成值，现金费用不存。

Hindsight 继续负责经验检索；原工作流保留业务状态、产物/验收权威与待回传事件。服务 SQLite 保存已收到的反馈，不替代来源端恢复补传。详细设计归[内部存储与数据归属](docs/architecture.md#内部存储与数据归属)。

服务已部署到现有 VPS，使用独立进程、凭据和持久数据目录；Mac 保留 Herdr 协调与执行接续，Windows 保留制作与 Hindsight 后端。MVP 包含适配器自动反馈；Hindsight webhook 与全库补偿后续增加。

## 不承担的职责

- 不创建第二套 Herdr、Task Mailbox、审批平台或实时业务状态库。
- 不发明或扩大用户授权，不把高置信度当批准。
- 不直接执行 shell、派发业务任务、改变工作流状态或最终验收。
- 不把模型建议直接写成 Hindsight 已证实经验。
- 不把 Hindsight 检索分数当模型置信度，也不把历史记忆当当前事实。

## 后续顺序

跑通跨 bank MVP（工作流下一步 + 角色模型配置 + 结果回收） → 接入真实使用 → 根据质量与消耗改善决策、检索和模型强度 → 按需要扩展评测与 Hindsight 回收。

原适配器自动回传 application（实际采用）和 result（工作单元结果），按 decision_id 与原执行引用精确关联；人工纠正可补充。原检查点保存待传事件，恢复补传不重跑业务；质量可后补修订，成本去重，缺反馈单列。Hindsight 用于召回经验，不承担找全结果。详见[结果回收与效果验证](docs/outcome-feedback.md)。

基本联调确认链路、实际应用、两类反馈与恢复可用；质量复用原检查/验收，效果对照在使用后完善，不设前置收益证明、统一影子期或逐项批准。详见[路线图](docs/roadmap.md)、[架构](docs/architecture.md)与[本轮分工](docs/implementation-plan.md)。实现、隔离联调、实际运行及业务验收分别记录，不因派工或代码完成声称生产已接通。
