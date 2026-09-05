------------------------------- MODULE Kernel -------------------------------
EXTENDS Naturals, FiniteSets, TLC

CONSTANTS Jobs, Budget
ASSUME /\ IsFiniteSet(Jobs) /\ Jobs # {} /\ Budget \in Nat

VARIABLES phase, held, charged, available, spent, epoch, snapEpoch,
          version, snapVersion, live, data, dispatched, writes,
          lastAuthorized

vars == <<phase, held, charged, available, spent, epoch, snapEpoch,
          version, snapVersion, live, data, dispatched, writes,
          lastAuthorized>>

RECURSIVE Sum(_)
Sum(f) == IF DOMAIN f = {} THEN 0
          ELSE LET k == CHOOSE x \in DOMAIN f : TRUE
               IN f[k] + Sum([x \in DOMAIN f \ {k} |-> f[x]])

Init == /\ phase = [j \in Jobs |-> "idle"]
        /\ held = [j \in Jobs |-> 0]
        /\ charged = [j \in Jobs |-> 0]
        /\ available = Budget /\ spent = 0 /\ epoch = 0
        /\ snapEpoch = [j \in Jobs |-> 0]
        /\ version = 0 /\ snapVersion = [j \in Jobs |-> 0]
        /\ live = TRUE /\ data = 0
        /\ dispatched = [j \in Jobs |-> 0]
        /\ writes = 0 /\ lastAuthorized = TRUE

Reserve(j) ==
    /\ phase[j] = "idle" /\ available >= 1 /\ epoch = 0
    /\ phase' = [phase EXCEPT ![j] = "reserved"]
    /\ held' = [held EXCEPT ![j] = 1]
    /\ available' = available - 1
    /\ snapEpoch' = [snapEpoch EXCEPT ![j] = epoch]
    /\ snapVersion' = [snapVersion EXCEPT ![j] = version]
    /\ UNCHANGED <<charged, spent, epoch, version, live, data,
                   dispatched, writes, lastAuthorized>>

Dispatch(j) ==
    /\ phase[j] = "reserved" /\ epoch = snapEpoch[j] /\ epoch = 0
    /\ phase' = [phase EXCEPT ![j] = "running"]
    /\ dispatched' = [dispatched EXCEPT ![j] = @ + 1]
    /\ UNCHANGED <<held, charged, available, spent, epoch, snapEpoch,
                   version, snapVersion, live, data, writes, lastAuthorized>>

Cancel(j) ==
    /\ phase[j] = "reserved"
    /\ phase' = [phase EXCEPT ![j] = "cancelled"]
    /\ available' = available + held[j]
    /\ held' = [held EXCEPT ![j] = 0]
    /\ UNCHANGED <<charged, spent, epoch, snapEpoch, version, snapVersion,
                   live, data, dispatched, writes, lastAuthorized>>

Unknown(j) ==
    /\ phase[j] = "running"
    /\ phase' = [phase EXCEPT ![j] = "unknown"]
    /\ UNCHANGED <<held, charged, available, spent, epoch, snapEpoch,
                   version, snapVersion, live, data, dispatched,
                   writes, lastAuthorized>>

Revoke ==
    /\ epoch = 0 /\ epoch' = 1
    /\ UNCHANGED <<phase, held, charged, available, spent, snapEpoch,
                   version, snapVersion, live, data, dispatched,
                   writes, lastAuthorized>>

Complete(j, charge, op, value) ==
    /\ phase[j] \in {"running", "unknown"}
    /\ charge \in 0..held[j]
    /\ op \in {"create", "replace", "delete", "none", "invalid"}
    /\ value \in {0, 1}
    /\ LET fresh == epoch = snapEpoch[j] /\ epoch = 0
                    /\ version = snapVersion[j]
           lifecycle == IF op = "create" THEN ~live ELSE live
           commit == fresh /\ lifecycle
                     /\ op \in {"create", "replace", "delete"}
       IN /\ version' = IF commit THEN version + 1 ELSE version
          /\ live' = IF commit THEN op # "delete" ELSE live
          /\ data' = IF commit /\ op # "delete" THEN value ELSE data
          /\ writes' = IF commit THEN writes + 1 ELSE writes
          /\ lastAuthorized' = IF commit THEN fresh ELSE lastAuthorized
    /\ phase' = [phase EXCEPT ![j] = "done"]
    /\ held' = [held EXCEPT ![j] = 0]
    /\ charged' = [charged EXCEPT ![j] = charge]
    /\ available' = available + held[j] - charge
    /\ spent' = spent + charge
    /\ UNCHANGED <<epoch, snapEpoch, snapVersion, dispatched>>

Next == \/ \E j \in Jobs : Reserve(j) \/ Dispatch(j) \/ Cancel(j) \/ Unknown(j)
        \/ Revoke
        \/ \E j \in Jobs, c \in 0..1,
               op \in {"create", "replace", "delete", "none", "invalid"},
               value \in {0, 1} : Complete(j, c, op, value)

Spec == Init /\ [][Next]_vars

TypeOK == /\ phase \in [Jobs -> {"idle", "reserved", "running", "unknown",
                                "done", "cancelled"}]
          /\ held \in [Jobs -> 0..1] /\ charged \in [Jobs -> 0..1]
          /\ available \in 0..Budget /\ spent \in 0..Budget
          /\ epoch \in 0..1 /\ snapEpoch \in [Jobs -> 0..1]
          /\ version \in 0..Cardinality(Jobs)
          /\ snapVersion \in [Jobs -> 0..Cardinality(Jobs)]
          /\ live \in BOOLEAN /\ data \in {0, 1}
          /\ dispatched \in [Jobs -> 0..1]

Conservation == available + spent + Sum(held) = Budget
ChargeAccounting == spent = Sum(charged)
TerminalHoldsNothing == \A j \in Jobs :
    phase[j] \in {"done", "cancelled"} => held[j] = 0
UnknownKeepsReservation == \A j \in Jobs : phase[j] = "unknown" => held[j] = 1
OneDispatch == \A j \in Jobs : dispatched[j] <= 1
AuthorizedWrites == lastAuthorized
VersionCountsWrites == version = writes

=============================================================================
