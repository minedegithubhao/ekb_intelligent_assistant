-- Initialize user conversation and chat message tables.
-- Non-destructive: creates the tables only when they do not already exist.

SET NAMES utf8mb4 COLLATE utf8mb4_0900_ai_ci;

USE knowforge_rag;

CREATE TABLE IF NOT EXISTS conversations (
  id BIGINT NOT NULL AUTO_INCREMENT,
  user_id BIGINT NOT NULL,
  title VARCHAR(255) NULL,
  knowledge_base_type VARCHAR(32) NOT NULL,
  last_message_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  is_deleted TINYINT(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  KEY ix_conversations_user_id (user_id),
  KEY ix_conversations_knowledge_base_type (knowledge_base_type),
  KEY ix_conversations_last_message_at (last_message_at),
  KEY ix_conversations_user_kb_deleted_updated (user_id, knowledge_base_type, is_deleted, updated_at),
  CONSTRAINT fk_conversations_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS conversation_messages (
  id BIGINT NOT NULL AUTO_INCREMENT,
  conversation_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  role VARCHAR(32) NOT NULL,
  content TEXT NOT NULL,
  sources_json JSON NULL,
  metadata_json JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  is_deleted TINYINT(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  KEY ix_conversation_messages_conversation_id (conversation_id),
  KEY ix_conversation_messages_user_id (user_id),
  KEY ix_conversation_messages_role (role),
  KEY ix_conversation_messages_conversation_deleted_created (conversation_id, is_deleted, created_at),
  CONSTRAINT fk_conversation_messages_conversation_id FOREIGN KEY (conversation_id) REFERENCES conversations (id) ON DELETE CASCADE,
  CONSTRAINT fk_conversation_messages_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
