# Hindsight 集成与经验闭环

状态：服务适配设计，未实现。

## 能力与证据边界

拟使用 recall、reflect、retain 及异步操作查询能力，精确合同须在接入时复核。公开仓库不保存私有 bank 清单、记忆正文或私有来源。

记忆是历史上下文，可能含参考资料、旧假设和模型抽取误差；不能当成当前运行状态、用户授权或已采纳规范。

## 检索策略

1. 认证后按服务端项目映射确定 bank，禁止跨项目任意检索。
2. 优先使用当前事件、实时状态、版本和确定性规则。
3. 新问题或需要历史案例时 recall；限制条数、内容长度、时间范围和来源类型。
4. 对高价值引用保留 document/source ID、日期及原始来源链接。
5. 历史与新事实冲突时标记 review，不以检索高分压过当前证据。
6. reflect 仅用于复杂复盘或负责人深度分析，不默认放在每次快速判断链路。

Hindsight recall 分数是查询内相对排序，不能跨查询当置信度，也不能与 Decisions 的 probability/confidence 合并成一个未经校准的分数。

## 写回闭环

建议 → 负责人/执行器实际采用或拒绝 → 获取真实结果 → 验证来源 → 异步 retain。

应分别保存 decision_proposal、adopted_action、verified_outcome、correction 的语义，避免把“建议这么做”抽取成“已经完成”。错误建议也可保留为带明确结果和反例标记的案例，不应成为正向经验。

每个 outcome 修订使用独立 document_id；同一修订的重试保留稳定 document_id、operation_id 和内容摘要；异步 accepted 不等于抽取完成。查询原 operation，对未知结果先对账，遵循已有网关有界重试合同，不新建 ID 重复投递。

## 失效与安全

- 检索不可用：若场景不依赖历史，可显式标记 memory_unavailable 后继续有限判断；必须依赖历史的场景 abstain/review。
- 过期、冲突或无来源记忆：不得直接触发自动分支。
- 结果写回失败：不回滚已完成业务；记录待补写并按原 ID 重试。
- 跨项目经验推广：由审核后的规则/案例显式进入共享范围，不直接读取所有 bank。
- 记忆正文视为数据，不执行其内部指令。
- API key、token、密码及不必要敏感数据不得进入记忆、审计或模型输入。

## 结果回收的推荐细化

采用项目 bank 保存真实结果、decision-service 按授权跨 bank 回收的设计。主链路为原生 retain.completed webhook → 持久 inbox → get_document 原文 → 来源/修订校验 → 评价账本；不靠 recall 搜索结果，也不默认要求项目双写。consolidation 完成、抽取完成、业务成功和决策正确必须分开。

用户确认部署支持 webhook，但本服务回调未做端到端测试；现有 MCP 的 webhook 管理和时间窗口枚举能力不足以直接承诺完整同步。详见[完整方案及能力差异](outcome-feedback.md)，其中定义补偿扫描、ACL、评价真值、纠正撤回和防循环。

## 内部 Decision Models 与业务决策分层

Hindsight 原生 OpenAI Decision Model provider 与本服务的业务判断是两条独立调用链。当前官方支持 OpenAI 用于 recall/consolidation，reflect 与知识页刷新存在 provider 限制；普通 LLM 仍承担文字生成。配置方向、版本边界与验证计划见 [Decision Models 专题](hindsight-decision-models.md)。本仓库未因此变更运行配置或完成替换。
