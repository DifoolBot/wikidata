/********************* COLLATES **********************/

/********************* ROLES **********************/

/********************* UDFS ***********************/

/********************* FUNCTIONS ***********************/

/****************** SEQUENCES ********************/

/******************** DOMAINS *********************/

CREATE DOMAIN BOOL_FALSE
 AS boolean
 DEFAULT False
 NOT NULL
;
CREATE DOMAIN BOOL_TRUE
 AS boolean
 DEFAULT True
 NOT NULL
;
CREATE DOMAIN INTCODE
 AS integer
;
CREATE DOMAIN QID
 AS varchar(15) CHARACTER SET ASCII
 COLLATE ASCII;
CREATE DOMAIN TEXT255
 AS varchar(255)
 COLLATE UTF8;
/******************* PROCEDURES ******************/

SET TERM ^ ;
CREATE PROCEDURE ADD_DONE (
    QID QID,
    MSG TEXT255 )
SQL SECURITY DEFINER
AS 
BEGIN 
END^
SET TERM ; ^

SET TERM ^ ;
CREATE PROCEDURE ADD_ERROR (
    QID QID,
    ERROR TEXT255 )
SQL SECURITY DEFINER
AS 
BEGIN 
END^
SET TERM ; ^

/******************* PACKAGES ******************/

/******************** TABLES **********************/

CREATE TABLE DONE
(
  QID QID NOT NULL,
  MSG TEXT255,
  DONE_DATE timestamp,
  RETRY BOOL_FALSE,
  NOTE TEXT255,
  CONSTRAINT PK_DONE PRIMARY KEY (QID)
);
CREATE TABLE ERRORS
(
  QID QID NOT NULL,
  ERROR TEXT255,
  ERROR_DATE timestamp,
  RETRY BOOL_FALSE,
  NOTE TEXT255,
  CONSTRAINT PK_ERRORS PRIMARY KEY (QID)
);
CREATE TABLE TODO
(
  ID INTCODE NOT NULL,
  QID QID NOT NULL,
  CONSTRAINT PK_TODO PRIMARY KEY (ID)
);
/********************* VIEWS **********************/

/******************* EXCEPTIONS *******************/

/******************** TRIGGERS ********************/

/******************** DB TRIGGERS ********************/

/******************** DDL TRIGGERS ********************/


SET TERM ^ ;
ALTER PROCEDURE ADD_DONE (
    QID QID,
    MSG TEXT255 )
SQL SECURITY DEFINER

AS
BEGIN
  delete from todo where qid = :qid;
  delete from done where qid = :qid;
  delete from errors where qid = :qid;
  insert into done (qid,msg) values (:qid,:msg);
 
END
^
SET TERM ; ^


SET TERM ^ ;
ALTER PROCEDURE ADD_ERROR (
    QID QID,
    ERROR TEXT255 )
SQL SECURITY DEFINER

AS
BEGIN
  delete from done where qid = :qid;
  delete from errors where qid = :qid;
  insert into errors (qid,error) values (:qid,:error);
 
END
^
SET TERM ; ^


GRANT EXECUTE
 ON PROCEDURE ADD_DONE TO  SYSDBA WITH GRANT OPTION GRANTED BY SYSDBA                                                                                                                                                                                                                                                      ;

GRANT EXECUTE
 ON PROCEDURE ADD_ERROR TO  SYSDBA WITH GRANT OPTION GRANTED BY SYSDBA                                                                                                                                                                                                                                                      ;

GRANT DELETE, INSERT, REFERENCES, SELECT, UPDATE
 ON DONE TO  SYSDBA WITH GRANT OPTION GRANTED BY SYSDBA;

GRANT DELETE, INSERT, REFERENCES, SELECT, UPDATE
 ON ERRORS TO  SYSDBA WITH GRANT OPTION GRANTED BY SYSDBA;

GRANT DELETE, INSERT, REFERENCES, SELECT, UPDATE
 ON TODO TO  SYSDBA WITH GRANT OPTION GRANTED BY SYSDBA;

