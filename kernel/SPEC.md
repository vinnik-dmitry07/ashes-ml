# AHSL-Core 0.5 — нормативная исполняемая спецификация

Дата: 5 сентября 2026 года. Профиль: `transactional_event_core`.

## 1. Статус, область и единственный источник семантики

Эта редакция задаёт замкнутый язык событий для вызова компонентов и атомарного изменения версионированного состояния. Она заменяет нормативный статус AHSL 0.4. Прежний документ сохранён как `AHSL-0.4-design.md`: это **информативный архитектурный проект**, а не дополнительные правила данной версии.

Нормативными являются функции `load_json`, `initial`, `validate_event`, `proposal_error`, `apply_event`, `step` и вызываемые ими валидаторы в приложенном `core.py`. Они составляют исполняемое определение языка на Python 3.10+ со стандартной библиотекой. У кода нет сетевых запросов, исполнения произвольного кода, случайности, чтения часов или неявного состояния. Точная поставка фиксируется SHA-256 в `manifest.lock.json`.

Математические определения и таблицы ниже объясняют тот же переход. При обнаружении противоречия нормативным остаётся закреплённый код; противоречие считается дефектом документации и требует исправления версии. Недопустимо выбирать удобную интерпретацию разных текстов. TLA+-модель — отдельная проверочная абстракция, её область указана в §12.

**Это формально определённая исполняемая семантика малого профиля. Это не доказанная эквивалентность Python и TLA+, не проверенный production runtime и не формализация всех возможностей проекта AHSL.**

В ядро входят:

- точный формат данных, статический реестр компонентов и типизация входов/выходов;
- снимки чтений, монотонные версии, Create/Replace/Delete по заранее объявленным адресам;
- конкурентные вызовы, резервирование, списание, неизвестный результат и отмена до запуска;
- отзыв допуска, атомарное применение предложения, идемпотентность при повторной доставке;
- журнал и точное восстановление управляющего состояния.

Отдельные расширения, **не входящие** в это соответствие: язык графовой оркестрации, release/certification, статистические тесты улучшения, доказательство полноты зависимостей артефактов, динамическая регистрация компонентов, изменение типов, миграции исполняющегося процесса, криптография, защита ОС и физическое исполнение инструментов. Неизвестные конструкции отклоняются. Неподдерживаемая возможность не получает неопределённую default-семантику.

## 2. Математическая область

Используются конечные отображения, конечные упорядоченные списки и обычное структурное равенство. Порядок ключей отображения незначим; порядок элементов списка значим. Строки сравниваются по последовательности Unicode code points без нормализации. Все операции выполняются над конечными значениями.

\[
N=\{0,\ldots,2^{31}-1\},\qquad
T=\{unit,bool,nat,text,ref\}.
\]

`Id` — строка, полностью соответствующая регулярному выражению `[A-Za-z][A-Za-z0-9_.-]{0,127}`. `Text` — конечная строка Unicode без surrogate code points U+D800–U+DFFF. `Bool` содержит только `true` и `false`; boolean не является натуральным числом.

Абстрактные значения и их **единственная допустимая JSON-форма**:

| Тип | Форма | Дополнительное условие |
|---|---|---|
| Unit | `{"type":"unit"}` | Поля `value` нет |
| Bool | `{"type":"bool","value":b}` | `b` — JSON boolean |
| Nat | `{"type":"nat","value":n}` | `n` — JSON integer из N |
| Text | `{"type":"text","value":s}` | `s` — Text |
| Ref | `{"type":"ref","value":r}` | `r` — Id |

`Ref` в ядре — непрозрачный идентификатор. Ядро не разыменовывает его и не доказывает неизменность внешнего объекта. Строка, содержащая программу или промпт, остаётся данными. Компонент может интерпретировать её за пределами ядра; это не добавляет ему прав записи.

Входные JSON-документы MUST NOT содержать повторные ключи, дробные числа, экспоненциальную запись чисел, NaN/Infinity, отрицательные или выходящие за N integer-значения, непарные surrogate. Проверка происходит в `load_json`; native JSON `null` допустим как промежуточное JSON-значение, но не как Value. Все описанные ниже записи имеют **ровно** перечисленные поля. Опциональных полей и подразумеваемых default нет.

## 3. Синтаксис начальной конфигурации

В записи `Map(K,V)` ключи и значения имеют указанные типы, `List(X)` — конечный список, `UniqueList(X)` — список без повторов.

```text
Manifest = {
  version: "0.5",
  budget: Nat,
  cells: Map(Id, CellInit),
  components: Map(Id, Component)
}

CellInit = {type: Type, live: Bool, value: Value}

Component = {
  inputs: Map(Id, Type),
  output: Type,
  read: UniqueList(Id),
  write: UniqueList(Id),
  cost: Nat
}
```

`Type` — одна из строк T. Для каждой ячейки тип `value` совпадает с полем `type`, включая неактивные ячейки. Все адреса `read` и `write` существуют в `cells`. Имена компонентов и ячеек уникальны внутри своих отображений; их пространства имён раздельны.

Реестр и типы неизменны в одном исполнении. `Create` активирует заранее объявленную неактивную ячейку; он не создаёт новый адрес. Для нового адреса или другого типа требуется новое исполнение с другим Manifest. Такая граница устраняет неоговорённые правила изменения схемы.

Для компонента c:

\[
F_c=Read_c\cup Write_c.
\]

При вызове компонент получает снимок **всего** F_c, включая значения ячеек записи. Следовательно, в данном профиле право записи включает доступ к снимку записываемой ячейки. Профиль не заявляет поддержку write-only secret cells.

`cost` — максимальный допустимый charge одного вызова в одной объявленной единице ресурса. Физический смысл единицы и достоверность измерения задаёт адаптер. Нулевой cost допустим. Утверждение conservation относится к этим кредитам; оно не доказывает ограничения RAM, CPU или денежных расходов провайдера.

## 4. Полное состояние ядра

\[
S=(M,C,J,a,z,e,R,I,L).
\]

| Символ / поле кода | Область и смысл |
|---|---|
| M / `manifest` | Зафиксированный Manifest |
| C / `cells` | Map(Id, Cell) с теми же адресами, что M.cells |
| J / `jobs` | Map(Id, Job); идентификаторы не переиспользуются |
| a / `available` | Доступные кредиты |
| z / `spent` | Уже списанные кредиты |
| e / `epoch` | Версия политики из N |
| R / `revoked` | Упорядоченный по Id список отозванных компонентов без повторов |
| I / `seen` | Map(EventId, Record) для обработанных событий |
| L / `log` | Упорядоченный список тех же Record |

```text
Cell = {type: Type, live: Bool, value: Value, version: Nat}

Job = {
  component: Id,
  args: Map(Id, Value),
  snapshot: Map(Id, Cell),
  epoch: Nat,
  status: reserved | running | unknown | done | cancelled,
  held: Nat,
  charged: Nat,
  result: null | JobResult
}

Record = {principal: Principal, event: Event, result: EventResult}
```

Снимок — копия C, ограниченная F_c на момент reserve. У него нет последующего неявного refresh. Типы, значения, флаг live и версии входят в копию.

Начальное состояние:

\[
C[s]=(M.cells[s],version=0),\quad
a=M.budget,\quad z=e=0,
\]

а J, R, I и L пусты. Все последующие состояния определяются исключительно применением `step` к достижимому состоянию. Прямое редактирование сериализованного S не является действием языка. Валидация произвольного внешнего checkpoint в эту версию не входит.

## 5. Полная грамматика событий

Principal — ровно `agent`, `provider` или `supervisor`. Это аргумент доверенного адаптера, **не поле события, которому можно поверить со слов модели**.

Все формы имеют обязательные `id: Id` и `kind`. Остальные поля перечислены полностью:

| kind | Поля | Допустимый principal |
|---|---|---|
| `reserve` | `job: Id, component: Id, args: Map(Id, Value)` | agent |
| `dispatch` | `job: Id` | agent |
| `cancel` | `job: Id` | agent |
| `unknown` | `job: Id` | provider |
| `complete` | `job: Id, charge: Nat, outcome: Outcome` | provider |
| `revoke` | `component: Id` | supervisor |

```text
Outcome = {
  kind: "failure", code: Id
} | {
  kind: "success", value: Value, writes: List(Write)
}

Write = {op: "create", cell: Id, value: Value}
      | {op: "replace", cell: Id, value: Value}
      | {op: "delete", cell: Id}
```

Здесь `code` в failure — непрозрачный код ошибки компонента, не инструкция ядру. Несоответствие Value выходному типу и повторные адреса writes являются семантическим отказом при завершении; структурно неверный Value является ошибкой схемы события. Это различие определяет, можно ли доверенно списать указанный charge.

Программа ядра — конечный упорядоченный список `{principal, event}`. Он задаёт один наблюдаемый сценарий, а не алгоритм генерации всех будущих ответов LLM. Промежуточный конец списка не завершает активные Job автоматически.

## 6. Единственная функция перехода

\[
Step:S\times Principal\times JSON
\longrightarrow S\times EventResult\times List(Request).
\]

Переход детерминирован. JSON здесь уже декодирован; синтаксически неверные байты отвергаются до Step. Достижимое корректное S является предусловием. Ограничения физической памяти интерпретатора не являются математическими ветвями перехода.

Порядок общей обработки строгий:

1. Неверный Principal или схема события: `(S, BAD_SCHEMA, [])`; I и L не меняются.
2. Уже существует I[id]: при структурном равенстве principal и всего event возвращаются S, сохранённый result и пустой список запросов. При отличии — `(S, EVENT_ID_REUSE, [])`.
3. Для нового корректного event неправильная роль даёт FORBIDDEN, иначе применяется соответствующий переход §7.
4. После пункта 3 в I и L записываются principal, исходное event и полученный result. Даже семантически отклонённое событие занимает id. Сами рабочие поля меняются только по §7.

Повтор старого id после изменения состояния не выполняет действие заново. Например, BUDGET с тем же id не превращается позже в успешный reserve. Для новой попытки нужен новый id.

Порядок ключей JSON не влияет на повторную доставку; порядок списка writes влияет. При повторной доставке успешного dispatch возвращается прежний OK, но новый Request не возникает. При неверной схеме id не занимает запись. За отдельный журнал повреждённого сетевого ввода отвечает адаптер; он не входит в L.

Во всех следующих переходах **неперечисленные поля сохраняются**. При отказе рабочие поля S неизменны; исключение — COMPLETE, чей внутренний JobResult может быть отказом при успешном событии SETTLED.

## 7. Переходы, guards и приоритет ошибок

В каждой строке guards проверяются слева направо; возвращается первая ошибка. Это правило входит в семантику. `[]` — отсутствие исходящего запроса.

### 7.1 RESERVE

Для `reserve(j,c,args)` guards:

1. j уже в J → JOB_EXISTS.
2. c отсутствует в M.components → NO_COMPONENT.
3. c принадлежит R → DENIED.
4. Множество имён args не равно множеству inputs либо хотя бы один тип не совпадает → INPUT_TYPE.
5. a < cost_c → BUDGET.

При успехе, q=cost_c:

\[
a'=a-q,
\quad J'[j]=(c,args,C|_{F_c},e,reserved,q,0,null).
\]

EventResult=OK, Request отсутствует. Копии args и snapshot не разделяют изменяемые объекты с вызывающей стороной. `reserved` означает, что внешнее выполнение ещё не разрешено.

### 7.2 DISPATCH

Guards: j отсутствует → NO_JOB; status ≠ reserved → BAD_PHASE; Job.epoch ≠ e → STALE_POLICY; component ∈ R → DENIED.

При успехе status'=running, EventResult=OK, возникает ровно один:

```text
Request = {
  job: Id, component: Id, args: Map(Id, Value),
  snapshot: Map(Id, Cell), max_charge: Nat
}
```

Поля копируются из Job, max_charge=held. Это разрешённое намерение вызова адаптеру, а не доказательство того, что действие произошло во внешнем мире.

### 7.3 CANCEL

Guards: j отсутствует → NO_JOB; status ≠ reserved → BAD_PHASE.

При успехе a'=a+held, held'=0, status'=cancelled, Job.result=CANCELLED. EventResult=OK. После dispatch отмена этим событием невозможна: ядро не выдумывает откат или возврат уже неизвестных затрат.

### 7.4 UNKNOWN

Guards: j отсутствует → NO_JOB; status ∉ {running,unknown} → BAD_PHASE.

При успехе status'=unknown, EventResult=OK. Held и spent сохраняются. Повтор UNKNOWN с новым id разрешён и добавляется в L; повтор с прежним id обрабатывается §6. Часы и автоматические timeout в ядре отсутствуют: событие сообщает адаптер о состоянии канала.

### 7.5 REVOKE

Guards: component отсутствует → NO_COMPONENT. Если он уже в R, возвращается OK без изменения epoch. Иначе при e=MAX_NAT → EPOCH_EXHAUSTED.

При успехе e'=e+1, R'=sort(R∪{component}), EventResult=OK. Это **глобальная** epoch: все прежние snapshots политики становятся устаревшими, включая вызовы других компонентов. Это намеренно консервативное правило, а не зависимость, оставленная реализации.

Новые reserve для неотозванных компонентов используют новую epoch. Старые reserved-вызовы можно отменить. Running/unknown-вызовы могут завершиться и оплатиться, но их успешные предложения не фиксируются по старой epoch. Обратного grant/re-enable в этом профиле нет.

### 7.6 COMPLETE: завершение и списание

Сначала guards: j отсутствует → NO_JOB; status ∉ {running,unknown} → BAD_PHASE; charge > held → CHARGE_EXCEEDS_RESERVE.

При этих отказах рабочее состояние не меняется: сверхрезервный charge не принимается частично. Корректный последующий ответ требует нового id. Достоверность receipt и фактической цены — предпосылка доверенного provider adapter.

После прохождения guards определяется внутренний JobResult:

- failure(code) → COMPONENT_FAILURE с `detail=code`, без записи ячеек;
- success(value,writes) → проверки §7.7 и либо их ошибка, либо SUCCESS(value).

**Для любого такого JobResult**, включая конфликт или неправильный тип:

\[
a'=a+held-charge,\qquad z'=z+charge,
\]

\[
held'=0,\quad charged'=charge,\quad status'=done.
\]

Job.result=JobResult. EventResult=`{"code":"SETTLED","result":JobResult}`. Ни отмена, ни повторное завершение done не разрешены. Ошибка результата не стирает уже совершённую работу.

### 7.7 SUCCESS: точное правило локального commit

Проверки выполняются **до любого изменения ячеек**:

| Приоритет | Условие отказа | JobResult.code |
|---|---|---|
| 1 | Job.epoch ≠ e | STALE_POLICY |
| 2 | component ∈ R | DENIED |
| 3 | Есть s ∈ snapshot: snapshot[s].version ≠ C[s].version | CONFLICT |
| 4 | Тип output Value не равен Component.output | OUTPUT_TYPE |
| 5 | В writes есть повторный адрес | DUPLICATE_WRITE |
| 6 | Адреса writes не являются подмножеством Component.write | WRITE_DENIED |

Затем записи проверяются по возрастанию Id ячейки. Для каждой, в указанном порядке:

1. version=MAX_NAT → VERSION_EXHAUSTED.
2. create при live=true либо replace/delete при live=false → CELL_LIFECYCLE.
3. create/replace с несовпадающим типом значения → WRITE_TYPE.

Проверка чтений охватывает **весь** F_c, даже если компонент фактически не использовал часть снимка или возвратил пустой writes. Пустой writes при свежем снимке допустим. Изменение любой прочитанной версии даёт конфликт; автоматического merge нет.

Если ошибок нет, для каждого адреса s в writes версия увеличивается на единицу. Create/Replace устанавливает live=true и указанное Value; Delete устанавливает live=false и сохраняет прежнее Value как payload tombstone. Поэтому Delete означает логическое отключение, **не стирание данных**. Снимки F_c содержат и tombstones; это не механизм конфиденциального удаления.

\[
\forall s\notin dom(writes):\quad C'[s]=C[s].
\]

Тип каждой ячейки неизменен. Даже замена значения на равное увеличивает версию. Delete/Create не возвращают старую версию. Истощение пространства версий не приводит к wraparound. Отсутствующие поля и новые адреса не создаются неявно.

## 8. Полные результаты и ошибки

События используют записи `{code: C}`, кроме SETTLED, у которого обязательно поле result. Вложенный JobResult имеет одну из форм:

```text
{code: "SUCCESS", value: Value}
{code: "COMPONENT_FAILURE", detail: Id}
{code: "CANCELLED"}
{code: SemanticFailureCode}
```

Полный набор одиночных EventResult.code:

```text
OK, BAD_SCHEMA, EVENT_ID_REUSE, FORBIDDEN, NO_COMPONENT,
JOB_EXISTS, DENIED, INPUT_TYPE, BUDGET, NO_JOB, BAD_PHASE,
STALE_POLICY, EPOCH_EXHAUSTED, CHARGE_EXCEEDS_RESERVE
```

Полный SemanticFailureCode: `STALE_POLICY`, `DENIED`, `CONFLICT`, `OUTPUT_TYPE`, `DUPLICATE_WRITE`, `WRITE_DENIED`, `VERSION_EXHAUSTED`, `CELL_LIFECYCLE`, `WRITE_TYPE`.

`BAD_SCHEMA` не переводит существующий Job в failure. SETTLED означает только завершение учёта вызова; его внутренний результат может быть отрицательным. `SUCCESS` означает принятие типизированного ответа и его записей, а не истинность ответа, рост качества, безопасность всего мира или прохождение certification.

## 9. Конкурентность, replay и внешняя граница

Разные Job могут находиться в running одновременно. Адаптер выбирает порядок наблюдаемых событий; это вход модели. Одна операция Step атомарна по локальному S. Два вызова, прочитавшие одну версию и изменяющие одну ячейку, не могут оба зафиксировать свои предложения: второй встретит CONFLICT. Даже если оба присваивают одно и то же значение, версия первого commit меняется.

Система хранения для соответствующей реализации должна реализовывать линейную последовательность Step, включая проверку snapshot и замену всего write set. Два независимых Python-процесса с локальными копиями S **не** дают такое свойство автоматически.

Replay применяет записи L от initial(M), сверяет каждый EventResult и восстанавливает S, включая seen и log. Исходящие Requests при replay не передаются внешнему исполнителю. На сохранённом логическом журнале воспроизводится управление, а не новая генерация LLM.

Точка фиксации запроса и физическая отправка запроса требуют durable outbox/идемпотентности провайдера либо иной доказанной схемы доставки. Она не реализована в этом комплекте. Один Request в модели не доказывает exactly-once effect в мире. После UNKNOWN без достоверного COMPLETE резерв может оставаться занятым навсегда. Liveness без предпосылки о будущем ответе не заявляется.

Роли должны присваиваться аутентифицированным адаптером. Поле `principal` в примере — доверенная тестовая фикстура. Возможность вручную написать `supervisor` в JSON-файле не является реализацией авторизации. `core.py` не запускает недоверенный Python и не является sandbox.

## 10. Свойства и их основания

Пусть B=M.budget. Для любого достижимого состояния:

\[
a+z+\sum_{j\in dom(J)}J[j].held=B,
\qquad a,z,J[j].held\ge0,
\]

\[
z=\sum_j J[j].charged.
\]

Terminal Job имеет held=0. Reserved/running/unknown Job имеет held=cost своего компонента. Версии не уменьшаются, типы ячеек сохраняются, неуказанные записи сохраняются, повтор события не создаёт новый Request.

Индуктивные обоснования по определению Step:

| Свойство | База | Сохраняющие переходы |
|---|---|---|
| Conservation | a=B, z=held=0 | Reserve переносит q из a в held; Cancel возвращает held; Complete переносит charge в z и остаток в a; прочие шаги не меняют сумму |
| Неотрицательность | Из Manifest | Reserve проверяет a≥q; Complete проверяет 0≤charge≤held; остальные изменения добавляют неотрицательные величины |
| Учёт charge | z=Σcharged=0 | Только Complete увеличивает оба на один и тот же charge; Job становится done и больше не завершается |
| Сохранение типов | CellInit.value соответствует type | Только успешные create/replace меняют value; до commit проверяется точное равенство типов |
| Frame condition | Тривиальна | Только цикл commit меняет C; он адресует ровно неповторяющиеся разрешённые записи |
| Отсутствие повторного dispatch | Job отсутствует | Единственный переход, создающий Request, меняет reserved→running; обратного перехода нет; повтор event не исполняется |
| Проверка свежести | Snapshot создаётся из C | Commit выполняется только при равенстве всех версий и epoch в единственной атомарной операции |

Это математические аргументы по случаям, **не машинно проверенные доказательства на Lean/TLAPS**. Их перенос на произвольную оптимизированную реализацию требует отдельного refinement proof. Наличие теста, совпадающего с названием свойства, не подменяет такое доказательство.

## 11. Как это связано с исходной задачей

Промпт, память, веса или mutator могут представляться значением ячейки, обычно Text или Ref. Provider-компонент получает разрешённый snapshot и возвращает предложение записи. Изменение проходит те же guards независимо от названия алгоритма. Изменяемое описание mutator не меняет саму функцию Step, статический реестр или полномочия supervisor.

GEPA, distillation и Delphi в этой модели — возможные производители Outcome, не встроенные доказательства прогресса. Между внутренним score и допуском записи нет неявного перехода. Для оценки качества нужен отдельный явно специфицированный профиль certification; его нет в `transactional_event_core`.

Старая конструкция Repeat с неопределённым переносом bindings здесь **не допускается**. Аналогично не допускаются старые Parallel, Handle, произвольные Contract и boolean-флаг полноты зависимостей как основание безопасности. Для графового frontend требуется отдельная точная семантика и отображение его наблюдаемых событий в это ядро. Сейчас язык ядра принимает только формы §5 и отвергает другие.

Это осознанное уменьшение области утверждения: формальная часть должна быть закрытой и реализуемой. Архитектурные идеи 0.4 сохранены, но не наследуют формальный статус только благодаря соседству с ядром.

## 12. Машинная проверка и её точная граница

`model/Kernel.tla` задаёт отдельную переходную систему TLA+. Она проверяется TLC. [TLA+ tools](https://github.com/tlaplus/tlaplus) и [описание TLC](https://lamport.azurewebsites.net/tla/tools.html) различают перебор конечной модели и доказательство свойств во всех размерах системы.

Проверенная конфигурация: три Job, один компонент, одна изменяемая ячейка, значения 0/1, cost=1, общий бюджет 2, один возможный отзыв. Charge принимает 0 или 1. Вызовы могут отменяться, становиться unknown, завершаться без записи или предлагать create/replace/delete, включая конфликтующие и недопустимые предложения.

Отображение в абстракцию: отсутствующий Job → idle; C.x → version/live/data; остальные управляющие поля соответствуют одноимённым переменным. Snapshot сворачивается к одной версии; I/L и конкретные EventResult удаляются; ошибки без изменения рабочего состояния отображаются в stuttering. Прочие неизменяемые ячейки опускаются. Payload ограничен значениями 0/1. Дополнительные `dispatched` и `writes` — счётчики для проверки истории.

Это описание отображения, а не машинно доказанная симуляция Python в TLA+. Поэтому результат TLC относится к указанной модели. Проверки Python дополнительно охватывают типы, роли, ошибочные данные, повтор доставки, replay и алиасы изменяемых объектов, отсутствующие в абстракции.

TLC 2.19, tools release v1.7.4: **69 475 сгенерированных состояний, 6 942 различных, очередь полностью исчерпана, глубина 11; нарушений восьми инвариантов не найдено.** Проверка deadlock отключена намеренно: терминальные состояния и отсутствие ответа среды допустимы. Fairness и eventual completion не проверяются. TLC использует fingerprinting; это не сертификат доказательства в proof assistant.

Python conformance suite и точные версии файлов перечислены в `verification.json` и `manifest.lock.json`. Фикстура examples показывает два конкурентных вызова: оба оплачиваются, только первый commit принят. Вторая запись отклоняется после UNKNOWN из-за конфликта версии.

## 13. Воспроизведение и соответствие реализации

Комплект не требует сторонних Python-пакетов:

```bash
python -m unittest discover -s tests -v
python run.py examples/manifest.json examples/conflict.json
python verify.py
```

Для повторной проверки модели нужен Java и `tla2tools.jar` release v1.7.4. JAR не включён в комплект; его URL и SHA-256 использованного экземпляра записаны в verification.json. Из каталога model:

```bash
java -XX:+UseParallelGC -cp /absolute/path/tla2tools.jar tlc2.TLC -workers 1 -config Kernel.cfg Kernel.tla
```

Альтернативная реализация F соответствует **семантике ядра**, если для любого корректного M и любого допустимого потока входов её управляющее состояние, EventResult и порядок выдаваемых Requests совпадают со Step после каждого события с точностью до порядка ключей отображений. Это универсальное условие, а не вывод из конечного набора тестов.

Допустимы разные физические структуры хранения и языки реализации. Для claims о durable execution, авторизации, изоляции, стоимости провайдера и release требуется отдельно установленное соответствие адаптера. Поддержка только этого комплекта не даёт статуса «безопасный самоулучшающийся агент».

Для данной поставки корректное заявление: **точно определённый профиль событий, эталонный интерпретатор, проверенные примеры и конечная TLA+-модель с указанными границами**.

## Приложение A. Нормативный код

Этот блок совпадает с core.py побайтно после удаления конечного перевода строки. Совпадение проверяет verify.py.

```python
'''AHSL-Core 0.5: pure, deterministic reference transition function.

This module interprets trusted event fixtures. It does not authenticate
callers, execute model code, store durable data, or dispatch network requests.
'''

from copy import deepcopy
import json
import re


MAX_NAT = 2 ** 31 - 1
TYPES = frozenset(('unit', 'bool', 'nat', 'text', 'ref'))
IDENTIFIER = re.compile(r'[A-Za-z][A-Za-z0-9_.-]{0,127}\Z')
PRINCIPALS = frozenset(('agent', 'provider', 'supervisor'))
ROLE = {
    'reserve': 'agent',
    'dispatch': 'agent',
    'cancel': 'agent',
    'unknown': 'provider',
    'complete': 'provider',
    'revoke': 'supervisor',
}


class SchemaError(ValueError):
    pass


def require(condition):
    if not condition:
        raise SchemaError('BAD_SCHEMA')


def fields(value, names):
    require(type(value) is dict and set(value) == set(names))


def identifier(value):
    require(type(value) is str and IDENTIFIER.fullmatch(value) is not None)


def nat(value):
    require(type(value) is int and 0 <= value <= MAX_NAT)


def scalar_text(value):
    require(type(value) is str)
    require(not any(0xD800 <= ord(char) <= 0xDFFF for char in value))


def type_name(value):
    require(type(value) is str and value in TYPES)


def typed_value(value):
    require(type(value) is dict)
    type_name(value.get('type'))
    tag = value['type']
    fields(value, ('type',) if tag == 'unit' else ('type', 'value'))
    if tag == 'nat':
        nat(value['value'])
    elif tag == 'bool':
        require(type(value['value']) is bool)
    elif tag == 'text':
        scalar_text(value['value'])
    elif tag == 'ref':
        identifier(value['value'])


def names(value):
    require(type(value) is list)
    for name in value:
        identifier(name)
    require(len(value) == len(set(value)))


def named_values(value):
    require(type(value) is dict)
    for name, item in value.items():
        identifier(name)
        typed_value(item)


def load_json(text):
    '''Reject duplicate keys, floats, non-finite numbers and surrogates.'''
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result)
            result[key] = value
        return result

    def bad_number(_):
        raise SchemaError('BAD_SCHEMA')

    value = json.loads(
        text, object_pairs_hook=pairs, parse_float=bad_number,
        parse_constant=bad_number,
    )

    def walk(item):
        if type(item) is str:
            scalar_text(item)
        elif type(item) is dict:
            for key, child in item.items():
                scalar_text(key)
                walk(child)
        elif type(item) is list:
            for child in item:
                walk(child)
        elif type(item) is int:
            nat(item)
    walk(value)
    return value


def initial(manifest):
    fields(manifest, ('version', 'budget', 'cells', 'components'))
    require(manifest['version'] == '0.5')
    nat(manifest['budget'])
    require(type(manifest['cells']) is dict)
    require(type(manifest['components']) is dict)
    cells = {}
    for key, cell in manifest['cells'].items():
        identifier(key)
        fields(cell, ('type', 'live', 'value'))
        type_name(cell['type'])
        require(type(cell['live']) is bool)
        typed_value(cell['value'])
        require(cell['value']['type'] == cell['type'])
        cells[key] = dict(deepcopy(cell), version=0)
    for key, component in manifest['components'].items():
        identifier(key)
        fields(component, ('inputs', 'output', 'read', 'write', 'cost'))
        require(type(component['inputs']) is dict)
        for name, tag in component['inputs'].items():
            identifier(name)
            type_name(tag)
        type_name(component['output'])
        names(component['read'])
        names(component['write'])
        require(set(component['read'] + component['write']) <= set(cells))
        nat(component['cost'])
    return {
        'manifest': deepcopy(manifest), 'cells': cells,
        'available': manifest['budget'], 'spent': 0,
        'epoch': 0, 'revoked': [], 'jobs': {}, 'seen': {}, 'log': [],
    }


def validate_event(event):
    require(type(event) is dict)
    kind = event.get('kind')
    require(type(kind) is str and kind in ROLE)
    extra = {
        'reserve': ('job', 'component', 'args'),
        'dispatch': ('job',), 'cancel': ('job',), 'unknown': ('job',),
        'complete': ('job', 'charge', 'outcome'),
        'revoke': ('component',),
    }[kind]
    fields(event, ('id', 'kind') + extra)
    identifier(event['id'])
    if 'job' in event:
        identifier(event['job'])
    if 'component' in event:
        identifier(event['component'])
    if kind == 'reserve':
        named_values(event['args'])
    if kind == 'complete':
        nat(event['charge'])
        outcome = event['outcome']
        require(type(outcome) is dict)
        if outcome.get('kind') == 'failure':
            fields(outcome, ('kind', 'code'))
            identifier(outcome['code'])
        else:
            fields(outcome, ('kind', 'value', 'writes'))
            require(outcome['kind'] == 'success')
            typed_value(outcome['value'])
            require(type(outcome['writes']) is list)
            for write in outcome['writes']:
                require(type(write) is dict)
                op = write.get('op')
                require(op in ('create', 'replace', 'delete'))
                required = ('op', 'cell') if op == 'delete' else (
                    'op', 'cell', 'value'
                )
                fields(write, required)
                identifier(write['cell'])
                if op != 'delete':
                    typed_value(write['value'])


def answer(code, **extra):
    return {'code': code, **extra}


def compatible_args(component, args):
    return set(args) == set(component['inputs']) and all(
        args[name]['type'] == tag for name, tag in component['inputs'].items()
    )


def proposal_error(state, job, outcome):
    component = state['manifest']['components'][job['component']]
    if job['epoch'] != state['epoch']:
        return 'STALE_POLICY'
    if job['component'] in state['revoked']:
        return 'DENIED'
    if any(
        state['cells'][key]['version'] != cell['version']
        for key, cell in job['snapshot'].items()
    ):
        return 'CONFLICT'
    if outcome['value']['type'] != component['output']:
        return 'OUTPUT_TYPE'
    writes = outcome['writes']
    keys = [write['cell'] for write in writes]
    if len(keys) != len(set(keys)):
        return 'DUPLICATE_WRITE'
    if not set(keys) <= set(component['write']):
        return 'WRITE_DENIED'
    for write in sorted(writes, key=lambda item: item['cell']):
        cell = state['cells'][write['cell']]
        if cell['version'] == MAX_NAT:
            return 'VERSION_EXHAUSTED'
        if (write['op'] == 'create') == cell['live']:
            return 'CELL_LIFECYCLE'
        if write['op'] != 'delete' and write['value']['type'] != cell['type']:
            return 'WRITE_TYPE'
    return None


def apply_event(state, event):
    '''Mutate only a private copy; return result and dispatch requests.'''
    kind = event['kind']
    components = state['manifest']['components']
    if kind == 'revoke':
        key = event['component']
        if key not in components:
            return answer('NO_COMPONENT'), []
        if key in state['revoked']:
            return answer('OK'), []
        if state['epoch'] == MAX_NAT:
            return answer('EPOCH_EXHAUSTED'), []
        state['epoch'] += 1
        state['revoked'] = sorted(state['revoked'] + [key])
        return answer('OK'), []
    key = event['job']
    if kind == 'reserve':
        if key in state['jobs']:
            return answer('JOB_EXISTS'), []
        component_id = event['component']
        if component_id not in components:
            return answer('NO_COMPONENT'), []
        component = components[component_id]
        if component_id in state['revoked']:
            return answer('DENIED'), []
        if not compatible_args(component, event['args']):
            return answer('INPUT_TYPE'), []
        if state['available'] < component['cost']:
            return answer('BUDGET'), []
        footprint = sorted(set(component['read'] + component['write']))
        snapshot = {name: deepcopy(state['cells'][name]) for name in footprint}
        state['available'] -= component['cost']
        state['jobs'][key] = {
            'component': component_id, 'args': deepcopy(event['args']),
            'snapshot': snapshot, 'epoch': state['epoch'],
            'status': 'reserved', 'held': component['cost'],
            'charged': 0, 'result': None,
        }
        return answer('OK'), []
    if key not in state['jobs']:
        return answer('NO_JOB'), []
    job = state['jobs'][key]
    if kind == 'dispatch':
        if job['status'] != 'reserved':
            return answer('BAD_PHASE'), []
        if job['epoch'] != state['epoch']:
            return answer('STALE_POLICY'), []
        if job['component'] in state['revoked']:
            return answer('DENIED'), []
        job['status'] = 'running'
        request = {
            'job': key, 'component': job['component'], 'args': job['args'],
            'snapshot': job['snapshot'], 'max_charge': job['held'],
        }
        return answer('OK'), [deepcopy(request)]
    if kind == 'cancel':
        if job['status'] != 'reserved':
            return answer('BAD_PHASE'), []
        state['available'] += job['held']
        job.update(status='cancelled', held=0, result=answer('CANCELLED'))
        return answer('OK'), []
    if kind == 'unknown':
        if job['status'] not in ('running', 'unknown'):
            return answer('BAD_PHASE'), []
        job['status'] = 'unknown'
        return answer('OK'), []
    if job['status'] not in ('running', 'unknown'):
        return answer('BAD_PHASE'), []
    charge = event['charge']
    if charge > job['held']:
        return answer('CHARGE_EXCEEDS_RESERVE'), []
    outcome = event['outcome']
    error = None
    if outcome['kind'] == 'success':
        error = proposal_error(state, job, outcome)
    if outcome['kind'] == 'failure':
        result = answer('COMPONENT_FAILURE', detail=outcome['code'])
    elif error is not None:
        result = answer(error)
    else:
        for write in outcome['writes']:
            cell = state['cells'][write['cell']]
            cell['version'] += 1
            cell['live'] = write['op'] != 'delete'
            if write['op'] != 'delete':
                cell['value'] = deepcopy(write['value'])
        result = answer('SUCCESS', value=deepcopy(outcome['value']))
    state['available'] += job['held'] - charge
    state['spent'] += charge
    job.update(status='done', charged=charge, held=0, result=result)
    return answer('SETTLED', result=result), []


def step(state, principal, event):
    '''Total on well-formed reachable states and decoded JSON event values.

    Caller identity is supplied by the trusted adapter, not an event field.
    Resource exhaustion of the Python host is outside the abstract semantics.
    '''
    try:
        require(type(principal) is str and principal in PRINCIPALS)
        validate_event(event)
    except (SchemaError, TypeError):
        return deepcopy(state), answer('BAD_SCHEMA'), []
    previous = state['seen'].get(event['id'])
    if previous is not None:
        if previous['principal'] != principal or previous['event'] != event:
            return deepcopy(state), answer('EVENT_ID_REUSE'), []
        return deepcopy(state), deepcopy(previous['result']), []
    updated = deepcopy(state)
    if ROLE[event['kind']] != principal:
        result, requests = answer('FORBIDDEN'), []
    else:
        result, requests = apply_event(updated, event)
    record = {
        'principal': principal, 'event': deepcopy(event),
        'result': deepcopy(result),
    }
    updated['seen'][event['id']] = deepcopy(record)
    updated['log'].append(record)
    return updated, deepcopy(result), deepcopy(requests)


def invariants(state):
    jobs = state['jobs'].values()
    held = sum(job['held'] for job in jobs)
    return (
        state['available'] >= 0
        and state['spent'] >= 0
        and state['available'] + state['spent'] + held
        == state['manifest']['budget']
        and state['spent'] == sum(job['charged'] for job in jobs)
        and all(job['held'] >= 0 for job in jobs)
        and all(
            job['held'] == state['manifest']['components'][
                job['component']
            ]['cost']
            for job in jobs if job['status'] in (
                'reserved', 'running', 'unknown'
            )
        )
        and all(
            cell['value']['type'] == cell['type']
            for cell in state['cells'].values()
        )
        and all(
            job['held'] == 0
            for job in jobs if job['status'] in ('done', 'cancelled')
        )
    )


def replay(manifest, records):
    state = initial(manifest)
    for record in records:
        state, result, _ = step(state, record['principal'], record['event'])
        require(result == record['result'])
    return state
```
