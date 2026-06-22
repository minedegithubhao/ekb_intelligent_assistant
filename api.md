# 后端统一接口文档

## 1. 文档说明

本文档用于前端、后端、RAG 服务和测试人员对接当前第一版后端能力。

当前状态：

- 已实现：登录鉴权、当前用户信息、登出、管理员校验、管理员用户管理、仪表台参数配置、配置版本管理、健康检查。
- 已预留：用户端聊天会话、历史消息、提问接口、RAGService 调用边界。
- 暂不包含：真实 RAG 检索、向量库入库、文档切分、实时语音识别接口。

## 2. 通用约定

| 项目 | 说明 |
| --- | --- |
| Base URL | 本地开发通过前端代理访问 `/api`，后端实际地址为 `http://127.0.0.1:8000` |
| 请求格式 | `Content-Type: application/json` |
| 鉴权方式 | `Authorization: Bearer <token>` |
| 成功判断 | HTTP 状态码为 2xx，且响应体 `code === 0` |
| 数据库 | `knowforge_rag` |
| 用户密码 | 后端使用 `pbkdf2_sha256` 存储和校验 |
| Redis | 缓存 token/session 用户信息，当前本地无密码 |

统一成功响应：

```json
{
  "code": 0,
  "message": "success",
  "data": {}
}
```

统一错误响应：

```json
{
  "code": 40100,
  "message": "invalid token",
  "data": null
}
```

常见错误：

| HTTP 状态 | code | 说明 |
| --- | --- | --- |
| 400 | `40000` | 业务校验失败，例如用户名重复、不能禁用自己 |
| 401 | `40100` | 未登录、token 失效、session 失效 |
| 403 | `40300` | 权限不足，例如普通用户访问管理员接口 |
| 422 | `42200` | 请求字段校验失败 |
| 500 | `50000` | 服务内部异常 |

## 3. 知识库类型约定

知识库目前固定两类，真实知识库和 RAG 检索暂未实现。

| 用户分类 `category` | 知识库类型 `knowledge_base_type` | 展示名称 |
| --- | --- | --- |
| `merchant` / `enterprise` | `enterprise` | 企业知识库 |
| `individual` / `personal` | `personal` | 个人知识库 |
| `admin` | 默认 `enterprise`，管理员端后续可切换 | 企业知识库 / 个人知识库 |

后续聊天、历史消息、RAG 提问接口统一携带：

```json
{
  "knowledge_base_type": "enterprise"
}
```

允许值只包括：

```text
enterprise
personal
```

## 4. 登录鉴权接口

### 4.1 登录

已实现。

```http
POST /api/auth/login
```

请求体：

```json
{
  "username": "admin",
  "password": "Admin@123456",
  "login_type": "admin"
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `username` | string | 是 | 登录账号 |
| `password` | string | 是 | 登录密码。当前后端按明文密码接收，然后用 `pbkdf2_sha256` 校验 |
| `login_type` | string | 否 | `admin` 或 `user`。传 `admin` 时要求账号拥有管理员角色 |

响应 `data`：

```json
{
  "access_token": "jwt-token",
  "token_type": "bearer",
  "expires_at": "2026-06-22T12:00:00",
  "user": {
    "id": 1,
    "username": "admin",
    "name": "系统管理员",
    "display_name": "系统管理员",
    "email": "admin@example.com",
    "department": "平台运营部",
    "category": "admin",
    "user_type": "admin",
    "roles": [
      {
        "code": "admin",
        "name": "管理员"
      }
    ],
    "question_categories": ["enterprise_shop", "individual_shop"],
    "question_category_names": ["企业店规则", "个人个体店规则"]
  }
}
```

登录成功后：

- 后端生成 JWT token。
- 后端写入 `user_sessions`。
- 后端将用户信息、角色、分类、可查询问题分类缓存到 Redis。
- 前端保存 `token`、`userInfo`、`roles`、`knowledge_base_type`。

### 4.2 获取当前用户信息

已实现。

```http
GET /api/auth/me
```

请求头：

```http
Authorization: Bearer <token>
```

响应 `data`：

```json
{
  "id": 1,
  "username": "admin",
  "name": "系统管理员",
  "display_name": "系统管理员",
  "department": "平台运营部",
  "category": "admin",
  "user_type": "admin",
  "roles": ["admin"],
  "is_admin": true,
  "question_categories": ["enterprise_shop", "individual_shop"],
  "question_category_names": ["企业店规则", "个人个体店规则"]
}
```

### 4.3 登出

已实现。

```http
POST /api/auth/logout
```

请求头：

```http
Authorization: Bearer <token>
```

响应 `data`：

```json
{
  "revoked": true
}
```

登出后：

- 当前 token 写入 Redis blacklist。
- MySQL `user_sessions` 中对应 session 标记为失效。
- 旧 token 再访问受保护接口应返回 401。

### 4.4 管理员校验

已实现。

```http
GET /api/auth/admin-check
```

说明：

- 需要管理员 token。
- 普通用户访问返回 403。

响应 `data`：

```json
{
  "username": "admin",
  "roles": ["admin"]
}
```

## 5. 管理员用户管理接口

以下接口均已实现，且都需要管理员 token。

### 5.1 用户列表

```http
GET /api/admin/users
```

查询参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `keyword` | string | 否 | 搜索账号、姓名、展示名 |
| `role` | string | 否 | `admin` 或 `user` |
| `status` | string | 否 | `enabled` 或 `disabled` |
| `page` | number | 否 | 默认 `1` |
| `page_size` | number | 否 | 默认 `100`，最大 `500` |

示例：

```http
GET /api/admin/users?page=1&page_size=100&role=user&status=enabled
```

响应 `data`：

```json
{
  "items": [
    {
      "userId": 2,
      "username": "alice",
      "name": "Alice",
      "displayName": "Alice",
      "email": "alice@example.com",
      "department": "招商部",
      "role": "user",
      "status": "enabled",
      "category": "merchant",
      "knowledgeBaseType": "enterprise",
      "knowledgeBaseName": "企业知识库",
      "createdAt": "2026-06-22T10:00:00",
      "updatedAt": "2026-06-22T10:00:00"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 100
}
```

### 5.2 新增用户

```http
POST /api/admin/users
```

请求体：

```json
{
  "username": "new_user",
  "password": "User@123456",
  "displayName": "新用户",
  "name": "新用户",
  "email": "new_user@example.com",
  "department": "招商部",
  "role": "user",
  "status": "enabled",
  "category": "merchant"
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `username` | string | 是 | 登录账号，不能重复 |
| `password` | string | 是 | 初始密码，后端保存为 `pbkdf2_sha256` 密文 |
| `displayName` | string | 是 | 展示名 |
| `name` | string | 否 | 姓名 |
| `email` | string | 否 | 邮箱 |
| `department` | string | 否 | 部门 |
| `role` | string | 否 | `admin` 或 `user`，默认 `user` |
| `status` | string | 否 | `enabled` 或 `disabled`，默认 `enabled` |
| `category` | string | 否 | `merchant` 表示企业知识库，`individual` 表示个人知识库，管理员可用 `admin` |

响应 `data`：返回新增后的用户信息，结构同用户列表中的单个用户。

### 5.3 编辑用户

```http
PUT /api/admin/users/{user_id}
```

请求体：

```json
{
  "displayName": "修改后的名称",
  "name": "修改后的名称",
  "email": "user@example.com",
  "department": "运营部",
  "role": "user",
  "status": "enabled",
  "category": "individual"
}
```

说明：

- 所有字段均可按需传递。
- 如果传 `password`，表示重置密码。
- 管理员不能移除自己的管理员角色。

### 5.4 修改用户状态

```http
PATCH /api/admin/users/{user_id}/status
```

请求体：

```json
{
  "status": "disabled"
}
```

说明：

- `enabled`：启用。
- `disabled`：禁用。
- 管理员不能禁用自己。

### 5.5 禁用用户

```http
DELETE /api/admin/users/{user_id}
```

说明：

- 当前实现为逻辑禁用，不是物理删除。
- 管理员不能禁用自己。

## 6. 仪表台参数与配置版本接口

以下接口均已实现，且都需要管理员 token。

### 6.1 获取当前生效配置

```http
GET /api/admin/dashboard/config
```

响应 `data`：

```json
{
  "source": "mysql",
  "version": {
    "id": 1,
    "config_key": "retrieval",
    "version_no": 1,
    "status": "active"
  },
  "model": "qwen-plus",
  "embedding_model": "bge-m3",
  "rerank_model": "bge-reranker-v2-m3",
  "variant_generation_enabled": true,
  "rerank_enabled": true,
  "top_k": {
    "faq": 20,
    "doc": 22,
    "rerank": 10,
    "final_evidence": 6
  },
  "thresholds": {
    "faq_high_conf": 0.85,
    "faq_middle_conf": 0.65,
    "doc_evidence": 0.55
  },
  "weights": {
    "faq_dense": 0.5,
    "faq_sparse": 0.5,
    "doc_dense": 0.72,
    "doc_sparse": 0.3
  },
  "raw": {
    "model": "qwen-plus",
    "doc_k": 22,
    "faq_k": 20,
    "rerank_enabled": true
  }
}
```

说明：

- `source=mysql` 表示来自 MySQL active 配置版本。
- `source=yaml` 表示 MySQL 没有 active 版本时回退到 `config/retrieval.yaml`。
- 前端修改参数时应基于 `raw` 复制一份完整配置，只覆盖用户编辑的字段，再保存为新版本。

### 6.2 查询配置版本列表

```http
GET /api/admin/config/versions
```

响应 `data`：

```json
[
  {
    "id": 1,
    "config_key": "retrieval",
    "version_no": 1,
    "status": "active",
    "description": "默认配置",
    "created_by": 1,
    "activated_by": 1,
    "activated_at": "2026-06-22T10:00:00",
    "created_at": "2026-06-22T10:00:00",
    "updated_at": "2026-06-22T10:00:00"
  }
]
```

### 6.3 新增配置版本

```http
POST /api/admin/config/versions
```

请求体：

```json
{
  "config": {
    "doc_k": 22,
    "faq_k": 20,
    "model": "qwen-plus",
    "doc_fetch_k": 50,
    "faq_fetch_k": 20,
    "rerank_model": "bge-reranker-v2-m3",
    "rerank_top_k": 10,
    "rerank_enabled": true,
    "embedding_model": "bge-m3",
    "doc_dense_weight": 0.72,
    "doc_sparse_weight": 0.3,
    "faq_dense_weight": 0.5,
    "faq_sparse_weight": 0.5,
    "final_evidence_top_k": 6,
    "variant_generation_enabled": true
  },
  "description": "调整仪表台参数",
  "activate": true
}
```

说明：

- `config` 建议提交完整参数对象，不建议只提交单个字段。
- `activate=true` 表示保存后立即启用。
- 启用新版本后，旧 active 版本会自动归档。

响应 `data`：

```json
{
  "id": 2,
  "version_no": 2,
  "status": "active"
}
```

### 6.4 启用指定配置版本

```http
POST /api/admin/config/versions/{version_id}/activate
```

响应 `data`：

```json
{
  "id": 2,
  "version_no": 2,
  "status": "active",
  "activated_at": "2026-06-22T10:30:00"
}
```

## 7. 用户端聊天与历史消息接口

当前为预留接口，前端已有 API 封装，后端真实接口尚未实现。

这些接口后续由后端负责保存会话、历史消息，并调用 `RAGService` 获取回答。

### 7.1 查询会话列表

预留。

```http
GET /api/conversations?knowledge_base_type=enterprise
```

请求头：

```http
Authorization: Bearer <token>
```

响应 `data` 建议：

```json
[
  {
    "conversation_id": "conv_001",
    "title": "企业店入驻规则",
    "knowledge_base_type": "enterprise",
    "created_at": "2026-06-22T10:00:00",
    "updated_at": "2026-06-22T10:10:00"
  }
]
```

### 7.2 新增会话

预留。

```http
POST /api/conversations
```

请求体：

```json
{
  "knowledge_base_type": "enterprise"
}
```

响应 `data` 建议：

```json
{
  "conversation_id": "conv_001",
  "title": "新会话",
  "knowledge_base_type": "enterprise"
}
```

### 7.3 查询指定会话历史消息

预留。

```http
GET /api/conversations/{conversation_id}/messages?knowledge_base_type=enterprise
```

响应 `data` 建议：

```json
[
  {
    "message_id": "msg_001",
    "role": "user",
    "content": "企业店保证金怎么收取？",
    "created_at": "2026-06-22T10:00:00"
  },
  {
    "message_id": "msg_002",
    "role": "assistant",
    "content": "根据企业店相关规则，保证金标准需要结合类目资费规则确认。",
    "sources": [],
    "created_at": "2026-06-22T10:00:05"
  }
]
```

### 7.4 删除会话

预留。

```http
DELETE /api/conversations/{conversation_id}
```

说明：

- 后续建议逻辑删除会话。
- 同时逻辑删除该会话下的历史消息。

响应 `data` 建议：

```json
{
  "deleted": true
}
```

### 7.5 发送问题

预留。

```http
POST /api/conversations/{conversation_id}/messages
```

请求体：

```json
{
  "question": "企业店保证金怎么收取？",
  "knowledge_base_type": "enterprise"
}
```

响应 `data` 建议：

```json
{
  "message_id": "msg_002",
  "conversation_id": "conv_001",
  "answer": "根据企业店相关规则，保证金标准需要结合类目资费规则确认。",
  "knowledge_base_type": "enterprise",
  "sources": [
    {
      "doc_id": "638209647311982592",
      "title": "京东开放平台类目资费规则",
      "chunk_id": "chunk_001",
      "score": 0.82
    }
  ],
  "hit_type": "doc",
  "need_human_transfer": false,
  "created_at": "2026-06-22T10:00:05"
}
```

## 8. RAGService 对接边界

当前后端只保留抽象边界，真实 RAG 能力后续接入。

后端调用 RAG 服务时，建议输入：

```json
{
  "user_id": 1,
  "username": "alice",
  "conversation_id": "conv_001",
  "question": "企业店保证金怎么收取？",
  "knowledge_base_type": "enterprise",
  "user_category": "merchant",
  "question_categories": ["enterprise_shop"],
  "history_messages": [
    {
      "role": "user",
      "content": "企业店怎么入驻？"
    },
    {
      "role": "assistant",
      "content": "企业店入驻需要满足主体资质和平台规则要求。"
    }
  ],
  "retrieval_config": {
    "model": "qwen-plus",
    "doc_k": 22,
    "faq_k": 20,
    "rerank_enabled": true,
    "rerank_top_k": 10
  }
}
```

RAG 服务建议输出：

```json
{
  "answer": "根据企业店相关规则，保证金标准需要结合类目资费规则确认。",
  "confidence": 0.86,
  "sources": [
    {
      "doc_id": "638209647311982592",
      "title": "京东开放平台类目资费规则",
      "chunk_id": "chunk_001",
      "score": 0.82,
      "source_url": "https://learn-jdm.jd.com/knowledge/rule/detail?ruleId=638209647311982592"
    }
  ],
  "hit_type": "doc",
  "need_human_transfer": false,
  "debug": {
    "doc_k": 22,
    "faq_k": 20,
    "rerank_enabled": true
  }
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `answer` | 助手最终回答 |
| `confidence` | 置信度，范围建议 `0-1` |
| `sources` | 命中的文档、FAQ 或规则来源 |
| `hit_type` | `faq`、`doc`、`rule`、`none` |
| `need_human_transfer` | 是否建议转人工 |
| `debug` | 可选，调试信息，生产可关闭 |

## 9. 健康检查接口

### 9.1 服务健康检查

已实现。

```http
GET /api/health
```

响应 `data`：

```json
{
  "app": "KnowForge RAG Backend",
  "env": "local",
  "status": "ok"
}
```

### 9.2 依赖健康检查

已实现。

```http
GET /api/health/dependencies
```

响应 `data`：

```json
{
  "mysql": true,
  "redis": true,
  "milvus": true,
  "sample_collection": "knowforge_v1_doc"
}
```

## 10. 当前前端 API 封装文件

| 文件 | 说明 |
| --- | --- |
| `src/api/request.js` | 统一请求封装、token 注入、错误处理 |
| `src/api/auth.js` | 登录、当前用户、登出 |
| `src/api/adminUsers.js` | 管理员用户管理 |
| `src/api/adminConfig.js` | 仪表台参数和配置版本 |
| `src/api/conversation.js` | 用户端聊天和历史消息预留接口 |

## 11. 对接注意事项

- 管理员接口必须携带管理员 token，否则返回 403。
- 普通用户登录后，前端根据 `user.category` 决定 `knowledge_base_type`。
- 当前聊天接口只是前端预留，后端尚未实现真实路由。
- 仪表台保存参数时，建议提交完整配置对象，不要只提交单个字段。
- 重建表 SQL 仅保存在本地开发使用，不作为当前接口对接要求。
