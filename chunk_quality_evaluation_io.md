# Chunk 质量评估模块输入输出说明

## 1. 文档说明

本文档说明 chunk 质量评估模块每个功能的输入、输出，以及临时 JSON 数据集需要满足的字段格式。

当前模块使用两个临时 JSON 数据集：

| 数据集 | 用户类型 | 文件 |
| --- | --- | --- |
| `enterprise` | 企业用户 | `resources/seed_data/chunk_quality_enterprise.json` |
| `personal` | 个人用户 | `resources/seed_data/chunk_quality_personal.json` |

### 1.1 企业和个人临时数据集字段说明

`enterprise` 和 `personal` 两个临时数据集的 JSON 字段结构完全一致，区别只在于数据集标识、用户类型、文档数量和 chunk 内容。

两个数据集都使用以下顶层字段：

| 字段 | 企业数据集取值 | 个人数据集取值 | 说明 |
| --- | --- | --- | --- |
| `dataset_id` | `enterprise_temp_chunks` | `personal_temp_chunks` | 数据集业务 ID，用于区分评估数据来源 |
| `user_type` | `enterprise` | `personal` | 用户类型，和权限隔离场景对应 |
| `document_metrics_mode` | `simulated` | `simulated` | 文档入库完整率的数据模式。当前表示模拟值，不是真实入库对账 |
| `expected_document_count` | `4` | `3` | 模拟的期望入库文档数 |
| `actual_document_count` | `3` | `3` | 模拟的实际入库文档数 |
| `parent_chunk_size` | `500` | `500` | 父 chunk 配置大小，用于计算过长阈值 |
| `chunks` | 8 条 chunk | 8 条 chunk | 当前数据集中的 chunk 明细列表 |

两个数据集的 `chunks[]` 字段也保持一致：

| 字段 | 企业数据集示例 | 个人数据集示例 | 说明 |
| --- | --- | --- | --- |
| `chunk_id` | `enterprise_doc_001_chunk_001` | `personal_doc_001_chunk_001` | chunk 唯一 ID。临时数据中用用户类型、文档序号、chunk 序号拼接 |
| `document_id` | `enterprise_doc_001` | `personal_doc_001` | chunk 所属文档 ID，用于统计实际文档数 |
| `title` | `京东开放平台店铺星级规则` | `京东开放平台个人/个体开店管理规则` | 文档标题或 chunk 标题，用于排查问题 |
| `chunk_type` | `text` / `table` | `text` / `table` | chunk 类型。值为 `table` 时按表格 chunk 处理 |
| `text` | 企业规则 chunk 正文 | 个人/个体规则 chunk 正文 | chunk 正文，是质量评估的核心输入字段 |

当前两个临时数据集都故意放入了一些低质量样例，用于验证指标是否能正确触发：

| 数据集 | 内置低质量样例 |
| --- | --- |
| `enterprise` | 空 chunk、过短 chunk、重复正文 chunk、唯一字符比例过低 chunk |
| `personal` | 空 chunk、过短 chunk、重复正文 chunk |

后续替换真实数据集时，只要真实数据能转换成本文档定义的输入 JSON 结构，现有评估逻辑可以继续复用。

## 2. 模块功能总览

| 功能 | 输入 | 输出 | 说明 |
| --- | --- | --- | --- |
| 查询可评估数据集 | 无 | 数据集列表 | 返回当前支持的 `enterprise`、`personal` 临时数据集 |
| 执行指定数据集评估 | `dataset` | 单个数据集评估结果 | 根据数据集名称读取 JSON 并计算指标 |
| 执行原始 JSON payload 评估 | chunk 数据集 JSON | 单个数据集评估结果 | 适合后续真实数据源接入时复用 |

## 3. 功能一：查询可评估数据集

### 3.1 后端函数

```python
list_chunk_quality_datasets() -> list[ChunkQualityDatasetInfo]
```

### 3.2 输入

无。

### 3.3 输出

```json
[
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
]
```

### 3.4 输出字段说明

| 字段 | 类型 | 必有 | 说明 |
| --- | --- | --- | --- |
| `dataset` | string | 是 | 数据集名称，用于调用评估接口 |
| `dataset_id` | string | 是 | 数据集业务 ID |
| `user_type` | string | 是 | 用户类型，当前为 `enterprise` 或 `personal` |
| `path` | string | 是 | 临时 JSON 文件路径 |

## 4. 功能二：执行指定数据集评估

### 4.1 后端函数

```python
evaluate_chunk_quality_dataset(dataset: str) -> ChunkQualityEvaluationResult
```

### 4.2 输入

`dataset` 是字符串。

允许值：

```text
enterprise
personal
```

输入示例：

```python
evaluate_chunk_quality_dataset("enterprise")
```

### 4.3 处理逻辑

1. 根据 `dataset` 找到对应临时 JSON 文件。
2. 读取 JSON。
3. 校验 JSON 根节点必须是 object。
4. 校验 `chunks` 必须是 array。
5. 计算模拟文档入库完整率。
6. 计算 chunk 长度分布。
7. 识别低质量 chunk。
8. 返回评估结果。

### 4.4 输出

输出结构与“功能三”的 `ChunkQualityEvaluationResult` 相同。

## 5. 功能三：执行原始 JSON payload 评估

### 5.1 后端函数

```python
evaluate_chunk_quality_payload(
    dataset: str,
    payload: dict[str, Any],
) -> ChunkQualityEvaluationResult
```

### 5.2 输入

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `dataset` | string | 是 | 当前评估的数据集名称 |
| `payload` | object | 是 | chunk 数据集 JSON 内容 |

### 5.3 输入 JSON 总体格式

```json
{
  "dataset_id": "enterprise_temp_chunks",
  "user_type": "enterprise",
  "document_metrics_mode": "simulated",
  "expected_document_count": 4,
  "actual_document_count": 3,
  "parent_chunk_size": 500,
  "chunks": [
    {
      "chunk_id": "enterprise_doc_001_chunk_001",
      "document_id": "enterprise_doc_001",
      "title": "京东开放平台店铺星级规则",
      "chunk_type": "text",
      "text": "chunk 正文"
    }
  ]
}
```

### 5.4 输入 JSON 顶层字段说明

| 字段 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `dataset_id` | string | 否 | 使用 `dataset` 参数 | 数据集业务 ID |
| `user_type` | string | 否 | 使用 `dataset` 参数 | 用户类型，例如 `enterprise`、`personal` |
| `document_metrics_mode` | string | 否 | `simulated` | 文档入库完整率的数据模式。当前临时数据使用 `simulated` |
| `expected_document_count` | integer | 否 | `actual_document_count` | 期望文档数。当前用于模拟文档入库完整率 |
| `actual_document_count` | integer | 否 | 从 `chunks[].document_id` 去重推导 | 实际文档数。当前用于模拟文档入库完整率 |
| `parent_chunk_size` | integer | 否 | `500` | 父 chunk 配置大小，用于计算过长阈值 |
| `chunks` | array | 是 | 无 | chunk 列表 |

### 5.5 `chunks[]` 字段说明

| 字段 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `chunk_id` | string | 否 | `chunk_序号` | chunk 唯一 ID，建议真实数据必须提供 |
| `document_id` | string | 否 | `null` | 所属文档 ID，用于推导实际文档数 |
| `title` | string | 否 | 无 | 文档标题或 chunk 标题，仅用于展示和排查 |
| `chunk_type` | string | 否 | 空字符串 | chunk 类型。值为 `table` 时按表格 chunk 处理 |
| `is_table` | boolean | 否 | `false` | 是否表格 chunk。为 `true` 时优先按表格处理 |
| `text` | string | 否 | 空字符串 | chunk 正文，质量评估的核心字段 |

### 5.6 最小可用输入 JSON

这是当前评估逻辑可以运行的最小结构：

```json
{
  "chunks": [
    {
      "text": "chunk 正文"
    }
  ]
}
```

但真实接入时不建议只传最小结构。推荐至少提供：

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

## 6. 输出 JSON 格式

### 6.1 完整输出示例

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

### 6.2 输出顶层字段说明

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `dataset` | string | 当前评估的数据集名称 |
| `dataset_id` | string | 数据集业务 ID |
| `user_type` | string | 用户类型 |
| `document_metrics_mode` | string | 文档入库完整率的数据模式。当前为 `simulated`，表示模拟值 |
| `parent_chunk_size` | integer | 父 chunk 配置大小 |
| `min_chunk_length_threshold` | integer | 过短阈值，当前固定为 `30` |
| `max_chunk_length_threshold` | integer | 过长阈值，等于 `max(parent_chunk_size * 2, 2000)` |
| `low_unique_ratio_threshold` | number | 唯一字符比例阈值，当前固定为 `0.08` |
| `document_metrics` | object | 文档层级指标 |
| `chunk_metrics` | object | chunk 层级指标 |
| `low_quality_issues` | array | 低质量 chunk 明细 |

### 6.3 `document_metrics` 字段说明

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `expected_document_count` | integer | 期望文档数 |
| `actual_document_count` | integer | 实际文档数 |
| `document_ingest_completeness_rate` | number | 文档入库完整率。当前由模拟字段计算，不代表真实入库对账 |

计算公式：

```text
document_ingest_completeness_rate = actual_document_count / expected_document_count
```

特殊情况：

| 情况 | 返回值 |
| --- | --- |
| `expected_document_count = 0` 且 `actual_document_count = 0` | `1.0` |
| `expected_document_count = 0` 且 `actual_document_count > 0` | `0.0` |

### 6.4 `chunk_metrics` 字段说明

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `chunk_count` | integer | chunk 总数 |
| `duplicate_chunk_count` | integer | 重复冗余 chunk 数，不包含每组重复内容中的第一条 |
| `min_chunk_length` | integer | 最短 chunk 长度 |
| `max_chunk_length` | integer | 最长 chunk 长度 |
| `avg_chunk_length` | number | 平均 chunk 长度，保留两位小数 |
| `low_quality_issue_count` | integer | 低质量问题总数 |
| `empty_chunk_count` | integer | 空 chunk 数 |
| `empty_chunk_rate` | number | 空 chunk 占比 |
| `too_short_chunk_count` | integer | 过短 chunk 数 |
| `too_short_chunk_rate` | number | 过短 chunk 占比 |
| `too_long_chunk_count` | integer | 过长 chunk 数 |
| `too_long_chunk_rate` | number | 过长 chunk 占比 |
| `low_unique_ratio_chunk_count` | integer | 唯一字符比例过低 chunk 数 |
| `low_unique_ratio_chunk_rate` | number | 唯一字符比例过低 chunk 占比 |
| `duplicate_group_count` | integer | 重复正文分组数 |

### 6.5 `low_quality_issues[]` 字段说明

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `chunk_id` | string | 命中问题的 chunk ID |
| `document_id` | string / null | chunk 所属文档 ID |
| `issue_type` | string | 低质量问题类型 |
| `reason` | string | 命中原因 |
| `text_length` | integer | chunk 去除首尾空白后的文本长度 |
| `unique_ratio` | number / null | 唯一字符比例，仅部分问题类型返回 |
| `duplicate_hash` | string / null | 重复正文 hash，仅 `duplicate_content` 返回 |

## 7. 低质量问题输入触发规则

| issue_type | 依赖输入字段 | 触发规则 |
| --- | --- | --- |
| `empty` | `chunks[].text` | `text.strip()` 为空 |
| `too_short` | `chunks[].text`、`chunks[].chunk_type`、`chunks[].is_table` | 文本长度 `< 30`，且不是表格 chunk |
| `too_long` | `chunks[].text`、`parent_chunk_size` | 文本长度 `> max(parent_chunk_size * 2, 2000)` |
| `low_unique_ratio` | `chunks[].text`、`chunks[].chunk_type`、`chunks[].is_table` | 文本长度 `>= 50`，唯一字符比例 `< 0.08`，且不是表格 chunk |
| `duplicate_content` | `chunks[].text`、`chunks[].chunk_id` | 多个非空 chunk 正文 hash 相同，重复组中第一条不标记，后续副本标记 |

## 8. 接口层输入输出

### 8.1 查询数据集接口

```http
GET /api/admin/evaluations/chunk-quality/datasets
```

输入：

```text
无路径参数
无 query 参数
无请求体
需要 Authorization: Bearer <token>
```

输出：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "items": [
      {
        "dataset": "enterprise",
        "dataset_id": "enterprise_temp_chunks",
        "user_type": "enterprise",
        "path": "resources/seed_data/chunk_quality_enterprise.json"
      }
    ],
    "total": 2
  }
}
```

### 8.2 执行评估接口

```http
GET /api/admin/evaluations/chunk-quality/{dataset}
```

输入：

| 输入位置 | 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `dataset` | string | 是 | 允许值：`enterprise`、`personal` |
| header | `Authorization` | string | 是 | `Bearer <token>` |

请求体：

```text
无
```

输出：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "dataset": "enterprise",
    "dataset_id": "enterprise_temp_chunks",
    "user_type": "enterprise",
    "document_metrics": {},
    "chunk_metrics": {},
    "low_quality_issues": []
  }
}
```

## 9. 输入校验和异常

| 场景 | 处理方式 |
| --- | --- |
| `dataset` 不是 `enterprise` 或 `personal` | 返回 404 |
| 数据集文件不存在 | 返回 404 |
| JSON 根节点不是 object | 返回 400 |
| `chunks` 不存在 | 返回 400 |
| `chunks` 不是 array | 返回 400 |
| `chunks[]` 中某项不是 object | 返回 400 |
| `text` 缺失 | 按空字符串处理 |
| `chunk_id` 缺失 | 使用 `chunk_序号` 兜底 |
| `document_id` 缺失 | 不参与文档数推导 |
| `parent_chunk_size` 缺失或非法 | 使用默认值 `500` |
| `document_metrics_mode` 缺失 | 使用默认值 `simulated` |
| `expected_document_count` 缺失 | 使用实际文档数兜底 |
| `actual_document_count` 缺失 | 从 `document_id` 去重推导 |

## 10. 当前临时数据集结果

| 数据集 | 输入 chunk 数 | 输出低质量问题数 | 输出模拟文档入库完整率 |
| --- | ---: | ---: | ---: |
| `enterprise` | 8 | 4 | 0.75 |
| `personal` | 8 | 3 | 1.0 |
