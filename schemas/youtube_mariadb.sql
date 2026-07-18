-- MariaDB schema for the clean_youtube tracker (Toolforge / ToolsDB).
-- Load with (the database itself must already exist, prefixed with your
-- ToolsDB user, e.g. CREATE DATABASE sNNNNN__youtube; via `sql tools`):
--   mysql --defaults-file=$HOME/replica.my.cnf -h tools.db.svc.wikimedia.cloud \
--     sNNNNN__youtube < schemas/youtube_mariadb.sql
-- (`sql tools <db_name>` does NOT work: extra args are executed as a query.)
--
-- Firebird counterpart (local dev): schemas/youtube.sql

-- channelId -> @handle lookups, cached across runs (status: found/not_found/error)
CREATE TABLE IF NOT EXISTS channel_handles (
  channel_id  VARCHAR(64)  NOT NULL,
  handle      VARCHAR(255),
  status      VARCHAR(16)  NOT NULL,
  created_at  TIMESTAMP    NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (channel_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- handle-or-channelId -> publisher item on Wikidata (status: found/not_found/error)
CREATE TABLE IF NOT EXISTS channel_publishers (
  channel_key    VARCHAR(255) NOT NULL,
  publisher_qid  VARCHAR(20),
  status         VARCHAR(16)  NOT NULL,
  created_at     TIMESTAMP    NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (channel_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- per-item processing status (status: success/failed)
CREATE TABLE IF NOT EXISTS qids (
  qid         VARCHAR(20)  NOT NULL,
  status      VARCHAR(16),
  error_msg   VARCHAR(255),
  summary     VARCHAR(255),
  created_at  TIMESTAMP    NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (qid)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------------
-- Maintenance queries (the Firebird schema has these as procedures)
-- ---------------------------------------------------------------------------
--
-- CORRECTIONS: reclassify known-harmless failures so they are not retried.
--
--   UPDATE qids SET status = 'success'
--   WHERE status = 'failed' AND error_msg = 'No YouTube URLs found';
--
-- GET_LIST(code): failed QIDs by error category, for building retry lists.
--
--   SELECT qid FROM qids WHERE status = 'failed' AND <condition> ORDER BY qid;
--
--   private   error_msg LIKE '%private/deleted%'
--   audio     error_msg LIKE '%missing audio language%'
--   publisher error_msg LIKE '%existing publisher%'
--   extract   error_msg LIKE '%could not extract%'
--               AND error_msg NOT LIKE '%/live/%' AND error_msg NOT LIKE '%/post/%'
--               AND error_msg NOT LIKE '%/playlist?%' AND error_msg NOT LIKE '%/playables/%'
--   playlist  error_msg LIKE '%could not extract%' AND error_msg LIKE '%/playlist?%'
--   live      error_msg LIKE '%could not extract%' AND error_msg LIKE '%/live/%'
--   post      error_msg LIKE '%could not extract%' AND error_msg LIKE '%/post/%'
