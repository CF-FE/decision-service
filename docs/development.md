# 本地开发与隔离验证

使用 Python 3.11+ 和项目唯一的 `.venv`。依赖由 `pyproject.toml` 声明，`uv.lock` 固定解析结果。验证时使用 CPython 3.11.15、SQLite 3.50.4、FastAPI 0.162.2、Pydantic 2.14.3、HTTPX 0.28.1、Uvicorn 0.54.0、MCP SDK 2.3.0、FastMCP 4.1.6 和 pytest 9.2.0。

在仓库根目录运行：

```sh
rtk proxy uv sync --locked --no-cache --python 3.11
rtk proxy .venv/bin/python -m pytest -q
```

如 shell 没有 RTK，直接运行其后面的命令。用 `uv python list --only-installed` 查实际解释器；若基础解释器的扩展加载失败，可将 `--python` 指向已安装的 CPython 3.11+ 绝对路径。不要另建一套 provider 环境。版本敏感入口依据 [FastAPI 错误处理](https://fastapi.tiangolo.com/tutorial/handling-errors/)、[Pydantic 严格校验](https://docs.pydantic.dev/latest/concepts/strict_mode/)、[Python sqlite3](https://docs.python.org/3.11/library/sqlite3.html) 及 [HTTPX transports](https://www.python-httpx.org/advanced/transports/)，启动参数以安装的 `.venv/bin/python -m uvicorn --help` 为准。

以下示例使用临时数据目录、虚拟凭据和单一候选，完整经过真实 HTTP 与 SQLite，无上游调用。在仓库根目录启动：

```sh
decision_dev_dir="$(mktemp -d)"
chmod 700 "$decision_dev_dir"
cat > "$decision_dev_dir/config.json" <<EOF_CONFIG
{
  "db_path": "$decision_dev_dir/decision.sqlite3",
  "callers": {
    "local-test-only": {"caller_scope": "local-test", "project_ids": ["demo"], "bank_ids": []}
  },
  "service_bank_ids": [],
  "default_banks": {}
}
EOF_CONFIG
DECISION_SERVICE_OPENAI_API_KEY= DECISION_SERVICE_HINDSIGHT_API_KEY= \
DECISION_SERVICE_CONFIG="$decision_dev_dir/config.json" \
rtk proxy .venv/bin/python -m uvicorn decision_service.app:create_app \
  --factory --host 127.0.0.1 --port 8765 --workers 1 --no-access-log
```

在另一终端：

```sh
curl -fsS http://127.0.0.1:8765/health
curl -fsS http://127.0.0.1:8765/v1/decisions/evaluate \
  -H 'Authorization: Bearer local-test-only' -H 'Content-Type: application/json' \
  -d '{"schema_version":1,"request_id":"demo-1","kind":"choice","question":"继续到下一步？","context":{},"recall":"skip","choices":[{"candidate_id":"continue","description":"继续","parameters":{"step":"next"}}]}'
curl -fsS 'http://127.0.0.1:8765/v1/decisions?request_id=demo-1' \
  -H 'Authorization: Bearer local-test-only'
```

使用相同配置和数据库文件重启后，可再次查询同一记录。服务为单进程、单实例；重启时未落下上游结果的 `processing` 记录转为 `unknown`，无法确认答案的 Decisions 超时也记 `unknown`。同 ID 不自动重算。不要同时启动第二个实例访问同一文件；不要让消费者直读 SQLite。需要保留记录时配置持久数据目录，控制该目录和配置文件的读取权限。

`DECISION_SERVICE_CONFIG` 指向 JSON 文件。静态 caller 配置绑定身份、项目和 bank；有效 bank 为 caller 与 `service_bank_ids` 的交集。`default_banks` 是项目到默认列表的映射，无映射跳过 recall。使用同一 caller scope 的令牌应代表同一受信调用方。没有配置 caller 时，受保护接口没有有效凭据。

需要上游时，配置 `openai_base_url` 和 `hindsight_base_url`，用 `DECISION_SERVICE_OPENAI_API_KEY`、`DECISION_SERVICE_HINDSIGHT_API_KEY` 分别注入凭据；不要复用既有 Win 配置。其他配置见[接入文档](provider-integration.md)。`timeout_seconds`（默认 15）是一次判断的上游时间预算；recall 使用其中一部分后，Decisions 只得到剩余预算。没有后台重试。调试使用临时数据和替身；上游真实认证、部署及业务验收另行确认。

执行 API、反馈事件样例及错误码见 [v1 合同](api-contract.md)。`get` 的结果覆盖率从当前关联的源端观察计算。空且不完整的观察保留结果统计为 `null`。服务保存 usage 中的非现金数据，反馈重投按剔除现金字段后的内容判断。存在重叠或范围未知的用量保留在原事件中。

## Herdr 跨仓联调

准备包含 Decision Service 集成的 `herdr-4-codexcloud` checkout，需有 `scripts/project_workflow_decision.py`、`scripts/herdr_model_selection.py` 和 `tests/test_project_workflow_decision.py`。在 Decision Service 仓库根目录用现有 `.venv` 运行：

```sh
rtk proxy .venv/bin/python tests/integration/verify_cross.py
rtk proxy .venv/bin/python tests/integration/verify_role.py
```

默认使用与本仓相邻的 `herdr-4-codexcloud` 目录。其他位置可给任一命令加 `--herdr-root /path/to/herdr-4-codexcloud`。脚本使用临时 SQLite、真实 loopback HTTP、虚拟凭据以及 provider 和角色宿主替身，成功时各输出一条 JSON 回执。第一条检查回执丢失、进程中断和原端补传，第二条检查角色配置回读和共享结果事件。

## MCP 与部署

同一进程在 `/mcp` 提供无状态 Streamable HTTP。反向代理使用 `deploy/caddy-route.example` 时，客户端连接 `https://<host>/decision-service/mcp`。服务按 `mcp_allowed_hosts` 和 `mcp_allowed_origins` 核对请求。REST 和 MCP 都接受 Decision Service 的静态 Bearer 凭据。MCP 的 `evaluate_decision` 和 `record_decision_feedback` 直接接收 v1 请求对象，`get_decision` 接收 `decision_id` 或 `request_id`。成功结果沿 REST 字段返回，工具错误在 `structuredContent.error.code` 中返回。

云端 MCP 可用独立的 GitHub OAuth App。私有配置的 `github_oauth` 对象指定 `public_base_url`、已验证 GitHub 登录名到现有 `caller_scope` 的 `principals` 映射，以及 `allowed_client_redirect_uris`。OAuth App 的 callback 使用公共 base URL 加 `/auth/callback`。服务提供 DCR 和 S256 PKCE，调用前检查已验证主体与原 caller 权限。OAuth 签名用独立稳定密钥，客户端登记和令牌状态加密保存于服务数据目录的 `oauth/`。该目录的拒写预算为 8 MiB 与 512 个文件，已有记录不会被驱逐。

部署模板位于 `deploy/`。用 `rtk proxy sh deploy/build-release.sh /path/to/new-release` 构建 wheel、带哈希的锁定依赖和模板。目标主机用独立虚拟环境安装依赖，建议执行 `pip install --require-hashes -r requirements.lock.txt`，再用 `pip install --no-deps` 安装服务 wheel。将代码放在 release 目录并切换 `current`，SQLite 与 OAuth 状态放在 systemd 的 `StateDirectory`。首次回退可撤下服务路由并停止独立单元，后续回退可切回已验证的 release 与配置。

systemd 模板从 root 私有目录通过 `LoadCredential` 加载配置与分开的 OpenAI、Hindsight、GitHub 和签名材料。仅部署静态 Bearer 时可为未配置的上游和 OAuth 凭据路径准备空的 0600 文件，服务按配置选择启用的认证方式。管理员可用 `deploy/prepare-provider-key.py` 在交互终端隐藏录入 provider 凭据，随后经 SSH 标准输入交给服务主机的 `deploy/install-provider-key.py`。签名材料在目标主机生成。生产路由和凭据存放于仓库外。

公开入口部署后可用下方命令核对鉴权、工具发现、决策重放和反馈回执。加 `--live-decisions` 会为该稳定请求 ID 请求一次真实 OpenAI predicate。

```sh
rtk proxy .venv/bin/python deploy/smoke-deployment.py \
  https://decision.example.org/decision-service /path/to/private-caller-token \
  --request-id deployment-check-01
```

MCP 封装与安全配置依据 [Python SDK 低层接口](https://py.sdk.modelcontextprotocol.io/advanced/low-level-server/)、[Streamable HTTP 规范](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)、[FastMCP GitHub OAuth](https://github.com/PrefectHQ/fastmcp/blob/main/docs/v3/integrations/github.mdx) 和 [systemd 凭据说明](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html#Credentials)。
