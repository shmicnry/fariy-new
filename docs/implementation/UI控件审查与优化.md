# UI 控件审查与优化

日期：2026-11-17。

本轮审查覆盖管理端 15 个页面，并分别在 1440px macOS 桌面宽度、390px iPhone 宽度以及四页深色模式下验证，共 34 个页面状态。

## 主要调整

- 侧栏按“工作台、认知、自主能力、个人空间、系统”分组，并统一为线性图标、清晰的选中指示与 `aria-current="page"`。
- 连接成功后隐藏重复的服务令牌输入；连接状态改用颜色圆点表达，重连中断时切换为琥珀色。
- 按钮分为主操作、次操作和危险操作。异步按钮执行期间显示“处理中…”并进入禁用状态，防止重复提交。
- 文本输入、下拉框、文本域和文件选择统一高度、边框、悬停、焦点、禁用和无效状态。
- 表单增加稳定可见的标签和说明文字，不再依赖消失后的 placeholder 识别字段含义。
- 复选框视觉保持紧凑，但整个标签行提供可点击区域；iPhone 下统一到至少 44pt 的操作区域。
- 卡片层级收敛为普通面板与行内记录两级；技能卡重新排列权限、授权与操作，避免文字和按钮碰撞。
- 记忆检查改用原生 `dialog` 弹层，支持关闭按钮、Esc、点击遮罩关闭、焦点管理和移动端自适应高度。
- 移动端底栏更新为一致的线性图标，保留毛玻璃、安全区和选中背景。
- 页面进入、弹层打开、按钮按压和设置切换均有动效，并完整支持 `prefers-reduced-motion`。
- 深色模式重做了面板、输入框、主按钮、次按钮、星图和弹层关闭按钮的文字对比度。
- 浅色辅助文字与 iPhone/macOS 背景的对比度提升至 WCAG AA 阈值以上。

## 自动审查结果

最终干净数据库审计结果：

```text
pages: 34
unnamed controls: 0
undersized effective targets: 0
clipped controls: 0
dialogs verified: 2
horizontal overflow: 0
runtime errors: 0
browser errors: 0
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

审查脚本为 `scripts/browser_ui_audit.cjs`。它不会写入真实模型或云服务，只使用临时数据库、合成记忆和本机浏览器。
