USE knowforge_rag;

ALTER TABLE kb_versions
  ADD COLUMN doc_ready TINYINT(1) NOT NULL DEFAULT 0 COMMENT '文档数据是否已准备完成' AFTER description,
  ADD COLUMN faq_ready TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'FAQ 数据是否已准备完成' AFTER doc_ready,
  ADD COLUMN document_count INT NOT NULL DEFAULT 0 COMMENT '版本内文档数量' AFTER faq_ready,
  ADD COLUMN child_chunk_count INT NOT NULL DEFAULT 0 COMMENT '版本内文档 child chunk 数量' AFTER document_count,
  ADD COLUMN faq_count INT NOT NULL DEFAULT 0 COMMENT '版本内 FAQ 数量' AFTER child_chunk_count;

