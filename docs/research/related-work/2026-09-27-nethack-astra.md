# NetHack Astra

Answer from the ASHES-ML v2.0 chat, 2026-09-27 00:06 (UTC-7).

> how is it related to:
> [https://github.com/kenforthewin/nethack_astra](https://github.com/kenforthewin/nethack_astra)
> [https://kenforthewin.github.io/blog/posts/llm-nethack-ascension/#run=astra-3&frame=0&turn=1](https://kenforthewin.github.io/blog/posts/llm-nethack-ascension/#run=astra-3\&frame=0\&turn=1)

---

**This is a concrete example of your seed-harness idea: the agent develops parts of its own operating system while solving the task.** It also strengthens our earlier point that useful learning can persist in executable code and memory, with no weight update.

I checked the repository at [`38b1a38`](https://github.com/kenforthewin/nethack_astra/tree/38b1a38b340d4cb154fe5e4411b2819dc407d5e3), including the movement guard, session controller, audit code, tests, and journal excerpts. The independent Hardfought record confirms the ascension after **37,140 game turns**. That establishes the game outcome; attribution and learning claims require additional evidence. genui{"citation":{"ref":"turn25view0"}}

**The important change is what the agent can act on.** It can choose an in-game action, but it can also change how future actions are planned, executed, observed, and remembered.

My mapping to our discussion is:

| System | Where improvement is retained | Main connection |
|---|---|---|
| **NetHack Astra** | Helpers, guards, instructions, journals | Builds and repairs a task-specific harness during use |
| **Harness-Zero** | Model weights | Transfers harness-induced behavior into the executor |
| **Atria Dawn** | Trained model; human–agent development process | Studies learning from verified experience and research interventions |
| **OpenResearch** | Experiment code and records | Infrastructure for testing and retaining candidate improvements |
| **Your \(\Phi\)** | The inherited improvement procedure | Must generate better subsequent improvements |

The NetHack release contains the task interface and supporting tools. Model inference and context orchestration remain supplied by the surrounding coding-agent host; the repository is not a standalone autonomous player. [README](https://github.com/kenforthewin/nethack_astra/blob/38b1a38b340d4cb154fe5e4411b2819dc407d5e3/README.md)

**The clearest example is a repaired observation rule.**

The movement guard originally stopped batches when health fell. During the winning run, healing masked damage from a falling-rock trap: the character suffered damage, but the observed net health change did not reveal it.

The recorded response was to add a check for newly appearing trap messages, with regression cases covering wrapped messages and lingering old messages. The journal records testing and checkpointing before play resumed. The corresponding implementation and tests are present. [Recorded repair](https://github.com/kenforthewin/nethack_astra/blob/38b1a38b340d4cb154fe5e4411b2819dc407d5e3/EVIDENCE.md) · [Tests](https://github.com/kenforthewin/nethack_astra/blob/38b1a38b340d4cb154fe5e4411b2819dc407d5e3/scripts/test_guard.py)

That matters for AHSL because the improvement changes **how evidence is interpreted**, rather than merely selecting a different move. The general lesson is familiar from your evaluation work: a convenient observable can conceal the event you actually care about.

There is also a useful boundary case. Run 2 ended in an instantaneous death-ray attack. The guard stopped at the death prompt, but reacting after the step could not save the character. The postmortem instead proposed a strategic prerequisite—acquiring relevant protection before another Castle attempt—and explicitly prohibited carrying that run’s maps and randomized item identities into the next run. [Run 2 journal](https://github.com/kenforthewin/nethack_astra/blob/38b1a38b340d4cb154fe5e4411b2819dc407d5e3/memory/run-2.md)

This separates three things we should preserve in the framework:

- **Execution checks:** did the action behave as expected?
- **Strategic prerequisites:** should this action have been attempted?
- **Knowledge scope:** which lessons transfer, and which facts belong only to this episode?

**Its relationship to Harness-Zero is complementary.**

Schematically:

\[
\text{NetHack:}\qquad
(\theta,H_t,M_t)\rightarrow(\theta,H_{t+1},M_{t+1})
\]

\[
\text{Harness-Zero:}\qquad
(\theta,H^*)\rightarrow(\theta',H_0).
\]

The first expresses discovered competence externally; the second tries to internalize harness-induced behavior through training. Harness-Zero specifically constructs corrections compatible with the student’s deployment interface. genui{"citation":{"ref":"turn13view0"}}

My proposed combination would be selective: **retain exact algorithms and mandatory checks as code, while training the model to recognize when to invoke, revise, or replace them.** A learned habit of checking is useful; an enforced check supplies a different property.

The NetHack code illustrates why this division can be efficient. Its route helper performs graph search, while guarded movement executes a short sequence with observations and checks between steps. It therefore reduces model round trips while retaining intermediate feedback. [Route helper](https://github.com/kenforthewin/nethack_astra/blob/38b1a38b340d4cb154fe5e4411b2819dc407d5e3/scripts/route.py) · [Movement guard](https://github.com/kenforthewin/nethack_astra/blob/38b1a38b340d4cb154fe5e4411b2819dc407d5e3/scripts/guard.py)

That suggests a more precise interpretation of Harness Tax: measure which decisions need another model call and which can be delegated to a checked program. Harness complexity alone does not determine cost.

**For AHSL, the implementation provides examples of provenance controls—and their limits.**

The normal input path requires a healthy recorder and records input intent before sending it. The recorder checks session binding, available disk space, and transcript lag. [Session controller](https://github.com/kenforthewin/nethack_astra/blob/38b1a38b340d4cb154fe5e4411b2819dc407d5e3/scripts/session.py) · [Audit implementation](https://github.com/kenforthewin/nethack_astra/blob/38b1a38b340d4cb154fe5e4411b2819dc407d5e3/scripts/audit.py)

However, `--raw` provides a logged bypass of movement checks, and the controlling agent can edit the harness itself. This is an intentional interface feature, not evidence of a universally enforced safety boundary. Likewise, checking a hash chain establishes consistency with its checkpoint; it does not establish that no unrecorded intervention occurred. The publication notes state that limitation explicitly. [Publication scope](https://github.com/kenforthewin/nethack_astra/blob/38b1a38b340d4cb154fe5e4411b2819dc407d5e3/docs/PUBLICATION.md)

For our design, that means separately specifying permission to **modify a checker**, evidence required to **accept that modification**, and authority to **bypass it**.

**The remaining gap is between improving \(H\) and improving \(\Phi\).**

The campaign demonstrates tool construction, repair, and persistent adaptation. Its three attempts used an evolving system, reference access, and no fixed overall evaluation budget. They do not establish a win rate or isolate the causal contribution of each component. genui{"citation":{"ref":"turn24view0"}}

More specifically:

\[
H_{t+1}=\Phi(H_t,E_t)
\]

can produce substantial improvements while \(\Phi\) remains unchanged. To establish effective recursive meta-improvement, we need evidence that an inherited revision to \(\Phi\) produces better subsequent harnesses under comparable resources.

I would test this in two stages:

1. **Harness transfer:** freeze early and final harness versions, evaluate on fresh games, and independently vary access to general strategy notes. Reset episode-specific maps and item identities.
2. **Improver transfer:** start from the same minimal harness and compare original versus revised improvement procedures across independent campaigns, counting tool development and testing costs.

The strongest implication for your project is that **a small seed can support substantial, agent-built structure**. The next research question is whether the system can learn a more effective procedure for building that structure—and demonstrate that improvement beyond the campaign that produced it.
