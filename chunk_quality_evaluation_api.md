# RAG 数据清洗与 Chunk 质量评估接口文档

## 1. 文档说明

本文档用于前端、后端、测试人员对接当前第一版 chunk 质量评估能力。

当前状态：

- 已实现：临时 chunk 数据集列表查询、企业用户 chunk 质量评估、个人用户 chunk 质量评估。
- 暂未实现：真实入库 chunk 数据读取、真实入库文档数对账、评估结果落库、异步评估任务。

说明：当前 `文档入库完整率` 是模拟指标，通过临时 JSON 中的 `expected_document_count` 和 `actual_document_count` 计算，不连接数据库或 Milvus 做真实对账。

当前评估接口先读取项目内两个临时 JSON 数据集：

| 数据集 | 用户类型 | 文件位置 |
| --- | --- | --- |
| `enterprise` | 企业用户 | `resources/seed_data/chunk_quality_enterprise.json` |
| `personal` | 个人用户 | `resources/seed_data/chunk_quality_personal.json` |

后续接入真实数据时，接口路径和响应结构保持不变，只替换后端数据来源。

## 2. 通用约定

| 项目 | 说明 |
| --- | --- |
| Base URL | 本地后端地址为 `http://127.0.0.1:8000` |
| API 前缀 | `/api` |
| 请求格式 | `Content-Type: application/json` |
| 鉴权方式 | `Authorization: Bearer <token>` |
| 权限要求 | 管理员角色 |
| 成功判断 | HTTP 状态码为 2xx，且响应体 `code === 0` |

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
  "code": 40300,
  "message": "admin role required",
  "data": {}
}
```

常见错误：

| HTTP 状态 | code | 说明 |
| --- | --- | --- |
| 401 | `40100` | 未登录、token 失效、session 失效 |
| 403 | `40300` | 当前用户不是管理员 |
| 404 | `40400` | 指定的数据集不存在 |
| 422 | `42200` | 请求参数校验失败 |
| 500 | `50000` | 服务内部异常 |

## 3. 登录鉴权

评估接口是管理员接口，调用前需要先登录获取 token。

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

响应 `data`：

```json
{
  "access_token": "jwt-token",
  "token_type": "bearer",
  "expires_at": "2026-06-23T18:00:00",
  "user": {
    "id": 1,
    "username": "admin",
    "roles": [
      {
        "code": "admin",
        "name": "管理员"
      }
    ]
  }
}
```

后续请求头：

```http
Authorization: Bearer jwt-token
```

## 4. 指标口径

### 4.1 文档入库完整率（当前为模拟）

```text
文档入库完整率 = 实际入库文档数 / 期望文档数
```

当前临时数据集中通过以下字段提供：

| 字段 | 说明 |
| --- | --- |
| `expected_document_count` | 期望文档数 |
| `actual_document_count` | 实际文档数 |

当前临时数据还会返回：

| 字段 | 说明 |
| --- | --- |
| `document_metrics_mode` | 当前固定为 `simulated`，表示文档入库完整率为模拟值 |

如果后续真实数据源没有直接提供 `actual_document_count`，后端会从 chunk 的 `document_id` 去重推导。

### 4.2 chunk 空值率

```text
chunk 空值率 = 空 chunk 数 / chunk 总数
```

判定规则：

- `text` 为空字符串
- `text` 去除首尾空白后为空

### 4.3 chunk 过短率

```text
chunk 过短率 = 过短 chunk 数 / chunk 总数
```

判定规则：

```text
文本长度 < 30，且不是表格 chunk
```

表格 chunk 不参与过短判断，因为短表格仍可能承载结构化业务信息。

### 4.4 chunk 过长率

```text
chunk 过长率 = 过长 chunk 数 / chunk 总数
```

判定规则：

```text
文本长度 > max(parent_chunk_size * 2, 2000)
```

### 4.5 低质量问题类型

| 类型 | 触发条件 | 说明 |
| --- | --- | --- |
| `empty` | chunk 文本为空 | 没有可检索语义 |
| `too_short` | 文本长度 `< 30`，且不是表格 chunk | 可能是标题、页码、目录碎片 |
| `too_long` | 文本长度 `> max(parent_chunk_size * 2, 2000)` | 语义过杂，召回不精准 |
| `low_unique_ratio` | 文本长度 `>= 50`，唯一字符比例 `< 0.08`，且不是表格 chunk | 可能是 OCR 噪声或解析失败 |
| `duplicate_content` | 多个 chunk 正文 hash 相同 | 重复召回会污染排序和引用 |

## 5. 接口列表

| 接口 | 方法 | 说明 |
| --- | --- | --- |
| `/api/admin/evaluations/chunk-quality/datasets` | GET | 查询当前可评估的数据集 |
| `/api/admin/evaluations/chunk-quality/{dataset}` | GET | 执行指定数据集的 chunk 质量评估 |

## 6. 查询 chunk 质量评估数据集

已实现。

```http
GET /api/admin/evaluations/chunk-quality/datasets
```

请求头：

```http
Authorization: Bearer <token>
```

请求参数：无。

响应 `data`：

```json
{
  "items": [
    {
      "dataset": "enterprise",
      "dataset_id": "enterprise_temp_chunks",
      "user_type": "enterprise",
      "path": "resources/seed_data/chunk_quality_enterprise.json"
    },
    {
      "dataset": "personal",
      "dataset_id": "personal_temp_chunks",
      "user_type": "personal",
      "path": "resources/seed_data/chunk_quality_personal.json"
    }
  ],
  "total": 2
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `items` | array | 数据集列表 |
| `items[].dataset` | string | 接口调用使用的数据集名称 |
| `items[].dataset_id` | string | 数据集业务 ID |
| `items[].user_type` | string | 用户类型，当前为 `enterprise` 或 `personal` |
| `items[].path` | string | 临时数据集文件路径 |
| `total` | integer | 数据集总数 |

## 7. 执行 chunk 质量评估

已实现。

```http
GET /api/admin/evaluations/chunk-quality/{dataset}
```

路径参数：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `dataset` | string | 是 | 数据集名称。允许值：`enterprise`、`personal` |

请求示例：

```http
GET /api/admin/evaluations/chunk-quality/enterprise
```

响应 `data`：

```json
{
  "dataset": "enterprise",
  "dataset_id": "enterprise_temp_chunks",
  "user_type": "enterprise",
  "document_metrics_mode": "simulated",
  "parent_chunk_size": 500,
  "min_chunk_length_threshold": 30,
  "max_chunk_length_threshold": 2000,
  "low_unique_ratio_threshold": 0.08,
  "document_metrics": {
    "expected_document_count": 4,
    "actual_document_count": 3,
    "document_ingest_completeness_rate": 0.75
  },
  "chunk_metrics": {
    "chunk_count": 8,
    "duplicate_chunk_count": 1,
    "min_chunk_length": 0,
    "max_chunk_length": 128,
    "avg_chunk_length": 65.62,
    "low_quality_issue_count": 4,
    "empty_chunk_count": 1,
    "empty_chunk_rate": 0.125,
    "too_short_chunk_count": 1,
    "too_short_chunk_rate": 0.125,
    "too_long_chunk_count": 0,
    "too_long_chunk_rate": 0.0,
    "low_unique_ratio_chunk_count": 1,
    "low_unique_ratio_chunk_rate": 0.125,
    "duplicate_group_count": 1
  },
  "low_quality_issues": [
    {
      "chunk_id": "enterprise_doc_002_chunk_001",
      "document_id": "enterprise_doc_002",
      "issue_type": "empty",
      "reason": "chunk text is empty after stripping whitespace",
      "text_length": 0,
      "unique_ratio": null,
      "duplicate_hash": null
    }
  ]
}
```

响应字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `dataset` | string | 当前评估的数据集名称 |
| `dataset_id` | string | 数据集业务 ID |
| `user_type` | string | 用户类型 |
| `document_metrics_mode` | string | 文档入库完整率的数据模式。当前为 `simulated` |
| `parent_chunk_size` | integer | 父 chunk 配置大小 |
| `min_chunk_length_threshold` | integer | 过短阈值 |
| `max_chunk_length_threshold` | integer | 过长阈值 |
| `low_unique_ratio_threshold` | number | 唯一字符比例阈值 |
| `document_metrics` | object | 文档层级指标 |
| `chunk_metrics` | object | chunk 层级聚合指标 |
| `low_quality_issues` | array | 低质量 chunk 明细 |

`document_metrics` 字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `expected_document_count` | integer | 期望文档数 |
| `actual_document_count` | integer | 实际文档数 |
| `document_ingest_completeness_rate` | number | 文档入库完整率。当前为模拟值，不代表真实入库对账 |

`chunk_metrics` 字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `chunk_count` | integer | chunk 总数 |
| `duplicate_chunk_count` | integer | 重复冗余 chunk 数，不包含重复组中的第一条 |
| `min_chunk_length` | integer | 最短 chunk 长度 |
| `max_chunk_length` | integer | 最长 chunk 长度 |
| `avg_chunk_length` | number | 平均 chunk 长度 |
| `low_quality_issue_count` | integer | 低质量问题总数 |
| `empty_chunk_count` | integer | 空 chunk 数 |
| `empty_chunk_rate` | number | chunk 空值率 |
| `too_short_chunk_count` | integer | 过短 chunk 数 |
| `too_short_chunk_rate` | number | chunk 过短率 |
| `too_long_chunk_count` | integer | 过长 chunk 数 |
| `too_long_chunk_rate` | number | chunk 过长率 |
| `low_unique_ratio_chunk_count` | integer | 唯一字符比例过低 chunk 数 |
| `low_unique_ratio_chunk_rate` | number | 唯一字符比例过低 chunk 占比 |
| `duplicate_group_count` | integer | 重复正文分组数 |

`low_quality_issues` 字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `chunk_id` | string | chunk ID |
| `document_id` | string | 所属文档 ID |
| `issue_type` | string | 低质量类型 |
| `reason` | string | 命中原因 |
| `text_length` | integer | chunk 文本长度 |
| `unique_ratio` | number / null | 唯一字符比例，仅部分问题类型返回 |
| `duplicate_hash` | string / null | 重复正文 hash，仅 `duplicate_content` 返回 |

## 8. 当前临时数据评估结果

当前代码内置的临时数据集评估结果如下：

| 数据集 | chunk 总数 | 重复冗余 chunk 数 | 低质量问题数 | 模拟文档入库完整率 |
| --- | ---: | ---: | ---: | ---: |
| `enterprise` | 8 | 1 | 4 | 0.75 |
| `personal` | 8 | 1 | 3 | 1.0 |

## 9. 后续接入真实数据说明

后续替换真实数据集时，建议保持接口不变，只调整后端数据加载逻辑。

当前数据加载入口：

```text
app/services/chunk_quality_evaluation.py
```

当前临时数据集注册位置：

```python
DEFAULT_DATASETS = {
    "enterprise": DEFAULT_DATASET_DIR / "chunk_quality_enterprise.json",
    "personal": DEFAULT_DATASET_DIR / "chunk_quality_personal.json",
}
```

真实数据接入后，建议提供与当前临时 JSON 等价的内部结构：

```json
{
  "dataset_id": "enterprise_real_chunks",
  "user_type": "enterprise",
  "document_metrics_mode": "simulated",
  "expected_document_count": 1000,
  "actual_document_count": 998,
  "parent_chunk_size": 500,
  "chunks": [
    {
      "chunk_id": "chunk_001",
      "document_id": "doc_001",
      "chunk_type": "text",
      "text": "chunk 正文"
    }
  ]
}
```

只要真实数据能转换成上述结构，现有指标计算逻辑可以直接复用。
