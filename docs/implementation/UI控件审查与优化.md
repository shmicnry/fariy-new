# UI 控件审查与优化

日期：2026-11-19。

本轮审查覆盖管理端 16 个页面，并分别在 1440px macOS 桌面宽度、390px iPhone 宽度以及四页深色模式下验证，共 36 个页面状态。

## 主要调整

- 侧栏按“工作台、认知、自主能力、个人空间、系统”分组；顶部身份、中间分组导航和底部系统工具分区固定，只有中间区域在短窗口中滚动。
- 连接成功后隐藏重复的服务令牌输入；连接状态改用颜色圆点表达，重连中断时切换为琥珀色。
- 按钮分为主操作、次操作和危险操作。异步按钮保留动作名称和宽度，以小型进度标记和禁用状态防止重复提交。
- 文本输入、下拉框、文本域和文件选择统一高度、边框、悬停、焦点、禁用和无效状态。
- 表单增加稳定可见的标签和说明文字，不再依赖消失后的 placeholder 识别字段含义。
- 复选框视觉保持紧凑，但整个标签行提供可点击区域；iPhone 下统一到至少 44pt 的操作区域。
- 卡片层级收敛为普通面板与行内记录两级；技能卡重新排列权限、授权与操作，避免文字和按钮碰撞。
- 记忆检查改用原生 `dialog` 弹层，支持关闭按钮、Esc、点击遮罩关闭、焦点管理和移动端自适应高度。
- 移动端底栏保持五个主入口；溢出页面统一从“更多”分组进入，保留毛玻璃、安全区和选中背景。
- 路由数据等待超过 180ms 时显示结构匹配的骨架屏；API 很快返回时不会闪现骨架。
- Chrome 支持时渐进使用连续曲率，其他浏览器保留普通圆角。
- 原始记录折叠项在关闭态显示字段数量，展开后保持完整原始数据。
- 页面进入、弹层打开、按钮按压和设置切换均有动效，并完整支持 `prefers-reduced-motion`。
- 深色模式重做了面板、输入框、主按钮、次按钮、星图和弹层关闭按钮的文字对比度。
- 浅色辅助文字与 iPhone/macOS 背景的对比度提升至 WCAG AA 阈值以上。

## 自动审查结果

最终干净数据库审计结果：

```text
pages: 36
unnamed controls: 0
undersized effective targets: 0
clipped controls: 0
dialogs verified: 2
horizontal overflow: 0
runtime errors: 0
browser errors: 0
fixed sidebar shell: passed
skeleton delay: passed
continuous corners: supported
```

机器可读结果见 `ui-audit-browser-results.json`。

真实交互回归同时通过：

- P2：文件上传、worker、练习原文、检索、来源复核、知识主张、练习评定、最终确认和来源撤销；
- P3–P5：Mac 只读状态、设备范围、技能安装/授权/调用/停用、自主候选、预算、隔离进化评测和人工评审；
- PWA manifest、Service Worker 注册与 390px 布局。

## 截图

- `screenshots/ui-controls/desktop-learning.png`
- `screenshots/ui-controls/iphone-models.png`
- `screenshots/ui-controls/desktop-dialog.png`
- `screenshots/ui-controls/dark-learning.png`

v1.1 交付截图：

- `screenshots/ui-v1.1/desktop-overview.png`
- `screenshots/ui-v1.1/desktop-route-skeleton.png`
- `screenshots/ui-v1.1/iphone-overview.png`
- `screenshots/ui-v1.1/iphone-chat.png`
- `screenshots/ui-v1.1/iphone-dialog.png`
- `screenshots/ui-v1.1/iphone-more.png`
- `screenshots/ui-v1.1/dark-models.png`

审查脚本为 `scripts/browser_ui_audit.cjs`。它不会写入真实模型或云服务，只使用临时数据库、合成记忆和本机浏览器。

## 交互语言复核

基于 `fairy-ui-design` Skill 的第二轮优化进一步覆盖：

- 通知和长内容使用右侧 Drawer；
- 危险操作使用动作名称明确的确认 Modal，遮罩不能误关；
- 操作完成使用 Toast；
- 嵌套记录改为单层分隔，不再形成框中框；
- 技能中心使用四阶段生命周期；
- 自主预算使用真实进度计与数字动画；
- macOS 侧栏可拖拽、键盘调节并持久化；
- 聊天上翻后停止跟随，提供“跳到最新”；
- 中文输入法组合态 Enter 不误发送；
- 长文件名从中间截断并保留扩展名。

对应浏览器证据见 `ui-language-browser-results.json`。
