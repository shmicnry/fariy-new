# Mac bridge integration boundary

当前未实现输入注入、屏幕采集、桌宠宿主和换装渲染。主 API 的 `/v2/mac/runs` 返回 501。
后续桥须独立校验 device / grant / policy_version / fencing / bundle_id / realpath / origin。
不能将主服务持有的令牌转换为任意 shell 权限。用户在系统中授予 AX 或 ScreenCaptureKit 权限前只支持能力检测。
