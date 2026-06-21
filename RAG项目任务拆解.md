# RAG 项目任务拆解

本文档基于 `RAG项目功能设计文档.md` 重新拆分，目标是让组员或 Agent 领取后可以直接开工，并且最后能够集成为一个可运行系统。

## 1. 本次拆分范围

本次只拆当前文档中信息足够明确、可以直接开发的功能：

- 单 Vue 前端工程，包含用户界面和管理员界面；前端由独立 Git 仓库承载，本仓库只维护后端工程、部署与后端相关脚本
- FastAPI 后端工程底座
- 登录鉴权、角色权限、知识库可见级别控制
- 用户会话、历史消息、用户提问流式输出
- 知识库版本管理
- 管理员上传文档、解析、分块、保存、版本构建
- Python 命令行上传脚本
- 知识库参数仪表台
- 关键词规则配置查看与维护
- 配置文件加载、更新、内存配置对象

本次不拆以下“当前文档未细化”的内容：

- 管理员-评估调优
- 管理员-调优参数设置
- 完整检索流程算法细节

上述内容后续有专项文档后再单独拆分。本文件不安排空页面、空接口、占位服务作为任务。

## 2. 推荐开发顺序

### 第一阶段：系统基底

先完成工程结构、配置、数据库、鉴权、公共能力。没有这层，前端和业务模块会互相等待。

### 第二阶段：用户问答闭环

完成用户登录、会话列表、历史消息、新建会话、删除会话、用户提问流式响应。

### 第三阶段：知识库管理闭环

完成管理员版本列表、版本状态操作、上传文档、上传进度、构建入库、人工确认切换。

### 第四阶段：配置管理闭环

完成检索参数仪表台、关键词规则配置文件展示与增删改。

## 3. 全局技术约定

### 3.1 技术栈

- 前端：Vue（独立 Git 仓库）
- 后端：Python、FastAPI
- 检索与向量库：LangChain、LangChain Milvus、Milvus
- 数据库：MySQL
- 缓存：Redis

说明：第一阶段后端基底只需要验证 Milvus 连接、collection 命名和基础管理能力，可以直接使用 `pymilvus`。`LangChain Milvus` 在后续检索服务、版本构建入库和 Retriever/VectorStore 封装中接入。

### 3.2 工程建议结构

本仓库为后端仓库，不再包含 `frontend/` 目录。前端仓库只通过接口契约、OpenAPI 文档和联调环境与本仓库协作。

```text
ekb_intelligent_assistant/
  app/
    main.py
    api/
      deps.py
      routers/
    core/
      config.py
      security.py
      response.py
      exceptions.py
      logging.py
    db/
      mysql.py
      redis.py
      milvus.py
      models/
      repositories/
    schemas/
    services/
    parsers/
    splitters/
    utils/
  config/
    app.yaml
    retrieval.yaml
    keyword_rules.yaml
  resources/
    prompts/
    templates/
    seed_data/
  scripts/
    sql/
    upload_kb.py
  tests/
  deploy/
    wsl-docker/
  source_data/
  logs/
```

目录约定：

- `app/`：后端 Python 应用代码，`app` 是 Python 包根。
- `config/`：可版本化的 YAML 配置，启动时加载到内存配置对象。
- `resources/`：轻量、可版本化的后端资源，例如 prompt 模板、导入导出模板、小型种子数据。大模型文件不放入本仓库，继续通过 `config/app.yaml` 引用外部模型目录。
- `scripts/`：后端运维或批处理脚本，`scripts/sql/` 存放初始化和迁移 SQL。
- `deploy/`：本地和生产部署相关文件。
- `source_data/`：当前已有知识源原始/清洗数据。后续用户上传文件和构建产物不应直接写入本目录，生产应进入对象存储、数据库或向量库。
- `logs/`：本地运行日志目录，由程序运行时生成，不纳入 Git。

### 3.3 通用接口约定

普通 JSON 接口统一返回：

```json
{
  "code": 0,
  "message": "success",
  "data": {}
}
```

分页接口统一返回：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "items": [],
    "total": 0,
    "page": 1,
    "page_size": 20
  }
}
```

用户提问流式接口建议使用 SSE：

```text
event: message
data: {"type":"answer_delta","content":"回答片段"}

event: title
data: {"type":"conversation_title","title":"会话标题"}

event: done
data: {"type":"done"}
```

### 3.4 权限与可见级别约定

需要同时支持两类控制：

- 角色权限：普通用户、管理员
- 知识库可见级别：上传文档时设置可见级别和允许访问的角色

用户提问时必须鉴权，并在知识库检索时只允许使用当前用户可见的知识内容。

管理员上传文档时必须设置：

- 文档类型：FAQ 或文档
- 可见级别
- 允许访问的角色

### 3.5 知识库版本状态

| 状态 | 含义 |
| --- | --- |
| building | 正在构建 |
| ready | 构建完成，待发布 |
| active | 当前线上使用 |
| standby | 上一个可回滚版本 |
| archived | 已归档，不在线使用 |
| dropped | 已删除 |
| failed | 构建失败 |

状态机规则放在后端统一判断，前端只负责展示后端返回的状态和可执行动作。

## 4. 后端基底任务

### BE-01 FastAPI 工程初始化

负责人：待分配

目标：搭建后端基础工程，让项目能启动、能注册路由、能输出接口文档。

具体工作：

- 创建 `app/main.py`
- 注册 API 路由总入口
- 配置 CORS
- 配置健康检查接口
- 配置环境变量读取
- 配置本地启动命令
- 配置依赖文件，如 `requirements.txt` 或 `pyproject.toml`

建议接口：

- `GET /api/health`

交付物：

- 后端工程可以本地启动
- Swagger/OpenAPI 页面可以访问
- 健康检查接口可用

验收标准：

- 启动后无报错
- `GET /api/health` 返回成功
- 新增业务路由时不需要改动主程序结构

### BE-02 配置文件与内存配置对象

负责人：待分配

目标：实现项目启动时加载配置文件，并形成全局可读取的配置对象。

具体工作：

- 创建 `config/app.yaml`
- 创建 `config/retrieval.yaml`
- 创建 `config/keyword_rules.yaml`
- 实现配置加载类
- 实现配置校验
- 实现配置对象在服务中读取
- 为后续管理端修改配置文件提供统一读写方法

`retrieval.yaml` 初始参数至少包含：

```yaml
model: qwen-plus
embedding_model: bge-m3
sparse_retrieval: Milvus BM25
rerank_model: bge-reranker-v2-m3

variant_generation_enabled: true
rerank_enabled: true
rule_variant_count: 1
llm_variant_count: 1
query_variant_total: 3

faq_exact_match_max_length: 48
follow_up_max_length: 10
recent_message_keep_count: 8
history_summary_boundary_round: 8
history_summary_max_chars: 800

faq_dense_top_k_exact: 3
faq_sparse_top_k_exact: 3
faq_fetch_k: 20
faq_k: 20
doc_fetch_k: 50
doc_k: 20
rerank_top_k: 8
faq_rerank_top_k: 3
doc_rerank_top_k: 5
final_evidence_top_k: 6

faq_dense_weight: 0.5
faq_sparse_weight: 0.5
doc_dense_weight: 0.7
doc_sparse_weight: 0.3

faq_high_conf_threshold: 0.85
faq_middle_conf_threshold: 0.65
doc_evidence_threshold: 0.55

rule_hit_priority:
  - human_transfer
  - out_of_scope
  - greeting
  - faq_fast_retrieval

faq_exact_match_policy: normalized_exact_match
standby_keep_days: 30
standby_min_keep_versions: 1
```

`keyword_rules.yaml` 初始集合至少包含：

```yaml
greeting:
  name: 打招呼关键词集合
  keywords: [你好, 嗨, hello, 请问, 告诉我, 问一下]
out_of_scope:
  name: 越界关键词集合
  keywords: [吃什么, 喝什么, 天气如何]
human_transfer:
  name: 转人工关键词集合
  keywords: [转人工, 人工客服, 人工坐席客服]
faq_fast_retrieval:
  name: FAQ 检索关键词集合
  keywords: [退款流程, 重置密码, 发票开错了]
```

交付物：

- 配置加载模块
- 配置校验模块
- 初始配置文件
- 配置读写工具

验收标准：

- 后端启动时自动加载配置
- 配置缺失或类型错误时启动失败并输出明确日志
- 业务代码可以读取当前内存配置对象
- 修改配置文件并重启后，新值生效

### BE-03 MySQL 数据库基础与模型规范

负责人：待分配

目标：实现 MySQL 连接、ORM 基础类、事务管理和基础模型规范。

具体工作：

- 实现 MySQL 连接池
- 实现数据库 session 依赖
- 实现 ORM Base
- 统一主键、创建时间、更新时间、逻辑删除字段规范
- 提供 migration 或初始化 SQL 方案

交付物：

- `db/mysql.py`
- ORM Base
- migration 初始化方式

验收标准：

- 接口中可以获取数据库 session
- 数据库连接异常有清晰日志
- 新增模型时可以复用统一字段规范

### BE-04 Redis 与 Milvus 基础连接

负责人：待分配

目标：提供 Redis、Milvus 的基础连接能力和工具封装。

具体工作：

- Redis 连接池
- Redis 基础 get/set/delete 工具
- Milvus 连接配置
- Milvus collection 命名规则
- collection 创建、存在检查、加载、释放、删除工具
- 支持按知识库版本生成 collection 名称

交付物：

- `db/redis.py`
- `db/milvus.py`
- Milvus collection 工具类

验收标准：

- 后端可以正常连接 Redis
- 后端可以正常连接 Milvus
- 可以根据知识库版本生成唯一 collection 名称

### BE-05 统一响应、异常与日志

负责人：待分配

目标：全后端接口使用统一返回格式、统一异常处理和统一日志。

具体工作：

- 成功响应封装
- 分页响应封装
- 业务异常类
- 参数异常类
- 鉴权异常类
- 权限异常类
- 全局异常处理器
- 请求日志
- 错误日志

交付物：

- `core/response.py`
- `core/exceptions.py`
- `core/logging.py`

验收标准：

- 所有 JSON 接口返回格式一致
- 未捕获异常不会把堆栈直接暴露给前端
- 日志能定位请求路径、用户、错误原因

### BE-06 登录鉴权与角色权限

负责人：待分配

目标：实现账号密码登录、JWT 鉴权、普通用户/管理员角色控制。

具体工作：

- 用户表设计
- 角色表设计，或用户表内角色字段设计
- 密码哈希
- 登录接口
- 当前用户信息接口
- JWT 生成与校验
- 普通登录用户依赖
- 管理员权限依赖
- 前端退出登录支持

建议接口：

- `POST /api/auth/login`
- `GET /api/auth/me`
- `POST /api/auth/logout`

交付物：

- 用户与角色模型
- 登录鉴权服务
- 鉴权依赖函数

验收标准：

- 未登录访问受保护接口返回 401
- 普通用户访问管理员接口返回 403
- 管理员可以访问管理员接口
- token 过期后前端可识别并重新登录

### BE-07 知识库可见级别与访问控制模型

负责人：待分配

目标：建立知识库文档可见级别和角色访问控制的数据基础。

具体工作：

- 定义可见级别枚举
- 定义文档允许访问角色字段或关联表
- 上传文档时保存可见级别
- 上传文档时保存允许访问角色
- 用户提问时可以根据当前用户角色生成知识库过滤条件

建议表或字段：

- `kb_documents.visibility_level`
- `kb_documents.allowed_roles`
- `kb_chunks.visibility_level`
- `kb_chunks.allowed_roles`

交付物：

- 可见级别枚举
- 访问控制模型字段
- 访问过滤工具函数

验收标准：

- 管理员上传文档时必须填写可见级别和角色控制
- 用户提问时不能访问无权限知识内容
- 管理员可访问全部或按配置访问

## 5. 前端基础任务

### FE-01 单 Vue 工程初始化

负责人：待分配

目标：搭建一个 Vue 前端工程，同时承载用户界面和管理员界面。

具体工作：

- 创建 `frontend` 工程
- 配置 Vue Router
- 配置状态管理
- 配置接口请求工具
- 配置环境变量
- 配置用户端布局
- 配置管理端布局
- 配置基础菜单

交付物：

- 前端工程可启动
- 用户端路由组
- 管理端路由组

验收标准：

- 本地启动无报错
- 用户端和管理端页面通过路由区分
- 一个工程内可以同时访问用户界面和管理员界面

### FE-02 前端登录态与权限守卫

负责人：待分配

目标：前端统一处理登录态、token、角色权限和接口错误。

具体工作：

- 登录态 store
- token 存储与清理
- 请求自动携带 token
- 401 自动跳转登录
- 403 展示无权限提示
- 路由守卫
- 管理端路由限制管理员访问
- 退出登录

依赖接口：

- `POST /api/auth/login`
- `GET /api/auth/me`
- `POST /api/auth/logout`

交付物：

- 登录态 store
- 请求拦截器
- 路由守卫

验收标准：

- 未登录访问业务页跳转登录页
- 普通用户不能进入管理端页面
- 管理员可以进入管理端页面
- token 失效时能回到登录页

### FE-03 登录页面

负责人：待分配

目标：实现统一登录页面，支持普通用户和管理员登录。

具体工作：

- 账号密码表单
- 表单校验
- 登录请求
- 登录失败提示
- 登录成功后根据角色跳转

交付物：

- 登录页面

验收标准：

- 账号密码为空时有提示
- 账号密码错误时展示后端错误信息
- 普通用户登录后进入用户聊天页
- 管理员登录后可进入管理后台

## 6. 用户问答任务

### BE-08 会话与消息后端

负责人：待分配

目标：实现用户会话和历史消息的后端数据模型与接口。

具体工作：

- 会话表
- 消息表
- 查询当前用户所有会话
- 查询指定会话历史消息
- 新增会话
- 逻辑删除会话和消息
- 保证用户只能操作自己的会话

建议表：

- `conversations`
- `conversation_messages`

建议接口：

- `GET /api/user/conversations`
- `POST /api/user/conversations`
- `GET /api/user/conversations/{conversation_id}/messages`
- `DELETE /api/user/conversations/{conversation_id}`

交付物：

- 会话模型
- 消息模型
- 会话 service
- 会话 API

验收标准：

- 登录后只能看到自己的会话
- 会话按更新时间倒序返回
- 消息按创建时间正序返回
- 删除会话后列表和历史消息不再返回该会话内容

### BE-09 用户提问流式接口

负责人：待分配

目标：实现用户提问接口的后端业务链路，包括鉴权、会话校验、消息保存、流式输出和标题生成。

具体工作：

- 校验登录用户
- 校验会话归属
- 保存用户提问消息
- 调用检索回答服务
- 使用 SSE 流式输出回答
- 保存助手回答消息
- 如果是会话第一次提问，生成会话标题并保存
- SSE 中返回标题更新事件

建议接口：

- `POST /api/user/chat/stream`

请求字段建议：

```json
{
  "conversation_id": "string",
  "question": "string"
}
```

交付物：

- 用户提问 API
- SSE 工具
- 消息落库逻辑
- 会话标题生成逻辑

验收标准：

- 用户问题会保存为历史消息
- 助手回答会保存为历史消息
- 前端可以逐步收到回答片段
- 第一次提问后会话标题更新
- 用户不能向不属于自己的会话提问

### FE-04 用户聊天主界面

负责人：待分配

目标：实现用户端聊天主页面。

具体工作：

- 左侧会话列表
- 右侧聊天窗口
- 顶部用户信息和退出登录
- 新建会话按钮
- 删除会话按钮
- 消息列表
- 输入框
- 发送按钮
- 流式回答展示

依赖接口：

- `GET /api/user/conversations`
- `POST /api/user/conversations`
- `GET /api/user/conversations/{conversation_id}/messages`
- `DELETE /api/user/conversations/{conversation_id}`
- `POST /api/user/chat/stream`

交付物：

- 用户聊天页面
- 会话列表组件
- 消息列表组件
- 消息输入组件

验收标准：

- 登录后自动加载会话列表
- 点击会话后展示历史消息
- 新建会话后自动进入新聊天窗口
- 删除会话前有确认
- 发送问题后能看到流式回答
- 首次提问生成标题后左侧列表同步更新

## 7. 知识库版本管理任务

### BE-10 知识库版本与版本指针

负责人：待分配

目标：实现知识库版本表、版本指针和版本基础查询。

具体工作：

- 知识库版本表
- 版本指针表
- active 指针
- standby 指针
- 版本基础信息查询
- 版本关联 collection 名称
- 版本文档数、chunk 数统计字段

建议表：

- `kb_versions`
- `kb_version_pointers`
- `kb_version_action_logs`

建议接口：

- `GET /api/admin/kb/versions`

交付物：

- 版本模型
- 版本指针模型
- 版本查询 service
- 版本列表 API

验收标准：

- 可以查询所有版本
- 可以识别当前 active 版本
- 可以识别 standby 版本
- 新版本 building 不影响 active 指针

### BE-11 知识库版本状态机与操作

负责人：待分配

目标：实现版本状态切换、删除、回滚规则，确保线上版本安全。

具体工作：

- 状态枚举
- 状态机流转规则
- 发布 ready 版本为 active
- 发布时旧 active 变为 standby
- 回滚到 standby
- 归档版本
- 删除版本，实际状态改为 dropped
- 禁止删除 active
- 禁止非法状态流转
- 操作前置校验
- 操作日志

建议接口：

- `POST /api/admin/kb/versions/{version_id}/actions`

请求字段建议：

```json
{
  "action": "publish | rollback | archive | drop"
}
```

交付物：

- 状态机 service
- 版本操作 API
- 操作日志写入

验收标准：

- 同一时间只有一个 active 版本
- 发布新版本不会破坏历史版本
- 回滚后 active 和 standby 指针正确
- 删除 active 版本会被拒绝
- 非法操作返回明确错误原因

### FE-05 管理员知识库版本页面

负责人：待分配

目标：管理员可以查看和操作知识库所有版本。

具体工作：

- 版本表格
- 状态标签
- active/standby 明显标识
- 分页
- 操作按钮
- 操作二次确认
- 操作失败提示
- 操作成功后刷新列表

依赖接口：

- `GET /api/admin/kb/versions`
- `POST /api/admin/kb/versions/{version_id}/actions`

交付物：

- 知识库版本管理页面

验收标准：

- 管理员能看到所有版本基础信息和状态
- 发布、回滚、归档、删除操作可执行
- 危险操作必须二次确认
- 后端拒绝的操作能展示拒绝原因

## 8. 文档上传与知识库构建任务

### 8.1 上传入库增量判断规则

文档上传入库时，后端需要计算每个文件的 SHA256 指纹，用于识别文件是否需要重新解析、分块和写入向量库。

判断口径：

- 文件唯一标识建议使用：`relative_path + file_name + doc_type`
- 文件指纹使用：原始文件二进制内容的 SHA256
- 对比基准建议使用：当前 active 知识库版本中的同名同路径同类型文件

文件状态：

| 状态 | 判断规则 | 处理方式 |
| --- | --- | --- |
| new | active 版本中不存在相同文件唯一标识 | 正常解析、分块、入库 |
| changed | active 版本中存在相同文件唯一标识，但 SHA256 不同 | 重新解析、分块、入库 |
| unchanged | active 版本中存在相同文件唯一标识，且 SHA256 相同 | 不重复解析和向量化，复用或引用上一版本结果 |

入库要求：

- `new` 和 `changed` 文件必须进入解析、分块、写入 MySQL、写入 Milvus 流程
- `unchanged` 文件不应重复解析、分块和向量化，避免浪费构建时间
- 构建任务详情中必须能看到每个文件的 SHA256 和状态
- 新版本仍然要保留完整的文档清单，不能因为文件未变化就让新版本缺少这些文件的记录
- 如果采用版本独立 Milvus collection，`unchanged` 文件需要复制上一版本已有向量数据到新 collection，但不能重新 embedding
- 如果采用共享 Milvus collection，`unchanged` 文件需要建立新版本引用关系，确保按版本检索时能查到这些内容
- 如果上传的是文件夹，文件相对路径必须参与判断，避免不同目录下同名文件被误判

### BE-12 上传任务与文件接收

负责人：待分配

目标：实现管理员上传文件或目录后的后端接收、校验、SHA256 指纹计算、文件变化识别和任务创建。

具体工作：

- 上传任务表
- 上传文件表
- 创建上传任务
- 接收多文件上传
- 保存文件原始名称
- 保存目录相对路径
- 计算每个文件的 SHA256 指纹
- 基于 active 版本识别文件状态：new、changed、unchanged
- 保存文件状态和对比到的历史文档 id
- 文件格式白名单校验
- 上传参数保存：文档类型、可见级别、允许角色
- 上传任务状态维护

文件白名单：

- MD
- PDF
- WORD
- CSV

建议表：

- `kb_upload_tasks`
- `kb_upload_files`

`kb_upload_files` 建议字段：

- `id`
- `task_id`
- `file_name`
- `relative_path`
- `file_ext`
- `file_size`
- `sha256`
- `doc_type`
- `visibility_level`
- `allowed_roles`
- `change_status`，取值：new、changed、unchanged
- `matched_document_id`
- `save_path`
- `process_status`
- `error_message`

建议接口：

- `POST /api/admin/kb/upload-tasks`
- `POST /api/admin/kb/upload-tasks/{task_id}/files`
- `GET /api/admin/kb/upload-tasks`
- `GET /api/admin/kb/upload-tasks/{task_id}`

交付物：

- 上传任务模型
- 上传文件模型
- 上传 API
- 文件保存工具
- SHA256 计算工具
- 文件变化识别 service

验收标准：

- 非管理员不能上传
- 不在白名单内的文件会被拒绝
- 多文件可以归属到同一个上传任务
- 文件夹上传时能保存相对路径
- 每个上传文件都能保存 SHA256
- 能识别文件状态为 new、changed、unchanged
- 同路径同名同类型且 SHA256 相同的文件识别为 unchanged
- 同路径同名同类型但 SHA256 不同的文件识别为 changed
- active 版本中不存在的文件识别为 new
- 上传参数能保存到任务或文件记录中

### BE-13 文档解析器

负责人：待分配

目标：根据文件类型使用不同解析器，把文件解析成统一文本结构。

具体工作：

- 定义解析器基类
- MD 解析器
- PDF 解析器
- WORD 解析器
- CSV 解析器
- 解析结果统一结构
- 解析失败原因记录
- 只解析 new 和 changed 文件，跳过 unchanged 文件

建议解析结果：

```json
{
  "title": "文档标题",
  "content": "解析后的文本",
  "metadata": {
    "file_name": "xxx.pdf",
    "relative_path": "folder/xxx.pdf",
    "file_type": "pdf",
    "sha256": "文件 SHA256",
    "change_status": "new"
  }
}
```

交付物：

- parser 基类
- 四类文件 parser
- parser 工厂

验收标准：

- MD/PDF/WORD/CSV 都能解析
- 不同文件类型自动匹配解析器
- unchanged 文件不会重复解析
- 解析失败不会中断整个批次
- 解析失败能在上传任务详情中看到原因

### BE-14 FAQ 与文档分块

负责人：待分配

目标：按 FAQ 和文档两种类型分别分块，其中文档需要父子分块。

具体工作：

- 定义 splitter 基类
- FAQ 分块策略
- 文档父子分块策略
- chunk metadata 结构
- 父 chunk 与子 chunk 关系保存
- 保存 chunk 到 MySQL
- new 和 changed 文件生成新 chunk
- unchanged 文件复用上一版本文档和 chunk 结果，或创建新版本下的引用记录

建议表：

- `kb_documents`
- `kb_chunks`

`kb_documents` 建议增加字段：

- `sha256`
- `source_upload_file_id`
- `source_document_id`
- `change_status`

`kb_chunks` 建议增加字段：

- `sha256`
- `source_chunk_id`

交付物：

- FAQ splitter
- 文档父子 splitter
- chunk 保存 service
- unchanged 文件复用逻辑

验收标准：

- FAQ 类型文件走 FAQ 分块
- 文档类型文件走父子分块
- 每个 chunk 能关联所属文档、所属版本、权限信息
- new 和 changed 文件会生成新的文档记录和 chunk 记录
- unchanged 文件不会重复分块
- 新版本中可以查询到 unchanged 文件对应的文档记录
- 父子 chunk 关系可以查询

### BE-15 构建版本与写入 Milvus

负责人：待分配

目标：上传文档解析分块后写入新知识库版本，不影响当前线上 active 版本。

具体工作：

- 创建 building 版本
- 为版本创建独立 Milvus collection
- 根据文件状态决定入库策略
- 写入 chunk 向量
- 写入稀疏检索所需字段
- unchanged 文件不重复向量化
- 版本独立 collection 方案下，unchanged 文件复制上一版本已有向量数据到新 collection
- 共享 collection 方案下，unchanged 文件写入新版本引用映射
- 记录 document_count
- 记录 chunk_count
- 记录 new、changed、unchanged 文件数量
- 构建成功后状态改为 ready
- 构建失败后状态改为 failed
- failed 记录失败原因
- 不修改 active 指针

交付物：

- 知识库构建 service
- Milvus 写入 service
- 版本构建状态更新

验收标准：

- 新版本写入独立 collection
- 构建期间线上 active 版本不变
- new 和 changed 文件会写入新版本 collection
- unchanged 文件不会重复解析、分块、向量化
- 新版本的文档数统计包含 new、changed、unchanged 文件
- 构建成功后版本状态为 ready
- 构建失败后版本状态为 failed 且能看到原因

### BE-16 上传后自动校验与人工确认切换

负责人：待分配

目标：构建完成后进行自动校验，校验通过后等待管理员人工确认切换。

具体工作：

- 自动校验任务状态
- 校验文件状态统计：new、changed、unchanged 数量
- 校验结果保存
- 校验失败原因保存
- 人工确认发布接口
- 确认发布时调用版本状态机

建议接口：

- `POST /api/admin/kb/upload-tasks/{task_id}/confirm-release`

交付物：

- 自动校验结果模型字段
- 人工确认发布 API

验收标准：

- 构建完成后管理员能看到校验结果
- 管理员能看到本次上传中新文件、变化文件、未变化文件数量
- 校验失败不能发布
- 校验通过后管理员确认才切换 active
- 切换后版本指针正确

### FE-06 管理员文档上传页面

负责人：待分配

目标：管理员可以选择文件或文件夹，设置上传参数并提交。

具体工作：

- 文件选择
- 文件夹选择
- 递归展示目录内文件
- 前端白名单初步校验
- 待上传文件列表
- 上传后展示后端返回的文件状态：new、changed、unchanged
- 上传后展示后端返回的 SHA256
- 文档类型选择：FAQ/文档
- 可见级别选择
- 允许访问角色选择
- 上传进度展示

依赖接口：

- `POST /api/admin/kb/upload-tasks`
- `POST /api/admin/kb/upload-tasks/{task_id}/files`

交付物：

- 文档上传页面
- 文件列表组件
- 上传参数表单

验收标准：

- 支持批量选择文件
- 支持选择文件夹并保留相对路径
- 不支持的文件类型前端提示
- 上传前必须选择文档类型、可见级别、访问角色
- 上传后能看到每个文件的 SHA256 和变化状态
- 上传成功后进入任务详情或进度页面

### FE-07 上传任务与构建进度页面

负责人：待分配

目标：管理员可以查看上传、解析、分块、入库、校验、确认发布等状态。

具体工作：

- 上传任务列表
- 上传任务详情
- 文件级处理结果
- 文件级 SHA256 展示
- 文件级变化状态展示：new、changed、unchanged
- 阶段状态展示
- 失败原因展示
- 校验结果展示
- 人工确认发布按钮

依赖接口：

- `GET /api/admin/kb/upload-tasks`
- `GET /api/admin/kb/upload-tasks/{task_id}`
- `POST /api/admin/kb/upload-tasks/{task_id}/confirm-release`

交付物：

- 上传任务列表页面
- 上传任务详情页面

验收标准：

- 管理员能看到任务当前阶段
- 管理员能看到每个文件的处理结果
- 管理员能看到每个文件是新文件、变化文件还是未变化文件
- 管理员能看到 new、changed、unchanged 数量统计
- 构建失败能看到失败原因
- 校验通过后可以人工确认发布

### SCRIPT-01 Python 文档上传脚本

负责人：待分配

目标：提供命令行方式上传文档到知识库，复用后端上传构建逻辑，省去人工确认。

具体工作：

- 支持传入文件路径
- 支持传入目录路径并递归扫描
- 支持白名单校验
- 支持传入文档类型
- 支持传入可见级别
- 支持传入允许访问角色
- 本地或后端计算 SHA256 指纹
- 输出每个文件的变化状态：new、changed、unchanged
- 调用后端接口或复用后端 service
- 构建成功后自动发布
- 输出版本号、任务 id、处理结果

建议命令：

```bash
python scripts/upload_kb.py \
  --path ./docs \
  --doc-type document \
  --visibility internal \
  --roles user,admin \
  --auto-publish true
```

交付物：

- `scripts/upload_kb.py`
- 脚本使用说明

验收标准：

- 可以上传单文件
- 可以上传目录
- 可以设置 FAQ/文档类型
- 可以设置权限参数
- 可以输出每个文件的 SHA256
- 可以输出每个文件的新建、变化、未变化状态
- 成功后生成新版本并自动发布

## 9. 参数仪表台与规则关键词任务

### BE-17 知识库参数仪表台接口

负责人：待分配

目标：将当前内存中的检索配置参数返回给管理端展示。

具体工作：

- 读取内存配置对象
- 按展示分组返回参数
- 返回模型参数
- 返回检索参数
- 返回权重参数
- 返回阈值参数
- 返回规则命中优先级
- 返回 standby 保留策略
- 管理员权限校验

建议接口：

- `GET /api/admin/kb/config/dashboard`

交付物：

- 参数仪表台 API
- 参数分组 schema

验收标准：

- 返回值与 `retrieval.yaml` 加载后的内存对象一致
- 只有管理员可以访问
- 前端不需要自己拼接参数含义

### FE-08 知识库参数仪表台页面

负责人：待分配

目标：管理员可以查看当前项目知识库查询功能使用的各类参数。

具体工作：

- 模型参数展示
- 查询变体参数展示
- 历史上下文参数展示
- FAQ 检索参数展示
- 文档检索参数展示
- Rerank 参数展示
- Evidence 参数展示
- 权重参数展示
- 阈值参数展示
- 规则优先级展示
- standby 策略展示

依赖接口：

- `GET /api/admin/kb/config/dashboard`

交付物：

- 参数仪表台页面

验收标准：

- 页面展示内容与后端返回一致
- 参数分组清晰
- 本页面只读，不修改参数

### BE-18 关键词规则配置后端

负责人：待分配

目标：实现关键词规则配置文件的查看、集合增删、集合内关键词增删改。

具体工作：

- 读取 `keyword_rules.yaml`
- 返回所有关键词集合
- 新增关键词集合
- 删除关键词集合
- 新增集合内关键词
- 修改集合内关键词
- 删除集合内关键词
- 写回配置文件
- 更新内存配置对象
- 操作日志
- 管理员权限校验

建议接口：

- `GET /api/admin/kb/keyword-rules`
- `POST /api/admin/kb/keyword-rules/collections`
- `DELETE /api/admin/kb/keyword-rules/collections/{collection_key}`
- `POST /api/admin/kb/keyword-rules/collections/{collection_key}/keywords`
- `PUT /api/admin/kb/keyword-rules/collections/{collection_key}/keywords/{keyword_id}`
- `DELETE /api/admin/kb/keyword-rules/collections/{collection_key}/keywords/{keyword_id}`

交付物：

- 关键词规则 service
- 关键词规则 API
- 配置文件写回工具

验收标准：

- 管理员可以查询当前关键词集合
- 管理员可以新增和删除集合
- 管理员可以增删改集合内关键词
- 修改后配置文件和内存对象保持一致
- 普通用户不能访问这些接口

### FE-09 关键词规则管理页面

负责人：待分配

目标：管理员可以在界面中维护关键词规则配置。

具体工作：

- 展示关键词集合列表
- 展示集合内关键词
- 新增集合
- 删除集合
- 新增关键词
- 修改关键词
- 删除关键词
- 操作确认
- 操作失败提示

依赖接口：

- `GET /api/admin/kb/keyword-rules`
- `POST /api/admin/kb/keyword-rules/collections`
- `DELETE /api/admin/kb/keyword-rules/collections/{collection_key}`
- `POST /api/admin/kb/keyword-rules/collections/{collection_key}/keywords`
- `PUT /api/admin/kb/keyword-rules/collections/{collection_key}/keywords/{keyword_id}`
- `DELETE /api/admin/kb/keyword-rules/collections/{collection_key}/keywords/{keyword_id}`

交付物：

- 关键词规则管理页面

验收标准：

- 能看到四类初始关键词集合
- 能新增集合
- 能删除集合
- 能增删改集合内关键词
- 修改后刷新页面仍能看到最新结果

## 10. 联调与验收任务

### QA-01 接口契约文档

负责人：待分配

目标：整理前后端对接所需的接口契约，避免各任务实现时字段不一致。

具体工作：

- 整理认证接口字段
- 整理用户会话接口字段
- 整理聊天流式接口事件格式
- 整理版本管理接口字段
- 整理上传任务接口字段
- 整理参数仪表台接口字段
- 整理关键词规则接口字段

交付物：

- 接口契约文档
- 示例请求和响应

验收标准：

- 前端可以按文档 mock 开发
- 后端可以按文档实现 schema
- 字段命名统一

### QA-02 种子数据与本地联调数据

负责人：待分配

目标：提供本地开发和联调所需的基础数据。

具体工作：

- 创建管理员账号
- 创建普通用户账号
- 创建示例角色
- 创建示例会话
- 创建示例关键词配置
- 创建示例知识库版本

交付物：

- 初始化 SQL 或 seed 脚本
- 本地账号说明

验收标准：

- 新成员拉取项目后可以快速初始化数据
- 前端登录后能看到基础页面数据
- 管理员能进入管理端验证页面

### QA-03 最小闭环联调

负责人：待分配

目标：验证系统从登录到用户问答、管理员上传、版本切换、配置查看的最小闭环。

联调路径：

1. 普通用户登录
2. 新建会话
3. 发送问题并收到流式回答
4. 查看历史消息
5. 管理员登录
6. 上传文档并生成新版本
7. 构建完成后人工确认发布
8. 查看知识库版本 active/standby 状态
9. 查看参数仪表台
10. 修改关键词规则并刷新验证

交付物：

- 联调记录
- 问题清单
- 修复结果

验收标准：

- 上述 10 步可以连续完成
- 前后端权限控制符合预期
- 知识库版本指针正确
- 配置展示与配置文件一致

## 11. 第一批建议分配

第一批优先领取这些任务：

| 任务编号 | 任务名称 | 原因 |
| --- | --- | --- |
| BE-01 | FastAPI 工程初始化 | 后端所有任务依赖 |
| BE-02 | 配置文件与内存配置对象 | 参数仪表台、关键词、检索均依赖 |
| BE-03 | MySQL 数据库基础与模型规范 | 所有持久化模块依赖 |
| BE-05 | 统一响应、异常与日志 | 所有接口依赖 |
| BE-06 | 登录鉴权与角色权限 | 用户端和管理端都依赖 |
| FE-01 | 单 Vue 工程初始化 | 前端所有页面依赖 |
| FE-02 | 前端登录态与权限守卫 | 用户界面和管理界面都依赖 |
| QA-01 | 接口契约文档 | 保证多人并行字段一致 |

第二批在基底可运行后领取：

| 任务编号 | 任务名称 |
| --- | --- |
| BE-08 | 会话与消息后端 |
| BE-09 | 用户提问流式接口 |
| FE-03 | 登录页面 |
| FE-04 | 用户聊天主界面 |
| BE-10 | 知识库版本与版本指针 |
| BE-11 | 知识库版本状态机与操作 |
| FE-05 | 管理员知识库版本页面 |

第三批在知识库版本模型稳定后领取：

| 任务编号 | 任务名称 |
| --- | --- |
| BE-12 | 上传任务与文件接收 |
| BE-13 | 文档解析器 |
| BE-14 | FAQ 与文档分块 |
| BE-15 | 构建版本与写入 Milvus |
| BE-16 | 上传后自动校验与人工确认切换 |
| FE-06 | 管理员文档上传页面 |
| FE-07 | 上传任务与构建进度页面 |
| SCRIPT-01 | Python 文档上传脚本 |

第四批领取配置管理相关：

| 任务编号 | 任务名称 |
| --- | --- |
| BE-17 | 知识库参数仪表台接口 |
| FE-08 | 知识库参数仪表台页面 |
| BE-18 | 关键词规则配置后端 |
| FE-09 | 关键词规则管理页面 |

## 12. 最终可用标准

项目合并后至少满足：

- 一个 Vue 前端工程同时包含用户界面和管理员界面
- 普通用户可以登录、创建会话、查看历史、删除会话、提问并看到流式回答
- 管理员可以登录、查看知识库版本、操作版本状态、上传文档、查看构建进度、确认发布
- 后端能按配置文件加载检索参数和关键词规则
- 管理端能查看知识库参数仪表台
- 管理端能维护关键词规则集合
- 上传的新知识库版本不会影响线上 active 版本
- 发布和回滚通过版本指针完成
- 用户提问时会执行身份鉴权和知识库可见范围控制
