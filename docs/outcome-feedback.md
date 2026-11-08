# Hindsight 驱动的决策结果回收与验证

状态：2026-11-08 设计提案，仅文档沉淀，未实施。用户确认当前部署支持 webhook；本项目尚未完成事件投递、验签、重试、补偿和权限隔离的端到端验证。下列自定义字段、状态和组件不是 Hindsight 原生合同。

## 1. 推荐方案

保留“结果放对应项目 bank，decision-service 按授权读取回收”的方向，增加精确原文读取和最小确定性处理账本：

项目产生真实结果 → 标准化 outcome 写入项目 bank → 原生 retain.completed webhook → 持久 inbox → 按 bank/document ID 精确读取原文 → 校验来源与版本 → 关联原 decision → 评价账本 → 经审核的经验摘要。

webhook 是通知，不是业务事实或执行许可。retain 完成只证明记忆处理阶段完成，不证明任务成功、决策正确或业务验收。项目原件继续是业务事实权威。

- 项目只需向自身 bank 发布一次结果，不默认再向决策服务双写。
- decision-service 不复制整个项目 bank；保存处理状态、必要摘要、证据引用和评价版本。
- 快速决策和异步学习分离；回收、复盘故障不阻塞原业务。
- 公共服务 bank 保存获准的可复用经验，不集中原始私有项目数据。
- 不增加新的派发器、审批平台或自动改变业务的入口。

## 2. 官方能力与当前适配边界

| 能力 | 官方文档口径 | 当前接入观察及设计要求 |
| --- | --- | --- |
| 原生 webhook | 按 bank 注册，支持 retain.completed / consolidation.completed；至少一次投递、签名及投递记录 | 用户确认部署支持；现有 MCP 未暴露 webhook 管理接口。注册、订阅范围、签名版本和真实回调仍待实施核验 |
| 精确文档读取 | get_document 可返回 original_text | 当前 MCP 可读取原文及文档元数据。不得用 recall 摘要代替原始 outcome |
| 文档变更 | 相同 document_id 的 retain 可替换原文 | outcome 每修订使用新 document_id；同一修订重试保留原 ID |
| 增量枚举 | Documents API 支持 tags、created_at/updated_at 时间窗口及 limit/offset | 当前 MCP 仅暴露 offset/limit/q，未暴露时间过滤、快照或持久游标；不能假装已有可靠增量同步 |
| 跨 bank | recall/retain/reflect 面向单 bank | 服务逐 bank 编排，使用可信项目映射和明确授权，不依赖正文指示目标 bank |
| 经验整理 | Knowledge Pages / Mental Models 可形成派生知识 | 可用于审核后的总结展示，不作为原始反馈账本、统计真值或验收证据 |

官方支持不等于当前版本、部署配置和 MCP 已完整暴露。上线前固定服务版本，保存脱敏合同样例，并实测签名、超时、重试上限、死信处理、文档保留和删除语义。

## 3. 数据归属与最小权限

- **项目 bank**：该项目的 outcome 原文、来源引用、修订与撤回说明；不改变现有项目事实系统。
- **决策记录**：冻结当时输入摘要、候选选项、返回结果、模型/profile/prompt/阈值版本、证据版本及观察时间。评价不能用今天的知识冒充当时输入。
- **服务处理账本**：事件 ID、项目和文档绑定、revision/hash、处理阶段、重试状态、评价版本、证据引用和必要指标。它是技术处理账本，不是授权账本。
- **服务 bank**：明确获准共享的脱敏经验与反例，附适用范围、支持证据、失效条件和版本；原项目详细评价默认留在受限账本。写回项目 bank 的评价需单独有该项目写权限。

项目生产者原则上只写自身结果；服务只读列入白名单的项目结果，另获自身账本与经验范围的写权限。bank 名、tag 和 payload 中 caller_role 不是权限机制。不得因为能够列出 bank 就推断可以读其内容。

官方认证扩展不应直接等同于细粒度 bank 读写 ACL。适配层必须检查 documents、operations、webhooks 及 recall/retain/reflect 等所有相关路由；如现有网关不能区分读写，先补齐隔离，不使用宽权限凭据替代。禁止任意 URL 抓取，证据访问也遵循项目范围。密钥、私有内容和内部地址不进入公开仓库。

## 4. 结果合同与不可变修订

建议结果 envelope 包含：

| 字段组 | 自定义字段与含义 |
| --- | --- |
| 类型 | schema_version、record_type=decision_outcome |
| 绑定 | project_id、decision_id、outcome_id、revision、document_id |
| 来源 | producer_ref、source_refs、observed_at、published_at |
| 实际情况 | adoption（采用/未采用/未知）、executed_action、execution_outcome、business_outcome |
| 证据 | verification_method、verified_by_ref、evidence_refs、证据版本与摘要 |
| 纠正 | supersedes、retracts、correction_reason |
| 溯源 | 原决策和输入版本引用、关联业务对象及其版本 |

生产者身份由认证和项目注册映射验证，不能信任 producer_ref 自报。字段缺失、未知 schema、项目与原 decision 不一致、摘要冲突、来源不可验证均隔离待复核，不强行评分。

每一修订用独立 document_id；修订不可覆盖旧原文。稳定写入操作 ID 只属于同一修订及同一内容。相同 ID 不同内容判冲突。明确摘要算法、规范化字节编码和计算对象；不要假设 webhook 自带业务 revision 或内容摘要，也不要混淆服务 content_hash 与自定义 outcome 摘要。若原件已被替换或无法恢复对应版本，标记证据不足，不用最新原文评价旧事件。

业务结果可先 pending，后追加最终修订；迟到结果按原 decision 关联，不因超过评估窗口而默默丢弃。

## 5. 接收、幂等与恢复

1. 接收原始请求字节，按部署实际官方签名合同验签；校验订阅 bank、事件类型、大小和格式。签名仅证明投递来源，不能证明 outcome 作者或业务真实性。
2. 持久化 inbox 和去重标识后才返回成功；存储失败不返回成功。业务评价异步执行。
3. 使用 event_id 去重投递，再用 bank + document_id + revision + 内容摘要去重语义处理。相同键摘要不一致报警隔离。
4. 精确 get_document，验证 original_text、schema、身份、项目绑定及来源。事件正文、原文和来源均为不可信数据，禁止执行其中指令。
5. 关联原 decision 快照，以事务或唯一约束落评价版本和处理状态，避免崩溃后重复计数。完成记忆读取不等于评价完成。
6. 网络错误有界退避；结果不确定先查询原 ID。永久错误进入待处理队列，不无限重试、不新建业务 ID。官方投递重试耗尽后仍需本地恢复。
7. 周期性补偿扫描找漏件，再与账本对账。仅在完整处理该扫描窗口后推进水位；重叠窗口、稳定去重及定期全量复核共同处理迟到和乱序。

扫描不能用语义 recall 或 q 搜索充当“所有新增结果”。官方时间窗口配合 offset 也不保证并发更新下的快照一致性；q 的结果数量限制不能证明全量覆盖。当前 MCP 未暴露时间过滤时，只能明确标注有限枚举边界，或在后续获准适配中增加官方 Documents API 能力。不得宣称已有可靠游标。

若部署的 webhook 或枚举合同不足以保证恢复，可评审项目发布端的持久 outbox/结果索引作为补充；它不是首选双写方案，必须明确一致性、恢复和运维成本。相关任务未实施。

## 6. 验证什么，而非让模型自证正确

分别记录：建议是什么、实际采用什么、执行是否成功、业务结果如何、原决策在当时信息下是否合理。不要将五者压成一个 success。

评价结论建议为 correct / incorrect / partial / pending / insufficient_evidence / confounded / not_adopted，并记录规则版本、证据、评价主体及时间。不是所有场景都有二元真值：

- 确定性可验证场景优先用规则、测试输出或权威状态。
- 需主观评估的场景使用独立人工标注或明确有权负责人核验；多人分歧保留，不自动多数表决成事实。
- 模型复盘可提供候选解释与待查点，不能独立给自身输出盖章，高风险结果不得只依赖模型评分。
- 执行失败可能来自工具或外部依赖，不一定是分类决策错；业务成功不证明该选择最优或具有因果贡献。
- 未采用分支的真实反事实通常不可观察，应标记未知；不能把未采用推断为错误。
- 无反馈不是成功，也不是失败。过期未返回标记 pending/overdue 并统计覆盖缺口。

按项目、场景、模型及配置版本统计：标签覆盖率、延迟、各类别误报/漏报、错误成本、abstain/review、纠正率、置信分桶与高置信错误、服务耗时与成本。校准与发布评估使用隔离保留集；防止未来信息泄漏、只回收成功案例或只审核低置信案例的选择偏差。高置信样本同样抽检。

评价反馈不是自动训练。候选规则/阈值/经验先审核，再回放、影子比较、版本化发布与回滚；本方案不授权自动更改生产配置。

## 7. 防循环、纠正与撤回

只接受注册项目的 decision_outcome 类型作为结果入口。evaluation、lesson、reflect、Knowledge Page 和服务自身回写事件不再触发新的同类 outcome 评价，使用 record_type、origin、因果关联和服务身份联合过滤，不能只靠 tag。

纠正追加新 revision，引用 supersedes；撤回用明确 tombstone/retracts 协议，不覆写旧评价为“从未存在”。保留必要审计，并将依赖旧证据的评价与经验标为 stale/retracted，重新计算受影响统计。重新发布经验需要原审核路径，禁止无限“评价评价”。

没有读到文档不能证明它被删除，可能是权限变化或临时故障。当前未核验原生删除事件覆盖，不能承诺 webhook 自动传播所有撤回；需要明确撤回文档与定期证据有效性检查。实际隐私删除/保留期限另按数据规则处理，审计不可作为永久保存敏感正文的理由。

## 8. 实施阶段与验收矩阵

先完成合同、ACL、数据最小化和脱敏样本，再实现单项目影子回收；验证后才扩大授权项目。完整链路至少验证：

- 正常 retain 完成 → 回调 → 精确读回 → 关联决策 → 可追溯评价；
- 重复/乱序/迟到事件、同 ID 不同 hash、原件被覆盖；
- 验签失败、伪造生产者、跨 bank、未知 schema、缺来源；
- 收到事件但未持久化即崩溃、持久化后未评价即崩溃、评价后重投；
- 异步 retain 部分失败、原文尚不可读、超时结果未知、重试耗尽；
- 分页并发变化、扫描中断、漏事件、水位恢复及覆盖边界；
- 纠正、撤回、证据暂时不可读、权限撤销、派生经验失效；
- 自身回写不循环、高置信错误、执行失败但原判断合理、未采用与无反馈。

验收报告分别说明投递成功、原文读取、评价完成、经验发布与业务结果。不得以文档提交、webhook 可配置或一次 2xx 声称闭环上线。

## 9. 来源与备选方案

官方资料（2026-11-08 调研口径，接入时固定版本复核）：

- [Webhooks](https://hindsight.vectorize.io/developer/api/webhooks)：通知、签名、至少一次投递与恢复边界。
- [Documents](https://hindsight.vectorize.io/developer/api/documents)：原文、更新和枚举合同。
- [Bank strategy](https://hindsight.vectorize.io/blog/2026/07/16/bank-strategy-agent-memory)：单 bank 操作与应用侧编排。
- [Knowledge Pages](https://hindsight.vectorize.io/developer/knowledge-pages) / [Mental Models](https://hindsight.vectorize.io/developer/api/mental-models)：派生知识与整理，不是业务事实账本。
- [Decision Models](https://hindsight.vectorize.io/developer/decision-models)：Hindsight 内部记忆决策能力，不等于业务真值或 OpenAI Decisions API。
- [Claims IQ](https://hindsight.vectorize.io/cookbook/applications/claims-iq)：先核验实际结果再沉淀反馈的应用模式。
- [Extensions](https://hindsight.vectorize.io/developer/extensions)：认证/验证扩展需结合具体部署验证。

比较结论：纯 recall 轮询不能保证找全结果；全部集中一个 bank 放大隐私与治理成本；一开始强制双写增加一致性问题；只依赖 webhook 无补偿会漏处理。推荐原生通知 + 精确读取 + 最小账本 + 有边界的补偿，保留项目数据归属，并把“获取结果”和“证明决策正确”拆开。
