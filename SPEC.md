# Agent Harness Specification Language (AHSL) 0.1

**Status:** research draft  
**Date:** 2026-09-02  
**Purpose:** a backend-neutral language for specifying, executing, auditing, and evolving LLM-agent harnesses and hyperagents.

## 1. Executive decision

AHSL is a two-level language:

1. A human-oriented declarative surface language, serializable as YAML or JSON.
2. A small normative intermediate representation, AHIR, whose execution is an event-sourced state machine.

The surface syntax is replaceable. AHIR types, transition rules, authority checks, provenance, and conformance tests are normative.

AHSL is not intended to be more computationally expressive than Python or another general-purpose language. Its advantage is analyzability: agents, evidence, memory, entropy, evaluation, aggregation, evolution, authority, and promotion are first-class typed objects instead of conventions hidden across prompts and application code.

## 2. Research synthesis: five passes

### Pass 1 — workflow semantics and provenance

The language should reuse mature ideas rather than replace them:

- typed process inputs and outputs from the [Common Workflow Language](https://www.commonwl.org/v1.2/CommandLineTool.html);
- activities, events, gateways, and subprocesses from [BPMN](https://www.omg.org/spec/BPMN/2.0.2/About-BPMN);
- `Entity`, `Activity`, `Agent`, derivation, usage, and generation relations from [W3C PROV](https://www.w3.org/TR/prov-dm/);
- traces, spans, metrics, and logs as observability projections, following [OpenTelemetry semantic conventions](https://opentelemetry.io/docs/concepts/semantic-conventions/).

Decision: AHSL uses a typed process graph, but its immutable event ledger is the source of truth. Telemetry is a derived projection and may be discarded and rebuilt.

### Pass 2 — existing LLM frameworks

[LangGraph](https://docs.langchain.com/oss/python/langgraph/graph-api) and AutoGen GraphFlow express stateful graph execution; [DSPy](https://dspy.ai/getting-started/program-dont-prompt/) expresses typed LLM signatures and optimization; the [OpenAI Agents SDK](https://developers.openai.com/api/docs/guides/agents) provides agents, tools, handoffs, sessions, guardrails, approvals, and tracing.

Decision: AHSL does not compete with these runtimes. It compiles to them. Its missing layer is a portable specification of authority, evidence, memory derivation, experimental evaluation, aggregation, evolution, and promotion.

### Pass 3 — trajectories, memory, and world models

[PRO-LONG](https://arxiv.org/abs/2607.20064) shows the value of a complete append-only trajectory searchable with programs. [TELL](https://github.com/studio-dots-ai/TELL) condenses experience into explicit game memory. [MemRL](https://arxiv.org/abs/2601.03192) separates semantic relevance from learned utility. [Schema](https://schema-harness.github.io/) turns inferred mechanisms into executable models tested against observations.

Decision: `Memory` is not one vector database. AHSL separates raw events, derived memories, indices, retrieval policy, utility, world models, and latent checkpoints. Condensation may supersede another derived artifact but may never delete or rewrite its raw evidence.

### Pass 4 — evolution and aggregation

[GEPA](https://arxiv.org/abs/2507.19457) samples trajectories, reflects on them, and evolves prompts using Pareto selection. [PromptBreeder](https://arxiv.org/abs/2309.16797) evolves both task prompts and mutation prompts. [MAP-Elites](https://arxiv.org/abs/1504.04909) preserves elites across behavioral niches. [LLM Council](https://github.com/karpathy/llm-council) provides independent proposals, anonymous peer rankings, and chairman synthesis.

Decision: `Mutator`, `Council`, `Evaluator`, `Selector`, and `Archive` are different types. A council aggregates beliefs and recommends candidates; it does not establish empirical truth or promote candidates. Self-referential mutation creates a versioned candidate for a future epoch and cannot modify the current evaluator.

### Pass 5 — safety and reward hacking

Specification gaming satisfies a literal metric without satisfying its intended objective, as summarized by [DeepMind](https://deepmind.google/blog/specification-gaming-the-flip-side-of-ai-ingenuity/). Textual instructions alone therefore cannot protect evaluation. AHSL adopts deny-overrides authorization similar to [Cedar](https://docs.cedarpolicy.com/overview/terminology.html), state-machine safety/liveness properties in the style of TLA+, and content-addressed attestations inspired by [SLSA/in-toto](https://slsa.dev/spec/v1.2/faq).

Decision: an untrusted model may propose a transaction. Only the deterministic kernel may authorize, execute, evaluate, commit, promote, roll back, allocate budgets, or terminate a run.

## 3. Normative language

The terms **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** are normative.

An AHSL implementation consists of:

- a parser and schema validator;
- a compiler from AHSL to AHIR;
- a deterministic kernel implementing AHIR transition semantics;
- one or more backend adapters;
- a conformance test suite.

## 4. Scope and non-goals

AHSL MUST describe:

- models, agents, tools, environments, and workflows;
- context construction, memory, and transcript processing;
- councils and decision aggregation;
- candidate generation, mutation, evaluation, selection, and archives;
- budgets, permissions, visibility, provenance, and observability;
- explicit-to-implicit distillation and implicit-to-explicit auditing;
- immutable and mutable surfaces;
- safety and liveness invariants.

AHSL does not attempt to formalize the internal semantics of arbitrary Python, model weights, or natural-language reasoning. Such components are opaque typed implementations with declared effects and attestations.

## 5. High-level grammar

```ebnf
specification  = header, { import }, { declaration } ;
declaration    = type_decl | artifact_decl | actor_decl | tool_decl
               | environment_decl | memory_decl | workflow_decl
               | council_decl | evaluator_decl | evolution_decl
               | policy_decl | invariant_decl | test_decl ;

workflow_decl  = 'workflow', identifier, '{', { node | edge | trigger }, '}' ;
node           = identifier, ':', node_kind, input_ports, output_ports,
                 effects, authority, [ retry ], [ budget ] ;
edge           = source, '->', target, [ guard ], [ mapping ] ;

evolution_decl = 'evolution', identifier, '{', genome, population,
                 mutators, evaluator_ref, selector, archive, stop_rule, '}' ;
council_decl   = 'council', identifier, '{', members, rounds, ballot,
                 aggregator, dissent_policy, authority, '}' ;
```

The reference serialization is YAML. Every document MUST have a canonical JSON form for hashing and signing.

## 6. Core type system

### 6.1 Values

```text
Bool | Int | Float | Decimal | Text | Bytes | Timestamp | Duration
Tensor[dtype, shape] | Image[format] | Audio[format]
Record{...} | Enum{...} | List[T] | Set[T] | Map[K,V] | Option[T]
Artifact[T] | Stream[T] | Secret[T, label]
```

`Secret[T, label]` MUST be taint-tracked. A value with `sealed` or `evaluator_private` visibility MUST NOT flow into a candidate-visible port unless an explicit trusted declassification node authorizes the exact projection.

### 6.2 Principals

```text
Human | ModelAgent | Tool | Council | Mutator | Evaluator | Selector | Kernel
```

Every action is attributed to exactly one principal. Responsibility may additionally be attributed to a parent principal, for example a council invoking a member model.

### 6.3 Artifacts

Every artifact has:

```text
Artifact {
    id: ContentHash
    type: TypeRef
    bytes_or_ref: Opaque
    created_by: PrincipalRef
    generated_by: EventRef
    derived_from: Set[ArtifactRef | EventRef]
    spec_version: ContentHash
    implementation_digest: ContentHash
    visibility: public | candidate_visible | evaluator_private | sealed
    status: draft | evaluated | promoted | rejected | revoked
}
```

Artifact identity is content-addressed. Mutable names such as `current_best` are references to immutable artifact versions.

## 7. Operational semantics

The runtime state is:

```text
Σ = (control, artifacts, ledger, budgets, archive, policies, epoch)
```

An untrusted component emits a request:

```text
ρ = (principal, action, resource, payload, expected_version)
```

The kernel performs:

```text
request → validate types → authorize → reserve budget
        → execute in adapter → attest output → append event → commit or rollback
```

Formally, the kernel is the only component allowed to produce a committed transition:

```text
Σ --event--> Σ'
```

If validation or authorization fails, the attempted request is still appended as a denied event, but no protected state changes.

### 7.1 Transaction states

```text
proposed → authorized → running → committed
                    ↘ failed → rolled_back
proposed → denied
```

### 7.2 Effects

Nodes MUST declare effects from this extensible base set:

```text
read | query | append | create | modify | delete
execute | call_model | sample | retrieve | mutate
evaluate | aggregate | promote | rollback | declassify | terminate
```

Undeclared effects are denied.

## 8. Agent and environment contracts

### 8.1 Agent

```text
AgentSpec {
    model: Artifact[Model]
    decoder: DecoderConfig
    instructions: Artifact[Prompt | Program]
    context: ContextPolicy
    tools: Set[Capability]
    memory_views: Set[MemoryView]
    input: Type
    output: Type
    budget: Budget
}
```

Model revision, decoding parameters, prompt, tool schemas, and context policy MUST be versioned independently.

### 8.2 Environment

An interactive environment is represented as a bounded partially observable process:

```text
Environment[S, O, A] {
    reset(seed) -> O
    step(A) -> Transition[O]
    terminal(Transition) -> Bool
    hidden_state: S
    observation: O
    action: A
    horizon: Int
    side_effect_class: pure | sandboxed | external
}
```

`hidden_state` describes the type but does not grant access. Evaluation reward MAY be withheld from the acting agent.

## 9. Trajectories, evidence, and observability

### 9.1 Event

```text
Event {
    id: EventId
    run: RunId
    logical_time: Int
    wall_time: Option[Timestamp]
    parent_events: Set[EventRef]
    principal: PrincipalRef
    operation: Effect
    input_digests: Set[ContentHash]
    output_digests: Set[ContentHash]
    seed: Option[Seed]
    cost: ResourceUsage
    status: proposed | denied | committed | failed | rolled_back
    visibility: Visibility
}
```

A trajectory is a causally ordered event subgraph, not necessarily a single linear transcript.

### 9.2 Evidence

```text
Evidence {
    claim_scope: Predicate
    supporting_events: Set[EventRef]
    contradicting_events: Set[EventRef]
    evaluator: ArtifactRef
    uncertainty: Distribution | Interval | Unknown
}
```

`verified` always means verified relative to a named evaluator, evidence set, scope, and version. AHSL forbids an unscoped universal `verified: true`.

### 9.3 Observability

Logs, traces, metrics, dashboards, and summaries are materialized views over the ledger. They MAY be regenerated. The ledger MUST NOT depend on them for correctness.

## 10. Memory and the condensation/formalization cycle

```text
MemorySystem {
    raw: EventLedger
    derived: Set[DerivedMemory]
    indices: Set[Index]
    retrieval: RetrievalPolicy
    utility: Option[UtilityModel]
    latent: Set[LatentCheckpoint]
}
```

### 10.1 Derived memory

```text
DerivedMemory {
    kind: episode | summary | hypothesis | rule | plan | world_model
    content: Artifact
    derives_from: NonEmptySet[EventRef | ArtifactRef]
    scope: Predicate
    confidence: Interval | Distribution | Unknown
    status: proposed | corroborated | falsified | superseded
    supersedes: Set[ArtifactRef]
}
```

Derived memory MAY be revised by creating a new version. It MUST NOT mutate its cited evidence.

### 10.2 Retrieval

Retrieval is an observable decision:

```text
retrieve(query, scope, token_budget, entropy) -> RetrievalResult
```

The result records candidates considered, similarity, utility, diversity/noise contribution, chosen items, and context tokens consumed. KNN, programmatic search, hierarchy navigation, and random distant retrieval are implementations of the same interface.

### 10.3 Explicit and implicit transformations

```text
condense:  EvidenceSet -> DerivedMemory
formalize: DerivedMemory -> Artifact[ExecutableModel | Specification]
verify:    ExecutableModel × EvidenceSet -> VerificationReport
distill:   EvidenceSet × TrainingProcedure -> LatentCheckpoint
audit:     LatentCheckpoint × ProbeSuite -> Set[DerivedMemory]
```

`audit` is an inference about latent contents, not an inverse of `distill`.

Every latent checkpoint MUST include parent checkpoint, training evidence range, procedure digest, transfer scope, reset policy, and evaluation report.

## 11. Entropy

All nondeterminism MUST be declared as an `EntropySource`:

```text
model_sampling | rng | environment | retrieval_noise | external_corpus
population_sampling | mutation | crossover | human_input | clock
```

Each source declares seedability, distribution, budget, visibility, and replay status. Runs using unseeded or changing external sources are marked `non_replayable`; their external observations are nevertheless captured as artifacts where policy permits.

Entropy is injected by policy, never by silently perturbing data. A KNN system that mixes distant memories therefore declares a `retrieval_noise` source and records the injected items.

## 12. Councils and decision aggregation

```text
Council {
    members: Set[AgentRef]
    independence: shared_context | isolated
    anonymity: none | labels_hidden | double_blind
    rounds: List[CouncilRound]
    ballot: rank | approval | score | probability | argument
    aggregator: plurality | borda | condorcet[completion]
              | mean | median | bayesian_pool | chair | none
    preserve_dissent: Bool
    output: RecommendationSchema
    authority: advisory | propose_only
}
```

`chair` MUST be labeled as dictatorial aggregation, not consensus. A council output is a `Recommendation`, never an `EvaluationAttestation`.

For research mutation, the recommended output is:

```text
CouncilRecommendation {
    consensus_candidate: Option[Candidate]
    dissenting_candidates: Set[Candidate]
    discriminating_experiments: Set[Experiment]
    unresolved_disagreements: Set[Claim]
}
```

## 13. Evolution

### 13.1 Candidate

```text
Candidate[G] {
    genome: G
    parents: Set[CandidateRef]
    created_by: MutatorRef
    hypothesis: Claim
    predicted_effect: Distribution | Interval | Unknown
    falsification_test: ExperimentRef
    lineage: LineageId
}
```

Valid genomes include prompts, code, specifications, context policies, memory policies, world models, mutators, council configurations, and composites.

### 13.2 Mutator

```text
Mutator[G] {
    parents: List[Candidate[G]]
    evidence: EvidenceView
    entropy: Set[EntropySource]
    budget: Budget
    operator: zero_order | reflective | hypermutation | lamarckian
            | estimation_of_distribution | self_referential
            | differential | novelty | adversarial | council
    output: NonEmptySet[Candidate[G]]
}
```

These are AHSL operators, not claims that they belong to GEPA. GEPA is one configuration using trajectory-conditioned reflective mutation and Pareto-oriented selection.

### 13.3 Evaluator

```text
Evaluator {
    implementation: Artifact[Program]
    datasets: Map[train | public | private | sealed, Artifact[Dataset]]
    metrics: Set[Metric]
    constraints: Set[Predicate]
    replicates: ReplicationPolicy
    uncertainty: Estimator
    anti_gaming: Set[Test]
    epoch_policy: immutable_within_epoch
}
```

An evaluator produces a signed or content-addressed `EvaluationAttestation` containing candidate digest, evaluator digest, dataset partition digests, environment digest, seeds, raw measurements, aggregate metrics, uncertainty, constraint failures, and cost.

### 13.4 Selector and archive

```text
Selector {
    eligibility: Predicate
    rule: scalar | lexicographic | pareto | tournament | map_elites
    tie_break: List[Criterion]
    promotion_threshold: Predicate
}

Archive {
    kind: flat | pareto | map_elites | islands
    descriptor: Option[PureFunction[Candidate, Vector]]
    replacement: Rule
    capacity: Bound
}
```

Only evaluated candidates may enter a promotion selector. Behavioral descriptors MUST be versioned pure functions. Changing a descriptor starts a new archive epoch or runs an explicit migration.

### 13.5 Meta-evolution

A mutator, evaluator, selector, or AHSL fragment may itself be a genome. Such a meta-candidate:

1. executes only in a shadow epoch;
2. cannot affect the experiment that evaluates it;
3. is evaluated against multiple tasks or held-out search histories;
4. requires a kernel-controlled promotion into the next epoch;
5. cannot expand its own capabilities.

## 14. Authority and information-flow policy

Every request is evaluated as:

```text
authorize(principal, action, resource, context) -> allow | deny
```

Policy semantics are deny-overrides and default-deny.

The safe research profile requires:

| Principal | May propose | May execute candidate | May read sealed eval | May score | May promote |
|---|---:|---:|---:|---:|---:|
| Task agent | Yes | Through kernel | No | No | No |
| Mutator/council | Yes | No | No | No | No |
| Evaluator | No | Through kernel | Yes | Yes | No |
| Selector | No | No | Aggregate only | No | Recommends |
| Kernel | No | Yes | Yes | Records | Yes |

The kernel owns budgets, deadlines, termination, worktree creation, rollback, evaluator selection, and promotion.

## 15. Required safety invariants

Conforming research runtimes MUST enforce:

1. **Append-only evidence:** committed raw events are never changed or deleted in place.
2. **Provenance completeness:** every derived artifact cites its generating event and dependencies.
3. **Authority confinement:** no operation executes without an explicit capability.
4. **Evaluator isolation:** candidates cannot read or modify evaluator code, private data, seeds, or promotion state.
5. **Promotion integrity:** only the kernel promotes, and only from valid evaluation attestations.
6. **Epoch immutability:** contract, evaluator, metrics, and gates remain fixed during an epoch.
7. **Meta non-interference:** a meta-candidate cannot influence its own evaluation.
8. **Budget monotonicity:** remaining budgets never increase except through an externally authorized grant event.
9. **Secret noninterference:** sealed information cannot flow to candidate-visible artifacts without trusted declassification.
10. **Context non-authority:** omission from context does not delete or invalidate ledger state.
11. **Rollback completeness:** failed candidate execution leaves protected state unchanged except for failure evidence and consumed non-refundable resources.
12. **No self-termination authority:** an agent may request termination, but only the kernel applies the declared stop rule.

Recommended liveness properties:

- every admitted candidate is eventually evaluated or terminally classified;
- every run terminates on success, explicit failure, deadline, or exhausted budget;
- no reserved resource remains indefinitely owned by a failed transaction;
- every promoted artifact eventually receives post-promotion regression evaluation.

## 16. Conformance profiles

| Profile | Required modules |
|---|---|
| `core` | types, actors, graph, events, effects, capabilities |
| `research` | candidates, evaluator, attestations, gates, promotion |
| `memory` | ledger, derived memory, retrieval, utility |
| `world_model` | hypotheses, executable models, replay verification |
| `evolution` | mutators, population, selectors, archives |
| `council` | isolated members, ballots, aggregation, dissent |
| `latent` | distillation, checkpoint provenance, reset and transfer |
| `verified` | model-checked invariants, sealed evaluation, attestations |

A system claims only the profiles it implements. “Any harness can be described” means architectural interoperability through typed opaque components, not that AHSL can prove arbitrary component correctness.

## 17. Autoresearch compilation example

The following abbreviated AHSL captures the authority structure of [vinnik-dmitry07/autoresearch](https://github.com/vinnik-dmitry07/autoresearch):

```yaml
ahsl: 0.1
experiment: durak_memoryless_search

artifacts:
  contract: {path: program.md, mutable: false}
  engine: {path: durak/src/engine.cpp, mutable: false}
  candidate: {path: durak/src/strategy_heuristic.cpp, mutable: true}
  ledger: {path: results.tsv, mode: append_only}

environment:
  adapter: durak_simulator
  observation: DurakObservation
  action: LegalMove
  seed_policy: paired_splitmix64

evaluator:
  epoch_policy: immutable_within_epoch
  gates:
    - {name: smoke, seeds: 5000, rejects: [crash, illegal_move]}
    - {name: quick_b4, seeds: 100000}
    - {name: ladder, opponents: [B4, B1, B0]}
    - {name: full, seeds: 5000000, sealed: true}
  objective:
    rule: lexicographic
    constraints:
      - search_score >= current_best + 0.005
      - lower_ci >= current_best_lower_ci
    tie_break: minimize(complexity)

evolution:
  genome: Artifact[CppPolicy]
  archive: {kind: map_elites, optional: true}
  mutators: [reflective, novelty, adversarial]
  meta_mutator:
    genome: Artifact[EvolveSkill]
    write_scope: [evolve_skill.md]
    execution: shadow_epoch

council:
  trigger: plateau(rounds=5) or conflicting_evidence
  independence: isolated
  anonymity: labels_hidden
  ballot: rank
  aggregator: condorcet[minimax]
  preserve_dissent: true
  output: [consensus_child, dissent_children, discriminating_test]
  authority: propose_only

policy:
  default: deny
  permit:
    - [mutator, read, public_evidence]
    - [mutator, modify, candidate_worktree]
    - [kernel, evaluate, candidate_worktree]
    - [kernel, promote, evaluated_candidate]
  forbid:
    - [mutator, read, sealed_evaluator]
    - [mutator, modify, contract]
    - [mutator, terminate, run]
```

This compilation preserves the strongest feature of the project: the mutable heuristic and search policy are surrounded by a locked engine, staged evaluation, isolated worktrees, holdout-gated promotion, and an external keep/revert decision. LLM Council is inserted only as a triggered branching mutator.

## 18. Mapping existing systems to profiles

| System | AHSL representation |
|---|---|
| Duck Harness | `core`: REPL environment adapter and context policy |
| PRO-LONG | `memory`: append-only ledger plus programmatic retrieval |
| TELL | `memory + world_model`: hypothesis updates across a trajectory |
| Schema/EWMA | `world_model`: executable model plus replay verifier |
| MemRL | `memory`: relevance recall plus learned utility policy |
| Vision-CL | `latent`: versioned latent checkpoint and transfer policy |
| GEPA | `evolution`: reflective mutator plus Pareto archive |
| PromptBreeder | `evolution`: self-referential mutator genome |
| LLM Council | `council`: anonymous review and configurable aggregation |
| Autoresearch | `research + evolution + verified` |

## 19. Conformance tests

The first implementation SHOULD begin with executable tests, not a parser UI.

Minimum test suite:

1. Parse and canonicalize equivalent YAML documents to the same hash.
2. Reject undeclared ports, effects, types, and cyclic dependencies without loop guards.
3. Deny candidate access to sealed evaluator resources.
4. Prove that a denied request changes only the ledger.
5. Prove that raw evidence cannot be overwritten by condensation.
6. Reconstruct every promoted artifact from its provenance graph.
7. Reject promotion without a matching evaluator and candidate digest.
8. Reject evaluation attestations produced under a changed epoch.
9. Verify budget monotonicity and external termination ownership.
10. Run a self-referential mutator only in a shadow epoch.
11. Preserve council dissent when configured.
12. Replay a deterministic Autoresearch candidate from spec, seeds, and artifact digests.

## 20. Implementation sequence

1. Define the canonical JSON Schema and content hashing.
2. Implement the ledger and kernel transition state machine.
3. Implement capability policy and information labels.
4. Implement artifact attestations and isolated executor adapters.
5. Compile the existing Autoresearch configuration into AHSL.
6. Add PRO-LONG-compatible ledger search and typed derived memory.
7. Add evaluator, selector, and archive interfaces.
8. Add Council and mutation operators.
9. Export traces to OpenTelemetry and provenance to W3C PROV.
10. Translate the kernel state machine to TLA+ and model-check the required invariants.

The correct MVP is therefore not a universal library of every agent technique. It is a small verified kernel plus an extensible registry of typed components. New models, retrievers, councils, evolutionary algorithms, and training procedures enter as adapters; authority, evidence, and promotion semantics remain fixed.
