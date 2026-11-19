# PostgreSQL 单一数据库迁移

日期：2026-11-19。Fairy 已从 SQLite 本机库切换为 PostgreSQL 16 单一数据库。

## 当前部署

- PostgreSQL：Homebrew `postgresql@16`，本机 `127.0.0.1:5432`
- 数据库：`fairy`
- 所有者：当前 Mac 用户 `aliez`
- API 与 worker 连接：
  `postgresql+psycopg://aliez@127.0.0.1:5432/fairy`
- 运行中 API 返回：`storage = postgresql`

数据库与凭证分开保存。模型凭证仍在
`$HOME/Library/Application Support/Fairy/state/credentials`，不进入数据库备份。

## 数据迁移

迁移前停止 API、worker 与备份任务，冻结 SQLite，然后逐表导出到 PostgreSQL：

| 表 | 迁移记录 |
|---|---:|
| records | 14 |
| events | 3 |
| requests | 2 |
| scope_locks | 1 |
| schema_version | 1 |

迁移后对五张表逐行比较，SQLite 与 PostgreSQL 内容完全一致。事件自增序列按原最大
`seq` 恢复，API 和 worker 启动后继续使用原有 ID、revision、幂等记录和事件游标。

## 备份

PostgreSQL 备份使用 `pg_dump --format=custom`，不再是文件复制：

```text
/Users/aliez/Library/Application Support/Fairy/backups/fairy-20261119-165947.dump
sha256: 791f47ec26eed2744abb339d2cfced487e707ea7c76567148ce7e1c05726f2d6
mode: 0600
```

备份已通过 `pg_restore --list` 校验，包含 schema、表、数据、约束和索引。恢复使用
`pg_restore --exit-on-error`，只应指向新建或空的 PostgreSQL 数据库，不覆盖现有库。

## 代码变化

- `Store` 只接受 `postgresql` backend，其他 URL 直接拒绝；
- PostgreSQL advisory lock 是唯一迁移锁；
- API ASGI 入口改为 `fairy.asgi:app`，避免测试导入时创建数据库连接；
- API、worker 与本地启动脚本不再提供 SQLite 默认地址；
- 每日备份改为 PostgreSQL custom dump；
- 测试使用临时 PostgreSQL schema，每个测试隔离，结束后删除；
- CI 只运行 PostgreSQL；
- 测试、OpenAPI 生成和真实 Ollama 验收均要求显式 PostgreSQL URL。

## 已删除

以下 SQLite 运行文件在 PostgreSQL 备份校验成功后删除：

- `$HOME/Library/Application Support/Fairy/state/fairy.db`
- `$HOME/Library/Application Support/Fairy/state/fairy.db.migrate.lock`
- `$HOME/Library/Application Support/Fairy/backups/fairy-*.db`
- 仓库 `var/fairy.db`
- 仓库 `var/fairy.db.migrate.lock`

代码中只保留一个反向测试：传入 `sqlite://` 时必须被拒绝，防止以后误切回 SQLite。
Xcode/SwiftPM 的 `.build/.../build.db` 是编译系统内部缓存，不属于 Fairy 产品数据库。

## 验证

- 迁移数据逐行一致；
- PostgreSQL 应用启动后读取到 6 个技能和原有记忆；
- API：`storage = postgresql`；
- worker：心跳正常，`source_refresh_status = null`；
- PostgreSQL 自定义备份：通过 `pg_restore --list`；
- 全量测试：**135 passed，0 skipped**；
- API LaunchAgent、worker LaunchAgent 和每日 03:00 备份 LaunchAgent 均已指向 PostgreSQL。

## 运维要求

PostgreSQL 必须保持运行：

```sh
brew services start postgresql@16
brew services list | grep postgresql
```

如果数据库不可用，Fairy API 和 worker 会启动失败或在运行中降级；不会再静默退回
SQLite。
