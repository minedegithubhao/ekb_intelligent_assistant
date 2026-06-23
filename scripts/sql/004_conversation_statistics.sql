-- Conversation statistics table for admin dashboard.
-- Provides fast query for message count, last message time, and aggregated stats
-- without scanning conversation_messages every time.
--
-- Refresh strategy: admin query triggers a lightweight incremental refresh from
-- conversation_messages. C端 message writing logic does NOT need modification.

SET NAMES utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE knowforge_rag;

CREATE TABLE IF NOT EXISTS conversation_statistics (
  id BIGINT NOT NULL AUTO_INCREMENT,
  conversation_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  message_count INT NOT NULL DEFAULT 0,
  last_message_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  is_deleted TINYINT(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  UNIQUE KEY uq_conversation_statistics_conv_id (conversation_id),
  KEY ix_conversation_statistics_user_id (user_id),
  CONSTRAINT fk_conversation_statistics_conv_id FOREIGN KEY (conversation_id) REFERENCES conversations (id) ON DELETE CASCADE,
  CONSTRAINT fk_conversation_statistics_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Initialize from existing conversations + conversation_messages
INSERT INTO conversation_statistics (conversation_id, user_id, message_count, last_message_at)
SELECT
  c.id AS conversation_id,
  c.user_id,
  COALESCE(m.msg_count, 0) AS message_count,
  m.last_msg_at AS last_message_at
FROM conversations c
LEFT JOIN (
  SELECT
    conversation_id,
    COUNT(*) AS msg_count,
    MAX(created_at) AS last_msg_at
  FROM conversation_messages
  WHERE is_deleted = 0
  GROUP BY conversation_id
) m ON m.conversation_id = c.id
WHERE c.is_deleted = 0
ON DUPLICATE KEY UPDATE
  user_id = VALUES(user_id),
  message_count = VALUES(message_count),
  last_message_at = VALUES(last_message_at);
