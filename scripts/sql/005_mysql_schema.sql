-- 知识库版本管理模块表结构。
-- 设计说明：
-- 1. 版本管理只依据 kb_version，不管理企业/个人 source。
-- 2. 企业/个人仍可作为向量库 chunk 的过滤字段，但不进入版本管理表。
-- 3. Milvus collection 固定为 faq_collection/doc_collection 两个。
-- 4. 新版本入库前由业务代码生成 kb_时间戳 格式的 kb_version。
-- 5. embedding_model 默认值来自 config/retrieval.yaml 中的 embedding_model 参数：bge-m3。

CREATE TABLE IF NOT EXISTS kb_versions (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    kb_version VARCHAR(128) NOT NULL COMMENT '知识库版本号，格式为 kb_时间戳，例如 kb_20260623153045',
    type VARCHAR(16) NOT NULL DEFAULT 'staged' COMMENT '版本状态：staged / active / archived',
    embedding_model VARCHAR(64) NOT NULL DEFAULT 'bge-m3' COMMENT '向量化模型',
    faq_collection_name VARCHAR(191) NOT NULL DEFAULT 'faq_collection' COMMENT '固定 faq collection 名称',
    doc_collection_name VARCHAR(191) NOT NULL DEFAULT 'doc_collection' COMMENT '固定 doc collection 名称',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    created_by VARCHAR(64) DEFAULT NULL COMMENT '创建人',
    description VARCHAR(255) DEFAULT NULL COMMENT '版本说明',
    PRIMARY KEY (id),
    UNIQUE KEY uk_kb_versions_kb_version (kb_version),
    KEY idx_kb_versions_type (type),
    KEY idx_kb_versions_created_at (created_at),
    CONSTRAINT chk_kb_versions_type CHECK (type IN ('staged', 'active', 'archived'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识库版本表';

CREATE TABLE IF NOT EXISTS kb_version_pointers (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    kb_active_version VARCHAR(128) DEFAULT NULL COMMENT '当前正在使用的知识库版本',
    kb_previous_version VARCHAR(128) DEFAULT NULL COMMENT '上一个线上版本，用于快速回滚',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (id),
    KEY idx_kb_version_pointers_active (kb_active_version),
    KEY idx_kb_version_pointers_previous (kb_previous_version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识库版本指针表';

CREATE TABLE IF NOT EXISTS kb_version_action_logs (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    action VARCHAR(16) NOT NULL COMMENT '操作类型：publish / rollback',
    source_version VARCHAR(128) DEFAULT NULL COMMENT '切换前的 active 版本',
    target_version VARCHAR(128) NOT NULL COMMENT '本次要切换成 active 的目标版本',
    source_from_status VARCHAR(16) DEFAULT NULL COMMENT '源版本切换前状态，通常为 active',
    source_to_status VARCHAR(16) DEFAULT NULL COMMENT '源版本切换后状态，通常为 archived',
    target_from_status VARCHAR(16) NOT NULL COMMENT '目标版本切换前状态：staged / archived',
    target_to_status VARCHAR(16) NOT NULL COMMENT '目标版本切换后状态，通常为 active',
    operator_id VARCHAR(64) DEFAULT NULL COMMENT '操作人',
    message TEXT DEFAULT NULL COMMENT '操作说明或原因',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '操作时间',
    PRIMARY KEY (id),
    KEY idx_kb_version_action_logs_action (action),
    KEY idx_kb_version_action_logs_source_version (source_version),
    KEY idx_kb_version_action_logs_target_version (target_version),
    KEY idx_kb_version_action_logs_created_at (created_at),
    CONSTRAINT chk_kb_version_action_logs_action CHECK (action IN ('publish', 'rollback')),
    CONSTRAINT chk_kb_version_action_logs_source_from_status CHECK (source_from_status IN ('active')),
    CONSTRAINT chk_kb_version_action_logs_source_to_status CHECK (source_to_status IN ('archived')),
    CONSTRAINT chk_kb_version_action_logs_target_from_status CHECK (target_from_status IN ('staged', 'archived')),
    CONSTRAINT chk_kb_version_action_logs_target_to_status CHECK (target_to_status IN ('active'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识库版本操作日志表';
