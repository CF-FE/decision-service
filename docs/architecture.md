# 总体架构与接口草案

状态：设计草案，未实现。

## 数据流

调用方 → 认证/项目授权 → 校验决策配置与实时状态版本 → 可选 Hindsight recall → 精简证据包 → OpenAI Decisions API → 类型/枚举/阈值/硬规则校验 → 返回建议 → 现有负责人或执行器处理。

已验证的执行结果可在之后异步沉淀为记忆。建议结果、实际采用动作和最终业务结果分别记录，不能互相冒充。

## 核心组件

- **决策配置目录**：预先审核的 decision_kind、问题、候选枚举、规则和阈值版本。调用者不能任意替换系统规则或任意指定派发目标。
- **Evidence Builder**：输入最小化；记录事实来源、观察时间、状态版本、项目和作用域；标记缺失、过期和冲突。
- **Memory Adapter**：按可信项目映射选择 bank，过滤和限制检索；不能由不可信内容决定 bank 或权限。
- **Provider Adapter**：隔离 Decisions API 合同、模型配置、限流、错误和拒绝。模型、prompt、profile 版本要可追踪。
- **Policy Validator**：确定性检查返回类型、候选项、证据完整性、权限与业务硬约束。
- **Decision Record**：保存建议和依据摘要、引用、耗时和成本，不取代业务状态库。
- **HTTP/MCP Adapter**：共享相同核心实现与权限逻辑。

## 首批场景候选

| 场景 | 候选结果示例 | 不可越界 |
| --- | --- | --- |
| 项目路由 | 已注册项目 / unknown / review | 不任意创建目标或派发任务 |
| 事件分类 | 进度 / 依赖 / 异常 / 交付声明 / 未知 | 交付声明不等于验收 |
| 证据充分性 | 足够进入下一项检查 / 缺失 / 冲突 | 不代替真实文件和听审 |
| 异常分流 | 可按既有方案处理 / 需负责人 / 等待依赖 | 不自动重试未知副作用 |
| 负责人关注度 | 普通 / 高 / 紧急 / 待复核 | 不自动对外发消息 |

示例枚举需按真实标注案例修订；不是已上线协议。

## 建议的公共合同

以下为本服务自定义草案，不是 OpenAI 请求字段：

请求至少包含 request_id、project_id、caller_role、decision_kind、profile_version、subject_ref、state_version、observed_at、facts 与 evidence_refs。身份来自认证层，不能信任 caller_role 自报值。

响应至少包含 decision_id、request_id、disposition（suggested / abstain / needs_review / unavailable）、answer、模型返回的相关分数、reason_codes、evidence_refs、profile_version、model、created_at 与输入摘要。

- 严格区分 provider probability、confidence 和 Hindsight 相对检索排名。
- reason_codes 优先来自规则校验；不能伪称模型提供了未返回的解释。
- 所有调用均返回“不确定/无法判断”的可处理状态，禁止错误默认成通过。
- 决策计算无业务副作用。幂等键复用时若输入或版本变化，应冲突报错；缓存须纳入状态、配置与证据版本。
- 超时后的原 decision 可查询；实际执行方负责原业务 ID 对账和幂等。
- 不将固定 0.9 等阈值作为通用标准；阈值由每场景的错误代价和离线样本校准。

## 最小工具面

- evaluate_decision：返回建议，不派发、不改业务。
- get_decision：查询原结果、证据与版本。
- record_decision_outcome：后续阶段增加，需验证反馈来源，只记录实际采纳与已核实结果。

工具名为提案，不代表已经存在。MVP 不暴露任意 Hindsight 管理/删除工具、shell、Herdr socket 或无限制 URL 抓取。

## 既有系统边界

Herdr 继续负责协调、执行检查点和现有审批状态；Task Mailbox 继续负责持久传输、事件及版本；项目原件负责业务事实与验收。公共决策服务没有批准账本的权威地位。业务推进权限不得从历史记忆、Issue/评论或模型答案推导。
