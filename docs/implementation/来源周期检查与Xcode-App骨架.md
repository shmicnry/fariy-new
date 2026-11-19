# 来源周期检查与 Xcode App 骨架

日期：2026-11-19。本迭代完成网页来源的周期检查、每日网络预算和失败退避，并把
SwiftUI Package 补成可构建的 macOS/iOS Xcode App target。

## 网页来源周期检查

新增配置：

- `source_refresh_enabled`，默认关闭；
- `source_refresh_interval_hours`，默认 24 小时，范围 1–168；
- `source_refresh_daily_limit`，默认每日 5 次，范围 0–50。

每项网页来源都有独立 `source_refresh_schedule`。worker 每次周期最多检查一个到期来源，
使用 Mac 本地日期或 `FAIRY_DAY_TIMEZONE` 统计当日网络检查次数。手动刷新和自动检查
共同占用每日上限。

检查结果：

- 内容未变：记录检查时间，按间隔安排下一次；
- 内容变化：创建来源新版本，旧来源和派生内容失效，新版本按间隔继续调度；
- 读取失败：当前来源保持有效，失败次数加一，并采用指数退避；
- 退避从基础间隔翻倍，最长 168 小时；
- 同一调度 revision 使用独立幂等键，重放不会重复网络请求。

管理端「世界与知识」页面可以设置启用状态、间隔和每日上限，并显示网页来源的下一次
检查时间。其他页面保存无关配置时会保留这些字段。

## Xcode App target

`apps/ios/FairyApp/FairyApp.xcodeproj` 现包含一个单一多平台 `Fairy` App target：

- 共享 `FairyApp` Scheme；
- `Config/Fairy-Info.plist`；
- iOS entitlements；
- macOS App Sandbox，包含出站网络权限；
- macOS 14、iOS 17 最低版本；
- application product，而不是命令行 executable。

以下无签名构建已实际生成 `.app`：

```sh
xcodebuild -project FairyApp.xcodeproj -scheme FairyApp \
  -destination 'platform=macOS' CODE_SIGNING_ALLOWED=NO build

xcodebuild -project FairyApp.xcodeproj -scheme FairyApp \
  -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build
```

当前没有选择 Apple Developer Team，因此不声称完成签名、APNs、App Store 归档或真机
安装。APNs 与麦克风权限 entitlement 需要在实际签名能力和隐私用途确定后加入。

## 验证

- PostgreSQL 16：**137 passed，0 skipped**；
- 内容变化、未变化、失败退避和每日预算均有回归；
- 真实 Chromium：来源计划 UI、配置保留、自主账本、表单保稿和 P3–P5 通过；
- 34 个桌面/390px iPhone/深色页面状态无未命名或过小控件、截断、溢出和运行错误；
- iOS Simulator Xcode App target：构建通过；
- macOS Xcode App target：构建通过；
- `Info.plist` 与两个 entitlements：`plutil` 校验通过。

## 当前边界

周期检查只在 Fairy worker 运行时发生，不承诺 Mac 睡眠期间准点执行。当前每轮只检查
一个来源，避免网络读取阻塞 worker 过久。真实公网访问仍受现有 DNS 和公网地址规则
约束，失败会按退避计划重试。
