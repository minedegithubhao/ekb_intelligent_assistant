# ekb_intelligent_assistant

本仓库是 RAG 知识库项目的 Python/FastAPI 后端仓库。前端 Vue 工程由独立 Git 仓库维护，本仓库只包含后端应用、配置、部署脚本、初始化 SQL 和后端资源。

## 当前完成范围

- BE-01：FastAPI 工程初始化
- BE-02：YAML 配置加载与内存配置对象
- BE-03：MySQL 连接、ORM 基类、数据库 session 依赖
- BE-04：Redis 与 Milvus 基础连接工具
- BE-05：统一响应、统一异常、请求日志和错误日志
- BE-06：登录鉴权、JWT token、普通用户/管理员角色权限

BE-07 暂未实现。当前只建了系统角色模型（`admin`、`user`）。知识库可见级别会影响上传参数、文档/chunk 元数据、Milvus 过滤条件和检索服务，需要先确认设计后再落表。

## 第一阶段检查结论

当前基底与 `RAG项目任务拆解.md` 的第一阶段目标基本一致：

- FastAPI 可以从项目根目录启动，并提供 Swagger/OpenAPI。
- 配置文件集中在 `config/`，启动时加载为内存配置对象。
- MySQL、Redis、Milvus 均已有基础连接封装和健康检查。
- JSON 接口统一返回 `code/message/data`。
- 未登录返回 `401`，普通用户访问管理员接口返回 `403`。
- 初始化 SQL 已记录在 `scripts/sql/001_init_auth.sql`。
- 日志模块已提供请求日志和错误日志落盘能力。

暂未进入第一阶段之外的内容：

- BE-07 知识库可见级别与访问控制模型。
- 会话、消息、检索链路、文档上传、构建入库。
- LangChain Milvus 的 Retriever/VectorStore 封装。

## 项目结构

```text
ekb_intelligent_assistant/
  app/                 后端 Python 应用代码，app 是 Python 包根
  config/              YAML 配置文件
  resources/           prompt、模板、小型种子数据等轻量可版本化资源
  scripts/sql/         初始化和迁移 SQL
  deploy/wsl-docker/   WSL Docker 基础服务部署文件
  source_data/         当前已有知识源原始/清洗数据
  logs/                运行时日志目录，程序自动生成，Git 忽略
```

大模型文件不放入本仓库。当前通过 `config/app.yaml` 引用：

```text
E:/Heima-AI/knowforge-rag-platform/models
```

## 启动后端

先确认 WSL Docker 中 MySQL、Redis、Milvus 已启动，然后在 PowerShell 中执行：

```powershell
cd E:\Heima-AI\ekb_intelligent_assistant
D:\Tools\Anaconda3\envs\knowforge-rag\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

接口文档：

- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/openapi.json`

健康检查：

- `GET /api/health`
- `GET /api/health/dependencies`

## 初始化账号表

SQL 脚本：

```text
scripts/sql/001_init_auth.sql
```

执行命令：

```powershell
cd E:\Heima-AI\ekb_intelligent_assistant
wsl -d Ubuntu -- bash -lc "docker exec -i knowforge-mysql mysql --default-character-set=utf8mb4 -uroot -pknowforge_root_2026 < /mnt/e/Heima-AI/ekb_intelligent_assistant/scripts/sql/001_init_auth.sql"
```

示例账号：

| 用户名 | 密码 | 角色 |
| --- | --- | --- |
| `admin` | `Admin@123456` | `admin` |
| `alice` | `User@123456` | `user` |
| `bob` | `User@123456` | `user` |

## 认证接口

- `POST /api/auth/login`
- `GET /api/auth/me`
- `POST /api/auth/logout`
- `GET /api/auth/admin-check`

所有普通 JSON 接口统一返回：

```json
{
  "code": 0,
  "message": "success",
  "data": {}
}
```

## 日志位置

日志模块在 `app/core/logging.py`。

程序启动后会自动创建 `logs/` 目录：

- `logs/app.log`：请求日志和普通应用日志
- `logs/error.log`：错误日志

同时日志也会输出到控制台，方便本地开发时直接查看。

## LangChain Milvus 说明

当前第一阶段的 BE-04 只完成 Milvus 底层连接、collection 命名和基础工具，因此代码里直接使用 `pymilvus`。

`LangChain Milvus` 会在后续检索与写入链路中接入，主要对应：

- BE-09 用户提问流式接口中的检索服务
- BE-15 构建版本与写入 Milvus
- 具体 Retriever / VectorStore 封装
