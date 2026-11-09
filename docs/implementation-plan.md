# 首版并行实施与审计安排

日期：2026-11-09。公子要求与“梳理仓库与关联项目”协作，重整方案、拆任务并新开 gpt-6.1-sol 会话并行推进；随后明确两位原会话只负责审计复核，不编写实现代码。此前“先不开发”和当日暂停针对上一阶段，本次实施以此新指令为准；既有设计、权限及 Hindsight 配置约束继续有效。

## 依据、范围与责任

基线为本仓 `59a23d3` 及当前已确认文档；昨晚 `docs/hindsight-decision-models.md` 的未提交运行回执修订单独保留。约束优先顺序为公子当前指令、[已采纳架构](architecture.md)/[ADR-001](decisions/001-shared-decision-service.md)/[ADR-002](decisions/002-mvp-deliverables-and-sqlite.md)、[反馈语义](outcome-feedback.md)、[v1 接口合同](api-contract.md)，再到本计划的派工细节。

本次实现目标：一个可本地运行的 HTTP/SQLite 决策服务，原生 OpenAI Decisions 与按需跨 bank 检索，两类预设，以及 Herdr 的采用、结果回收和恢复补传。先把两仓闭环做实，MCP 在 Agent 消费需要明确后共用核心增加；本轮不扩展插件、Hindsight webhook、任意运行中改图或新的业务状态机。

- 当前会话：服务合同、任务队列和服务/provider 审查；只改方案/说明，运行已有验证，不写或代修实现及测试代码。
- 关联审查会话：Herdr 消费者方案、源码兼容性和接入审查；与本会话交叉复核，亦不写或代修实现及测试代码。
- 新实现会话：各自实现、测试、修复审查发现并交证据；均请求 `gpt-6.1-sol`、`high` 推理强度。请求设置与工具接受/实际读回证据分别记录，不凭自报宣称后台型号。
- 这是一轮临时实现协作，不授予组织岗位、角色任命或业务验收权。真实任务验收沿原项目负责人/指定验收者，不把代码审查通过写成业务验收。

## 发散比较与收敛

| 拆法 | 价值 | 主要代价 | 结论 |
| --- | --- | --- | --- |
| 服务、workflow 接入、role 接入各一会话 | 三条业务结果直观 | 两个 Herdr 写者同时依赖 HTTP client、outbox 与原单关联；现有审批还精确依赖 `{choice,evidence}`，增加公共文件冲突 | 不采用本轮并行拆法；workflow/role 保留为同一会话的两个切片 |
| 服务核心、外部 provider、Herdr 消费者 | HTTP 与两函数接缝可以先固定；服务/provider 文件隔离，Herdr 原状态与补传一个写者 | 需先固定请求/响应和 provider 返回结构，再集中联调 | 采用 |

ARCHITECTURE TRIAGE：`BOUNDARY_NOTE`。本轮将已接受的公共服务/原执行器边界具体化为 v1 HTTP 和两个内部 provider 函数；SQLite 仍归服务，检查点与业务执行仍归 Herdr/项目，依赖方向不变。以两仓合同测试和原审批兼容性核对这些边界；不借任务拆分改写验收口径，不新增 ADR 回合。

## 并行边界与共同约定

先由两位审查会话复核 `api-contract.md`，再释放 S/P/H 实现。三个会话可同时研究原源码、准备各自用例；依赖未到时完成本片独立工作，不复制对方模块抢跑。当前未请求 worktree，复用两个现有 checkout，按下列文件归属隔离写入。

- 一份可变状态队列：本仓 `.codex/agent-state/decision-mvp/todo.md`；本计划只定义任务，不重复维护完成勾选。实现者通过会话回报，原审查会话更新队列。
- `docs/api-contract.md`、本计划、README、架构、路线图和 ADR 由审查会话维护。实现者提出修改意见，不自行覆盖公共合同或昨晚既存文档修改。
- 实现会话不得执行全仓 `git add`、切换共享分支、重置或提交其他写者文件；本轮先交局部 diff 和验证回执。提交/推送由后续明确的串行收口处理，不让共享索引并发写入。
- 不创建或变更真实组织角色、生产任务、私有 bank/权限、Hindsight 配置、Win 服务或凭据。普通开发依赖安装可在项目 `.venv` 内进行；不改系统 Python 或另建复杂部署设施。
- 原 Hindsight Luna 专用 key 和普通 LLM key 保持分离，不自动复制到新的业务服务。真实外部调用及部署所需配置列为独立联调输入，缺失不阻塞隔离环境中的实现，但也不能将 mock 结果冒称实际接通。

## S：服务核心与最小反馈闭环

- 输入：架构、反馈合同、api-contract v1，P 的两函数接缝。
- 独占写权：`pyproject.toml`、依赖锁定文件、`.gitignore`、`src/decision_service/`（排除 P 的 `providers.py`）、服务单元/HTTP测试（排除 `tests/test_providers.py`）、`docs/development.md`、`skill/decision-service/SKILL.md`。不改公共方案文档。
- 技术约束：Python 3.11+、标准 sqlite3；HTTP 使用 FastAPI/Pydantic/uvicorn，P 所需 httpx 依赖由 S 统一维护。先核当前官方/实际安装 API 和版本，不从文档假设已有环境。不开 ORM、缓存平台或泛化多存储接口。
- 切片：先完成 evaluate→SQLite→get 和 application/result→查询；再接入 P 的真实适配、两类预设、身份/范围、错误与冲突处理、覆盖率和轻量 Skill。先有端到端路径，再补剩余有效错误场景。
- 验收：冻结候选重放不重新推理；相同 ID 异内容冲突；查询只读；重启后记录可读；同事件修订去重/乱序正确；模型推荐与实际值分开；usage 全缺省仍有效且无现金字段；越界不扩大 bank/project 范围。
- 证据：实际安装版本、可运行启动/测试命令、测试结果与受影响 diff；在 `docs/development.md` 给出固定的 `.venv/bin/python` 检查入口和隔离配置示例。服务自身 API/持久化用例必须覆盖有意义的失败路径，不只测试字段映射。
- 依赖：可先用测试替身实现；合并接通依赖 P 函数，跨仓检查依赖 H。真实 provider/部署验收另列，不因凭据未知声称 M1 已完成。

## P：OpenAI Decisions 与 Hindsight 检索适配

- 输入：api-contract 的两函数接缝、官方 Decisions/recall 合同、仓内 Hindsight 接入说明。
- 独占写权：`src/decision_service/providers.py`、`tests/test_providers.py`、`docs/provider-integration.md`。不改包初始化、pyproject、SQLite、HTTP 入口或 S 的测试。
- 切片：实现对已获准 bank 列表的有界并行 recall，保存必要来源/部分失败，限制实际送入模型的证据；实现 gpt-6-luna 有限问题请求、类型/refusal/异常处理；返回原生可得 usage，不估算现金。
- 验收：不默认扫库；空检索/部分失败能按合同返回；API 异常不默认通过；predicate/choice/score/refusal 分开；无私有 bank 内容或 key 写入日志；不通过模型生成 shell/新业务计划。
- 验证：使用本地可控 HTTP 替身或 httpx mock transport，检查请求体、模型返回、超时/拒绝/部分 bank 失败；不为开发用例访问生产记忆或调用真实付费模型。版本敏感合同查官方来源并在接入文档说明。
- 依赖：S 提供包/依赖环境和启动调度；P 不创建第二套 runtime。函数签名调整先报两位审查者并同步消费者。

## H：Herdr 工作流与角色消费者

- 输入：v1 HTTP 合同、Herdr 工作流/角色宿主文档及原模板、Worker、执行器代码；以对侧审查者核准的文件范围为准。
- 独占写权：Herdr 的 `scripts/project_workflow_template.py`、必要的 `scripts/project_workflow.py`，新增 `scripts/decision_service_client.py`、`scripts/project_workflow_decision.py`、`scripts/herdr_model_selection.py`；`tests/test_project_workflow.py` 及相应新增 client/decision/model-selection 测试。消费者文档由原审查会话根据实际交付更新，实现者不直接修改；昨晚 `docs/status.md` 修改保留。
- H1：status→冻结请求/候选→evaluate/get→原 decide→读回 application；原 checkpoint 保存关联和待回传事件，沿原恢复入口补传。保持 `decisions[step]` 的 `{choice,evidence}` 精确结构，关联/outbox 另存；不破坏旧生成定义/source hash 绑定。同一步可关联 workflow 与 model 等多个 decision_ids；一次执行的 result 使用一个稳定事件关联这些决策，不重复上报两份执行。
- H2：一条 Mac Codex 原创建/下一工作单元入口的模型选型与配置接线，复用同一 HTTP client/反馈。必须交出可调用的 apply/reconcile 接线，不止于 prepare/helper；消费已绑定的原 workflow 单元和目标 Herdr 原生身份，沿原创建者已允许的入口应用。先核安装参数 schema；recommended、launch、effective 分别记录，准备 argv 不冒称生效，effective 未确认可回传；未知启动不再次 start。
- 验收：采用前重核原 step/快照；decide 保存后 advance 失败不判未采用；action 清空后仍能关联原单元；补传不调用 decide/resume/派发；空模型候选直接 unavailable；使用原工作单元结果和已有质量引用，取消请求不算终态。
- 禁止：改现任角色恢复参数、审批模块、coordinator_goal_channel、私有配置、在途生成物；不复制任务状态机，不凭本轮测试创建实际组织角色。若现有入口必须改这些边界，先向审查会话给具体阻碍及最小替代，不扩大写权。
- 验证：先跑 `python3 -m unittest discover -s tests -p 'test_project_workflow*.py' -v` 和新增专项；最终集中跑一次 `python3 scripts/check_repository.py`、`python3 -m unittest discover -s tests -v`。保持原测试命令和既存失败证据，不因隔离用例通过标记真实宿主采用。

## 集成、审查与完成边界

S/P/H 首轮可并行；S 接入 P 后，S 与 H 按同一 HTTP 合同跑本地跨仓闭环。实现者负责诊断和修复自己代码，审查会话只读 diff/证据并运行已交付检查；不替实现者补代码。

集中检查正常路径，以及响应丢失、同 ID 冲突、部分 bank 失败、反馈重投/质量修订、原 decide 已提交但后续报错和未知模型配置。S 对服务/provider 负责本仓集成，H 对消费者和原兼容性负责，两个审查会话交叉确认观察范围。

完成等级分开：

1. **实现可审**：指定文件的代码、适用测试、开发入口和局部回执齐备；生产配置未变。
2. **隔离闭环通过**：真实本地 HTTP/SQLite 与原 workflow 模板运行、反馈及恢复可读回；provider/角色宿主使用替身处明确标记。
3. **实际运行与业务验收**：另以获准 provider/明确 bank、一条合法原生角色配置应用及原工作流任务取得回执；生产部署位置/认证/密钥注入及业务验收责任方须具体落实。前两级不等于第三级，也不等于整个路线图完成。

当前三个任务具备并行编码与隔离验证的输入；真实凭据、部署位置和自然任务/角色验收尚未落实到本次执行队列，不承诺已具备无人干预的全生产交付条件。先完成明确授权的工程工作，后续只对需要真实配置/原生接续的部分收口。未授权新建 Goal、自动监控或新组织岗位，本计划不启用这些设施。
