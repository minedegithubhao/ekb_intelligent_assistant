-- Retrieval runtime configuration tables and initial data.
-- This script owns retrieval hot parameters, keyword rules, and term normalization rules.

SET @retrieval_config_admin_id := (
  SELECT id FROM users WHERE username = 'admin' AND is_deleted = 0 ORDER BY id LIMIT 1
);

CREATE TABLE IF NOT EXISTS retrieval_hot_configs (
  id BIGINT NOT NULL AUTO_INCREMENT,
  config_name VARCHAR(64) NOT NULL DEFAULT 'default',
  description TEXT NULL,
  is_enabled TINYINT(1) NOT NULL DEFAULT 1,
  created_by BIGINT NULL,
  updated_by BIGINT NULL,
  activated_by BIGINT NULL,
  activated_at DATETIME NULL,

  faq_exact_match_max_length INT NOT NULL DEFAULT 48,
  faq_fast_retrieval_limit INT NOT NULL DEFAULT 5,
  faq_fast_dense_weight DOUBLE NOT NULL DEFAULT 0.5,
  faq_fast_sparse_weight DOUBLE NOT NULL DEFAULT 0.5,
  follow_up_max_length INT NOT NULL DEFAULT 10,
  recent_message_keep_count INT NOT NULL DEFAULT 8,
  history_summary_max_chars INT NOT NULL DEFAULT 800,
  variant_generation_enabled TINYINT(1) NOT NULL DEFAULT 1,
  llm_variant_count INT NOT NULL DEFAULT 1,
  faq_candidate_limit_per_query INT NOT NULL DEFAULT 20,
  faq_fusion_top_k INT NOT NULL DEFAULT 20,
  faq_dense_weight DOUBLE NOT NULL DEFAULT 0.5,
  faq_sparse_weight DOUBLE NOT NULL DEFAULT 0.5,
  faq_rerank_top_k INT NOT NULL DEFAULT 3,
  faq_high_conf_threshold DOUBLE NOT NULL DEFAULT 0.85,
  faq_middle_conf_threshold DOUBLE NOT NULL DEFAULT 0.65,
  doc_candidate_limit_per_query INT NOT NULL DEFAULT 50,
  doc_fusion_top_k INT NOT NULL DEFAULT 20,
  doc_dense_weight DOUBLE NOT NULL DEFAULT 0.7,
  doc_sparse_weight DOUBLE NOT NULL DEFAULT 0.3,
  doc_rerank_top_k INT NOT NULL DEFAULT 5,
  doc_evidence_threshold DOUBLE NOT NULL DEFAULT 0.55,
  final_evidence_top_k INT NOT NULL DEFAULT 6,

  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  is_deleted TINYINT(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  KEY idx_retrieval_hot_configs_name_enabled (config_name, is_enabled, is_deleted),
  KEY idx_retrieval_hot_configs_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS retrieval_keyword_rules (
  id BIGINT NOT NULL AUTO_INCREMENT,
  rule_code VARCHAR(64) NOT NULL,
  rule_name VARCHAR(128) NOT NULL,
  keywords_json JSON NOT NULL,
  response_text TEXT NULL,
  match_type VARCHAR(32) NOT NULL DEFAULT 'contains',
  match_order INT NOT NULL DEFAULT 100,
  is_enabled TINYINT(1) NOT NULL DEFAULT 1,
  created_by BIGINT NULL,
  updated_by BIGINT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  is_deleted TINYINT(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  UNIQUE KEY uq_retrieval_keyword_rules_code (rule_code),
  KEY idx_retrieval_keyword_rules_enabled_order (is_enabled, is_deleted, match_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS retrieval_term_normalizations (
  id BIGINT NOT NULL AUTO_INCREMENT,
  canonical_term VARCHAR(128) NOT NULL,
  aliases_json JSON NOT NULL,
  match_type VARCHAR(32) NOT NULL DEFAULT 'contains',
  description TEXT NULL,
  is_enabled TINYINT(1) NOT NULL DEFAULT 1,
  created_by BIGINT NULL,
  updated_by BIGINT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  is_deleted TINYINT(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  UNIQUE KEY uq_retrieval_term_normalizations_canonical (canonical_term),
  KEY idx_retrieval_term_normalizations_enabled (is_enabled, is_deleted)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO retrieval_hot_configs (
  config_name,
  description,
  is_enabled,
  created_by,
  updated_by,
  activated_by,
  activated_at,
  faq_exact_match_max_length,
  faq_fast_retrieval_limit,
  faq_fast_dense_weight,
  faq_fast_sparse_weight,
  follow_up_max_length,
  recent_message_keep_count,
  history_summary_max_chars,
  variant_generation_enabled,
  llm_variant_count,
  faq_candidate_limit_per_query,
  faq_fusion_top_k,
  faq_dense_weight,
  faq_sparse_weight,
  faq_rerank_top_k,
  faq_high_conf_threshold,
  faq_middle_conf_threshold,
  doc_candidate_limit_per_query,
  doc_fusion_top_k,
  doc_dense_weight,
  doc_sparse_weight,
  doc_rerank_top_k,
  doc_evidence_threshold,
  final_evidence_top_k
)
SELECT
  'default',
  '默认检索热参数配置',
  1,
  @retrieval_config_admin_id,
  @retrieval_config_admin_id,
  @retrieval_config_admin_id,
  NOW(),
  48,
  5,
  0.5,
  0.5,
  10,
  8,
  800,
  1,
  1,
  20,
  20,
  0.5,
  0.5,
  3,
  0.85,
  0.65,
  50,
  20,
  0.7,
  0.3,
  5,
  0.55,
  6
WHERE NOT EXISTS (
  SELECT 1 FROM retrieval_hot_configs
  WHERE config_name = 'default' AND is_enabled = 1 AND is_deleted = 0
);

INSERT IGNORE INTO retrieval_keyword_rules (
  rule_code,
  rule_name,
  keywords_json,
  response_text,
  match_type,
  match_order,
  is_enabled,
  created_by,
  updated_by
)
VALUES
  (
    'human_transfer',
    '转人工关键词集合',
    JSON_ARRAY('转人工', '人工客服', '人工坐席客服'),
    '现在为您转接人工客服，请稍后...',
    'contains',
    10,
    1,
    @retrieval_config_admin_id,
    @retrieval_config_admin_id
  ),
  (
    'out_of_scope',
    '越界关键词集合',
    JSON_ARRAY('吃什么', '喝什么', '天气如何'),
    '很抱歉，我是知识库 AI，您可以向我提问当前知识库相关的问题。',
    'contains',
    20,
    1,
    @retrieval_config_admin_id,
    @retrieval_config_admin_id
  ),
  (
    'greeting',
    '打招呼关键词集合',
    JSON_ARRAY('你好', '嗨', 'hello', '请问', '告诉我', '问一下'),
    '你好，我是知识库 AI，有什么可以帮您？',
    'contains',
    30,
    1,
    @retrieval_config_admin_id,
    @retrieval_config_admin_id
  ),
  (
    'faq_fast_retrieval',
    'FAQ 检索关键词集合',
    JSON_ARRAY('退款流程', '重置密码', '发票开错了'),
    NULL,
    'contains',
    40,
    1,
    @retrieval_config_admin_id,
    @retrieval_config_admin_id
  );

INSERT IGNORE INTO retrieval_term_normalizations (
  canonical_term,
  aliases_json,
  match_type,
  description,
  is_enabled,
  created_by,
  updated_by
)
VALUES
  (
    '笔记本电脑',
    JSON_ARRAY('laptop', 'lap top', '笔记型电脑'),
    'contains',
    '笔记本电脑相关同义词',
    1,
    @retrieval_config_admin_id,
    @retrieval_config_admin_id
  ),
  (
    'CPU',
    JSON_ARRAY('CPU', '中央处理器', '中央处理单元'),
    'contains',
    'CPU 相关同义词',
    1,
    @retrieval_config_admin_id,
    @retrieval_config_admin_id
  ),
  (
    'Wi-Fi',
    JSON_ARRAY('Wi-Fi', 'WIFI', '无线网络'),
    'contains',
    'Wi-Fi 相关同义词',
    1,
    @retrieval_config_admin_id,
    @retrieval_config_admin_id
  );
