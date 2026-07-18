-- MariaDB schema for the remove_sitelinks tracker (Toolforge / ToolsDB).
-- Load with (the database itself must already exist, prefixed with your
-- ToolsDB user, e.g. CREATE DATABASE sNNNNN__remove_sitelinks; via `sql tools`):
--   mysql --defaults-file=$HOME/replica.my.cnf -h tools.db.svc.wikimedia.cloud \
--     sNNNNN__remove_sitelinks < schemas/remove_sitelinks_mariadb.sql
-- (`sql tools <db_name>` does NOT work: extra args are executed as a query.)

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
