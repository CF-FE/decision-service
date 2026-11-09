# Decision Service 插件安装

云端和本地包共用 [Decision Service Skill](../skill/decision-service/SKILL.md) 和三个 MCP 工具。MCP 是部署服务上的 Streamable HTTP 入口，工具使用与 [REST v1](api-contract.md) 相同的核心、权限和记录。

使用部署方已验证的完整 MCP URL。云端 App 和本地 Codex 分别完成 Decision Service 的原生 OAuth 授权。程序接入使用单独发放的 caller 凭据。

## 本地 Codex

从仓库根目录生成一个新的、可长期保留的本地 marketplace 目录。用实际已验证地址替换示例的 `MCP_URL`，并将 `MARKETPLACE_DIR` 设置为仓库外的新目录。

```sh
rtk proxy .venv/bin/python plugin/package_plugin.py local \
  --mcp-url "$MCP_URL" --output "$MARKETPLACE_DIR"
rtk proxy codex plugin marketplace add "$MARKETPLACE_DIR"
rtk proxy codex plugin add decision-service@cf-fe-decision-local
rtk proxy codex plugin list --marketplace cf-fe-decision-local --json
rtk proxy codex mcp login decision-service
```

本地包使用 Codex 兼容 manifest 和 `.mcp.json`。默认使用 Codex 的 OAuth 凭据存储。完成登录后，在新开的本地 Desktop 会话和 CLI 分别检查 `decision-service` 工具，并按获准的 `request_id` 运行一次 `get_decision`。CLI 安装回执、工具发现和查询结果分别核对。参见 [Codex 插件命令](https://learn.chatgpt.com/docs/developer-commands) 和 [Codex MCP 配置](https://learn.chatgpt.com/docs/extend/mcp)。

更新已安装的本地 Skill 时，提升本地 manifest 的补丁版本，将新 manifest 和 Skill 同步到已注册的 marketplace 源目录，再运行 `rtk proxy codex plugin add decision-service@cf-fe-decision-local`。沿用原 MCP 配置与 OAuth 登录，并从安装结果核对版本和 Skill 内容。

对已有安全凭据注入的本地调用进程，可用 `--auth bearer` 构建环境变量版本。进程从 `DECISION_SERVICE_MCP_TOKEN` 读取 caller token。该版本的安装验证限于实际获得变量的进程。

## 私有云端插件

1. 部署方验证 HTTPS MCP 入口、OAuth 发现和允许身份。公子在 ChatGPT 打开 **插件 → ＋ → 添加自定义 MCP 服务器**，使用已验证入口和 OAuth 方式，选择 **创建为插件**。在详情页完成账号安装，并按宿主提示授权。
2. 从原生插件读取已创建的 plugin ID、当前 release ID、`.codex-plugin/plugin.json` 和 `.app.json`。确认实际 App ID 和当前发布归属，然后生成 Skill 更新包。使用 Plugin Creator 的更新入口和原 release ID 应用补丁。
3. 重新读取同一个插件，核对 App ID、连接及 Skill。用目标云端会话选择插件，发现工具后执行一次获准的 `get_decision`，并核对源记录。

```sh
rtk proxy .venv/bin/python plugin/package_plugin.py cloud-skill \
  --native-manifest "$NATIVE_MANIFEST" --native-app "$NATIVE_APP" \
  --output "$ARCHIVE_PATH"
```

这个 ZIP 用于更新同一原生插件，引用原有 `.app.json`。首次挂载 Skill 及后续更新都应从当前发布读取 manifest。兼容清单中的 `./skills` 和 `./skills/` 都可用于打包，已有路径原样保留。Task Mailbox 已在同一账号验证过原生 App 路径，其初版直接打包的 MCP 插件曾显示为仅限桌面。参见 [原生创建步骤](https://developers.openai.com/plugins/build/plugins#create-and-test-a-plugin-locally-with-an-mcp-server) 和 [Task Mailbox 接入记录](https://github.com/ghyghoo8/create-network-sh/blob/main/fastmcp/task-mailbox/clients/README.md)。

## 验证

```sh
rtk proxy .venv/bin/python -m pytest tests/test_plugin_package.py -q
```

本地格式在 Codex CLI 0.167.0-alpha.3.2 的隔离配置目录内验证。原生 CLI 注册、安装和启用读回通过。原生 app-server 携环境变量配置的测试 Bearer 凭据，连接本地运行的 Decision Service，发现三个工具，执行 `evaluate_decision` 和 `get_decision`，并与同一临时 SQLite 上的 REST 读回核对。测试使用单个确定候选并跳过 recall。目标账号的安装、OAuth 和正式入口调用各自验证。
