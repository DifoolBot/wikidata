-- Firebird schema for the clean_youtube tracker (projects/clean_youtube).
-- Referenced as the create script by ChannelHandleTracker; the config JSON
-- (projects/clean_youtube/channel_handles.json) points at the database file.

/******************** DOMAINS *********************/

CREATE DOMAIN CHANNEL_ID
 AS varchar(64)
 COLLATE UTF8;
CREATE DOMAIN D_TIMESTAMP
 AS timestamp
 DEFAULT current_timestamp;
CREATE DOMAIN HANDLE
 AS varchar(255)
 COLLATE UTF8;
CREATE DOMAIN MSG255
 AS varchar(255)
 COLLATE UTF8;
CREATE DOMAIN QID
 AS varchar(20)
 COLLATE UTF8;
CREATE DOMAIN STATUS
 AS varchar(16)
 COLLATE UTF8;

/******************** TABLES **********************/

-- channelId -> @handle lookups, cached across runs (status: found/not_found/error)
CREATE TABLE CHANNEL_HANDLES
(
  CHANNEL_ID CHANNEL_ID NOT NULL,
  HANDLE HANDLE,
  STATUS STATUS NOT NULL,
  CREATED_AT D_TIMESTAMP,
  CONSTRAINT PK_CHANNEL_HANDLES PRIMARY KEY (CHANNEL_ID)
);

-- handle-or-channelId -> publisher item on Wikidata (status: found/not_found/error)
CREATE TABLE CHANNEL_PUBLISHERS
(
  CHANNEL_KEY HANDLE NOT NULL,
  PUBLISHER_QID QID,
  STATUS STATUS NOT NULL,
  CREATED_AT D_TIMESTAMP,
  CONSTRAINT PK_CHANNEL_PUBLISHERS PRIMARY KEY (CHANNEL_KEY)
);

-- per-item processing status (status: success/failed)
CREATE TABLE QIDS
(
  QID QID NOT NULL,
  STATUS STATUS,
  ERROR_MSG MSG255,
  SUMMARY MSG255,
  CREATED_AT D_TIMESTAMP,
  CONSTRAINT PK_QIDS PRIMARY KEY (QID)
);

/******************* PROCEDURES ******************/

SET TERM ^ ;

-- Reclassify known-harmless failures so they are not retried.
CREATE PROCEDURE CORRECTIONS
AS
BEGIN
  UPDATE QIDS SET STATUS = 'success'
  WHERE STATUS = 'failed'
    AND ERROR_MSG = 'No YouTube URLs found';
END^

-- Failed QIDs grouped by error category, for building retry lists:
--   private   - video reported private/deleted by the API
--   audio     - missing audio language in the API response
--   publisher - existing publisher qualifier differs from the fetched one
--   extract   - unparsable YouTube URL (excluding the specific kinds below)
--   playlist  - unparsable /playlist? URL
--   live      - unparsable /live/ URL
--   post      - unparsable /post/ URL
CREATE PROCEDURE GET_LIST (
    CODE varchar(10) )
RETURNS (
    QID QID )
AS
BEGIN
  IF (CODE = 'private') THEN
    FOR SELECT QID FROM QIDS
        WHERE STATUS = 'failed' AND ERROR_MSG CONTAINING 'private/deleted'
        ORDER BY 1 INTO :QID
    DO SUSPEND;

  IF (CODE = 'audio') THEN
    FOR SELECT QID FROM QIDS
        WHERE STATUS = 'failed' AND ERROR_MSG CONTAINING 'missing audio language'
        ORDER BY 1 INTO :QID
    DO SUSPEND;

  IF (CODE = 'publisher') THEN
    FOR SELECT QID FROM QIDS
        WHERE STATUS = 'failed' AND ERROR_MSG CONTAINING 'existing publisher'
        ORDER BY 1 INTO :QID
    DO SUSPEND;

  IF (CODE = 'extract') THEN
    FOR SELECT QID FROM QIDS
        WHERE STATUS = 'failed' AND ERROR_MSG CONTAINING 'could not extract'
          AND NOT ERROR_MSG CONTAINING '/live/'
          AND NOT ERROR_MSG CONTAINING '/post/'
          AND NOT ERROR_MSG CONTAINING '/playlist?'
          AND NOT ERROR_MSG CONTAINING '/playables/'
        ORDER BY 1 INTO :QID
    DO SUSPEND;

  IF (CODE = 'playlist') THEN
    FOR SELECT QID FROM QIDS
        WHERE STATUS = 'failed' AND ERROR_MSG CONTAINING 'could not extract'
          AND ERROR_MSG CONTAINING '/playlist?'
        ORDER BY 1 INTO :QID
    DO SUSPEND;

  IF (CODE = 'live') THEN
    FOR SELECT QID FROM QIDS
        WHERE STATUS = 'failed' AND ERROR_MSG CONTAINING 'could not extract'
          AND ERROR_MSG CONTAINING '/live/'
        ORDER BY 1 INTO :QID
    DO SUSPEND;

  IF (CODE = 'post') THEN
    FOR SELECT QID FROM QIDS
        WHERE STATUS = 'failed' AND ERROR_MSG CONTAINING 'could not extract'
          AND ERROR_MSG CONTAINING '/post/'
        ORDER BY 1 INTO :QID
    DO SUSPEND;
END^

SET TERM ; ^
