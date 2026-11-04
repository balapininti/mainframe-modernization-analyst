"""Reduce a statement to its shape: mainframe keywords stay, names and values do not."""
import re

MAX_LENGTH = 300
PLACEHOLDERS = {"<ID>", "<NUM>", "<LIT>"}
KEYWORDS = set("""
ACCEPT ADD ALTER AND ASSIGN AT BY CALL CANCEL CLOSE COMMIT COMPUTE CONTINUE COPY CURSOR DATA DECLARE DELETE DISPLAY
DIVIDE DIVISION ELSE END-EXEC ENTRY EVALUATE EXEC EXIT FETCH FILE FOR FROM GO GOBACK IF INCLUDE INITIALIZE INSPECT
INTO INVOKE IS MERGE MOVE MULTIPLY NOT OF OPEN OR PERFORM PIC PROCEDURE READ RELEASE REPLACING RETURN REWRITE
ROLLBACK SEARCH SECTION SELECT SET SORT START STOP STRING SUBTRACT THRU TO UNSTRING UPDATE USING VALUE VALUES WHEN
WHERE WITH WRITE INSERT JOIN CREATE TABLE VIEW GRANT LOCK SAVEPOINT CONNECT HOLD
CICS SQL SQLIMS DLI GU GN GNP GHU GHN GHNP ISRT DLET REPL CHKP XRST SCHD TERM PCB PSB SEGMENT WHERE FIELD KEYS
LINK XCTL LOAD SEND RECEIVE MAP MAPSET PROGRAM TRANSID COMMAREA LENGTH RESP RESP2 RIDFLD GTEQ EQUAL QUEUE QNAME
WRITEQ READQ DELETEQ TS TD SYNCPOINT ENQ DEQ ABEND HANDLE CONDITION AID IGNORE ASKTIME FORMATTIME WEB DOCUMENT
JSON XML TRANSFORM CONTAINER CHANNEL PUT GET INQUIRE BIF DEEDIT
JOB PROC PEND DD PGM DSN DISP COND PARM SYSIN SYSOUT IF THEN ENDIF JCLLIB OUTPUT CNTL ENDCNTL COMMAND XMIT
CSECT DSECT USING MACRO MEND PSBGEN DBDGEN DATASET INPUT
""".split())
_TOKEN = re.compile(r"""'[^']*'?|"[^"]*"?|[A-Za-z0-9#@$_-]+|[^\sA-Za-z0-9#@$_-]""")
_ALLOWED_SYMBOLS = set("()=,.:*+-/<>&%;")


def mask_statement(text):
    tokens = []
    for token in _TOKEN.findall(text):
        if token[0] in "'\"":
            tokens.append("<LIT>")
        elif token.isdigit():
            tokens.append("<NUM>")
        elif token.upper() in KEYWORDS:
            tokens.append(token.upper())
        elif re.match(r"[A-Za-z0-9#@$_-]", token):
            tokens.append("<ID>")
        elif token in _ALLOWED_SYMBOLS:
            tokens.append(token)
    masked = " ".join(tokens)
    if len(masked) > MAX_LENGTH:
        masked = masked[:MAX_LENGTH].rsplit(" ", 1)[0]
    return masked


def is_masked(text):
    if not isinstance(text, str) or len(text) > MAX_LENGTH:
        return False
    return all(
        token in KEYWORDS or token in PLACEHOLDERS or token in _ALLOWED_SYMBOLS
        for token in text.split()
    )
