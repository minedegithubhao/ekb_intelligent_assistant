SET NAMES utf8mb4 COLLATE utf8mb4_0900_ai_ci;

USE knowforge_rag;

CREATE TABLE IF NOT EXISTS retrieval_hot_configs (
  id BIGINT NOT NULL AUTO_INCREMENT,
  config_name VARCHAR(64) NOT NULL COMMENT '配置名称，如 default',
  is_enabled TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用',
  created_by BIGINT NULL COMMENT '新增人用户ID，关联 users.id',

  variant_generation_enabled TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用查询变体生成',
  rerank_enabled TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用重排',
  rule_variant_count INT NOT NULL COMMENT '规则生成变体数量',
  llm_variant_count INT NOT NULL COMMENT 'LLM生成变体数量',
  query_variant_total INT NOT NULL COMMENT '查询变体总数量',

  faq_exact_match_max_length INT NOT NULL COMMENT 'FAQ精确匹配最大问题长度',
  follow_up_max_length INT NOT NULL COMMENT '追问识别最大长度',
  recent_message_keep_count INT NOT NULL COMMENT '保留最近消息数量',
  history_summary_boundary_round INT NOT NULL COMMENT '历史摘要触发轮次',
  history_summary_max_chars INT NOT NULL COMMENT '历史摘要最大字符数',

  faq_dense_top_k_exact INT NOT NULL COMMENT 'FAQ精确场景稠密召回数量',
  faq_sparse_top_k_exact INT NOT NULL COMMENT 'FAQ精确场景稀疏召回数量',
  faq_fetch_k INT NOT NULL COMMENT 'FAQ候选召回数量',
  faq_k INT NOT NULL COMMENT 'FAQ最终候选数量',
  doc_fetch_k INT NOT NULL COMMENT '文档候选召回数量',
  doc_k INT NOT NULL COMMENT '文档最终候选数量',
  rerank_top_k INT NOT NULL COMMENT '重排候选数量',
  faq_rerank_top_k INT NOT NULL COMMENT 'FAQ重排后保留数量',
  doc_rerank_top_k INT NOT NULL COMMENT '文档重排后保留数量',
  final_evidence_top_k INT NOT NULL COMMENT '最终证据数量',

  faq_dense_weight DOUBLE NOT NULL COMMENT 'FAQ稠密召回权重',
  faq_sparse_weight DOUBLE NOT NULL COMMENT 'FAQ稀疏召回权重',
  doc_dense_weight DOUBLE NOT NULL COMMENT '文档稠密召回权重',
  doc_sparse_weight DOUBLE NOT NULL COMMENT '文档稀疏召回权重',

  faq_high_conf_threshold DOUBLE NOT NULL COMMENT 'FAQ高置信阈值',
  faq_middle_conf_threshold DOUBLE NOT NULL COMMENT 'FAQ中置信阈值',
  doc_evidence_threshold DOUBLE NOT NULL COMMENT '文档证据阈值',

  rule_hit_priority JSON NOT NULL COMMENT '规则命中优先级',
  faq_exact_match_policy VARCHAR(64) NOT NULL COMMENT 'FAQ精确匹配策略',
  standby_keep_days INT NOT NULL COMMENT '备用版本保留天数',
  standby_min_keep_versions INT NOT NULL COMMENT '备用版本最少保留数量',

  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  KEY idx_retrieval_hot_configs_name_enabled (config_name, is_enabled, created_at),
  KEY idx_retrieval_hot_configs_enabled_created (is_enabled, created_at),
  KEY idx_retrieval_hot_configs_created_by (created_by),
  CONSTRAINT fk_retrieval_hot_configs_created_by
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='RAG检索热更新配置历史';

INSERT INTO retrieval_hot_configs (
  config_name,
  is_enabled,
  created_by,
  variant_generation_enabled,
  rerank_enabled,
  rule_variant_count,
  llm_variant_count,
  query_variant_total,
  faq_exact_match_max_length,
  follow_up_max_length,
  recent_message_keep_count,
  history_summary_boundary_round,
  history_summary_max_chars,
  faq_dense_top_k_exact,
  faq_sparse_top_k_exact,
  faq_fetch_k,
  faq_k,
  doc_fetch_k,
  doc_k,
  rerank_top_k,
  faq_rerank_top_k,
  doc_rerank_top_k,
  final_evidence_top_k,
  faq_dense_weight,
  faq_sparse_weight,
  doc_dense_weight,
  doc_sparse_weight,
  faq_high_conf_threshold,
  faq_middle_conf_threshold,
  doc_evidence_threshold,
  rule_hit_priority,
  faq_exact_match_policy,
  standby_keep_days,
  standby_min_keep_versions
) SELECT
  'default',
  1,
  NULL,
  1,
  1,
  1,
  1,
  3,
  48,
  10,
  8,
  8,
  800,
  3,
  3,
  20,
  20,
  50,
  20,
  8,
  3,
  5,
  6,
  0.5,
  0.5,
  0.7,
  0.3,
  0.85,
  0.65,
  0.55,
  JSON_ARRAY('human_transfer', 'out_of_scope', 'greeting', 'faq_fast_retrieval'),
  'normalized_exact_match',
  30,
  1
WHERE NOT EXISTS (
  SELECT 1
  FROM retrieval_hot_configs
  WHERE is_enabled = 1
);
