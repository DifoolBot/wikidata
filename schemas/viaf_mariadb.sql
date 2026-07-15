-- MariaDB schema for the VIAF bot (Toolforge / ToolsDB), ported from
-- schemas/viaf.sql (Firebird). Load with the mariadb client, which honours the
-- DELIMITER changes needed for the stored procedures (the DB handler's naive
-- ';'-split cannot create procedures):
--
--   mariadb --defaults-file=~/replica.my.cnf -h tools.db.svc.wikimedia.cloud \
--       sNNNNN__viaf < schemas/viaf_mariadb.sql
--
-- Firebird DOMAINs become inline types here:
--   QID, PID -> VARCHAR(16)   VIAF_ID -> VARCHAR(25)
--   AUTH_ID, MESSAGE -> VARCHAR(255)
-- Firebird `timestamp` -> DATETIME (not TIMESTAMP: DATETIME has no UTC shift and
-- no 2038 limit, so migrated values are stored exactly as-is).

-- Collation is pinned to utf8mb4_unicode_ci everywhere, on the database as well
-- as the tables. Stored-procedure parameters inherit the *database* collation,
-- while `CHARSET=utf8mb4` alone gives a table the charset's default collation
-- (utf8mb4_general_ci); if those differ, `WHERE QID = p_qid` inside a procedure
-- fails with error 1267 (illegal mix of collations). Procedures capture the
-- database collation when created, so re-create them after changing it.
ALTER DATABASE CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ======================= TABLES =======================

-- QIDs a VIAF id was added to during the current session.
CREATE TABLE IF NOT EXISTS ADDED (
  QID         VARCHAR(16) NOT NULL,
  ADDED_DATE  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (QID)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- QIDs that could not be processed; RETRY marks transient errors to try again.
CREATE TABLE IF NOT EXISTS ERRORS (
  QID         VARCHAR(16)  NOT NULL,
  MESSAGE     VARCHAR(255),
  ERROR_DATE  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  RETRY       BOOLEAN      NOT NULL DEFAULT FALSE,
  NOTE        VARCHAR(255),
  PRIMARY KEY (QID)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- QIDs to skip permanently.
CREATE TABLE IF NOT EXISTS IGNORED (
  QID VARCHAR(16) NOT NULL,
  PRIMARY KEY (QID)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- (item, authority source) pairs VIAF returned 'not_found' for, cached so they
-- are not re-queried for a while. Persists across sessions.
CREATE TABLE IF NOT EXISTS NOT_FOUND (
  QID           VARCHAR(16) NOT NULL,
  PID           VARCHAR(16) NOT NULL,
  CHECKED_DATE  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (QID, PID)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Items sharing a VIAF cluster with another item (reported, then cleared).
CREATE TABLE IF NOT EXISTS DUPLICATES (
  ID             INT          NOT NULL AUTO_INCREMENT,
  QID            VARCHAR(16),
  DUPLICATE_QID  VARCHAR(16),
  LOCAL_AUTH_ID  VARCHAR(255),
  VIAF_ID        VARCHAR(25),
  PRIMARY KEY (ID),
  UNIQUE KEY UQ_DUPLICATES (QID, DUPLICATE_QID, LOCAL_AUTH_ID, VIAF_ID)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Items whose VIAF cluster lists several local authority ids (reported, then cleared).
CREATE TABLE IF NOT EXISTS DUPLICATE_LOCAL_AUTH_IDS (
  ID             BIGINT       NOT NULL AUTO_INCREMENT,
  QID            VARCHAR(16),
  LOCAL_AUTH_ID  VARCHAR(255),
  VIAF_ID        VARCHAR(25),
  PRIMARY KEY (ID)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Authority-source config, read by an external report.
CREATE TABLE IF NOT EXISTS CODES (
  PID          VARCHAR(16)  NOT NULL,
  CODE         VARCHAR(25),
  DESCRIPTION  VARCHAR(100),
  DO_IGNORE    BOOLEAN      NOT NULL DEFAULT FALSE,
  IS_EMPTY     BOOLEAN      NOT NULL DEFAULT FALSE,
  SORT_ORDER   INT,  -- processing order; NULL = default (after prioritised)
  PRIMARY KEY (PID)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Per-session stats archive, read by an external report.
CREATE TABLE IF NOT EXISTS PDONE (
  ID         INT       NOT NULL AUTO_INCREMENT,
  PID        VARCHAR(16),
  CHECKED    INT,
  ADDED      INT,
  NOT_FOUND  INT,
  DONE_DATE  DATETIME  NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (ID)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ======================= INDEXES =======================

CREATE INDEX IDX_DUPLICATES_QID           ON DUPLICATES (QID);
CREATE INDEX IDX_DUPLICATES_DUPLICATE_QID ON DUPLICATES (DUPLICATE_QID);
CREATE INDEX IDX_DUPLICATE_LOCALS_QID     ON DUPLICATE_LOCAL_AUTH_IDS (QID);

-- ===================== PROCEDURES ======================
-- Parameters are renamed to p_* to avoid ambiguity with same-named columns
-- (callers use positional arguments, so the names don't matter to them).

DELIMITER $$

-- Record that a VIAF id was added to QID (and drop any earlier error for it).
CREATE OR REPLACE PROCEDURE ADD_DONE (IN p_qid VARCHAR(16))
BEGIN
  DELETE FROM ERRORS WHERE QID = p_qid;
  INSERT INTO ADDED (QID) VALUES (p_qid)
    ON DUPLICATE KEY UPDATE QID = QID;   -- keep existing ADDED_DATE
END$$

-- Record a processing error for QID.
CREATE OR REPLACE PROCEDURE ADD_ERROR (IN p_qid VARCHAR(16), IN p_message VARCHAR(255))
BEGIN
  DELETE FROM ADDED  WHERE QID = p_qid;
  DELETE FROM ERRORS WHERE QID = p_qid;
  INSERT INTO ERRORS (QID, MESSAGE) VALUES (p_qid, p_message);
END$$

-- Current-session counts for the wiki report: one row (CHECKED, ADDED, NOT_FOUND).
CREATE OR REPLACE PROCEDURE GET_STATS ()
BEGIN
  SELECT
    (SELECT COUNT(*) FROM ADDED) + (SELECT COUNT(*) FROM ERRORS)          AS CHECKED,
    (SELECT COUNT(*) FROM ADDED)                                          AS ADDED,
    (SELECT COUNT(*) FROM ERRORS WHERE MESSAGE LIKE '%status not_found%') AS NOT_FOUND;
END$$

-- Cache (or refresh) a 'not_found' result for QID under authority source PID.
CREATE OR REPLACE PROCEDURE ADD_NOT_FOUND (IN p_qid VARCHAR(16), IN p_pid VARCHAR(16))
BEGIN
  INSERT INTO NOT_FOUND (QID, PID, CHECKED_DATE)
    VALUES (p_qid, p_pid, CURRENT_TIMESTAMP)
    ON DUPLICATE KEY UPDATE CHECKED_DATE = CURRENT_TIMESTAMP;
END$$

-- Record that QID duplicates DUPLICATE_QID within a VIAF cluster (idempotent via
-- the UQ_DUPLICATES unique key).
CREATE OR REPLACE PROCEDURE ADD_DUPLICATE (
  IN p_qid           VARCHAR(16),
  IN p_duplicate_qid VARCHAR(16),
  IN p_local_auth_id VARCHAR(255),
  IN p_viaf_id       VARCHAR(25))
BEGIN
  INSERT INTO DUPLICATES (QID, DUPLICATE_QID, LOCAL_AUTH_ID, VIAF_ID)
    VALUES (p_qid, p_duplicate_qid, p_local_auth_id, p_viaf_id)
    ON DUPLICATE KEY UPDATE ID = ID;   -- no-op; the unique key dedups
END$$

-- Record a local authority id belonging to QID's VIAF cluster (dedup happens
-- later in CLEANUP_DUPLICATE_LOCAL_AUTH_IDS).
CREATE OR REPLACE PROCEDURE ADD_DUPLICATE_LOCAL_AUTH_ID (
  IN p_qid           VARCHAR(16),
  IN p_local_auth_id VARCHAR(255),
  IN p_viaf_id       VARCHAR(25))
BEGIN
  INSERT INTO DUPLICATE_LOCAL_AUTH_IDS (QID, LOCAL_AUTH_ID, VIAF_ID)
    VALUES (p_qid, p_local_auth_id, p_viaf_id);
END$$

-- Mark transient errors so they get retried on the next run.
CREATE OR REPLACE PROCEDURE CLEAN_UP ()
BEGIN
  UPDATE ERRORS SET RETRY = TRUE
    WHERE RETRY = FALSE
      AND (MESSAGE LIKE '%connection%' OR MESSAGE LIKE '%object is not iterable%');
END$$

-- Normalize and de-duplicate the duplicate-local-auth-id report.
CREATE OR REPLACE PROCEDURE CLEANUP_DUPLICATE_LOCAL_AUTH_IDS ()
BEGIN
  UPDATE DUPLICATE_LOCAL_AUTH_IDS
    SET LOCAL_AUTH_ID = REPLACE(LOCAL_AUTH_ID, 'http://d-nb.info/gnd/', '')
    WHERE LOCAL_AUTH_ID LIKE 'http://d-nb.info/gnd/%';

  -- keep the lowest-ID row of each (QID, LOCAL_AUTH_ID, VIAF_ID) group
  DELETE d1 FROM DUPLICATE_LOCAL_AUTH_IDS d1
    JOIN DUPLICATE_LOCAL_AUTH_IDS d2
      ON d1.QID = d2.QID
     AND d1.LOCAL_AUTH_ID = d2.LOCAL_AUTH_ID
     AND d1.VIAF_ID = d2.VIAF_ID
     AND d1.ID > d2.ID;
END$$

-- Archive this session's stats to PDONE, then empty the per-session tables.
CREATE OR REPLACE PROCEDURE END_SESSION (IN p_pid VARCHAR(16))
BEGIN
  DECLARE v_checked   INT;
  DECLARE v_added     INT;
  DECLARE v_not_found INT;

  SELECT
    (SELECT COUNT(*) FROM ADDED) + (SELECT COUNT(*) FROM ERRORS),
    (SELECT COUNT(*) FROM ADDED),
    (SELECT COUNT(*) FROM ERRORS WHERE MESSAGE LIKE '%status not_found%')
  INTO v_checked, v_added, v_not_found;

  INSERT INTO PDONE (PID, CHECKED, ADDED, NOT_FOUND)
    VALUES (p_pid, v_checked, v_added, v_not_found);

  DELETE FROM ADDED;
  DELETE FROM DUPLICATES;
  DELETE FROM DUPLICATE_LOCAL_AUTH_IDS;
  DELETE FROM ERRORS;
END$$

DELIMITER ;
