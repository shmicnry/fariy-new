# 备份健康、扫描 PDF 与来源白名单

日期：2026-11-19。本迭代补齐三项不依赖外部账号的上线前能力。

## PostgreSQL 备份健康与恢复演练

每日备份现在执行完整闭环：

1. 读取数据库各表记录数；
2. 使用 `pg_dump --format=custom` 创建 `0600` 备份；
3. 在一次性 PostgreSQL 数据库中执行 `pg_restore --exit-on-error`；
4. 比较恢复后的 records、events、requests、scope_locks、schema_version 数量；
5. 删除恢复演练数据库；
6. 原子写入 `backup-status.json`。

状态 API：

```text
GET /v2/maintenance/backup/status
```

返回最后备份时间、文件、SHA256、恢复数量、错误和年龄。超过 36 小时未成功更新时
自动标记为 `stale`。管理端“运行总览”已显示该状态。

## 扫描 PDF 逐页 OCR

Mac bridge 增加 PDFKit 逐页渲染和 Vision OCR：

- 文字层页面继续直接提取；
- 只有空白或扫描页执行 OCR；
- 每页最多限制 2000 像素边长；
- 最多 100 页、256000 字符；
- PDF 解析 CPU 时限为 60 秒；
- 输出保留页码、OCR 页列表和混合提取方法。

真实扫描 PDF 验收已完成：由界面截图生成的纯图片 PDF 被逐页识别，页码为 1，
正文包含预期的 `Fairy` 和“学习中心”等文字。

## 来源白名单与版本差异

新增配置 `source_allowed_hosts`：

- 支持精确域名，例如 `example.com`；
- 支持子域通配，例如 `*.example.com`；
- 留空时仍执行原有公网 HTTPS 和私网拒绝规则；
- 链接导入、手动刷新和 worker 自动检查三处共同校验；
- 被禁止的域名不会发起网络请求。

版本变化时生成有限差异摘要，包括新增/删除行数、最多三条样例行和截断状态。摘要写入
新来源与刷新审计，不保留旧正文副本。管理端可设置白名单，并在新来源卡片显示变化行数。

## 验证

- PostgreSQL 全量回归：**137 passed，0 skipped**；
- 自动备份和恢复演练：逐表数量一致；
- 真实 Vision PDF OCR：通过；
- 图片 OCR + 扫描 PDF OCR + worker 浏览器闭环：通过；
- 来源白名单拒绝发生在抓取前；
- 内容变化生成新增/删除行摘要；
- 34 个桌面、iPhone、深色页面状态：无控件、溢出或运行错误；
- Mac bridge release 构建：通过。

## 当前边界

- 恢复演练要求数据库用户具有 `CREATEDB` 权限；
- 备份仍保存在本机，没有异地副本；
- OCR 仍依赖 macOS Vision；
- 域名白名单只限制主机，不判断页面内容质量；
- 差异摘要是按行比较，不是语义 diff。
