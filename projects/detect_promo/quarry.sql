-- Bulk companion to detect_promo_accounts.py, to run on Quarry
-- (https://quarry.wmcloud.org) against the wikidatawiki_p replica. The Python
-- pass is per-account via the API; this finds the warm-up fingerprint across
-- ALL recent accounts at once, which is what you need for network detection.
--
-- UNTESTED against the replica from here -- verify column names on Quarry
-- (schema: revision -> actor via rev_actor; revision -> comment via
-- rev_comment_id). Narrow the window if it runs long.
--
-- Database is wikidatawiki_p (the sanitized public replica; note the _p suffix).

USE wikidatawiki_p;

-- 1) Warm-up accounts: recent editors whose edits are dominated by the
--    "Added missing description" boilerplate. Many accounts sharing this
--    fingerprint = one operator / a network.
SELECT actor_name,
       COUNT(*)                                                       AS total_edits,
       SUM(comment_text LIKE '%Added missing description%')          AS boilerplate_edits,
       ROUND(AVG(comment_text LIKE '%Added missing description%'), 2) AS boilerplate_frac,
       MIN(rev_timestamp)                                            AS first_edit,
       MAX(rev_timestamp)                                            AS last_edit
FROM revision
JOIN actor   ON actor_id   = rev_actor
JOIN comment ON comment_id = rev_comment_id
WHERE rev_timestamp > DATE_FORMAT(DATE_SUB(NOW(), INTERVAL 30 DAY), '%Y%m%d%H%i%s')
  AND actor_user IS NOT NULL           -- registered only
GROUP BY actor_name
HAVING total_edits >= 20
   AND boilerplate_frac >= 0.5
ORDER BY boilerplate_frac DESC, total_edits DESC
LIMIT 200;

-- 1b) Phrase-AGNOSTIC farming scan. Query (1) keys on the operator-chosen phrase
--     "Added missing description", so it only finds accounts that reuse it (in
--     testing: just Johnpacklamber1). This instead keys on the software's
--     structured auto-comment ("/* wbsetdescription...", present on every
--     description edit in any language) plus the farming SHAPE: a newly-
--     registered account whose first ~50 edits are description-heavy and burned
--     inside the 4-day autoconfirmed window. Finds siblings that phrase
--     differently. Bounded to recently-registered users to stay tractable.
--     NOTE: will also surface legitimate new description-gnomes -- treat the
--     output as candidates to feed the Python scorer's warmup+payload
--     conjunction, not a verdict. Needs MariaDB window functions (Quarry has them).
-- WITH new_users AS (
--   SELECT actor_id, actor_name
--   FROM actor
--   JOIN `user` ON user_id = actor_user
--   WHERE user_registration > DATE_FORMAT(DATE_SUB(NOW(), INTERVAL 120 DAY), '%Y%m%d%H%i%s')
-- ),
-- ranked AS (
--   SELECT r.rev_actor, r.rev_timestamp,
--          (c.comment_text LIKE '/* wbsetdescription%') AS is_desc,
--          ROW_NUMBER() OVER (PARTITION BY r.rev_actor ORDER BY r.rev_timestamp) AS rn
--   FROM revision r
--   JOIN new_users nu ON nu.actor_id = r.rev_actor
--   JOIN comment  c  ON c.comment_id = r.rev_comment_id
-- )
-- SELECT nu.actor_name,
--        COUNT(*)               AS first_n,
--        ROUND(AVG(is_desc), 2) AS desc_frac,
--        MIN(r.rev_timestamp)   AS first_edit,
--        MAX(r.rev_timestamp)   AS n50_edit,
--        TIMESTAMPDIFF(HOUR, MIN(r.rev_timestamp), MAX(r.rev_timestamp)) / 24.0 AS span_days
-- FROM ranked r
-- JOIN new_users nu ON nu.actor_id = r.rev_actor
-- WHERE r.rn <= 50
-- GROUP BY nu.actor_name
-- HAVING first_n >= 50 AND desc_frac >= 0.7 AND span_days <= 5
-- ORDER BY desc_frac DESC
-- LIMIT 200;

-- 3) PIPELINE query for "examine the last 24h" -> feed detect_promo_accounts.py
--    --users-file. Returns the DISTINCT creators of new ns0 items in the window,
--    which the live-API path cannot cover (it truncates newest-first at --limit;
--    24h is ~15k new items). Restricted to recently-registered accounts because
--    the promo profile we saw scores on PAYLOAD alone with warmup=0 (fresh
--    single-purpose accounts) -- the veteran warm-up pattern is covered by (1)/(1b).
--    Run this one ALONE on Quarry (comment the others out), download the result as
--    CSV, delete the "actor_name" header row, save as input/candidates.txt, then:
--        python projects/detect_promo/detect_promo_accounts.py \
--            --users-file projects/detect_promo/input/candidates.txt
--    To sweep ALL creators (established editors too, much larger, slower Python
--    pass), drop the user_registration line.
SELECT DISTINCT actor_name
FROM revision
JOIN page   ON page_id  = rev_page
JOIN actor  ON actor_id = rev_actor
JOIN `user` ON user_id  = actor_user
WHERE rev_parent_id = 0                 -- first revision = page creation
  AND page_namespace = 0               -- items only
  AND actor_user IS NOT NULL           -- registered only
  AND rev_timestamp     > DATE_FORMAT(DATE_SUB(NOW(), INTERVAL 24  HOUR), '%Y%m%d%H%i%s')
  AND user_registration > DATE_FORMAT(DATE_SUB(NOW(), INTERVAL 120 DAY),  '%Y%m%d%H%i%s')
ORDER BY actor_name;

-- 2) New-item creations by registered users in the window (payload candidates).
--    Cross-reference the creators here against query (1): a creator that also
--    appears as a warm-up account is the warm-up+payload conjunction.
--    (rev_parent_id = 0 marks a page's first revision = creation.)
-- SELECT p.page_title AS qid, actor_name, rev_timestamp, rev_len
-- FROM revision
-- JOIN page  ON page_id  = rev_page
-- JOIN actor ON actor_id = rev_actor
-- WHERE rev_parent_id = 0
--   AND page_namespace = 0
--   AND actor_user IS NOT NULL
--   AND rev_timestamp > DATE_FORMAT(DATE_SUB(NOW(), INTERVAL 3 DAY), '%Y%m%d%H%i%s')
-- ORDER BY rev_timestamp DESC
-- LIMIT 500;
