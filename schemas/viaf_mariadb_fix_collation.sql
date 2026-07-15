-- One-time collation fix for an existing VIAF database on ToolsDB.
--
-- Symptom: the bot dies with
--   (1267, "Illegal mix of collations (utf8mb4_general_ci,IMPLICIT) and
--           (utf8mb4_unicode_ci,IMPLICIT) for operation '='")
-- Cause: the tables were created with `DEFAULT CHARSET=utf8mb4` and no COLLATE,
-- so they got utf8mb4_general_ci (the charset default), while stored-procedure
-- parameters inherit the database collation (utf8mb4_unicode_ci). Comparing
-- them inside a procedure (`WHERE QID = p_qid`) is then illegal.
--
-- This converges everything on utf8mb4_unicode_ci. Same charset in and out, so
-- the stored bytes do not change - only comparison rules do.
--
--   mariadb --defaults-file=~/replica.my.cnf -h tools.db.svc.wikimedia.cloud \
--       sNNNNN__viaf < schemas/viaf_mariadb_fix_collation.sql
--
-- Then re-run schemas/viaf_mariadb.sql to re-create the procedures: they capture
-- the database collation at creation time, so they must be replaced afterwards.
-- (Its CREATE TABLE statements are IF NOT EXISTS, so existing data is kept.)

ALTER DATABASE CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

ALTER TABLE ADDED                    CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE ERRORS                   CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE IGNORED                  CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE NOT_FOUND                CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE DUPLICATES               CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE DUPLICATE_LOCAL_AUTH_IDS CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE CODES                    CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE PDONE                    CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
