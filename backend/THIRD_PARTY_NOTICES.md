# 第三方组件

后端直接依赖的第三方组件。依赖有变化时同步更新本文件。

| 组件 | 版本 | 许可证 | 用途 |
|---|---|---|---|
| fastapi | 0.143.2 | MIT | HTTP 接口 |
| pydantic | 2.14.1 | MIT | 数据模型与校验 |
| uvicorn | 0.54.0 | BSD-3-Clause | ASGI 服务器 |
| SQLAlchemy | 2.0.54 | MIT | 数据库访问（Core） |
| python-oracledb | 26.0.1 | Apache-2.0 或 UPL-1.0 | Oracle 驱动 |
| Alembic | 1.20.0 | MIT | 平台表迁移 |
| redis-py | 7.1.0 | MIT | Redis 客户端 |

开发和测试用（不随产品分发）：pytest 8.4.2（MIT）、httpx 0.28.1（BSD-3-Clause）、Hypothesis 6.140.2（MPL-2.0）、import-linter 2.15（BSD-2-Clause）。
