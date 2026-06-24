-- Evaluation module tables.
-- This script is idempotent for table creation, but it does not migrate existing indexes.

CREATE TABLE IF NOT EXISTS evaluation_datasets (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '数据库主键',
  dataset_id VARCHAR(64) NOT NULL COMMENT '评估集业务ID',
  name VARCHAR(128) NOT NULL COMMENT '评估集名称',
  evaluation_type VARCHAR(32) NOT NULL COMMENT '评估集适用类型：ingestion_quality/retrieval_eval/end_to_end/mixed',
  description TEXT NULL COMMENT '评估集说明',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_dataset_id (dataset_id),
  KEY idx_evaluation_type (evaluation_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='评估集表';

CREATE TABLE IF NOT EXISTS evaluation_cases (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '数据库主键',
  case_id VARCHAR(64) NOT NULL COMMENT '评估样本业务ID',
  dataset_id VARCHAR(64) NOT NULL COMMENT '所属评估集业务ID',
  question TEXT NOT NULL COMMENT '评估问题',
  expected_json JSON NULL COMMENT '期望结果JSON，包含expected_faq_ids、expected_rule_ids、参考答案等',
  category VARCHAR(64) NULL COMMENT '样本类型，如faq/policy_fact/table_lookup/no_answer',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_dataset_case (dataset_id, case_id),
  KEY idx_dataset_id (dataset_id),
  KEY idx_category (category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='评估样本表';

CREATE TABLE IF NOT EXISTS evaluation_runs (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '数据库主键',
  run_id VARCHAR(64) NOT NULL COMMENT '评估任务业务ID',
  dataset_id VARCHAR(64) NULL COMMENT '使用的评估集业务ID，入库质量评估可为空',
  evaluation_type VARCHAR(32) NOT NULL COMMENT '评估类型：ingestion_quality/retrieval_eval/end_to_end',
  knowledge_base_version VARCHAR(64) NULL COMMENT '被评估的知识库版本',
  config_json JSON NULL COMMENT '本次评估配置，如top_k、kb_version、source_filter、RAGAS指标等',
  status VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT '任务状态：pending/running/success/failed',
  summary_json JSON NULL COMMENT '汇总指标结果',
  detail_json JSON NULL COMMENT '评估明细，如入库质量评估的低质量chunk、重复chunk列表等',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  finished_at DATETIME NULL COMMENT '完成时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_run_id (run_id),
  KEY idx_dataset_id (dataset_id),
  KEY idx_evaluation_type (evaluation_type),
  KEY idx_status (status),
  KEY idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='评估任务表';

CREATE TABLE IF NOT EXISTS evaluation_case_results (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '数据库主键',
  run_id VARCHAR(64) NOT NULL COMMENT '所属评估任务业务ID',
  case_id VARCHAR(64) NOT NULL COMMENT '所属评估样本业务ID',
  retrieved_items_json JSON NULL COMMENT '实际召回结果JSON，包含query、rewritten_query、faq_hits、kb_hits等',
  metric_results_json JSON NULL COMMENT '单条样本指标结果JSON，如faq_hit_rate@5、kb_recall@10、kb_mrr@10',
  actual_answer LONGTEXT NULL COMMENT '端到端评估中的实际模型回答，检索评估可为空',
  latency_json JSON NULL COMMENT '耗时信息JSON，如faq_retrieval_ms、kb_retrieval_ms、total_ms',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_run_case (run_id, case_id),
  KEY idx_run_id (run_id),
  KEY idx_case_id (case_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='评估样本结果表';
