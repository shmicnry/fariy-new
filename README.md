# Fairy · fariy-new

基于你提供的 Fairy v4.2 设计包，重构为可以启动、验证、逐步扩展的个人 AI 助手工程。仓库名按要求保留为 `fariy-new`，产品名为 Fairy。

**当前交付是可运行的核心工程 0.1，完整自主助手仍在建设。** API、管理网页、文字学习队列、来源记忆、站内审批闭环已实现；Mac 执行、语音视频、自动进化和完整 iOS App 尚未实现。能力状态直接反映在 API 和界面中。

## 从这里阅读

- [完善后的架构与实施方案](docs/implementation/Fairy-v4.3-实施方案.md)：系统边界、交互流程、设计修正、验收路线。
- [实现状态与验证记录](docs/implementation/验证与能力矩阵.md)：逐项区分设计、实现与实际验证。
- [原始设计资料](docs/reference/)：解压后的原始文档、页面原型、截图、Mermaid 图和 JSON 示例，保持参考用途。
- [API 契约](contracts/openapi.json)：以当前代码生成的 `/v2` OpenAPI，不代表原设计中全部接口已实现。

## 本机启动

Python 3.11+，以下命令从仓库根目录运行：

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install -e '.[test]'
export FAIRY_TOKEN='替换为你自己生成的足够长的随机令牌'
export FAIRY_DATABASE_URL='sqlite:///var/fairy.db'
python -m uvicorn fairy.app:app --host 127.0.0.1 --port 8000
```

浏览器打开 `http://127.0.0.1:8000`，在连接框输入同一令牌。令牌只保存在页面内存，刷新后需重新连接。`.env.example` 只是配置说明，应用不会自动读取它；通过环境变量传入。

另开终端，进入同一目录、激活同一虚拟环境，并设置相同的 `FAIRY_DATABASE_URL`：

```sh
python -m fairy.worker
```

在「学习中心」登记文字材料，worker 将建立提取式笔记，进入「待人工验证」。填写实际练习证据并确认通过，才可归纳为「习得知识」。这一过程不会安装可执行技能。

模型可选，在启动 API 前配置：

```sh
export FAIRY_MODEL_BASE_URL='http://127.0.0.1:11434/v1'
export FAIRY_MODEL_NAME='你实际安装的模型名称'
export FAIRY_MODEL_API_KEY='服务商要求的密钥，本地模型可留空'
```

这只是 OpenAI 兼容 Chat Completions 传输适配器；没有模型会明确返回 `model_not_configured`。配置远程模型后，当前输入、选中的来源记忆和最近对话会发给该模型。密钥仅在后端使用，不进入页面或仓库。

## 已贯通的路径

1. 文字输入 → 幂等回合 → 来源记录 → 模型回答 → 独立回执事件；同一 scope 只能有一个 pending 回合。
2. 原文证据 → 人工摘录记忆 → 关键词召回 → 上下文装配；删除来源会使派生记录及在途回答失效。
3. 文字材料 → 持久任务 → 有边界的提取式阅读 → 人工验证 → 习得知识。
4. 站内保存笔记提案 → 五分钟有效的审批 → 摘要与版本校验 → 一次执行；自建卡片不能替代审批。
5. Mac 应用/目录允许列表预配置 → 持久化版本；执行开关固定关闭，不会操作本机。

## 测试与部署

```sh
python -m pytest -q
python scripts/export_contract.py
```

当前验证：25 项 SQLite/接口/并发回归通过；浏览器验收记录与截图见能力矩阵。模型成功测试使用可控 HTTP mock，没有消耗付费调用或验证特定真实服务商。

`compose.yaml` 提供 Postgres、API、worker 的部署结构，需要设置 `FAIRY_TOKEN` 和 URL 安全的 `FAIRY_DB_PASSWORD`。本次未运行 Docker/Postgres 验收。当前使用开发建表逻辑，正式上线前需补迁移、备份恢复和 Postgres 集成测试。HTTP 服务面向本机单所有者，不提供公网多用户认证。

## 代码分工

```text
server/fairy/       持久化、认知规则、领域服务、API、worker
apps/web/           接真实 API 的响应式管理台与文字会话
apps/ios/           Swift API 传输起点（不是完整 App 工程）
apps/mac-bridge/    Mac 执行桥契约（没有执行器）
contracts/          当前接口契约
scripts/            契约导出、浏览器验收
tests/             可执行回归测试
docs/reference/    原始设计交付包内容
docs/implementation/ 本次完善方案、状态、真实运行截图
```

不固定在原来的十大系统；完整目标采用六个平面、十三个职责模块，逐项映射到上述工程与后续里程碑。参考资料内的命令、安装步骤及发布建议是设计输入，不会因此自动执行。仓库保持私有；未替你选择新代码的开源许可证，原设计与第三方素材的权利不因上传而改变。
