# Decision Service · 快速决策公共服务

跨项目、跨 Agent 与工作流复用的快速决策服务，拟通过 OpenAI Decisions API 和 Hindsight 跨 bank 检索，为动态工作流选择推进/调整方案，并按任务需求与复杂度选择角色使用的模型及推理强度。

> 当前阶段：方案与文档迭代（2026-11-08）。用户已确认先跑通跨 bank MVP、再按实际使用迭代；本轮先不开发。仓库没有运行服务、部署或效果验证；具体接口仍为草案，模型判断不产生用户批准或业务验收。

- [GitHub Project #7](https://github.com/orgs/CF-FE/projects/7)
- [讨论与决策记录](docs/discussion-record.md)
- [总体架构与接口草案](docs/architecture.md)
- [Hindsight 集成与经验闭环](docs/hindsight-integration.md)
- [Hindsight Decision Models 与 OpenAI 支持边界](docs/hindsight-decision-models.md)
- [决策结果回收与验证方案](docs/outcome-feedback.md)
- [部署、安全与故障边界](docs/deployment.md)
- [阶段路线图与验收](docs/roadmap.md)
- [ADR-001：独立公共服务与接入层](docs/decisions/001-shared-decision-service.md)
- [来源、事实与待验证事项](docs/evidence-and-open-questions.md)

## 定位

核心目标是提升工作流执行效率和模型 token 利用率：减少等待、重复整理上下文、无效模型回合与返工，让相同质量的任务消耗更少 token，或用相同预算取得更多有效进展。

“公共”指获准项目共享，不是匿名开放。MVP 支持两类核心预设：workflow_next_action 选择下一动作或具体调整方案，role_model_selection 按能力需求与复杂度选择模型/强度组合；通用 evaluate 同时支持项目路由、分类等有限答案问题。已有结构化状态和程序规则直接复用，不为每个节点或无变化轮询增加模型调用。

先跑通再完善，不等待收益证明、完整标签集、基线对照或 recall 消融。受信调用方可直接提供问题、候选与上下文，常用问题存成预设，不逐场景审批。跨 bank 检索直接入首版：静态配置可读范围，按问题取相关项目经验，无需先复制到共享库或逐次批准；输入充分时也可跳过检索。

三个消费方：

1. Router/协调器：选择可见目标项目和推进方案，沿既有路径派发。
2. 项目负责人及角色创建者：按任务能力需求、复杂度与预算选择模型和推理强度，交 Herdr 原入口创建或接续。
3. 项目工作流：提供当前状态及具体动作/计划候选，消费选择结果，在原授权内自动推进；复杂计划仍由原规划者产生。

## 技术分层

| 层 | 职责 |
| --- | --- |
| 核心 Decision Service | 通用判断与预设、跨 bank 检索、动作/模型配置选择、简单调用和反馈记录 |
| HTTP API | 给工作流代码和程序直接调用，按首个消费者需求提供 |
| MCP | 给 Agent 暴露相同核心能力，按需求增加，不另实现一套逻辑 |
| Skill | 角色使用规范：何时调用、如何提供事实、如何回退 |
| 插件 | 打包、安装与分发 MCP 和 Skill |

首版一个进程、一份核心，先提供实际需要的 HTTP 或 MCP 入口；两者都需要时共用核心。运行位置优先考虑现有 VPS，按联调实际连通性选择；Mac 保留 Herdr 协调与执行接续，Windows 保留制作与 Hindsight 后端。MVP 包含适配器自动反馈，插件、Hindsight webhook 与全库补偿等完整设施后续增加。

## 不承担的职责

- 不创建第二套 Herdr、Task Mailbox、审批平台或实时业务状态库。
- 不发明或扩大用户授权，不把高置信度当批准。
- 不直接执行 shell、派发业务任务、改变工作流状态或最终验收。
- 不把模型建议直接写成 Hindsight 已证实经验。
- 不把 Hindsight 检索分数当模型置信度，也不把历史记忆当当前事实。

## 后续顺序

跑通跨 bank MVP（工作流下一步 + 角色模型配置 + 结果回收） → 接入真实使用 → 根据质量与消耗改善决策、检索和模型强度 → 按需要扩展评测与 Hindsight 回收。

原适配器自动回传 application（实际采用）和 result（工作单元结果），按 decision_id 与原执行引用精确关联；人工纠正可补充。原检查点保存待传事件，恢复补传不重跑业务；质量可后补修订，成本去重，缺反馈单列。Hindsight 用于召回经验，不承担找全结果。详见[结果回收与效果验证](docs/outcome-feedback.md)。

基本联调确认链路、实际应用、两类反馈与恢复可用；质量复用原检查/验收，效果对照在使用后完善，不设前置收益证明、统一影子期或逐项批准。详见[路线图](docs/roadmap.md)与[架构](docs/architecture.md)。本轮仅修订文档，未同步看板、开始开发或改变运行权限。
