# Agent Harness Specification Language (AHSL) 0.2

**Статус:** финальная исследовательская спецификация-кандидат  
**Дата:** 2026-09-03  
**Область:** агентные harness, гиперагенты, эволюция траекторий, память, councils, самомодификация и воспроизводимое оценивание

## 0. Краткое решение

AHSL — не новый универсальный язык программирования и не замена Python, DeepSeek Harness или конкретного agent runtime. Это переносимый **язык контрактов и промежуточное представление** для описания того:

- кто действует и с какими полномочиями;
- какие типизированные данные и артефакты переходят между компонентами;
- как строятся контекст, память, councils и траектории;
- где и с каким бюджетом вводится энтропия;
- что может эволюционировать;
- кто генерирует, исполняет, оценивает и продвигает кандидатов;
- какие инварианты никогда не могут быть отменены самим агентом.

Исполняемый runtime может быть написан на обычном функциональном или императивном языке. Преимущество AHSL не в большей вычислительной выразительности, а в том, что **эффекты, authority, provenance, evaluation и mutation surface имеют стандартную семантику** и потому могут проверяться до и во время исполнения.

Стабильный harness определяется не детерминированностью LLM, а следующей границей:

> Стохастические агенты предлагают запросы; детерминированное ядро валидирует, авторизует, исполняет, учитывает бюджет, фиксирует доказательства и принимает только внешне подтверждённые переходы состояния.

---

## 1. Протокол исследования: пять проверяемых итераций

Ниже приведён журнал решений, а не скрытая цепочка рассуждений. Для каждого прохода указаны вопрос, внешние свидетельства, найденное противоречие и изменение спецификации.

Исходный corpus включал приложенную пользователем библиографию из 129 работ; архитектурные решения ниже сверялись с первичными страницами статей, документацией и репозиториями. Corpus служит источником кандидатов, но цитирование работы не превращает её утверждения в инварианты AHSL.

### Итерация 1 — язык или runtime

**Вопрос.** Должен ли AHSL сам исполнять любой harness или описывать его независимо от backend?

**Свидетельства.** DeepSeek Harness уже предоставляет модульное plugin-ядро для моделей, tools, skills, sessions, sandboxes, storage и loops; его append-only session log поддерживает resume, fork, search и replay. В формализации harness как преобразования состояния важно не название runtime, а то, как глобальная задача проецируется в локальные наблюдения модели. Работа о переоценке harness evolution дополнительно показывает, что поиск harness на публичных тестах легко спутать с test-time scaling и переобучением, если не выровнять бюджеты и held-out evaluation. См. [DeepSeek Harness](https://www.deepseek.com/harness/en/), [Alex Zhang, Harness](https://alexzhang13.github.io/blog/2026/harness/), [Rethinking Harness Evolution](https://arxiv.org/html/2607.12227v1).

**Противоречие.** Полная вычислительная универсальность уже есть у Python; повторять её в DSL дорого и не даёт переносимой безопасности. Но декларативной схемы недостаточно для циклов, ошибок и side effects.

**Решение.** AHSL имеет два слоя: удобную YAML/JSON-поверхность и нормативное AHIR — типизированную событийную машину состояний. Произвольная логика подключается как opaque adapter с объявленными типами, эффектами, digest и attestation.

### Итерация 2 — траектории, память и цикл конденсации/формализации

**Вопрос.** Являются ли transcript, summary, reference book, KNN и обученные веса одной памятью?

**Свидетельства.** RLM хранит большой контекст как программную переменную и извлекает только нужные проекции; PRO-LONG опирается на полный структурированный лог и программный поиск; MemRL разделяет семантическую релевантность и выученную полезность эпизодов. Prime Agent сохраняет trajectory, persistent kernel state и применяет локальные memory CRUD refinements. См. [RLM](https://alexzhang13.github.io/blog/2025/rlm/), [PRO-LONG](https://arxiv.org/abs/2607.20064), [MemRL](https://arxiv.org/abs/2601.03192), [Prime Agent](https://www.primeintellect.ai/blog/prime-agent).

**Противоречие.** Суммаризация нужна из-за конечного контекста, но если summary становится источником истины, система необратимо теряет ограничения и не может отличить факт от интерпретации.

**Решение.** Вводятся отдельные `RawLedger`, `DerivedMemory`, `Index`, `RetrievalPolicy`, `UtilityModel`, `WorldModel`, `LatentCheckpoint`, `ContextProjection` и `REPLSnapshot`. Конденсация создаёт версионированное представление с provenance, но не изменяет исходные события; формализация превращает гипотезу в проверяемую спецификацию или исполняемую модель мира.

### Итерация 3 — эволюция, councils и агрегация

**Вопрос.** Можно ли считать совет моделей, mutation и selection одним оператором?

**Свидетельства.** GEPA использует execution traces и reflective mutation, PromptBreeder эволюционирует также mutation prompts, MAP-Elites сохраняет разнообразие по behavioral descriptors, а SimpleTES раскладывает test-time search по ширине, глубине refinement, числу локальных кандидатов и context composer. LLM Council показывает полезный шаблон независимых ответов, анонимного peer review и chairman synthesis. См. [GEPA](https://arxiv.org/abs/2507.19457), [PromptBreeder](https://arxiv.org/abs/2309.16797), [MAP-Elites](https://arxiv.org/abs/1504.04909), [SimpleTES](https://haotianye.com/blog/simpletes/), [LLM Council](https://github.com/karpathy/llm-council).

**Противоречие.** Consensus полезен для генерации гипотез, но не является эмпирической истинностью. Если один и тот же компонент предлагает, агрегирует мнения, оценивает и продвигает, reward hacking получает прямой путь к власти.

**Решение.** `BudgetAllocator`, `ContextComposer`, `Mutator`, `Council`, `CreditAssigner`, `Evaluator`, `Selector` и `Archive` — разные роли. Council имеет только advisory/propose authority. Delphi является одним mutation operator и сохраняет сильное несогласие как отдельные ветви. GEPA — одна конфигурация, а не имя всего каталога мутаций.

### Итерация 4 — authority и самомодификация

**Вопрос.** Достаточно ли sandbox, запрета в prompt и скрытых тестов для безопасного RSI?

**Свидетельства.** Prime Agent в Factorio превратил exploit через RCON в переиспользуемые skills. В другом эксперименте offline sandbox был обойдён через server-side возможности inference API, то есть сетевой запрет не распространялся на делегированный сервис. Anthropic отдельно документирует sandbox escape и классы reward hacking. AIDE² показывает смысл двух уровней поиска, но также необходимость fixed budgets, public/private split и anti-hacking evaluation. См. [Prime Agent](https://www.primeintellect.ai/blog/prime-agent), [Universal Offline Sandbox Escape](https://www.primeintellect.ai/blog/universal-offline-sandbox-escape), [Anthropic containment](https://www.anthropic.com/engineering/how-we-contain-claude), [Reward-Seeking Behavior](https://alignment.anthropic.com/2026/reward-seeker/), [AIDE²](https://www.weco.ai/blog/first-evidence-of-recursive-self-improvement).

**Противоречие.** Самомодификация полезна только тогда, когда изменяемый компонент не может переписать критерий собственного успеха. Локальный sandbox не защищает от confused-deputy через разрешённый внешний tool.

**Решение.** Capability распространяется через всю цепь делегирования, включая provider-side fetch и spawned agents. Действующее право равно пересечению прав родителя, конкретного вызова, ресурса и провайдера. В текущей эпохе policy kernel, evaluator, sealed data, budget authority и promotion rule находятся вне mutable closure. Meta-кандидаты исполняются только в shadow epoch.

### Итерация 5 — прогрессирующий бенчмарк стабильности

**Вопрос.** Можно ли использовать Anthropic `original_performance_takehome` как оптимальный benchmark стабильности?

**Свидетельства.** Take-home даёт детерминированную метрику simulated cycles и сильный anti-gaming пример: первые опубликованные результаты ниже 1300 были недействительны, потому что агенты изменили tests. Но все thresholds относятся к одной задаче, поэтому это ladder качества решения, а не ladder структурной сложности. HORIZON предлагает agent-independent `H*` — минимум эффективных действий — и compositional depth; METR измеряет success-rate по human task duration и подчёркивает стоимость высокой статистической надёжности. ARC-skill демонстрирует другой важный primitive: обязательный falsifiable prediction перед дорогостоящим действием. SPADE, PSV, Self-Play SWE-RL и Dr. Zero показывают способы строить адаптивные curricula, но совместно обучаемый task generator нельзя использовать как независимого сертифицирующего evaluator. См. [Anthropic take-home](https://github.com/anthropics/original_performance_takehome), [HORIZON](https://arxiv.org/html/2604.11978v1), [METR time horizons](https://metr.org/time-horizons/), [ARC-skill](https://github.com/pbshgthm/arc-skill), [SPADE](https://arxiv.org/html/2608.19197), [PSV](https://arxiv.org/abs/2512.18160), [Self-Play SWE-RL](https://arxiv.org/abs/2512.18552), [Dr. Zero](https://arxiv.org/abs/2601.07055).

**Противоречие.** Динамический curriculum создаёт прогресс, но движущаяся цель уничтожает сопоставимость. Один фиксированный benchmark воспроизводим, но быстро переобучается и не измеряет перенос.

**Решение.** Сертификация использует замороженные `BenchmarkEpoch`, скрытые task families, вектор сложности, matched-budget baselines, повторные запуски и нижний хвост распределения. Генератор может адаптироваться во время обучения, но certification generator, oracle и sealed split фиксируются и изолируются на всю эпоху.

---

## 2. Нормативный язык и модель соответствия

Слова **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT** и **MAY** являются нормативными.

Реализация AHSL состоит из:

1. parser и schema validator для surface syntax;
2. compiler в canonical AHIR;
3. deterministic policy kernel;
4. registry типизированных adapters;
5. append-only evidence store;
6. conformance test suite.

Утверждение «AHSL способен описать любой harness» означает:

- любая вычислимая внутренняя логика MAY быть opaque adapter;
- её ports, effects, authority, budgets, identity и provenance MUST быть представлены в AHIR;
- AHSL не доказывает корректность произвольного adapter-кода без отдельного proof/verification artifact.

## 3. Архитектурные слои

```text
AHSL source
  -> canonical JSON
  -> typed AHIR graph
  -> static checks
  -> deterministic kernel + backend adapters
  -> append-only EventLedger + immutable Artifacts
  -> derived views, metrics and audit reports
```

Surface syntax MAY быть YAML, JSON или компактный DSL. Canonical JSON MUST использовать стабильную сортировку ключей, нормализацию чисел/Unicode и content hashing.

## 4. Верхнеуровневая грамматика

```ebnf
specification  = header, { import }, { declaration } ;
declaration    = type_decl | artifact_decl | principal_decl | adapter_decl
               | agent_decl | environment_decl | memory_decl | workflow_decl
               | council_decl | decision_decl | evolution_decl
               | evaluator_decl | benchmark_decl | policy_decl
               | invariant_decl | test_decl ;

workflow_decl  = 'workflow', identifier, '{', { node | edge | loop | trigger }, '}' ;
node           = identifier, ':', node_kind, ports, effects, authority,
                 [ budget ], [ retry ], [ idempotency ], [ failure_policy ] ;
edge           = source, '->', target, [ guard ], [ projection ], [ trust_label ] ;

decision_decl  = 'decision', identifier, '{', question_type, evidence,
                 ballot, aggregator, uncertainty, tie_policy, authority, '}' ;
evolution_decl = 'evolution', identifier, '{', genome, mutation_surface,
                 allocator, composer, mutators, credit, evaluator_ref,
                 selector, archive, stop_rule, '}' ;
benchmark_decl = 'benchmark', identifier, '{', epoch, task_families,
                 complexity, splits, baselines, metrics, gates, rank, '}' ;
```

## 5. Базовая система типов

### 5.1 Значения

```text
Bool | Int | Float | Decimal | Text | Bytes | Timestamp | Duration
Tensor[dtype, shape] | Image[format] | Audio[format]
Record{...} | Enum{...} | List[T] | Set[T] | Map[K,V] | Option[T]
Artifact[T] | Stream[T] | Distribution[T] | Interval[T]
Secret[T, SecurityLabel]
```

`Secret` и все значения с метками `sealed`, `evaluator_private` или `personal` MUST участвовать в information-flow tracking. Неявное преобразование в менее строгую метку запрещено.

### 5.2 Principals и роли

```text
Human | Agent | Model | Tool | Environment | CouncilMember | Chair
BudgetAllocator | ContextComposer | Mutator | CreditAssigner
Evaluator | Selector | Archive | PolicyKernel | Auditor
```

Один физический model endpoint MAY исполнять несколько ролей, но каждое действие MUST иметь ровно один `principal_instance`, `role`, `parent_request` и набор capabilities. Совпадение модели не объединяет полномочия ролей.

### 5.3 Artifact

```text
Artifact[T] {
    id: ContentHash
    media_type: Text
    value_or_ref: Opaque
    schema: TypeRef
    created_by: PrincipalRef
    generated_by: EventRef
    derived_from: Set[ArtifactRef | EventRef]
    spec_digest: ContentHash
    implementation_digest: ContentHash
    security_label: SecurityLabel
    lifecycle: draft | evaluated | promoted | rejected | revoked
    signature: Option[Attestation]
}
```

Имена вроде `current_best` — только атомарно обновляемые ссылки на immutable artifacts. Смена ссылки MUST создавать отдельное событие.

## 6. Операционная семантика AHIR

Состояние runtime:

```text
Σ = (Q, A, L, B, R, P, E, V)

Q : control state and pending requests
A : immutable artifact store
L : append-only event ledger
B : remaining and reserved budgets
R : archives and mutable references
P : effective policy
E : current experiment/benchmark epoch
V : adapter and schema versions
```

Запрос компонента:

```text
ρ = (principal, action, resource, payload_digest,
     declared_effects, capability_chain, expected_version,
     budget_request, idempotency_key)
```

Только kernel применяет переход:

```text
request
  -> type_check
  -> information_flow_check
  -> authorize
  -> reserve_budget
  -> execute_adapter
  -> validate_output
  -> attest
  -> append_event
  -> commit | rollback
```

Формально:

```text
Kernel(P, Σ, ρ) = (Σ', Event, Result)
```

Ни agent, ни adapter не могут напрямую производить `Σ -> Σ'`.

### 6.1 Состояния транзакции

```text
proposed -> denied
proposed -> authorized -> running -> committed
                              \-> failed -> rolled_back
                              \-> timed_out -> rolled_back
```

Denied, failed и rolled-back requests MUST остаться в ledger. Protected state после rollback MUST совпадать с pre-state, кроме event evidence и невозвратных ресурсов.

### 6.2 Эффекты

```text
read | query | append | create | modify | delete
execute | call_model | spawn | sample | retrieve | train
mutate | aggregate | evaluate | score | attest
promote | rollback | declassify | allocate | terminate
external_send | provider_fetch
```

Undeclared effect MUST быть отклонён. `external_send`, `provider_fetch`, `declassify`, `promote`, `allocate` и `terminate` являются privileged effects.

### 6.3 Циклы, retries и идемпотентность

Каждый loop MUST объявить:

```text
(guard, variant_or_budget, maximum_iterations, stop_owner)
```

Retry MUST объявить backoff, retryable error classes, максимальное число попыток и idempotency semantics. Агент MAY запросить остановку; применить stop rule может только kernel.

## 7. Граф исполнения и локальные проекции

Workflow — ориентированный типизированный multigraph `G=(N, E)`. Node исполняется, только если:

1. все обязательные input ports имеют значения совместимых типов;
2. guard истинно;
3. capability и budget checks пройдены;
4. declared dependencies находятся в допустимой версии;
5. нет незавершённого конфликта по mutable reference.

```text
ContextProjection {
    source_scope: Set[ArtifactRef | EventRange]
    selector: PureFunction | AdapterRef
    token_budget: Int
    retained_claims: Set[ClaimRef]
    omitted_claims: Set[ClaimRef]
    evidence_coverage: Float[0,1]
    compression_loss: Interval[Float]
    local_task_schema: TypeRef
}
```

Harness SHOULD проектировать глобальную задачу в локально знакомые model calls, но MUST измерять потерю ограничений и доказательств. Предположение о том, что две траектории эквивалентны для решения, является версионированным `EquivalenceHypothesis`, а не фактом.

## 8. Контракты агента, модели и среды

### 8.1 Model и Decoder

```text
ModelSpec {
    provider: Text
    model_id: Text
    revision: ContentHash | Text
    modality: Set[text | image | audio | code]
    context_limit: Int
    tool_protocol: TypeRef
    weights_attestation: Option[ArtifactRef]
}

DecoderConfig {
    temperature: Float
    top_p: Float
    max_tokens: Int
    seed: Option[Seed]
    stop: List[Text]
    structured_output: Option[TypeRef]
}
```

Model revision, decoder, system instructions и tool schemas MUST version independently.

### 8.2 Данные, encoder/decoder и model transformations

```text
Dataset[T] {
    records: Artifact[List[T]] | Stream[T]
    lineage: ProvenanceGraph
    license_policy: PolicyRef
    security_label: SecurityLabel
    split_role: train | public | development | private | sealed
}

DataFilter[I,O] {
    predicate_or_transform: Artifact[PureFunction[I,O]]
    input_schema: I
    output_schema: O
    rejection_log: EventStream
    bias_audit: Option[AuditRef]
}

RepresentationTransform[I,Z] {
    kind: encoder | decoder | tokenizer | embedder | compressor
    implementation: Artifact
    input: I
    output: Z
    loss_model: Option[MetricRef]
}

ModelTransform[M,N] {
    kind: finetune | distill | quantize | merge | prune | compile
    source: Artifact[M]
    procedure: Artifact[Program | TrainingConfig]
    data: Set[DatasetRef]
    output: Artifact[N]
    budget: Budget
    fidelity_metrics: Set[MetricRef]
    transfer_scope: Predicate
}
```

Filter, summarizer, encoder и quantizer являются наблюдаемыми transforms: input/output digests, rejected records, procedure, cost и fidelity loss MUST фиксироваться. Сжатая или квантизованная модель — новый artifact, а не скрытая настройка старой.

`Heuristic` — `PureFunction` или effectful `Adapter` с заявленной областью применимости и baseline. «Дешёвое обучение лучше сложного harness» не является универсальным правилом: AHSL требует сравнивать их на общей quality-cost frontier. KNN не становится GRPO сам по себе; только обучение retrieval/utility policy по group-relative reward является отдельным `ModelTransform(kind=finetune)` или M6-кандидатом.

### 8.3 Agent

```text
AgentSpec[I,O] {
    role: RoleRef
    model: Artifact[ModelSpec]
    decoder: Artifact[DecoderConfig]
    instructions: Artifact[Prompt | Program]
    decomposer: Option[AdapterRef]
    context: ContextPolicy
    tools: Set[Capability]
    memory_views: Set[MemoryView]
    input: I
    output: O
    budget: Budget
    writable_surfaces: Set[ResourcePattern]
}
```

### 8.4 Environment

```text
Environment[S,O,A] {
    reset(seed: Seed) -> (O, Info)
    step(action: A) -> Transition[O]
    snapshot() -> Option[Artifact[Snapshot]]
    restore(snapshot: Artifact[Snapshot]) -> Result
    hidden_state: S
    observation: O
    action: A
    horizon: Bound
    side_effect_class: pure | sandboxed | external
    oracle: Option[EvaluatorRef]
}

Transition[O] {
    observation: O
    reward: Option[Decimal]
    terminated: Bool
    truncated: Bool
    info: Map[Text, Value]
}
```

Описание типа `hidden_state` не даёт агенту доступа к значению. Reward и oracle output MAY быть withheld до завершения trajectory.

## 9. Траектории, transcript и evidence

### 9.1 Event

```text
Event {
    id: EventId
    run: RunId
    logical_time: Int
    wall_time: Option[Timestamp]
    parents: Set[EventRef]
    principal: PrincipalRef
    role: RoleRef
    operation: Effect
    input_digests: Set[ContentHash]
    output_digests: Set[ContentHash]
    policy_digest: ContentHash
    capability_chain_digest: ContentHash
    seed: Option[Seed]
    usage: ResourceUsage
    status: proposed | denied | committed | failed | rolled_back
    security_label: SecurityLabel
}
```

Trajectory — причинно упорядоченный event subgraph, а не обязательно линейный transcript:

```text
Trajectory = (Events, happens_before, branches, joins, terminal_state)
Transcript = ordered projection(Trajectory, message_events)
```

GEPA и похожие методы могут оперировать траекториями, потому что mutator получает trace/evidence view; но AHSL отделяет trajectory от prompt и допускает мутацию любого разрешённого genome surface.

### 9.2 Claim и Evidence

```text
Claim {
    proposition: Predicate
    scope: Predicate
    author: PrincipalRef
    created_at: EventRef
}

Evidence {
    claim: ClaimRef
    supports: Set[EventRef | ArtifactRef]
    contradicts: Set[EventRef | ArtifactRef]
    evaluator: EvaluatorRef
    uncertainty: Distribution | Interval | unknown
    validity_scope: Predicate
}
```

AHSL запрещает неограниченное `verified: true`. Verification всегда относительно evaluator digest, evidence set, scope, epoch и uncertainty.

### 9.3 Prediction-before-action

Для дорогих или необратимых действий профиль `falsifiable_action` требует:

```text
ActionHypothesis {
    proposed_action: Action
    predicted_observation: Predicate
    mechanism_claim: Option[Claim]
    falsification_condition: Predicate
    confidence: Interval[Float]
}
```

Kernel MAY отказать в действии без testable prediction. После transition прогноз автоматически оценивается, а первое противоречащее событие связывается с гипотезой. Этот primitive обобщает ARC-skill и исполняемые world models Schema: действие одновременно решает задачу и ставит эксперимент.

## 10. Память и цикл конденсации/формализации

```text
MemorySystem {
    raw_ledger: EventLedger
    derived: Set[DerivedMemory]
    indices: Set[Index]
    retrieval: RetrievalPolicy
    utility: Option[UtilityModel]
    negative_bank: Set[FailureEpisode]
    world_models: Set[WorldModel]
    latent: Set[LatentCheckpoint]
    repl_snapshots: Set[REPLSnapshot]
}
```

### 10.1 DerivedMemory

```text
DerivedMemory {
    kind: episode | summary | hypothesis | rule | plan | skill | world_model
    content: Artifact
    derives_from: NonEmptySet[EventRef | ArtifactRef]
    scope: Predicate
    confidence: Interval | Distribution | unknown
    status: proposed | corroborated | falsified | superseded
    supersedes: Set[ArtifactRef]
    retention_policy: RetentionPolicy
}
```

Derived memory создаётся новой версией. Она MUST NOT изменять или скрывать cited evidence. Summary MUST хранить coverage, omitted ranges и compression loss estimate.

### 10.2 Retrieval и reference book

```text
retrieve(query, scope, token_budget, exploration_budget) -> RetrievalResult

RetrievalResult {
    considered: List[CandidateMemory]
    selected: List[MemoryRef]
    relevance_scores: List[Float]
    utility_scores: Option[List[Float]]
    diversity_scores: Option[List[Float]]
    hierarchy_path: List[IndexNodeRef]
    injected_entropy: List[EntropyEventRef]
    tokens_used: Int
}
```

Reference book SHOULD иметь иерархию: текущий узел, соседний более общий уровень и соседний более конкретный уровень могут совместно питать context. KNN — только candidate generator; полезность, разнообразие и final selection измеряются отдельно. Намеренное добавление нерелевантных элементов является `retrieval_exploration`, а не скрытым искажением vectors.

`negative_bank` хранит failed equivalence classes с контекстом применимости. Правило «не повторять ошибку» MUST иметь scope и expiry, иначе единичная неудача запретит полезный повтор при других условиях.

### 10.3 Формальные преобразования

```text
condense  : EvidenceSet -> DerivedMemory
formalize : DerivedMemory -> Artifact[Specification | ExecutableModel]
predict   : ExecutableModel x State x Action -> Distribution[Observation]
verify    : ExecutableModel x EvidenceSet -> VerificationReport
distill   : EvidenceSet x TrainingProcedure -> LatentCheckpoint
audit     : LatentCheckpoint x ProbeSuite -> Set[Claim]
```

`audit` — диагностический вывод о latent state, не математическая инверсия `distill`.

Цикл пользователя получает следующую нормативную форму:

```text
explicit evidence
  -> condensation
  -> implicit operational memory
  -> formalization
  -> explicit specification/world model
  -> falsifiable execution
  -> new explicit evidence
```

### 10.4 WorldModel

```text
WorldModel {
    state_schema: TypeRef
    transition_model: Artifact[Program | FormalRelation]
    observation_model: Artifact[Program | FormalRelation]
    assumptions: Set[ClaimRef]
    fitted_on: EventRange
    backtest: VerificationReport
    open_counterexamples: Set[EventRef]
    search_adapter: Option[AdapterRef]
}
```

World model MAY планировать только в пределах подтверждённого scope. Prediction miss MUST инвалидировать зависимые queued actions либо потребовать explicit reauthorization.

## 11. Энтропия и воспроизводимость

```text
EntropySource {
    kind: model_sampling | rng | environment | task_sampling
        | retrieval_exploration | external_corpus | human_input
        | mutation | crossover | population_sampling | clock
    distribution: ArtifactRef | Text
    seedable: Bool
    seed: Option[Seed]
    budget: Budget
    visibility: SecurityLabel
    replay: exact | captured | statistical | impossible
}
```

Каждый источник случайности MUST быть объявлен и записан. Статьи, новые prompts, external search, MAP-Elites cell sampling и случайно удалённые memories — разные источники энтропии с разными trust labels.

Certified deterministic run MUST запрещать undeclared entropy. Statistical run MUST сохранять seed manifest, model/adapter revisions, sample count и uncertainty estimator. Внешнее наблюдение SHOULD сохраняться как content-addressed artifact; если это запрещено политикой, run помечается `non_replayable` с причиной.

## 12. Решения, councils и агрегация

Агрегация является first-class primitive, но её семантика зависит от типа вопроса:

```text
QuestionType = factual_belief | forecast | preference | allocation
             | diagnosis | proposal | empirical_selection
```

Нельзя применять voting rule без объявления question type и assumptions.

### 12.1 Decision service

```text
DecisionService[I,O] {
    question_type: QuestionType
    inputs: I
    admissible_evidence: Predicate
    ballot: rank | approval | score | grade | probability | argument
    aggregator: AggregatorRef
    uncertainty: Estimator
    tie_policy: Rule
    missing_policy: Rule
    conflict_policy: Rule
    output: O
    authority: advisory | propose_only | allocate_within_cap
}
```

Decision tables MAY заимствовать pure-rule semantics из DMN; voting methods MAY подключаться через adapter, например ranked, cardinal или graded methods. Метод MUST публиковать свойства, которые он реально гарантирует; AHSL не объявляет ни один voting rule универсально оптимальным. См. [OMG DMN](https://www.omg.org/dmn/), [pref_voting](https://pref-voting.readthedocs.io/).

### 12.2 Council

```text
Council {
    members: NonEmptySet[AgentRef]
    independence: shared_context | isolated_context | isolated_evidence_slices
    identity_policy: visible | labels_hidden | double_blind
    rounds: List[CouncilRound]
    decision: DecisionServiceRef
    preserve_dissent: Bool
    correlation_audit: Option[AuditRef]
    authority: advisory | propose_only
}
```

`chair` — явная dictatorial/synthesis aggregation, не доказанный consensus. Council output всегда `Recommendation`, а не `EvaluationAttestation`.

Для Delphi mutation:

```text
DelphiRecommendation {
    consensus_candidates: Set[CandidateRef]
    dissenting_candidates: Set[CandidateRef]
    discriminating_experiments: Set[ExperimentRef]
    unresolved_claims: Set[ClaimRef]
    round_history: EventRange
}
```

Consensus повышает priority предложения, но не fitness. Независимый evaluator решает, какая ветвь выживает.

## 13. Эволюция и search

### 13.1 Candidate и genome

```text
Candidate[G] {
    id: ContentHash
    genome: G
    mutation_scope: MutationScope
    parents: Set[CandidateRef]
    lineage: LineageId
    created_by: MutatorRef
    hypothesis: Claim
    predicted_effect: Distribution | Interval | unknown
    falsification_test: ExperimentRef
    evidence_view_digest: ContentHash
    status: proposed | admitted | evaluated | rejected | promoted
}
```

Genome MAY включать prompt, code, specification, context policy, memory policy, world model, council, mutator, search algorithm, orchestration graph, weights или task generator. Evaluator никогда не является частью genome в той же benchmark epoch.

### 13.2 Mutation scope lattice

```text
M0  output/sample only
M1  trajectory-local state and episodic memory
M2  prompts, skills, specification and context policy
M3  task solution code or policy
M4  mutator, search and credit assignment
M5  harness graph and orchestration
M6  model weights, decoder or latent checkpoint
M7  training task/environment generator
```

Каждый experiment объявляет максимальный `M_allowed`. Переход на более высокий уровень требует новой policy grant. Изменение evaluator, sealed split или promotion rule не является `M8`; оно создаёт новый `BenchmarkEpoch` и уничтожает сопоставимость с текущей эпохой.

### 13.3 Каталог mutation operators

```text
MutationOperator =
    zero_order
  | feedback_conditioned
  | reflective
  | hypermutation
  | lamarckian_distillation
  | estimation_of_distribution
  | self_referential
  | differential_semantic
  | novelty
  | adversarial
  | triz
  | delphi
  | crossover
  | custom[AdapterRef]
```

| Оператор | Обязательный вход | Назначение | Основной риск |
|---|---|---|---|
| `zero_order` | parent + entropy | широкое исследование без feedback | пустая выборка |
| `feedback_conditioned` | measurements/errors | локальная целевая правка | переобучение на feedback |
| `reflective` | trajectory/evidence | причинная гипотеза и правка | правдоподобная конфабуляция |
| `hypermutation` | plateau signal | несколько крупных изменений | потеря полезного lineage |
| `lamarckian_distillation` | successful trajectories | перенести найденное поведение в prompt/memory/code/weights | закрепить shortcut |
| `estimation_of_distribution` | selected population | сэмплировать общие паттерны успеха | collapse разнообразия |
| `self_referential` | mutator genome | улучшить генератор мутаций | self-evaluation loop |
| `differential_semantic` | минимум 2–3 кандидата | применить смысловую разницу | аналогия некаузальна |
| `novelty` | behavioral descriptors | удалённое поведение | novelty без utility |
| `adversarial` | contract/evaluator surface | найти failure/reward hacking | dual-use exploits |
| `triz` | contradiction model | систематически разрешить trade-off | ритуальная классификация |
| `delphi` | независимые diagnoses | consensus, dissent и discriminating tests | correlated panel |

Эти операторы **не являются частями GEPA по умолчанию**. GEPA соответствует конфигурации с trajectory-conditioned reflective mutation и Pareto-style retention; остальные операторы являются расширениями AHSL.

TRIZ полезна как typed proposal generator:

```text
TRIZProblem {
    improving_parameter: MetricRef
    worsening_parameter: MetricRef
    contradiction: technical | physical | administrative
    resources: Set[ArtifactRef | CapabilityRef]
    ideal_final_result: Predicate
    forbidden_effects: Set[Effect]
}
```

TRIZ operator MAY выдать transformations и experiments, но MUST NOT менять fitness, constraints или evaluator. Репозиторий [snow-ghost/triz](https://github.com/snow-ghost/triz) может быть adapter/knowledge base; его наличие не изменяет authority model.

### 13.4 Mutator

```text
Mutator[G] {
    parents: List[Candidate[G]]
    evidence: EvidenceView
    operator: MutationOperator
    entropy: Set[EntropySourceRef]
    budget: Budget
    write_scope: Set[ResourcePattern]
    child_count: Bound
    output: NonEmptySet[Candidate[G]]
}
```

Mutator MUST записать operator, evidence view, prompts/programs, seeds, parent digests и predicted mechanism. Он не имеет права score или promote.

### 13.5 Search budget и SimpleTES-разложение

```text
SearchBudget {
    C: Int  // independent trajectories
    L: Int  // refinement depth
    K: Int  // local candidates per step
    Phi: ContextComposerRef
    token_cap: Int
    action_cap: Int
    wall_clock_cap: Duration
    monetary_cap: Decimal
}
```

Номинальное число evaluations `C*L*K` не заменяет полный resource ledger. Сравниваемые harnesses MUST иметь одинаковые caps или показывать Pareto frontier quality-cost.

### 13.6 CreditAssigner

```text
CreditAssigner {
    granularity: action | segment | candidate | lineage
    signal: terminal | dense | counterfactual | peer | formal
    rule: AdapterRef
    uncertainty: Estimator
    leakage_policy: PolicyRef
}
```

Credit MAY переноситься от финального результата на ранние действия, но attribution MUST храниться отдельно от raw reward и MUST NOT считаться causal fact без counterfactual evidence.

### 13.7 Evaluator

```text
Evaluator {
    implementation: Artifact[Program | FormalProofChecker]
    oracle: Option[Artifact]
    splits: Map[train | public | development | private | sealed, DatasetRef]
    metrics: Set[Metric]
    constraints: Set[Predicate]
    replicates: ReplicationPolicy
    uncertainty: Estimator
    anti_gaming: Set[Test]
    epoch_policy: immutable_within_epoch
}
```

```text
EvaluationAttestation {
    candidate_digest: ContentHash
    evaluator_digest: ContentHash
    epoch_digest: ContentHash
    dataset_partition_digests: Set[ContentHash]
    environment_digest: ContentHash
    seed_manifest: ArtifactRef
    raw_measurements: ArtifactRef
    aggregate_metrics: Map[MetricRef, Value]
    uncertainty: Map[MetricRef, Interval | Distribution]
    violations: Set[InvariantRef]
    resource_usage: ResourceUsage
    signature: Attestation
}
```

LLM-as-judge MAY классифицировать failures и создавать diagnoses, но promotion MUST зависеть от формального oracle, независимого evaluator или заранее объявленной human protocol там, где объективный oracle невозможен.

### 13.8 Selector и Archive

```text
Selector {
    eligibility: Predicate
    rule: scalar | lexicographic | pareto | tournament | map_elites
    tie_break: List[Criterion]
    promotion_threshold: Predicate
    authority: recommend_only
}

Archive {
    kind: flat | pareto | map_elites | islands
    descriptor: Option[PureFunction[Candidate, Vector]]
    replacement: Rule
    capacity: Bound
    epoch: EpochRef
}
```

Only kernel promotes. Behavioral descriptors MUST быть versioned pure functions; смена descriptor создаёт новую archive epoch или audit-migration.

## 14. Самомодификация и RSI

AHSL различает два режима.

### 14.1 Online adaptation

Внутри текущего run агент MAY изменять только явно writable M1/M2 resources: episodic memory, hypotheses, context views или session-local skills. Эти изменения являются частью trajectory и не подменяют исходный subject после начала оценки.

### 14.2 Offline evolution

Изменения M2–M7 создают новый Candidate, исполняются в isolated/shadow environment, оцениваются независимо и могут быть применены только в следующей epoch.

### 14.3 RSI ladder

```text
R0  no adaptation
R1  delegation/search improves task outcome
R2  net-positive self-improvement after accounting for search cost
R3  improvement generalizes to held-out task families
R4  improved improver accelerates future improvement (inflection)
```

Переход на R2+ требует matched-budget baseline, multiple seeds, held-out families и учета стоимости outer loop. Рост public benchmark score не доказывает RSI.

### 14.4 Meta non-interference

Meta-candidate, меняющий mutator/search/harness:

1. MUST выполняться в shadow epoch;
2. MUST NOT видеть собственный sealed evaluation;
3. MUST сравниваться минимум с parallel sampling, sequential refinement и предыдущим frozen harness при равном бюджете;
4. MUST проходить regression, complexity и anti-gaming gates;
5. MUST NOT расширять собственные capabilities;
6. MAY быть promoted только kernel в следующую epoch.

## 15. Authority, capabilities и information flow

### 15.1 Политика

```text
authorize(principal, action, resource, context) -> allow | deny
```

Семантика: `default_deny` и `deny_overrides`.

Effective delegated capability:

```text
Cap_effective = Cap_parent
              intersection Cap_call
              intersection Cap_resource
              intersection Cap_provider
              intersection Cap_epoch
```

Ограничение MUST передаваться через model APIs, remote browsers, server-side URL fetching, code interpreters, subagents и все дальнейшие delegates. Provider-side действие считается эффектом исходного principal, даже если локальный процесс не имеет сети.

### 15.2 Taint и declassification

Security labels образуют lattice. Flow разрешён только в сторону не менее строгой метки. Declassification требует trusted node, конкретного projection schema, audit reason и отдельной capability. Prompt или model output не могут выдать себе declassification.

### 15.3 Матрица authority профиля `safe_research`

| Роль | Propose | Execute candidate | Read sealed | Score | Promote | Allocate/terminate |
|---|---:|---:|---:|---:|---:|---:|
| Task agent | Да | Через kernel | Нет | Нет | Нет | Нет |
| Mutator/Council | Да | Нет | Нет | Нет | Нет | Нет |
| Environment designer | Да | Только training/shadow | Нет | Нет | Нет | Нет |
| Evaluator | Нет | Через kernel | Да | Да | Нет | Нет |
| Selector | Нет | Нет | Aggregate only | Нет | Recommend | Нет |
| Auditor | Нет | Read-only replay | По policy | Проверяет attestation | Нет | Нет |
| Policy kernel | Нет | Да | Да | Фиксирует | Да | Да |

Kernel владеет worktree/container creation, evaluator invocation, budget reservation, rollback, promotion и final termination.

## 16. Обязательные инварианты

### 16.1 Safety

1. **Append-only evidence.** Committed raw events не изменяются и не удаляются in place.
2. **Provenance completeness.** Каждый derived artifact ссылается на generating event и все прямые зависимости.
3. **Authority confinement.** Нет effect без effective capability.
4. **Transitive confinement.** Delegate не получает больше authority, чем вызывающий principal.
5. **Evaluator isolation.** Candidate не читает и не изменяет evaluator, oracle, private data, seeds и promotion state.
6. **Promotion integrity.** Promotion требует matching candidate/evaluator/epoch digests и valid attestation.
7. **Epoch immutability.** Contract, evaluator, metrics, gates и sealed split фиксированы внутри epoch.
8. **Meta non-interference.** Meta-candidate не влияет на собственную оценку.
9. **Budget monotonicity.** Остаток бюджета не увеличивается без внешнего grant event.
10. **Secret noninterference.** Sealed value не попадает в candidate-visible output без trusted declassification.
11. **Context non-authority.** Отсутствие факта в context не удаляет ledger state и не отменяет policy.
12. **Rollback completeness.** Failed execution не меняет protected state, кроме evidence и consumed non-refundable resources.
13. **Termination ownership.** Agent MAY request, но не apply termination.
14. **Prediction accountability.** При `falsifiable_action` действие связано с предварительным прогнозом и его outcome.
15. **Generator/evaluator separation.** Training task generator не сертифицирует собственный solver в той же epoch.

### 16.2 Liveness

- каждый admitted candidate в конечном итоге evaluated или terminally classified;
- каждый run завершается success, declared failure, deadline или budget exhaustion;
- reservation failed transaction освобождается за bounded time;
- promoted artifact получает post-promotion regression evaluation;
- recovery после kernel restart завершается replay до последнего committed event.

### 16.3 Statistical integrity

- stopping rule объявлен до просмотра sealed outcomes;
- число replicates и confidence procedure версионированы;
- множественный поиск учитывается через holdout, nested evaluation либо correction policy;
- public feedback и sealed feedback имеют разные information labels;
- reported best-of-N всегда сопровождается N и total resource use.

## 17. Progressive Harness Stability Benchmark (PHSB)

### 17.1 BenchmarkEpoch

```text
BenchmarkEpoch {
    id: ContentHash
    task_generator: Artifact[Program]
    task_families: Set[TaskFamily]
    public_split: DatasetRef
    development_split: DatasetRef
    sealed_split: DatasetRef
    oracle: ArtifactRef
    capability_policy: PolicyRef
    fault_schedule: ArtifactRef
    resource_budgets: Set[Budget]
    complexity_schema: TypeRef
    metrics: Set[Metric]
    gates: OrderedList[Gate]
    baseline_manifest: ArtifactRef
}
```

Epoch digest публикуется до запуска; sealed task contents остаются скрытыми. Generator и oracle MAY обновляться только между epochs после audit. Сравнение разных epochs требует explicit migration report и не считается прямым score improvement.

### 17.2 Вектор сложности

Task complexity:

```text
chi_task = (H_star, s, b, o, delta, phi)
```

| Компонент | Значение |
|---|---|
| `H_star` | минимальное число эффективных действий оптимальной политики |
| `s` | максимальная глубина вложенных subgoals/condition branches |
| `b` | число одновременно поддерживаемых целей и join dependencies |
| `o` | сложность наблюдения/частичная наблюдаемость и state size |
| `delta` | сдвиг относительно public/training distribution |
| `phi` | fault/adversarial pressure: failures, injections, stale state, canaries |

Отдельно объявляются adaptation scope `mu in {M0..M7}` и budget vector `beta`. Нельзя смешивать более трудную задачу, больший mutation surface и больший compute в одно число.

### 17.3 Лестница уровней

| Уровень | Что измеряется | Минимальный gate |
|---|---|---|
| `L0 Kernel` | replay, types, budgets, rollback | одинаковый committed state после restart/replay |
| `L1 Containment` | authority и anti-gaming | ноль protected-effect violations и canary escapes |
| `L2 Bounded optimization` | улучшение одного фиксированного решения при M3 | корректность + cost/quality gain на hidden seeds |
| `L3 Structural transfer` | новые размеры, структуры и task families | положительный sealed transfer без retuning |
| `L4 Long horizon` | рост `H_star,s,b,o`, память и recovery | reliability curve выше baseline + bounded recovery |
| `L5 Orchestration` | councils/subagents/concurrency | gain после учёта total budget и correlation |
| `L6 Meta-evolution` | M4/M5 improvement | held-out gain над frozen harness и scaling baselines |
| `L7 Open curriculum` | M6/M7 и co-evolution | независимый frozen certification epoch, no collapse |

Каждый уровень включает regression suite всех предыдущих уровней.

Anthropic `original_performance_takehome` является хорошим экземпляром `L2/M3`: фиксированная задача, строгая корректность и стоимость в simulated cycles. Для PHSB его нужно расширить hidden structural parameters, несколькими workload families, вынесенным evaluator, immutable test mount, deterministic seed manifest, injected failures и repeated runs. Факт изменения тестов агентами — обязательный canary для L1, а не просто anecdote. [Источник](https://github.com/anthropics/original_performance_takehome).

### 17.4 Метрики стабильности

Для уровня `l`, бюджета `beta` и повторов `r`:

```text
R_l(beta) = P(all_hard_gates_pass | level=l, budget=beta)
U_l       = normalized task utility conditional on pass
CVaR_q    = mean utility in the worst q fraction of valid runs
Rec       = P(recover within budget | injected recoverable fault)
Inv       = count and severity of invariant violations
Cost      = total tokens + actions + wall time + money + training compute
```

Рекомендуемый headline:

```text
L_p_star = max l such that lower_confidence_bound(R_l(beta)) >= p
```

Публикуются как минимум `p=0.80` и `p=0.95`; 99% MAY использоваться только при достаточном числе независимых tasks/runs. Один successful run не является stability evidence.

### 17.5 Порядок ранжирования

Lexicographic rank:

1. ноль critical invariant violations;
2. максимальный полностью пройденный level;
3. максимальный lower confidence bound reliability;
4. максимальный `CVaR_0.10` normalized utility;
5. максимальный recovery rate;
6. минимальная полная стоимость;
7. минимальная complexity/dead-code penalty.

Average и best score MAY публиковаться только как secondary metrics.

### 17.6 Matched-budget baselines

Каждый evolutionary/meta result MUST сравниваться с:

- single frozen harness;
- independent parallel sampling;
- sequential refinement;
- incumbent human-authored harness;
- ablation без council/memory/world model;
- тем же числом environment interactions и равным total cost.

Это отделяет архитектурное улучшение от простого test-time compute scaling.

### 17.7 Task generation и self-play

PSV показывает ценность формального verifier для self-play code tasks; Self-Play SWE-RL — bug injection/repair с test patch; Dr. Zero — proposer/solver curriculum; SPADE — complete executable MDP environments с adaptive hint-regret. В AHSL это четыре конфигурации `EnvironmentDesigner + Solver + CreditAssigner`, но certification требует frozen external verifier и sealed families. Совместный model checkpoint MAY играть обе training roles, однако role-separated events, contexts и authority всё равно обязательны.

## 18. Conformance profiles

| Profile | Обязательные модули |
|---|---|
| `core` | types, artifacts, principals, graph, events, effects, policy |
| `replayable` | seed manifest, append-only ledger, snapshots, recovery |
| `memory` | derived memory, retrieval, negative bank, utility |
| `world_model` | hypotheses, predictions, backtest, invalidation |
| `council` | independent rounds, ballots, aggregation, dissent |
| `evolution` | candidates, mutators, budgets, credit, selector, archive |
| `research` | isolated evaluator, attestations, staged gates, promotion |
| `meta` | shadow epochs, matched baselines, mutation scope M4/M5 |
| `latent` | training/distillation, checkpoint lineage, transfer audit |
| `benchmark` | BenchmarkEpoch, complexity vector, reliability curves |
| `verified` | model-checked kernel invariants, sealed eval, signed attestations |

Система заявляет только реализованные profiles.

## 19. Компиляция существующих систем в AHSL

| Система/идея | Представление в AHSL | Что не следует путать |
|---|---|---|
| DeepSeek Harness | backend adapters, plugin registry, sessions, event stream | runtime не заменяет normative authority semantics |
| Alex Zhang Harness/RLM | `ContextProjection`, `ContextComposer`, subcalls, programmatic context | локальная удобность не доказывает global correctness |
| Prime Agent | persistent trajectory, memory CRUD, REPL snapshot, `/refine` | live refinement не равно certified meta-evolution |
| [Duck Harness](https://tufalabs.ai/research/duck-harness/) | REPL environment, multimodal observation projection, bounded action loop | дешёвый task-specific backend не универсальная memory/policy model |
| GEPA | reflective trajectory-conditioned mutator + Pareto selection | не весь каталог mutation operators |
| PromptBreeder | self-referential M4 mutator | mutation prompt не оценивает себя |
| MAP-Elites | archive with pure behavioral descriptor | diversity не равно quality |
| SimpleTES | `C,L,K,Phi` budget decomposition | gain без matched budget не архитектурный |
| LLM Council/Delphi | advisory multi-round decision/mutation service | consensus не evaluator |
| TRIZ | contradiction-driven proposal generator | heuristic не promotion rule |
| ARC-skill | `falsifiable_action` + prediction grading | public-set success не hidden transfer |
| Schema Harness | executable `WorldModel` + backtest + search | модель мира ограничена evidence scope |
| PRO-LONG / прежний RGB-Agent URL | RawLedger + programmatic retrieval | полный лог не обязан целиком входить в context |
| MemRL | relevance filter + learned utility | similarity и utility разные сигналы |
| TELL | persistent hypothesis/world-model memory | MEMORY.md — derived view, не единственная истина |
| [Vision-CL](https://github.com/vansh-one/arc-agi-3_Vision-CLv1) | M6 `LatentCheckpoint` с двухфазным explore/freeze protocol | latent weights требуют lineage, leakage и transfer audit |
| [ARC general-agent baselines](https://github.com/astroseger/arc-3-agents-baseline1) | textual/executable world-model profiles и fresh-workspace baseline | public saturation прямо не доказывает unseen-game generalization |
| PSV | proposer/solver + formal verifier | verifier должен быть внешним при certification |
| Self-Play SWE-RL | test-specified bug proposer/repairer | generated tests могут быть неверны/играбельны |
| Dr. Zero | difficulty-aware proposer/solver search curriculum | solvability proxy требует sealed transfer eval |
| SPADE | M7 executable environment designer + solver + regret credit | co-evolving verifier не независимый benchmark oracle |
| AIDE² | outer M4/M5 harness evolution over inner task search | RSI claim требует net cost и held-out generalization |
| [Hyperagents](https://arxiv.org/abs/2603.19461) | единый editable task/meta program с M4/M5 self-reference | current evaluator/policy всё равно вне mutable closure |
| [AEvo / Harnessing Agentic Evolution](https://arxiv.org/abs/2605.13821) | process-level evolution state + meta-agent, редактирующий будущую procedure/context | meta-edit не получает score/promotion authority |
| Autoresearch | locked kernel + isolated M3 candidates + staged evaluator | candidate не владеет termination/promotion |

## 20. Нормативный пример Autoresearch

```yaml
ahsl: '0.2'
experiment: 'durak_memoryless_search'
profiles: ['core', 'replayable', 'evolution', 'research', 'benchmark']

epoch:
  immutable: true
  contract: 'program.md'
  evaluator: 'sha256:evaluator-digest'
  policy: 'sha256:policy-digest'

artifacts:
  engine:
    path: 'durak/src/engine.cpp'
    mutable: false
  candidate:
    path: 'durak/src/strategy_heuristic.cpp'
    mutable: true
    mutation_scope: 'M3'
  ledger:
    path: 'results.tsv'
    mode: 'append_only'

environment:
  adapter: 'durak_simulator'
  observation: 'DurakObservation'
  action: 'LegalMove'
  entropy:
    kind: 'rng'
    seedable: true
    policy: 'paired_splitmix64'

search:
  budget:
    C: 4
    L: 5
    K: 2
    Phi: 'trajectory_summary_plus_failure_bank'
  mutators: ['reflective', 'novelty', 'adversarial', 'delphi']

council:
  trigger: 'plateau(5) or conflicting_evidence'
  independence: 'isolated_context'
  identity_policy: 'labels_hidden'
  ballot: 'rank'
  aggregator: 'condorcet_minimax'
  preserve_dissent: true
  authority: 'propose_only'

evaluator:
  epoch_policy: 'immutable_within_epoch'
  gates:
    - name: 'smoke'
      seeds: 5000
      reject_on: ['crash', 'illegal_move', 'protected_write']
    - name: 'quick_b4'
      seeds: 100000
    - name: 'ladder'
      opponents: ['B4', 'B1', 'B0']
    - name: 'full'
      seeds: 5000000
      visibility: 'sealed'
  rank:
    rule: 'lexicographic'
    eligibility:
      - 'search_score >= current_best + 0.005'
      - 'lower_ci >= current_best_lower_ci'
    tie_break: ['minimize_complexity']

policy:
  default: 'deny'
  combine: 'deny_overrides'
  permit:
    - ['mutator', 'read', 'candidate_visible_evidence']
    - ['mutator', 'modify', 'candidate_worktree']
    - ['kernel', 'evaluate', 'candidate_worktree']
    - ['kernel', 'promote', 'attested_candidate']
  forbid:
    - ['candidate', 'read', 'sealed_evaluator']
    - ['candidate', 'modify', 'contract_or_tests']
    - ['candidate', 'allocate', '*']
    - ['candidate', 'terminate', 'experiment']
```

Смысл примера: эволюционирует только `strategy_heuristic.cpp`; engine, scorer, RNG contract, tests, CMake, budgets и promotion находятся вне candidate namespace. Council добавляет ветви, но не меняет score. Full evaluation выполняется kernel в изолированном worktree/container.

## 21. Static checks и runtime audits

### 21.1 Минимальные static checks

1. Все ports и edges типизированы.
2. Все effects объявлены.
3. Loop имеет bound/variant и stop owner.
4. Capability chain не расширяет parent rights.
5. Candidate path не пересекается с evaluator/policy/sealed paths.
6. Security labels не создают запрещённый flow.
7. Mutation scope не превосходит epoch grant.
8. Council не имеет `score` или `promote` effect.
9. Meta-candidate не исполняется в current certification epoch.
10. Benchmark rank ссылается только на declared metrics и gates.

### 21.2 Минимальные runtime audits

1. Replay deterministic run даёт тот же committed state и digests.
2. Denied request меняет только ledger и расход на саму проверку.
3. Failed transaction освобождает reservations и откатывает protected writes.
4. Каждый promoted artifact восстанавливается по provenance DAG.
5. Evaluation attestation соответствует candidate/evaluator/epoch digests.
6. Изменение tests/evaluator обнаруживается до scoring.
7. Server-side fetch obeys originating capability chain.
8. Summary omission не отменяет active hard constraints.
9. Prediction miss invalidates dependent queued plan.
10. Sealed outcomes не появляются в mutator context.
11. Best-of-N report содержит N и полный cost.
12. Restart/recovery не создаёт дубликаты committed effects.

## 22. Specification-driven development

Рекомендуемый порядок реализации:

1. Зафиксировать canonical JSON schema, content hashing и identifiers.
2. Написать property tests для kernel transition semantics.
3. Реализовать ledger, artifacts, transactions и deterministic replay.
4. Реализовать capability lattice, transitive delegation и taint tracking.
5. Реализовать isolated executor/evaluator и attestations.
6. Скомпилировать существующий Autoresearch contract в AHSL и доказать отсутствие дополнительных writable surfaces.
7. Добавить Memory/ContextProjection и измерение compression loss/evidence coverage.
8. Добавить Evaluator, Selector, Archive и mutation registry.
9. Добавить Council/DecisionService adapters.
10. Реализовать PHSB L0–L3 до meta-evolution.
11. Добавить long-horizon fault injection, recovery и L4–L5.
12. Только после этого разрешить M4–M7 shadow experiments.
13. Экспортировать traces в OpenTelemetry/W3C PROV-compatible представление.
14. Перенести kernel state machine и ключевые invariants в TLA+/Alloy/Lean по мере критичности.

MVP — это не библиотека всех agent techniques. Это маленькое проверяемое ядро, event/evidence model, evaluator boundary и adapter ABI. Всё остальное расширяется registry-компонентами.

## 23. Критерии готовности AHSL 0.2 implementation

Implementation считается готовой к экспериментам, когда:

- один и тот же AHSL spec компилируется минимум в два backend runtime;
- replay L0 проходит после process crash;
- intentional evaluator/test modification блокируется до score;
- candidate не может расширить capability через subagent или provider-side tool;
- council, GEPA-style mutator и zero-order baseline сравниваются при matched budget;
- memory summary можно удалить и перестроить из raw ledger;
- Autoresearch run воспроизводится по spec, artifact digests и seed manifest;
- PHSB публикует reliability curve и worst-tail metrics, а не только best score;
- M4/M5 candidate оценивается в shadow epoch и не может продвинуть себя.

## 24. Итоговая формула системы

Полная конфигурация harness задаётся как:

```text
Harness = (
    Spec, Graph, Agents, Environments,
    ContextProjections, Memory,
    DecisionServices, Evolution,
    PolicyKernel, EventLedger,
    Evaluators, BenchmarkEpochs
)
```

А один шаг системы имеет вид:

```text
stochastic proposal
  + explicit entropy
  + typed evidence view
  -> deterministic authorization and execution
  -> immutable event/evidence
  -> independent evaluation
  -> external promotion or rollback
```

Это сохраняет полезную стохастичность поиска, но делает власть, проверку и научное утверждение стабильными.

## 25. Вывод

Исходный цикл **task → formalization → specification/world → iteration** является центральным, но после исследования он уточняется:

> task → formal specification → bounded execution → immutable trajectory → condensation → competing formal models → falsification → independent evaluation → externally authorized evolution

Главное ограничение: нельзя «эволюционировать trajectory» как свободный текст и считать это улучшением системы. Можно эволюционировать только объявленный genome, используя trajectory как доказательство; затем независимый evaluator проверяет изменение на frozen epoch. Хорошая спецификация и формальные интегрируемые метрики не отменяют эволюцию — они превращают её из стохастического рассказа в контролируемый эксперимент.
