-- Rebuild auth and dashboard configuration tables for development.
-- This script is intentionally destructive for the listed tables only.

SET NAMES utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE DATABASE IF NOT EXISTS knowforge_rag
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_0900_ai_ci;

USE knowforge_rag;

SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS user_question_categories;
DROP TABLE IF EXISTS user_sessions;
DROP TABLE IF EXISTS user_roles;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS roles;
SET FOREIGN_KEY_CHECKS = 1;

CREATE TABLE roles (
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

CREATE TABLE users (
  id BIGINT NOT NULL AUTO_INCREMENT,
  username VARCHAR(64) NOT NULL,
  name VARCHAR(128) NULL,
  display_name VARCHAR(128) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  email VARCHAR(255) NULL,
  department VARCHAR(128) NULL,
  category VARCHAR(64) NULL,
  user_type VARCHAR(32) NOT NULL DEFAULT 'user',
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  last_login_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  is_deleted TINYINT(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  UNIQUE KEY uq_users_username (username),
  KEY ix_users_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE user_roles (
  user_id BIGINT NOT NULL,
  role_id BIGINT NOT NULL,
  PRIMARY KEY (user_id, role_id),
  UNIQUE KEY uq_user_roles_user_role (user_id, role_id),
  CONSTRAINT fk_user_roles_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
  CONSTRAINT fk_user_roles_role_id FOREIGN KEY (role_id) REFERENCES roles (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE user_sessions (
  id BIGINT NOT NULL AUTO_INCREMENT,
  user_id BIGINT NOT NULL,
  token_jti VARCHAR(128) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  login_at DATETIME NOT NULL,
  expires_at DATETIME NOT NULL,
  logout_at DATETIME NULL,
  ip_address VARCHAR(64) NULL,
  user_agent VARCHAR(512) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  is_deleted TINYINT(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  UNIQUE KEY uq_user_sessions_token_jti (token_jti),
  KEY ix_user_sessions_user_id (user_id),
  KEY ix_user_sessions_expires_at (expires_at),
  CONSTRAINT fk_user_sessions_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE user_question_categories (
  id BIGINT NOT NULL AUTO_INCREMENT,
  user_id BIGINT NOT NULL,
  category_code VARCHAR(64) NOT NULL,
  category_name VARCHAR(128) NOT NULL,
  description TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  is_deleted TINYINT(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  UNIQUE KEY uq_user_question_category (user_id, category_code),
  KEY ix_user_question_categories_user_id (user_id),
  CONSTRAINT fk_user_question_categories_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT INTO roles (code, name, description, is_system)
VALUES
  ('admin', '管理员', '系统管理员，可访问管理端接口', 1),
  ('user', '普通用户', '普通问答用户，可访问用户端接口', 1);

INSERT INTO users (username, name, display_name, password_hash, email, department, category, user_type, is_active)
VALUES
  (
    'admin',
    '系统管理员',
    '系统管理员',
    'pbkdf2_sha256$260000$knowforge-admin-salt$21n1WWCrMMhv-VK_tN0AsNW2gbxWSd2LKzY2VHcu3FM',
    'admin@example.com',
    '平台运营部',
    'admin',
    'admin',
    1
  ),
  (
    'alice',
    'Alice',
    'Alice 普通用户',
    'pbkdf2_sha256$260000$knowforge-user-salt$VicOXeR8E1LqV8WcROFSAfMj3Y09rwyT2Y6_V0jh2W4',
    'alice@example.com',
    '招商部',
    'merchant',
    'user',
    1
  ),
  (
    'bob',
    'Bob',
    'Bob 普通用户',
    'pbkdf2_sha256$260000$knowforge-bob-salt$jYsafk8hFPp-SXBxH98va9H1YLoaZbPnceXKFr46K8o',
    'bob@example.com',
    '商家服务部',
    'individual',
    'user',
    1
  );

INSERT INTO user_roles (user_id, role_id)
SELECT u.id, r.id FROM users u JOIN roles r ON r.code = 'admin' WHERE u.username = 'admin';

INSERT INTO user_roles (user_id, role_id)
SELECT u.id, r.id FROM users u JOIN roles r ON r.code = 'user' WHERE u.username IN ('alice', 'bob');

INSERT INTO user_question_categories (user_id, category_code, category_name, description)
SELECT id, 'enterprise_shop', '企业店规则', '企业店相关规则问题' FROM users WHERE username IN ('admin', 'alice');

INSERT INTO user_question_categories (user_id, category_code, category_name, description)
SELECT id, 'individual_shop', '个人个体店规则', '个人/个体店相关规则问题' FROM users WHERE username IN ('admin', 'bob');

