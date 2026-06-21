-- KnowForge RAG backend auth initialization.
-- Safe to run repeatedly.
--
-- Example accounts for local development:
--   admin / Admin@123456
--   alice / User@123456
--   bob   / User@123456

SET NAMES utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE DATABASE IF NOT EXISTS knowforge_rag
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_0900_ai_ci;

USE knowforge_rag;

CREATE TABLE IF NOT EXISTS roles (
  id BIGINT NOT NULL AUTO_INCREMENT,
  code VARCHAR(64) NOT NULL,
  name VARCHAR(128) NOT NULL,
  description TEXT NULL,
  is_system TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  is_deleted TINYINT(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  UNIQUE KEY uq_roles_code (code),
  KEY ix_roles_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS users (
  id BIGINT NOT NULL AUTO_INCREMENT,
  username VARCHAR(64) NOT NULL,
  display_name VARCHAR(128) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  email VARCHAR(255) NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  last_login_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  is_deleted TINYINT(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  UNIQUE KEY uq_users_username (username),
  KEY ix_users_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS user_roles (
  user_id BIGINT NOT NULL,
  role_id BIGINT NOT NULL,
  PRIMARY KEY (user_id, role_id),
  UNIQUE KEY uq_user_roles_user_role (user_id, role_id),
  CONSTRAINT fk_user_roles_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
  CONSTRAINT fk_user_roles_role_id FOREIGN KEY (role_id) REFERENCES roles (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT INTO roles (code, name, description, is_system)
VALUES
  ('admin', '管理员', '系统管理员，可访问管理端接口', 1),
  ('user', '普通用户', '普通问答用户，可访问用户端接口', 1)
ON DUPLICATE KEY UPDATE
  name = VALUES(name),
  description = VALUES(description),
  is_system = VALUES(is_system),
  is_deleted = 0;

INSERT INTO users (username, display_name, password_hash, email, is_active)
VALUES
  (
    'admin',
    '系统管理员',
    'pbkdf2_sha256$260000$knowforge-admin-salt$21n1WWCrMMhv-VK_tN0AsNW2gbxWSd2LKzY2VHcu3FM',
    'admin@example.com',
    1
  ),
  (
    'alice',
    'Alice 普通用户',
    'pbkdf2_sha256$260000$knowforge-user-salt$VicOXeR8E1LqV8WcROFSAfMj3Y09rwyT2Y6_V0jh2W4',
    'alice@example.com',
    1
  ),
  (
    'bob',
    'Bob 普通用户',
    'pbkdf2_sha256$260000$knowforge-bob-salt$jYsafk8hFPp-SXBxH98va9H1YLoaZbPnceXKFr46K8o',
    'bob@example.com',
    1
  )
ON DUPLICATE KEY UPDATE
  display_name = VALUES(display_name),
  password_hash = VALUES(password_hash),
  email = VALUES(email),
  is_active = VALUES(is_active),
  is_deleted = 0;

INSERT IGNORE INTO user_roles (user_id, role_id)
SELECT u.id, r.id FROM users u JOIN roles r ON r.code = 'admin' WHERE u.username = 'admin';

INSERT IGNORE INTO user_roles (user_id, role_id)
SELECT u.id, r.id FROM users u JOIN roles r ON r.code = 'user' WHERE u.username IN ('alice', 'bob');
