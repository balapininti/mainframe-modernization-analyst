# Mainframe glossary for Java developers

| Term | What it is | Rough Java or Spring equivalent |
|------|------------|--------------------------------|
| 88-level | A named value or condition on a field | Enum constant or boolean method |
| Abend | An abnormal end of a program | Uncaught exception that stops the process |
| BMS | Basic Mapping Support: defines 3270 screens | HTML template or view definition |
| Batch window | The time when overnight jobs must finish | Scheduling constraint or SLA |
| CICS | The online transaction manager | Application server and transaction manager |
| COBOL paragraph | A named block of statements | Method, but execution can fall through to the next one |
| COMMAREA | Memory passed between CICS programs and screens | Request DTO or session state |
| COMP-3 | Packed decimal storage | `BigDecimal` in Java |
| Copybook | A shared source fragment, usually a record layout | Shared DTO or included class |
| CSD | The CICS system definition | Deployment and routing configuration |
| Data set (DSN) | A mainframe file | File or table |
| DB2 | IBM's relational database | Any relational database |
| DCLGEN | A generated table layout for DB2 | Generated entity class |
| DD statement | Connects a logical file in a program to a real dataset | Externalized file configuration |
| EBCDIC | The mainframe character encoding | A different charset, and a different sort order |
| GDG | Generation data group: versioned files | Dated files with retention |
| IDCAMS | A utility that manages VSAM files | Admin scripts for files or tables |
| IMS | IBM's hierarchical database and transaction manager | No direct equivalent |
| JCL | Job Control Language: defines batch jobs and steps | Spring Batch job definition plus shell |
| KSDS | A VSAM file with a key | Table with a primary key |
| Level number | Nesting in a COBOL record (01, 05, 10) | Nested class fields |
| LINK | CICS call that returns | Method call |
| PIC | Picture clause: a field's type and size | Type and length |
| PROC | A reusable JCL procedure | Reusable job template |
| Pseudo-conversational | The task ends between screens | Stateless request handling |
| REDEFINES | A second layout over the same bytes | A C union. Java has no equivalent |
| Return code (RC) | A step's result: 0 is good, 4 a warning, 8 or more an error | Exit status |
| SQLCODE | The DB2 result code: 0 is good, 100 is not found, other positive values are warnings, negative is an error | SQL exceptions and empty results |
| Syncpoint | A commit point in CICS | Transaction commit |
| Transaction ID | A short code that starts a CICS program | URL route |
| TSQ, TDQ | CICS temporary storage and transient data queues | Cache or message queue |
| VSAM | Keyed and sequential file storage | Key-value store or table |
| XCTL | CICS transfer that doesn't return | Forward or redirect |
