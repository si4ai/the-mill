---- MODULE Mail ----
\* Card 925 (mail slice): code-against-spec for mail delivery and recovery
\* guards at SYNC (see run.sh). Prioritises fail-loud size limits, no orphan
\* letters, and the open/receipt guards verify/spin/mail.pml assumes in the
\* real SQL. Every action cites path:lines. Guards are CONSTANTS for mutants.
\*
\* Not a concurrency model (that is verify/spin/mail.pml) and not the notice
\* cut suite (tests/server/test_mail_notice_cut_584.py). This asks: do the
\* real control-flow guards still implement the transitions those assume?
\*
\* Code at SYNC:
\*   agent_coord/server/api/mill/rpc.py
\*     _h_send body refuse (1557-1558), receipt=0 (1562-1563),
\*     _h_reply body refuse (1914-1915)
\*   agent_coord/server/sql/sp_mail.sql
\*     mill_mail_insert (235-286), orphan refuse (281-283)
\*   agent_coord/server/sql/sp_opened.sql
\*     mill_mail_open FOR UPDATE (29-31), first-open UPDATE (34-36),
\*     push_receipt (41)

EXTENDS Naturals

CONSTANTS
  MaxSteps,
  GuardBodyRefuse,       \* rpc: len(body) > 4096 raises CoordError
  GuardNoOrphan,         \* mill_mail_insert: empty mail_to SIGNALs
  GuardOpenLocked,       \* mill_mail_open: SELECT ... FOR UPDATE before stamp
  GuardFirstOpenOnly,    \* UPDATE ... AND opened IS NULL (first stamp kept)
  GuardOneReceipt,       \* push_receipt only when v_prev IS NULL and receipt set
  GuardRollbackOnError   \* mill_mail_insert EXIT HANDLER ROLLBACK (letter 4262)

ASSUME MaxSteps \in Nat /\ MaxSteps >= 1
ASSUME GuardBodyRefuse \in BOOLEAN
ASSUME GuardNoOrphan \in BOOLEAN
ASSUME GuardOpenLocked \in BOOLEAN
ASSUME GuardFirstOpenOnly \in BOOLEAN
ASSUME GuardOneReceipt \in BOOLEAN
ASSUME GuardRollbackOnError \in BOOLEAN

VARIABLES
  bodyLen,        \* proposed body length (chars)
  letterLive,     \* mail row exists
  recipient,      \* mail_to row exists for the desk
  opened,         \* 0 = NULL, 1 = first stamp, 2 = overwritten (mutant)
  firstKept,      \* ghost: first stamp still equals opened
  receipts,       \* receipts pushed for this recipient
  lastOut,        \* refused | stored | opened | noop | error
  lastStep,
  orphaned,       \* letterLive /\ ~recipient (should never stick when GuardNoOrphan)
  silentTrunc,    \* oversized body was stored after a truncate (mutant)
  steps

vars == <<bodyLen, letterLive, recipient, opened, firstKept, receipts,
          lastOut, lastStep, orphaned, silentTrunc, steps>>

TypeOK ==
  /\ bodyLen \in 0..5000
  /\ letterLive \in BOOLEAN
  /\ recipient \in BOOLEAN
  /\ opened \in 0..2
  /\ firstKept \in BOOLEAN
  /\ receipts \in 0..8
  /\ lastOut \in {"none", "refused", "stored", "opened", "noop", "error"}
  /\ lastStep \in {"init", "send", "reply", "open", "term"}
  /\ orphaned \in BOOLEAN
  /\ silentTrunc \in BOOLEAN
  /\ steps \in Nat

Room == steps < MaxSteps

Init ==
  /\ bodyLen = 0
  /\ letterLive = FALSE
  /\ recipient = FALSE
  /\ opened = 0
  /\ firstKept = TRUE
  /\ receipts = 0
  /\ lastOut = "none"
  /\ lastStep = "init"
  /\ orphaned = FALSE
  /\ silentTrunc = FALSE
  /\ steps = 0

\* Environment chooses a body length for the next send/reply.
PickBody(n) ==
  /\ Room
  /\ bodyLen' = n
  /\ lastStep' = "init"
  /\ lastOut' = "none"
  /\ steps' = steps + 1
  /\ UNCHANGED <<letterLive, recipient, opened, firstKept, receipts,
                 orphaned, silentTrunc>>

\* ---- _h_send / _h_reply body guard (rpc.py:1557-1558, 1914-1915) ----

SendOrReply ==
  /\ Room
  /\ bodyLen > 0
  /\ IF bodyLen > 4096
     THEN IF GuardBodyRefuse
          THEN /\ lastOut' = "refused"
               /\ lastStep' = "send"
               /\ silentTrunc' = FALSE
               /\ steps' = steps + 1
               /\ UNCHANGED <<bodyLen, letterLive, recipient, opened,
                              firstKept, receipts, orphaned>>
          ELSE \* mutant: store a truncated body
               /\ letterLive' = TRUE
               /\ recipient' = TRUE
               /\ opened' = 0
               /\ firstKept' = TRUE
               /\ receipts' = 0
               /\ lastOut' = "stored"
               /\ lastStep' = "send"
               /\ silentTrunc' = TRUE
               /\ orphaned' = FALSE
               /\ steps' = steps + 1
               /\ UNCHANGED bodyLen
     ELSE \* body fits: insert letter + recipients, or orphan under mutant
          /\ LET hasRecip == TRUE  \* happy path always names a dest
                 keep == IF GuardNoOrphan THEN hasRecip ELSE FALSE
             IN
               /\ letterLive' = TRUE
               /\ recipient' = keep
               /\ orphaned' = (TRUE /\ ~keep)
               /\ opened' = 0
               /\ firstKept' = TRUE
               /\ receipts' = 0
               /\ lastOut' = IF keep THEN "stored" ELSE "error"
               /\ lastStep' = "send"
               /\ silentTrunc' = FALSE
               /\ steps' = steps + 1
               /\ UNCHANGED bodyLen

\* Send that names no live recipient (empty roster / all retired).
SendNoRecipient ==
  /\ Room /\ bodyLen > 0 /\ bodyLen <= 4096
  /\ IF GuardNoOrphan
     THEN /\ lastOut' = "refused"
          /\ lastStep' = "send"
          /\ steps' = steps + 1
          /\ UNCHANGED <<bodyLen, opened, firstKept, receipts, silentTrunc>>
          /\ IF GuardRollbackOnError
             THEN /\ orphaned' = FALSE
                  /\ letterLive' = letterLive
                  /\ recipient' = recipient
             ELSE /\ letterLive' = TRUE
                  /\ recipient' = FALSE
                  /\ orphaned' = TRUE
     ELSE /\ letterLive' = TRUE
          /\ recipient' = FALSE
          /\ orphaned' = TRUE
          /\ lastOut' = "stored"
          /\ lastStep' = "send"
          /\ steps' = steps + 1
          /\ UNCHANGED <<bodyLen, opened, firstKept, receipts, silentTrunc>>

\* ---- mill_mail_open (sp_opened.sql) ----

Open ==
  /\ Room /\ letterLive /\ recipient
  /\ LET prev == opened
         bumpReceipt ==
           IF GuardOneReceipt
           THEN (prev = 0 /\ receipts = 0)  \* push_receipt only on first open
           ELSE TRUE                         \* mutant: every open pushes
     IN
       /\ IF prev = 0
          THEN /\ opened' = 1
               /\ firstKept' = TRUE
               /\ receipts' = IF bumpReceipt THEN receipts + 1 ELSE receipts
               /\ lastOut' = "opened"
               /\ lastStep' = "open"
               /\ steps' = steps + 1
               /\ UNCHANGED <<bodyLen, letterLive, recipient, orphaned, silentTrunc>>
          ELSE IF GuardFirstOpenOnly
               THEN /\ receipts' = IF bumpReceipt THEN receipts + 1 ELSE receipts
                    /\ lastOut' = IF bumpReceipt THEN "opened" ELSE "noop"
                    /\ lastStep' = "open"
                    /\ firstKept' = (opened = 1)
                    /\ steps' = steps + 1
                    /\ UNCHANGED <<bodyLen, letterLive, recipient, opened,
                                   orphaned, silentTrunc>>
               ELSE /\ opened' = 2
                    /\ firstKept' = FALSE
                    /\ receipts' = IF bumpReceipt THEN receipts + 1 ELSE receipts
                    /\ lastOut' = "opened"
                    /\ lastStep' = "open"
                    /\ steps' = steps + 1
                    /\ UNCHANGED <<bodyLen, letterLive, recipient, orphaned, silentTrunc>>

\* Mutant of GuardOpenLocked: a second open races and double-receipts even
\* with FirstOpenOnly, modelled by bumping receipts when lock is off.
OpenUnlockedRace ==
  /\ Room /\ letterLive /\ recipient /\ opened = 0
  /\ ~GuardOpenLocked
  \* Two racers both read v_prev NULL before either stamps: each pushes a
  \* receipt; opened stays NULL so a second racer can still run.
  /\ receipts' = receipts + 1
  /\ lastOut' = "opened"
  /\ lastStep' = "open"
  /\ firstKept' = TRUE
  /\ steps' = steps + 1
  /\ UNCHANGED <<bodyLen, letterLive, recipient, opened, orphaned, silentTrunc>>

Term ==
  /\ steps >= MaxSteps
  /\ UNCHANGED vars

Next ==
  \/ \E n \in {1, 100, 4096, 4097, 5000}: PickBody(n)
  \/ SendOrReply
  \/ SendNoRecipient
  \/ Open
  \/ OpenUnlockedRace
  \/ Term

Spec == Init /\ [][Next]_vars

\* ---- properties ----

\* Oversized bodies are refused, never stored (rpc.py:1557-1558 / 1914-1915).
OversizedBodyRefused ==
  ~silentTrunc

\* A live letter always has at least one recipient row (sp_mail.sql:281-283).
NoOrphanMail ==
  ~orphaned

\* The first open stamp is kept (sp_opened.sql:34-36).
FirstOpenKept ==
  firstKept

\* At most one receipt per recipient row (sp_opened.sql:41).
OneReceiptPerRecipient ==
  receipts <= 1

\* Handled is final: opened is NULL or the first stamp, never overwritten
\* (sp_opened.sql:34-36 AND opened IS NULL).
HandledIsFinal ==
  opened \in {0, 1}

\* SIGNAL on empty mail_to rolls back the insert (handler ROLLBACK).
FailedInsertLeavesNoPartial ==
  ~ (letterLive /\ ~recipient /\ lastOut = "refused")

====
