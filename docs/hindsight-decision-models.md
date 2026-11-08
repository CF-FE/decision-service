# Hindsight Decision Models 与 OpenAI Decisions

核对日期：2026-11-08。状态：官方能力调研与接入建议，未部署、未实测。

## 结论与职责边界

可以使用 OpenAI，但不是将 Hindsight 整体换成一个 OpenAI 模型。

Hindsight Decision Models 是可选的内部判断层：辅助筛选记忆、辨别重复事实、判断证据是否足够、判断知识页是否需要更新；需要生成文字的工作仍由普通 LLM 完成。[1] 它不是本项目面向协调员、负责人和工作流的业务决策服务。

三类模型用途应分开：

- **记忆内部优化**：Hindsight → 原生 Decision Model provider。
- **业务有限判断**：decision-service → OpenAI Decisions API；按授权向 Hindsight 检索背景。
- **角色执行模型**：decision-service 按任务需求与复杂度选择宿主实际可用的模型/推理强度组合，原创建者应用。被选择的执行模型不要求与本服务的判断模型、Hindsight 内部模型相同。

结果与纠正沿原任务、服务反馈记录或后续自动回收取得，不能由上述模型输出自行证明正确。MVP 不等待项目 bank 写回，详见[结果回收方案](outcome-feedback.md)。

不建议为内部记忆判断再绕经 decision-service：优先复用原生 provider，减少依赖环和额外延迟。这是架构建议，不是已实现状态。

## 当前官方支持范围

| Hindsight 环节 | 使用 OpenAI Decision Model |
| --- | --- |
| Recall 判断/排序 | 支持，需显式启用对应配置 |
| Consolidation 判断 | 支持；需要改写的内容仍交给 LLM |
| Reflect | 当前不支持此 provider，保留 LLM-only 路径并告警 |
| Knowledge-page refresh | 当前不支持此 provider，保留 LLM-only 路径并告警 |

官方列出 provider `openai`，默认 `gpt-6-luna`。Reflect 与知识页刷新目前只支持 `hindsight`、`typesafe` 的 Decision Model。[2] 因此，“支持 OpenAI”不代表四个环节全部替换，也不意味着普通 LLM、embedding 或其他组件不再需要。

OpenAI 官方指南当前使用 `POST /v1/decisions`、`gpt-6-luna`，提供 predicate、choice、score 等有限答案类型；SDK 使用 `client.decisions.create(...)`。[4] 实施时锁定 SDK/服务版本，再核对合同与账户可用性。

## 配置方向（非已生效配置）

以下只有非秘密配置示意，不能直接视为本地部署兼容性证明：

```dotenv
HINDSIGHT_API_DECISION_MODEL_PROVIDER=openai
HINDSIGHT_API_DECISION_MODEL_MODEL=gpt-6-luna
HINDSIGHT_API_RECALL_DECISION_MODEL_PROVIDER=openai
```

通过受控秘密注入提供 `HINDSIGHT_API_DECISION_MODEL_API_KEY`；不要把实际值提交到仓库、日志、记忆或文档。

全局设置不等于 recall 已切换，recall 默认保留原 reranker，须显式设置其 provider。[3] 此处使用的是 `DECISION_MODEL` 配置族，不是修改普通 `LLM_PROVIDER`。

如果确有 reflect 加速需求，可以单独选择 `HINDSIGHT_API_REFLECT_DECISION_MODEL_PROVIDER=hindsight` 或 `typesafe`，并提供对应的独立 API key；跨 provider 不能假定继承全局 OpenAI key。[2][3] 也可先保持已有 LLM 路径。不要仅为统一供应商牺牲受支持的功能。

## 推荐实施与验证顺序

本节仅针对以后更换 Hindsight 内部 provider，不作为业务 Decision Service MVP 的前置。

1. 记录实际 Hindsight 版本/镜像与当前有效配置，确认已包含上述原生适配。在线最新文档不能证明现有实例具备能力。
2. 使用不含项目私密信息的固定样例，验证账户访问、模型可用性、超时、限流、拒绝及回退；先不改变生产记忆。
3. 比较原路径与新路径：recall 的人工标注相关性/遗漏率，consolidation 的错误合并/遗漏率，以及延迟和费用。不要只比较“回答速度”。
4. 分环节灰度，每次只改变一个变量，保存基线；异常时恢复原配置并验证路径。关闭判断层不等于自动撤回已经发生的记忆变更。
5. 业务决策沿自身 MVP 与使用反馈迭代；需要量化效果时再补标注集、对照或影子观察，不能用检索排序分数替代业务正确率。

建议两条调用链分开记录 provider/model、版本、调用量、延迟、失败和预算。身份/数据权限继续由服务端控制；共享供应商不意味着共享所有 bank 或允许扩大数据传输范围。启用外部 provider 前应核对哪些记忆片段会传出，以及对应授权。

## 与反馈回收设计的关系

MVP 由适配器直接回传应用与工作单元结果，保存在服务记录中。以后采用 Hindsight 回收时保留“项目 bank 存结果、服务按授权回收”的方向；该链路不是首版前置。Webhook 通知、记忆抽取完成和 consolidation 完成均不等于业务完成，更不等于决策正确。

Decision Models 可优化记忆处理成本，但不是 ground truth、审批或自动验收。Knowledge Pages/Mental Models 可以辅助汇总经验；纠错、修订、撤回、幂等及来源验证仍按[反馈方案](outcome-feedback.md)处理。

## 证据边界与来源

已核对：官方在线文档中的功能、provider、模型名与配置方向。
未核对：用户部署版本、实际配置、账户权限、额度、凭据、请求效果及端到端性能。
本次仅沉淀文档，没有部署、替换 provider、注入 key、开放跨 bank 权限或执行模型测试。也未据此确定最低兼容版本。

1. [Hindsight Decision Models](https://hindsight.vectorize.io/developer/decision-models)
2. [Hindsight Models：OpenAI Decisions](https://hindsight.vectorize.io/developer/models#openai-decisions)
3. [Hindsight Configuration：Decision model](https://hindsight.vectorize.io/developer/configuration#decision-model)
4. [OpenAI Decisions API 指南](https://developers.openai.com/api/docs/guides/decisions)
