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
2. 哪 3–5 个场景足够高频，且误判代价可控？
3. 实时状态与规则的权威来源、版本和有效期是什么？
4. 各身份可访问哪些项目、bank、场景与预算？
5. Hindsight 何时检索，何时允许写回，如何验证结果来源？
6. VPS 实际资源和端到端延迟是否满足目标？
7. 何种情况下 abstain/review，如何退回既有负责人流程？
8. 灰度前有哪些测试、监控、成本预算和回滚标准？

## 当前交付边界

只有仓库、文档、看板与规划。没有声称模型准确率、生产 SLA、部署健康或业务验收完成。公开材料已去除凭据、个人信息、内部网络/连接细节和私有来源内容。

## Hindsight webhook 与反馈回收补充（2026-11-08）

用户确认当前部署支持 webhook；这是部署能力说明，不是本项目端到端验证。调研覆盖官方 Webhooks、Documents、Bank strategy、Knowledge Pages、Mental Models、Decision Models 与 Extensions；链接、合同差异及设计取舍见[结果回收方案](outcome-feedback.md)。

当前 MCP 能精确读取文档原文，未暴露 webhook 管理及 Documents API 的时间窗口过滤；官方存在这些能力不代表当前适配已具备。上线前必须验证签名、至少一次投递去重、重试耗尽恢复、并发分页覆盖、不可变修订和所有路由的项目读写隔离。原生删除事件覆盖尚未核验，撤回不能只依赖回调。当前新增交付仍只有文档，没有配置 webhook、开放跨项目访问、写入运行结果或执行自动评价。
