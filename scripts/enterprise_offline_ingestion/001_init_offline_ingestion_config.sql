SET NAMES utf8mb4 COLLATE utf8mb4_0900_ai_ci;

USE knowforge_rag;

CREATE TABLE IF NOT EXISTS offline_ingestion_configs (
  id BIGINT NOT NULL AUTO_INCREMENT,
  config_name VARCHAR(64) NOT NULL COMMENT '配置名称，如 default',
  is_enabled TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用',
  created_by BIGINT NULL COMMENT '创建人 users.id',

  source_data_root VARCHAR(512) NOT NULL COMMENT '源数据根目录，相对项目根目录或绝对路径',
  clean_markdown_dir VARCHAR(128) NOT NULL COMMENT '清洗后 Markdown 目录名',
  index_csv_name VARCHAR(128) NOT NULL COMMENT '索引文件名',
  faq_csv_dir VARCHAR(128) NOT NULL COMMENT 'FAQ 目录名',

  doc_parent_chunk_size INT NOT NULL COMMENT 'parent chunk 最大字符数',
  doc_child_chunk_size INT NOT NULL COMMENT 'child chunk 最大字符数',
  doc_child_chunk_overlap INT NOT NULL COMMENT 'child chunk 重叠字符数',

  table_split_strategy VARCHAR(32) NOT NULL COMMENT '表格切分策略',
  table_header_required TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否要求表头存在',
  table_row_max_chars INT NOT NULL COMMENT '单表格行最大字符数',

  rule_metadata_filter_keys JSON NOT NULL COMMENT '正文中需要过滤的规则元信息字段',

  doc_collection_name VARCHAR(128) NOT NULL COMMENT '文档 collection 名称',
  faq_collection_name VARCHAR(128) NOT NULL COMMENT 'FAQ collection 名称',
  dense_vector_dim INT NOT NULL COMMENT 'dense vector 维度',
  sparse_vector_enabled TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用 sparse vector',

  embedding_batch_size INT NOT NULL COMMENT 'embedding 批处理大小',
  milvus_insert_batch_size INT NOT NULL COMMENT 'Milvus 写入批处理大小',

  scope_enum JSON NOT NULL COMMENT 'scope 枚举映射',

  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  KEY idx_offline_ingestion_configs_name_enabled (config_name, is_enabled, created_at),
  KEY idx_offline_ingestion_configs_enabled_created (is_enabled, created_at),
  CONSTRAINT uq_offline_ingestion_configs_name UNIQUE (config_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='企业级离线入库配置表';

INSERT INTO offline_ingestion_configs (
  config_name,
  is_enabled,
  created_by,
  source_data_root,
  clean_markdown_dir,
  index_csv_name,
  faq_csv_dir,
  doc_parent_chunk_size,
  doc_child_chunk_size,
  doc_child_chunk_overlap,
  table_split_strategy,
  table_header_required,
  table_row_max_chars,
  rule_metadata_filter_keys,
  doc_collection_name,
  faq_collection_name,
  dense_vector_dim,
  sparse_vector_enabled,
  embedding_batch_size,
  milvus_insert_batch_size,
  scope_enum
) SELECT
  'default',
  1,
  NULL,
  'source_data',
  '清洗后数据',
  'index.csv',
  'faq',
  1200,
  400,
  80,
  'row',
  1,
  1000,
  JSON_ARRAY('rule_id', 'source_url', 'label_names', 'active_time', 'update_time'),
  'doc_collection',
  'faq_collection',
  1024,
  1,
  32,
  500,
  JSON_OBJECT('enterprise', '企业', 'personal_individual', '个人/个体')
WHERE NOT EXISTS (
  SELECT 1 FROM offline_ingestion_configs WHERE config_name = 'default'
);
