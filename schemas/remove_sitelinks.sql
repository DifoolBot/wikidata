/********************* COLLATES **********************/

/********************* ROLES **********************/

/********************* UDFS ***********************/

/********************* FUNCTIONS ***********************/

/****************** SEQUENCES ********************/

/******************** DOMAINS *********************/

CREATE DOMAIN D_TIMESTAMP
 AS timestamp
 DEFAULT current_timestamp
;
CREATE DOMAIN ERROR_MSG
 AS varchar(255)
 COLLATE UTF8;
CREATE DOMAIN QID
 AS varchar(20)
 COLLATE UTF8;
CREATE DOMAIN STATUS
 AS varchar(20)
 COLLATE UTF8;
/******************* PROCEDURES ******************/

SET TERM ^ ;
CREATE PROCEDURE CLEAN_UP
SQL SECURITY DEFINER
AS 
BEGIN 
END^
SET TERM ; ^

SET TERM ^ ;
CREATE PROCEDURE GET_ERROR_STATS
RETURNS (
    ERROR_TYPE varchar(50),
    ACOUNT integer )
SQL SECURITY DEFINER
AS 
BEGIN SUSPEND; 
END^
SET TERM ; ^

SET TERM ^ ;
CREATE PROCEDURE GET_ERROR_TYPE (
    ERROR_MSG ERROR_MSG )
RETURNS (
    ERROR_TYPE varchar(50) )
SQL SECURITY DEFINER
AS 
BEGIN SUSPEND; 
END^
SET TERM ; ^

SET TERM ^ ;
CREATE PROCEDURE GET_TOTAL_STATS
RETURNS (
    STATUS varchar(20),
    NR integer,
    PCT numeric(5,2) )
SQL SECURITY DEFINER
AS 
BEGIN SUSPEND; 
END^
SET TERM ; ^

/******************* PACKAGES ******************/

/******************** TABLES **********************/

CREATE TABLE QIDS
(
  QID QID NOT NULL,
  STATUS STATUS,
  ERROR_MSG ERROR_MSG,
  SUMMARY ERROR_MSG,
  CREATED_AT D_TIMESTAMP,
  CONSTRAINT INTEG_2 PRIMARY KEY (QID)
);
CREATE TABLE WIKIMEDIA_CATS
(
  QID QID NOT NULL,
  IS_WIKIMEDIA_CAT boolean NOT NULL,
  CONSTRAINT INTEG_5 PRIMARY KEY (QID)
);
/********************* VIEWS **********************/

/******************* EXCEPTIONS *******************/

/******************** TRIGGERS ********************/

/******************** DB TRIGGERS ********************/

/******************** DDL TRIGGERS ********************/


SET TERM ^ ;
ALTER PROCEDURE CLEAN_UP
SQL SECURITY DEFINER

AS
BEGIN
  delete
FROM QIDS r where 
  (error_msg containing 'Edit to page [[wikidata:Q' and error_msg containing ']] failed:') or
  (error_msg = 'Maximum retries attempted due to maxlag without success.');
END
^
SET TERM ; ^


SET TERM ^ ;
ALTER PROCEDURE GET_ERROR_STATS
RETURNS (
    ERROR_TYPE varchar(50),
    ACOUNT integer )
SQL SECURITY DEFINER

AS
BEGIN
  for
  SELECT x.ERROR_TYPE,count(*)
FROM QIDS r
left join GET_ERROR_TYPE(r.ERROR_MSG) x on true 
where r.status = 'failed'
group by 1 order by 2 desc
  into :error_type,:acount do
  begin
    suspend;
  end  

END
^
SET TERM ; ^


SET TERM ^ ;
ALTER PROCEDURE GET_ERROR_TYPE (
    ERROR_MSG ERROR_MSG )
RETURNS (
    ERROR_TYPE varchar(50) )
SQL SECURITY DEFINER

AS
BEGIN
    IF (ERROR_MSG CONTAINING 'status: MOVED_TO_DRAFT') THEN
      ERROR_TYPE = 'MOVED_TO_DRAFT';
    ELSE IF (ERROR_MSG CONTAINING 'status: EXISTS') THEN
      ERROR_TYPE = 'EXISTS';
    ELSE IF (ERROR_MSG CONTAINING 'status: REDIRECT') THEN
      ERROR_TYPE = 'REDIRECT';
    ELSE IF (ERROR_MSG CONTAINING 'status: NEVER_EXISTED') THEN
      ERROR_TYPE = 'NEVER_EXISTED';
    ELSE IF (ERROR_MSG CONTAINING 'status: RESTORED') THEN
      ERROR_TYPE = 'RESTORED';
    ELSE IF (ERROR_MSG CONTAINING 'Unrecognized wikimedia import URL') THEN
      ERROR_TYPE = 'Unrecognized';
    ELSE IF (ERROR_MSG CONTAINING 'Unrecognized Wikipedia URL format') THEN
      ERROR_TYPE = 'Unrecognized';
    ELSE IF (ERROR_MSG CONTAINING 'Unrecognized URL format') THEN
      ERROR_TYPE = 'Unrecognized';
    ELSE IF (ERROR_MSG CONTAINING 'Multiple distinct titles found in sources') THEN
      ERROR_TYPE = 'Multiple titles';
    ELSE IF (ERROR_MSG CONTAINING 'Multiple languages detected in one source') THEN
      ERROR_TYPE = 'Multiple lang';
    ELSE IF (ERROR_MSG CONTAINING ']] is a redirect page') THEN
      ERROR_TYPE = 'WD: Redirect';
    ELSE IF (ERROR_MSG CONTAINING ']] doesn''t exist') THEN
      ERROR_TYPE = 'WD: Does not exists';
    ELSE
      ERROR_TYPE = 'Other';

    SUSPEND;
END
^
SET TERM ; ^


SET TERM ^ ;
ALTER PROCEDURE GET_TOTAL_STATS
RETURNS (
    STATUS varchar(20),
    NR integer,
    PCT numeric(5,2) )
SQL SECURITY DEFINER

AS
BEGIN
 for SELECT 
  CASE 
    WHEN r.status = 'success' AND r.summary = 'Nothing done' THEN 'Nothing'
    WHEN r.status = 'success'                                THEN 'Success'
    ELSE 'Failed'
  END AS status,
  COUNT(*) AS nr,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct
FROM QIDS r
GROUP BY 1

union

select 'All' as status, (select count(*) from qids) as nr, 100 as pct from rdb$database into
:status,:nr,:pct do
begin
  suspend;
end
END
^
SET TERM ; ^


GRANT EXECUTE
 ON PROCEDURE CLEAN_UP TO  SYSDBA WITH GRANT OPTION GRANTED BY SYSDBA                                                                                                                                                                                                                                                      ;

GRANT EXECUTE
 ON PROCEDURE GET_ERROR_STATS TO  SYSDBA WITH GRANT OPTION GRANTED BY SYSDBA                                                                                                                                                                                                                                                      ;

GRANT EXECUTE
 ON PROCEDURE GET_ERROR_TYPE TO  SYSDBA WITH GRANT OPTION GRANTED BY SYSDBA                                                                                                                                                                                                                                                      ;

GRANT EXECUTE
 ON PROCEDURE GET_TOTAL_STATS TO  SYSDBA WITH GRANT OPTION GRANTED BY SYSDBA                                                                                                                                                                                                                                                      ;

GRANT DELETE, INSERT, REFERENCES, SELECT, UPDATE
 ON QIDS TO  SYSDBA WITH GRANT OPTION GRANTED BY SYSDBA;

GRANT DELETE, INSERT, REFERENCES, SELECT, UPDATE
 ON WIKIMEDIA_CATS TO  SYSDBA WITH GRANT OPTION GRANTED BY SYSDBA;

