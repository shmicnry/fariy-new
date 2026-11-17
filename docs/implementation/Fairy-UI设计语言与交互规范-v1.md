# Fairy UI 设计语言与交互规范 v1

日期：2026-11-18。

完整规范位于已安装 Skill：

- [`fairy-ui-design/SKILL.md`](../../.agents/skills/fairy-ui-design/SKILL.md)
- [`design-standards.md`](../../.agents/skills/fairy-ui-design/references/design-standards.md)
- [`sources-and-rationale.md`](../../.agents/skills/fairy-ui-design/references/sources-and-rationale.md)

## 方向

- 产品：本地优先的个人认知工作台，所有者在这里审阅记忆、教授知识、授权技能、监督自主行为并核验结果。
- 性格：安静、精确、有生命感。
- 世界：像一台 macOS 认知观测仪，而不是通用 AI 聊天模板。
- 记忆点：来源、当前状态、权限与执行结果之间的“trace rail”。
- 品牌信号：所有重要动作都能沿状态、证据、权限和恢复路径被看见。

## 六条不可妥协的规则

1. **设计先解释功能。** 能用分组、状态、直接操作、实时预览、过渡和可恢复历史表达的内容，不再补一段小字说明。
2. **选择正确浮层。** Tooltip 解释词义，Toast 报告完成，Popconfirm 确认局部动作，Alert 显示阻塞问题，Modal 只处理短决策，Drawer 审阅长对象，页面承担多步骤任务。
3. **禁止危险遮罩误关。** 脏表单和确认弹层不能通过点击遮罩关闭。
4. **单层边框、同心圆角。** 嵌套内容优先使用分隔线和表面层级；必须嵌套时 `内圆角 = 外圆角 - 间距`。
5. **动效只解释变化。** 使用按压、表面变化、抽屉、Toast、真实数字、进度和真实流式打字；不使用循环发光、边框流光、磁吸、3D 倾斜、文字乱码和装饰视差。
6. **平台行为必须原生。** macOS 保留侧栏、工具栏、键盘、悬停、拖拽和可调分栏；iPhone 保留 44pt 触控、底部标签、Sheet、安全区和触觉反馈。

## 已实施的交互细节

- macOS 侧栏可拖拽、方向键调整、Home/End 到边界、双击或 Esc 复位，宽度持久化。
- 通知中心与记忆检查使用右侧 Drawer；危险动作使用明确名称的确认 Modal。
- 操作完成使用 Toast，按钮在异步期间显示处理中。
- 记忆卡片、技能卡、自主候选不再形成“框中框”，改为单层分隔记录。
- 技能中心用四阶段生命周期展示安装、授权、启用和执行。
- 自主预算使用带数字动画的真实进度计。
- 对话记录上翻后停止自动跟随，显示“跳到最新”。
- 中文输入法组合态按 Enter 不会误发送，Shift+Enter 换行。
- 长文件名从中间截断并保留扩展名。
- 背景同步不会覆盖脏表单，也不会把用户拉回页面顶部。

## 参考视频

- [弹窗、抽屉、页面选型](https://www.douyin.com/video/7698358547440094502)
- [16 种 UI 动效](https://www.douyin.com/video/7707202818528910159)
- [Apple 风与 AI 组件方向](https://www.douyin.com/video/7704266431650993763)
- [大厂 AI 界面隐藏细节](https://www.douyin.com/video/7699520911870856483)

视频仅作为原则来源。没有复制视频画面、组件库代码或专有资产。

部分审查方法参考 Damir Sokolovsky 的 `unslop` Skill（CC BY 4.0）；本规范是针对 Fairy 的产品化改编。
