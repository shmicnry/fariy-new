# Fairy · fariy-new

最新设计规范：[Fairy UI 设计语言与交互规范 v1](docs/implementation/Fairy-UI设计语言与交互规范-v1.md)，对应本地 Skill：`$fairy-ui-design`。

最新阶段：[来源周期检查与 Xcode App 骨架](docs/implementation/来源周期检查与Xcode-App骨架.md)。网页来源支持计划检查、每日网络上限和失败退避；SwiftUI Package 已补齐可构建的 macOS/iOS App target、Info.plist 与 entitlements。

上一阶段：[网页来源版本刷新](docs/implementation/网页来源版本刷新.md)。网页内容变化会创建新来源与课程，失效旧来源及派生记忆；未变化和失败都有独立审计状态。

上一阶段：[自主执行账本与表单保稿](docs/implementation/自主执行账本与表单保稿.md)。自主目标现支持启动、暂停、继续、完成结算、取消释放和无上限时间自动停机；Web 与 SwiftUI 已同步。

最新全量审计：[P3–P5 缺漏审计与修复](docs/implementation/P3-P5缺漏审计与修复.md)。修复技能调用状态未持久化、自主页覆盖 Mac 授权、原生请求超时、PWA 离线回退、配置边界、Compose 端口和 CI PostgreSQL 缺口；加入执行账本、来源刷新与周期检查后 PostgreSQL 全量回归 **135 passed**。

最新审计：[P2缺漏审计与修复](docs/implementation/P2审计修复.md)。修复文件幂等、学习结论撤销、精确最终依据、来源失效、测验取消和撤回入口等问题；最终在隔离 Postgres 16 上 **108 项回归全部通过**。

最新P2：[学习、来源与世界知识闭环](docs/implementation/P2学习与世界知识.md)。新增链接登记、来源复核、带出处的知识主张、练习评分和效果记录；真实公网采集在当前DNS环境下受阻，详见限制。

最新进展：[P1可靠性收尾与P2文件学习启动](docs/implementation/P1收尾与P2启动.md)。学习中心现支持TXT/Markdown文件、带位置的阅读分块、断点续读和带出处的练习；数据库新增版本迁移与备份恢复命令。

Fairy 0.3 实现 **Ollama 本地主模型 + 可配置云副模型 + 可审阅记忆 + 学习与世界知识 + 技能/Mac + iPhone/Mac 界面 + 自主预算与隔离进化实验**。当前版本还增加了 macOS 常驻 worker/API、全页面 SSE 更新、通知中心、本地 TTS/OCR、只读 Mac helper 和 SwiftUI 操作页面。

## 当前可以做什么

- 先调用本机 Ollama 原生 `/api/chat`。本地明确表示能力/知识不足，或发生已配置的技术故障时，最多调用一次云副模型。
- 在「模型与路由」切换已安装的本地模型，配置兼容 Chat Completions 的云地址、模型、密钥、升级条件及每日请求次数。
- 每轮可选择自动路由、仅本机、先本机再请副模型协助。云端默认只收到当前问题；额外发送本轮检索到的已确认记忆需要明确选择。
- 对话生成有逐字出处的记忆提案；确认后才参与长期召回。支持拒绝、查看来源、纠正、版本记录及遗忘。记忆保留逐字原文，同时标明主体和第三人称事实；明确的饮品偏好问句只依据对应主体的已确认记录回答。
- 纠正会屏蔽相关旧对话来源；来源变化或取消后，旧模型结果不能提交，也不能继续发往云端。
- 投喂 TXT/Markdown/PDF/DOCX，按页或段落保留出处，支持练习、固定题测验和来源复核；网页来源可显式或按期检查版本，支持每日网络上限和失败退避。
- 技能安装、限时授权、启用和停用分离；Mac 桥可读取状态、应用和允许目录，并可在四层条件满足时启动允许列表中的应用。
- 管理界面接收 SSE 事件并更新相关页面；小表单有未提交内容时会保留草稿并显示刷新提示。
- 通知中心保存后台更新、审批和提醒；浏览器授权后可在页面后台显示系统通知。
- macOS 使用 `/usr/bin/say` 提供本地 TTS；配置 Whisper CLI 与模型后可使用本地 ASR。
- macOS Vision helper 可对用户明确上传的图片做 OCR，并报告真实辅助功能/屏幕录制权限状态。
- iPhone 可安装为 PWA；SwiftUI 页面可操作记忆、课程、审批、技能和自主候选，并提供设备本地通知与朗读。
- 自主候选受每日分钟和候选数量硬预算；接受后的目标可启动、暂停、完成或取消，达到预留时间后自动暂停；隔离进化实验不会自动修改运行版本。

**当前仍没有键鼠输入注入、屏幕内容采集、真实视频通话、APNs、自动公网选题或自动代码发布。** Mac helper 的 Accessibility Tree 读取仍要求用户在系统设置中授权；神经语义嵌入和真实云模型也需要用户选择并配置模型。

## 在这台 Mac 上运行

Python 3.11+，从仓库根目录执行：

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install -e '.[test]'
export FAIRY_OLLAMA_MODEL='qwen3:4b'
FAIRY_TOKEN='替换为你自己生成的足够长的随机令牌' scripts/start_local_api.sh
```

Ollama 应已启动，且模型已经安装。本次在你的机器上使用已有 `qwen3:4b` 完成真实验收，没有下载新模型。

打开 `http://127.0.0.1:8010`，输入同一 `FAIRY_TOKEN` 连接。令牌只在页面内存保存，刷新后需重新连接。主模型默认地址为 `http://127.0.0.1:11434`。`.env.example` 是说明文件，程序不自动读取它。

打开「模型与路由」，点击「检测本机模型」，选择模型并保存。模型配置保存在 SQL；环境变量仅用于首次建立配置，之后在后台更新，防止重启覆盖已保存的配置。

### 配置云副模型

1. 在「模型与路由」填写 HTTPS 接口根地址，例如服务商的 `/v1` 根地址、模型名和密钥。当前适配 `/chat/completions`、`max_tokens` 和普通文本响应。
2. 选择允许发送的内容、升级条件和每日请求上限。
3. 开启「允许本地能力不足或故障时调用云副模型」并保存。

密钥不写入 SQL、不返回给页面、不进入事件日志；本机凭证文件权限为 `0600`，目录为 `0700`，位于 `FAIRY_STATE_DIR/credentials`。当前为私有文件存储，尚未使用后端 Keychain，也不提供文件内容加密。更换接口地址需要重新提供密钥，避免把旧密钥发送到新地址。

也可用 `FAIRY_CLOUD_BASE_URL`、`FAIRY_CLOUD_MODEL` 初始化云配置，并通过与该地址绑定的 `FAIRY_CLOUD_API_KEY` 提供环境密钥。界面不回显环境密钥，清除它需要修改启动环境并重启。云模型默认关闭，填好配置后再开启。

当前没有真实云凭证，因此云端路由通过可控 HTTP 服务测试；没有发出付费云请求。模型自报“需要帮助”是升级信号，不能证明回答正确；需要实时数据时，云模型也不会凭空获得联网工具。用户要求补充信息和明确拒绝不会自动升级。

## Mac、iPhone 与 PWA

「Mac 操作」页可配置应用与目录允许范围。`mac_execute` 只有在至少一个允许应用存在时才能开启；开启后仍需要安装并限时授权 `Mac 启动允许应用` 技能。唯一写入动作是 `/usr/bin/open` 启动允许应用，返回结果明确标为“窗口未验证”。不允许任意 shell、参数透传、键盘/指针注入、屏幕录制或文件写入。

管理网页已是可安装 PWA。iPhone 本地用 Safari 连接可信 HTTPS 地址后，可通过“添加到主屏幕”使用大标题、底部标签栏、44pt 控件、毛玻璃和安全区布局。Service Worker 只缓存静态外壳，不缓存 `/v2/` API 数据。

默认 API 只接受回环 Host。物理 iPhone 接入时，应通过可信 HTTPS 反代或 Tailscale Serve，并同时设置：

```sh
export FAIRY_ALLOW_LAN=1
export FAIRY_ALLOWED_HOSTS='你的精确HTTPS主机名'
```

只监听可信私有网络，不应把 `0.0.0.0:8010` 明文暴露到公网。原生 SwiftUI 页面的地址栏可填写该 HTTPS 地址，所有者令牌保存到 Keychain。

### 体验记忆闭环

1. 在「对话」输入“请记住，我喜欢喝茉莉花茶。”
2. 打开「记忆审阅」，查看原文，再点击「确认记住」。
3. 回到对话询问“我喜欢喝什么？”
4. 在记忆页纠正为“我现在喜欢喝温水。”并填写原因；查看版本记录，再次询问。
5. 遗忘该记忆后，当前条目和版本不再召回，相关旧来源从后续上下文屏蔽。

纠正保留历史，遗忘清除对应记忆版本；原始材料/对话证据保留供手动查看。需要删除来源时使用来源删除 API，会级联失效其派生内容。不保证清除 SQLite 空闲页、已有备份或供应商副本。

## 常驻 API 与学习 worker

macOS 用户级 LaunchAgent 使用独立运行副本和共享状态目录，避免后台进程受 `Documents` 目录 TCC 限制：

```sh
scripts/fairy_worker_service.sh install
scripts/fairy_api_service.sh install
scripts/fairy_backup_service.sh install
```

安装后：

- API：`http://127.0.0.1:8010`
- API owner token：`$HOME/Library/Application Support/Fairy/api-token`
- 状态与数据库：`$HOME/Library/Application Support/Fairy/state`
- 运行副本：`$HOME/Library/Application Support/Fairy/worker-runtime`
- 日志：`$HOME/Library/Logs/Fairy`

服务和 token 文件不包含在 Git 中。常用命令：

```sh
scripts/fairy_worker_service.sh status
scripts/fairy_worker_service.sh logs
scripts/fairy_worker_service.sh restart
scripts/fairy_api_service.sh status
scripts/fairy_api_service.sh logs
scripts/fairy_api_service.sh restart
scripts/fairy_backup_service.sh run
scripts/fairy_backup_service.sh status
```

worker 具有单实例锁、心跳、异常退避和 SIGTERM 停止处理。API 界面在「运行总览」显示真实心跳。

文字材料经过提取式阅读进入待验证，所有者填写练习证据后确认；形成的习得知识没有执行权限。自主预算使用 Mac 本地日期，记录预留、执行秒数和结算；每日设置不能降到当前已预留和已执行时间以下。

## 验证

```sh
python -m pytest -q
python scripts/export_contract.py
# 显式运行真实本机模型验收；使用临时数据库和合成资料，不调用云端：
python scripts/acceptance_ollama.py
```

P1 基线 **62 项回归通过**；P2 最新为87项通过、1项Postgres环境测试跳过；加入常驻服务、同步、语音、OCR、语义检索、原生操作、P3–P5 缺漏修复、自主执行账本、来源版本刷新与周期检查后，在隔离 Postgres 16 上 **135 项全部通过**。真实浏览器和本机 Ollama 闭环分别保留在报告中：

- [P1 实施与验证记录](docs/implementation/P1-模型与记忆闭环.md)
- [Ollama 实测结果](docs/implementation/p1-ollama-acceptance.json)
- [浏览器实测结果](docs/implementation/p1-browser-results.json)
- [P1 运行截图](docs/implementation/screenshots/p1/)
- [P3–P5 纵切记录](docs/implementation/P3-P5-纵切交付与验证.md)
- [P3–P5 缺漏审计与修复](docs/implementation/P3-P5缺漏审计与修复.md)
- [自主执行账本与表单保稿](docs/implementation/自主执行账本与表单保稿.md)
- [网页来源版本刷新](docs/implementation/网页来源版本刷新.md)
- [来源周期检查与 Xcode App 骨架](docs/implementation/来源周期检查与Xcode-App骨架.md)
- [P3–P5 浏览器结果](docs/implementation/p3-p5-browser-results.json)
- [UI 控件审查与优化](docs/implementation/UI控件审查与优化.md)
- [Fairy UI 设计语言与交互规范 v1](docs/implementation/Fairy-UI设计语言与交互规范-v1.md)
- [fairy-ui-design Skill](.agents/skills/fairy-ui-design/SKILL.md)
- [UI 交互语言浏览器结果](docs/implementation/ui-language-browser-results.json)
- [UI 控件浏览器审计结果](docs/implementation/ui-audit-browser-results.json)
- [运行底座与自主能力增强](docs/implementation/运行底座与自主能力增强.md)
- [SSE 同步与通知浏览器结果](docs/implementation/sync-notifications-browser-results.json)
- [OCR 与本地语音浏览器结果](docs/implementation/ocr-voice-browser-results.json)
- [bge-m3 语义检索浏览器结果](docs/implementation/semantic-retrieval-browser-results.json)
- [通知中心截图](docs/implementation/screenshots/notification-center.png)
- [P3 Mac 页面截图](docs/implementation/screenshots/p3-mac-desktop.png)
- [P5 自主与进化截图](docs/implementation/screenshots/p5-autonomy-desktop.png)
- [iPhone PWA 截图](docs/implementation/screenshots/p4-iphone-layout.png)

云端请求预留在调用日志中，每个回合的每个阶段只派发一次。失败和超时也计入每日次数，超时费用为未知，不自动重试。重启时过期请求标记为结果未知；未过期的 pending 可以在对话或识海页中断。每日次数上限不是金额硬上限。

从 `apps/ios/FairyApp` 可运行 `swift build`，也可直接构建 `FairyApp.xcodeproj` 的 macOS/iOS Simulator App target；工程已包含显式 Info.plist、iOS entitlements 与 macOS App Sandbox 网络权限。尚缺开发者团队签名、APNs、真机推送和媒体验收。

GitHub Actions 已配置。前次云端 runner 受账号账单/支出限制，未能启动；本机验证独立完成。`compose.yaml` 是已有 Postgres/API/worker 模板，本轮未运行容器验收；Postgres在P1收尾时已通过独立实例回归。Ollama 回环连接目前按宿主进程部署，容器不能把其自身的 `127.0.0.1` 当作宿主 Mac。

## 工程与资料

```text
server/fairy/        领域服务、记忆/学习、模型、技能、Mac 桥、自主预算、进化实验、API、worker
apps/web/            管理端、iPhone PWA、记忆/学习/技能/Mac/自主页面和 SSE
apps/ios/FairyApp/   macOS/iOS SwiftUI Package、Keychain、真实 API 页面
apps/mac-bridge/     只读 Mac 桥与受限应用启动边界
contracts/           从代码生成的实际 OpenAPI
scripts/             契约导出、隔离的真实模型/浏览器验收
tests/              自动回归
docs/reference/     原始 v4.2 设计、Word、原型、截图、流程图、示例
docs/implementation/ v4.3 方案、P1 最新交付与运行证据
```

原始资料中的命令与部署建议仅作设计输入。仓库保持私有，未替你选择开源许可证。当前服务是本机单所有者模型，没有公网多用户认证。
