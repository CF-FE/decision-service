# Decision Service · 快速决策公共服务

跨项目、跨 Agent 与工作流复用的快速决策服务，拟通过 OpenAI Decisions API 做有限答案判断，并按需使用 Hindsight 项目记忆。

> 当前阶段：方案评审与文档迭代（2026-11-08）。本仓库只有设计文档和规划，没有运行服务、部署、API 凭据或效果验证。修订方案仍是提案；模型判断不是用户批准，也不是业务验收。

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

“公共”指获准项目共享，不是匿名开放。服务帮助做项目路由、事件分类、异常归类、证据充分性检查和候选分支选择，保留 unknown / review / abstain 等回退结果。

先验证具体判断相对现行方式是否有净收益，再决定服务化规模。已有项目绑定、结构化事件、错误码、权限和状态规则沿原系统处理；模型只补尚未解决的语义判断。首验从一个已绑定项目内的场景开始，未知项目路由需要另行定义入口可见范围。

三个消费方：

1. Router 协调员：识别项目与事件类别，从注册表选择候选目标。
2. 项目负责人：辅助区分可按已有方案继续、缺证据、依赖等待或需要裁决。
3. 项目工作流：快速选择候选检查路径，实际状态转换由既有确定性工作流控制。

## 技术分层

| 层 | 职责 |
| --- | --- |
| 核心 Decision Service | 认证与项目隔离、证据整理、按需检索、模型调用、结果校验、审计 |
| HTTP API | 给工作流代码和程序直接调用，按首个消费者需求提供 |
| MCP | 给 Agent 暴露相同核心能力，按需求增加，不另实现一套逻辑 |
| Skill | 角色使用规范：何时调用、如何提供事实、如何回退 |
| 插件 | 打包、安装与分发 MCP 和 Skill |

独立仓库与共享核心不等于立即建设独立运行服务、双入口和插件。需要服务化后优先评估现有 VPS；Mac 保留 Herdr 协调与执行接续，Windows 保留制作与现有 Hindsight 后端。运行形态按真实消费者、凭据隔离、资源与连通性选择，尚未定案。

## 不承担的职责

- 不创建第二套 Herdr、Task Mailbox、审批平台或实时业务状态库。
- 不发明或扩大用户授权，不把高置信度当批准。
- 不直接执行 shell、派发业务任务、改变工作流状态或最终验收。
- 不把模型建议直接写成 Hindsight 已证实经验。
- 不把 Hindsight 检索分数当模型置信度，也不把历史记忆当当前事实。

## 后续顺序

列出 3–5 个候选、首验一个 → 标签协议与现行基线 → 最小离线比较 → 一个消费者的影子接入 → 按收益分别增加 recall 与反馈自动化 → 有证据支持的低风险灰度。

反馈评价从首个样本开始，早期可人工关联；完整 webhook 回收不是离线验证前置。现行规则已足够或模型增益不足时允许停止。详见[路线图](docs/roadmap.md)与[架构取舍](docs/architecture.md#设计取舍)。本轮仅修订文档，未同步看板；文档、建仓和建板均不代表已授权部署或创建持久凭据。
