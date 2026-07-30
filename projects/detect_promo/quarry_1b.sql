-- Standalone, ready-to-run version. Paste the whole file into a fresh Quarry
-- query (https://quarry.wmcloud.org).
--
-- COARSE candidate filter for autoconfirmed-farming, over RECENT activity only.
--
-- Why recentchanges and not revision: revision is ~2.4 BILLION rows with no
-- index on user_registration, so any "recent accounts" scan degenerates into a
-- full table scan Quarry will not finish. recentchanges holds only ~30 days and
-- is indexed by timestamp, so it is cheap. Trade-off: finds accounts ACTIVE in
-- the last ~30 days, not historical ones -- which is what you want for ongoing
-- detection anyway.
--
-- Only columns known to exist on the sanitized replica view are used
-- (rc_timestamp, rc_actor, rc_comment_id). rc_type / rc_bot are NOT exposed, so
-- they are omitted -- the "/* wbsetdescription" comment filter already restricts
-- to description edits, and flagged bots that slip in are obvious by name and
-- get dropped by the Python farming check (they are not new accounts).
--
-- This is only the coarse filter. The precise checks -- is the account NEW and
-- front-loaded (farming), and did it create a payload -- are per candidate via
-- detect_promo_accounts.py --user <name>. Expect legit description-gnomes here.
--
-- Database: wikidatawiki_p.

USE wikidatawiki_p;

SELECT a.actor_name,
       COUNT(*)                                                  AS activity,
       SUM(c.comment_text LIKE '/* wbsetdescription%')           AS desc_edits,
       ROUND(AVG(c.comment_text LIKE '/* wbsetdescription%'), 2) AS desc_frac,
       MIN(rc.rc_timestamp)                                      AS first_seen,
       MAX(rc.rc_timestamp)                                      AS last_seen
FROM recentchanges rc
JOIN actor   a ON a.actor_id   = rc.rc_actor
JOIN comment c ON c.comment_id = rc.rc_comment_id
WHERE rc.rc_timestamp >
      DATE_FORMAT(DATE_SUB(NOW(), INTERVAL 30 DAY), '%Y%m%d%H%i%s')
  AND a.actor_user IS NOT NULL   -- registered users only
GROUP BY a.actor_id, a.actor_name
HAVING desc_edits >= 50
   AND desc_frac >= 0.7
ORDER BY desc_frac DESC, desc_edits DESC
LIMIT 200;
