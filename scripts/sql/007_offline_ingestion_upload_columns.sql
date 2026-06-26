USE knowforge_rag;

ALTER TABLE offline_ingestion_tasks
  ADD COLUMN ingest_type VARCHAR(24) NOT NULL DEFAULT 'mixed' COMMENT 'mixed/document/faq' AFTER config_id,
  ADD COLUMN upload_root VARCHAR(512) DEFAULT NULL COMMENT '本地上传任务保存根目录' AFTER ingest_type;

CREATE INDEX idx_offline_ingestion_tasks_type_created
  ON offline_ingestion_tasks (ingest_type, created_at);
