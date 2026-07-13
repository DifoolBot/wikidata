-- MariaDB schema for the remove_sitelinks tracker (Toolforge / ToolsDB).
-- Load with:  sql tools <db_name> < schemas/remove_sitelinks_mariadb.sql
-- (the database itself must already exist, prefixed with your ToolsDB user, e.g.
--  CREATE DATABASE sNNNNN__remove_sitelinks;)

CREATE TABLE IF NOT EXISTS qids (
  qid         VARCHAR(20)  NOT NULL,
  status      VARCHAR(20),
  error_msg   VARCHAR(255),
  summary     VARCHAR(255),
  created_at  TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (qid)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wikimedia_cats (
  qid               VARCHAR(20) NOT NULL,
  is_wikimedia_cat  TINYINT(1)  NOT NULL,
  PRIMARY KEY (qid)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
