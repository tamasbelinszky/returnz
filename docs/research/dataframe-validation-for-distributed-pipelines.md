# Dataframe validation for resumable, distributed pipelines

Research note. 2026-08-08. Primary sources only (official docs, specs, source code, issue trackers).

Attribution convention used throughout:
- **[docs]** — the documentation states this.
- **[src]** — I read this in the source file linked.
- **[issue]** — a tracker item, quoted.
- Anything I could not confirm is in [Open questions](#open-questions--unverified), not stated as fact.

---

## Question & scope

We are evaluating a Result-native dataframe validation library for the `monadz` monorepo:
`validate()` returns `Result[DataFrame[S], ValidationReport]` instead of raising, composing with
`@do`, `map_batch`/`BatchResult`, and `ResultRouter`.

The question is not "is pandera good" (it is). It is: **what does validation need to do
differently when the pipeline is resumable and sharded**, and where does today's tooling
actually fail those teams.

Scope: pandera, Great Expectations (GX Core 1.x), Soda (v3 SodaCL + v4 contracts), dbt data
tests, Deequ/PyDeequ, Spark reader modes, Delta Lake, Apache Iceberg, Pydantic, and the
orchestrators that consume validation output (Dagster, Airflow, Prefect, Flyte, Ray Data).
Plus narwhals as a candidate backend abstraction.

Out of scope: anomaly detection / ML-based profiling, data catalogs, lineage.

---

## Findings by axis

### 1. Checkpoint / restart semantics

**Nothing in the validation-library layer has a resume cursor.** Not one of pandera, GX, Soda,
dbt, or Deequ can be told "this partition was already validated, skip it."

- **A GX "Checkpoint" is not a pipeline checkpoint.** It is a bundle: "A Checkpoint executes one
  or more Validation Definitions and then performs a set of Actions based on the Validation
  Results each Validation Definition returns"
  ([docs](https://docs.greatexpectations.io/docs/core/trigger_actions_based_on_results/create_a_checkpoint_with_actions)).
  **[src]** `Checkpoint(name, validation_definitions, actions, result_format, id)` and
  `Checkpoint.run(batch_parameters=None, expectation_parameters=None, run_id=None) -> CheckpointResult`
  ([checkpoint.py](https://raw.githubusercontent.com/great-expectations/great_expectations/develop/great_expectations/checkpoint/checkpoint.py)).
  There is no watermark, no skip-if-already-validated.
- GX *does* persist results — **[src]** `ValidationDefinition.run()` calls
  `self._validation_results_store.store_validation_results(...)`
  ([validation_definition.py](https://raw.githubusercontent.com/great-expectations/great_expectations/develop/great_expectations/core/validation_definition.py))
  — but as an audit log. Nothing reads it back to short-circuit work. A closed issue spells out
  why it is hard: "Metadata across runs would have to be compared, `unexpected_index_list(s)`
  would have to be de-duped, and we would need a means of determining that one expectation in
  one batch is the same as another in a past batch"
  ([#5055](https://github.com/fivetran/great_expectations/issues/5055)).
- **Soda has no watermark.** Partition scoping is a dataset `filter` whose boundary you compute
  and pass in as a variable
  (`soda scan -d ds -v ts_start=2022-03-11 -v ts_end=2022-03-15`,
  [docs](https://docs.soda.io/soda-v3/sodacl-reference/filters.md)). Soda's CTO opened and closed
  an issue conceding the consequence: "I think in our current approach we don't provide the
  necessary transparency to users and in pipeline tests may leave records that are not tested"
  ([#2168](https://github.com/sodadata/soda-core/issues/2168)).
- **dbt State is the only genuine skip mechanism, and it is whole-test granularity.** "For data
  tests, if the nodes being tested haven't changed since the last run, the previous test result
  is reused without re-executing the test query"
  ([docs](https://docs.getdbt.com/docs/deploy/dbt-state-about)). It surfaces as
  `RunStatus.Reused` with a `NO-OP` adapter response — confusingly enough that there is an open
  issue about it ([#15838](https://github.com/dbt-labs/dbt-core/issues/15838)). When a test does
  run, it still scans the whole relation.
- **Deequ is the exception, and it is the one to study.** `VerificationSuite.run(...,
  aggregateWith: Option[StateLoader], saveStatesWith: Option[StatePersister])` and
  `runOnAggregatedStates(schema, checks, stateLoaders, ...)` compute a verdict from *persisted
  per-shard state*
  ([VerificationSuite.scala](https://raw.githubusercontent.com/awslabs/deequ/master/src/main/scala/com/amazon/deequ/VerificationSuite.scala)).
  **[src]** `runOnAggregatedStates` takes a `StructType` schema, not a `DataFrame` — it reads no
  data at all
  ([AnalysisRunner.scala](https://raw.githubusercontent.com/awslabs/deequ/master/src/main/scala/com/amazon/deequ/analyzers/runners/AnalysisRunner.scala)).
  This is exactly the resume primitive everyone else lacks. See axis 4.
- **The storage layer already solved the general problem, and validation libraries ignore it.**
  Delta's `txn` action records `{appId, version}` atomically with the data write; the documented
  recipe is: "Check the current version of the transaction with `appId = streamId` in the target
  table. If this value is greater than or equal to the batch being written, then this data has
  already been added to the table and processing can skip to the next batch"
  ([PROTOCOL.md § Transaction Identifiers](https://github.com/delta-io/delta/blob/master/PROTOCOL.md#transaction-identifiers)).
  Caveat from the same section: "Delta only ensures that the latest `version` for a given
  `appId` is available in the table snapshot" — so it is a single cursor per app, not a
  per-partition state store.
- Ray Data has the only *row-keyed* resume primitive found:
  `CheckpointConfig(id_column, checkpoint_path, delete_checkpoint_on_success)` lets a failed job
  "resume ... by skipping rows that were successfully processed in a previous run, instead of
  restarting from the beginning"
  ([docs](https://raw.githubusercontent.com/ray-project/ray/master/doc/source/data/execution-configurations.rst)).

**What resumption actually needs**, synthesised from the above: a validation state keyed by
`(schema identity, partition identity, data version)` that is (a) persistable, (b) mergeable,
and (c) cheap to check before doing work. Deequ has (a) and (b). Nobody in Python has all three.

---

### 2. Partial success & quarantine

**Every tool surveyed hands you the *failing* side only.** The passing subset is a set-difference
you compute yourself, in every single case.

| Tool | What you get | What you don't |
|---|---|---|
| pandera `drop_invalid_rows` | the good frame | the bad rows — discarded |
| GX `result_format: COMPLETE` | failing keys / a query / failing rows | the passing subset |
| Soda failed-row samples | capped sample of failing rows + a routing hook (v3) | the passing subset; the hook is gone in v4 |
| dbt `store_failures` | a materialised failures relation | the passing subset |
| Deequ `rowLevelResultsAsDataFrame` | boolean columns appended per check | nothing — you filter twice yourself |
| Spark `PERMISSIVE` | bad rows in-band via `_corrupt_record` | semantic failures (parse only) |

Detail:

- **pandera drops, it does not split.** **[src]** `drop_invalid_rows(check_obj, error_handler)`
  filters `check_obj` and returns only the survivors
  ([pandas/base.py](https://raw.githubusercontent.com/unionai-oss/pandera/main/pandera/backends/pandas/base.py),
  [polars/base.py](https://raw.githubusercontent.com/unionai-oss/pandera/main/pandera/backends/polars/base.py)).
  The docs confirm: it "will prevent data-level schema errors being raised and will instead
  remove the rows which causes the failure"
  ([docs](https://pandera.readthedocs.io/en/stable/drop_invalid_rows.html)). Requires
  `lazy=True`. Documented caveat: "if the index is not unique on the dataframe, this could
  result in incorrect rows being dropped" (same page).
- The feature is also **acknowledged-buggy upstream**:
  [#1830](https://github.com/unionai-oss/pandera/issues/1830) "`pa.Column(drop_invalid_rows=True)`
  has no effect for Pandas DataFrames" (open, with a source-level diagnosis in the body), and
  [#1737](https://github.com/unionai-oss/pandera/issues/1737) documents that mixing schema-level
  and column-level `drop_invalid_rows` gives "non intuitive behavior" (open).
  For pyspark, a user asked for exactly the quarantine use case — "get indices of invalid rows so
  that I can post process or dump into a different corrupt records database" —
  ([#1540](https://github.com/unionai-oss/pandera/issues/1540), open).
- **GX gives you the failing side in three shapes, all key-dependent.**
  `unexpected_index_list` and `unexpected_list` appear only at `result_format: COMPLETE`
  ([docs](https://docs.greatexpectations.io/docs/core/trigger_actions_based_on_results/choose_a_result_format/));
  `unexpected_index_column_names` "takes a list to define the column(s) that will be used to
  identify unexpected results returned ... primary key (PK) column(s)" — **you must supply a key
  or the indices are unusable**. `unexpected_index_query` is "a query that can be used to
  retrieve all unexpected values (SQL and Spark)". Both apply "only to Expectations that have a
  yes/no answer for each row" — column-map expectations, not aggregates (same page).
  **[src]** `include_unexpected_rows` pulls an `UNEXPECTED_ROWS` metric (an actual frame of
  failing rows) into `_format_map_output()`
  ([expectation.py](https://raw.githubusercontent.com/great-expectations/great_expectations/develop/great_expectations/expectations/expectation.py)).
  A user asked for the complement and got no design answer: "as you already build the list of
  keys for failures, would it be possible for you to also retrieve the keys for good records"
  ([#11010](https://github.com/fivetran/great_expectations/issues/11010), open). The emitted
  Spark `unexpected_index_query` is also reported as syntactically invalid
  ([#10701](https://github.com/fivetran/great_expectations/issues/10701), open).
- **Soda regressed here.** v3 offers `failed rows` checks with a `fail condition` or `fail query`
  ([docs](https://docs.soda.io/soda-v3/sodacl-reference/failed-rows-checks.md)), default 100
  samples with `samples limit` / `samples columns` / `collect failed rows`
  ([docs](https://docs.soda.io/soda-v3/run-a-scan/failed-row-samples.md)), and a routing hook —
  subclass `Sampler`, override `store_sample`, assign `scan.sampler = CustomSampler()`
  ([docs](https://docs.soda.io/soda-v3/use-case-guides/route-failed-rows.md)). That page also
  states passing rows cannot be routed. In v4 the hook is gone; a Soda maintainer confirms on
  [#2554](https://github.com/sodadata/soda-core/issues/2554): "What's missing is a hook to
  capture and surface the actual rows to user code."
  [#1555](https://github.com/sodadata/soda-core/issues/1555) asks for failed *and passed* rows
  and has sat open with zero comments since 2022.
- **dbt's failures table is the best quarantine artifact anyone ships.** `store_failures` "saves
  all records (up to limit) that failed the test" into `{{ profile.schema }}_dbt_test__audit`
  ([docs](https://docs.getdbt.com/reference/resource-configs/store_failures)); `store_failures_as`
  takes `ephemeral | table | view` and takes precedence
  ([docs](https://docs.getdbt.com/reference/resource-configs/store_failures_as)). It is a real
  queryable relation, not a sample. Limitations: "A test's results will always **replace**
  previous failures for the same test", the name is fixed (parallel runs collide —
  [#11938](https://github.com/dbt-labs/dbt-core/issues/11938)), it is not incremental
  ([#11379](https://github.com/dbt-labs/dbt-core/issues/11379)), and it holds only the test's own
  output columns ([#12584](https://github.com/dbt-labs/dbt-core/issues/12584), where a maintainer
  responds that extra columns are "possible via writing a custom generic data test").
  `run_results.json` reports `failures` as an **`Optional[int]` count**, not the rows
  ([src, results.py](https://raw.githubusercontent.com/dbt-labs/dbt-core/1.13.latest/core/dbt/artifacts/schemas/results.py)).
- **Deequ appends per-check boolean columns**, which is the closest thing to a split primitive:
  **[src]** `rowLevelResultsAsDataFrame(sparkSession, verificationResult, data)` returns
  `data.select(col("*") +: columnsAliased: _*)` where each added column is the AND of that
  check's row-level constraints
  ([VerificationResult.scala](https://raw.githubusercontent.com/awslabs/deequ/master/src/main/scala/com/amazon/deequ/VerificationResult.scala)).
  Exposed in PyDeequ as `VerificationResult.rowLevelResultsAsDataFrame`
  ([src, verification.py](https://raw.githubusercontent.com/awslabs/python-deequ/master/pydeequ/verification.py)).
  You still write the two `filter` calls.
- **Spark's reader modes are the only in-band partial-success mechanism, and they only catch
  parse failures.** `PERMISSIVE` "puts the malformed string into a field configured by
  `columnNameOfCorruptRecord`, and sets malformed fields to `null`. To keep corrupt records, an
  user can set a string type field named `columnNameOfCorruptRecord` in an user-defined schema.
  If a schema does not have the field, it drops corrupt records during parsing"
  ([docs](https://spark.apache.org/docs/latest/sql-data-sources-csv.html)).
  **[src]** the mechanism: `corruptFieldIndex = schema.getFieldIndex(columnNameOfCorruptRecord)`;
  when `None`, the permissive path returns `nullResult` and the bad record vanishes
  ([FailureSafeParser.scala](https://raw.githubusercontent.com/apache/spark/master/sql/catalyst/src/main/scala/org/apache/spark/sql/catalyst/util/FailureSafeParser.scala)).
  There is a named error for the obvious follow-up query,
  `UNSUPPORTED_FEATURE.QUERY_ONLY_CORRUPT_RECORD_COLUMN`: "Queries from raw JSON/CSV/XML files are
  disallowed when the referenced columns only include the internal corrupt record column ...
  Instead, you can cache or save the parsed results and then send the same query"
  ([error-conditions.json](https://raw.githubusercontent.com/apache/spark/master/common/utils/src/main/resources/error/error-conditions.json)).
  So you cannot even count rejects without materialising first.
- `badRecordsPath` is **Databricks-only**, not Apache Spark — absent from the Spark CSV/JSON/XML
  option tables and **[src]** absent from `CSVOptions.scala` / `JSONOptions.scala`. Databricks
  documents two verbatim limitations: "It is non-transactional and can lead to inconsistent
  results. Transient errors are treated as failures"
  ([docs](https://learn.microsoft.com/en-us/azure/databricks/ingestion/bad-records)).
  Non-transactional means the reject set and the output are not committed atomically — fatal for
  a resumable pipeline.
- **Ray Data has no row-level isolation at all.** **[src]**
  `DEFAULT_MAX_ERRORED_BLOCKS = 0`
  ([context.py](https://raw.githubusercontent.com/ray-project/ray/master/python/ray/data/context.py)),
  and the docs say of the only knob: "Max number of blocks that are allowed to have errors ...
  **Data in the failed blocks are dropped.** ... By default, no retries are allowed"
  ([docs](https://raw.githubusercontent.com/ray-project/ray/master/doc/source/data/execution-configurations.rst)).
  `map_batches` has no `on_error` parameter
  ([API ref](https://docs.ray.io/en/latest/data/api/doc/ray.data.Dataset.map_batches.html)).
  One raising row kills the job; the escape hatch drops the whole block.

---

### 3. Schema evolution across pipeline versions

**The storage layer has schema identity. The messaging layer has compatibility policy. The
validation layer has neither.**

- **pandera has no schema versions, and the maintainer closed the request.** Issue
  [#406 "Schema Versioning?"](https://github.com/unionai-oss/pandera/issues/406) (closed
  2021-05-16). Maintainer `cosmicBboy`: "the way I personally use pandera, I let the versioning
  system (i.e. git) handle versioning of a schema ... I generally don't need to maintain both the
  old and new versions simultaneously." Another maintainer, `jeffzi`, describes the case that
  breaks that assumption: "We do have a `version` field. Sometimes, the new version of the data
  schema is tied to a new version of the app. Not all users will update right away, if ever. In
  that case, we will receive a mix of events on multiple version." Closed with "feel free to
  re-open". The gap is real and acknowledged in-thread.
- pandera *does* have schema algebra and serialisation, which is the raw material:
  `add_columns`, `remove_columns`, `update_column`, `rename_columns`
  ([src, dataframe/container.py](https://raw.githubusercontent.com/unionai-oss/pandera/main/pandera/api/dataframe/container.py)),
  `to_yaml`/`from_yaml`, `to_json`/`from_json`, `to_script`
  ([docs](https://pandera.readthedocs.io/en/stable/schema_inference.html) — caveat on the same
  page: "only built-in Check methods are supported" when persisting), plus a free-form
  `metadata: dict | None` on the schema and on every column
  ([src, model_config.py](https://raw.githubusercontent.com/unionai-oss/pandera/main/pandera/api/dataframe/model_config.py)).
- **GX has conformance expectations but zero suite versioning.** `ExpectTableColumnsToMatchSet`
  and `ExpectTableColumnsToMatchOrderedList` exist
  ([src, expectations/core/__init__.py](https://raw.githubusercontent.com/great-expectations/great_expectations/develop/great_expectations/expectations/core/__init__.py)),
  but **[src]** `ExpectationSuite.__init__(name, expectations, suite_parameters, meta, notes, id)`
  has no revision history; updates go through `_store.update()` and overwrite
  ([expectation_suite.py](https://raw.githubusercontent.com/great-expectations/great_expectations/develop/great_expectations/core/expectation_suite.py)).
- **Soda v3 has the only true *evolution* check, and it needs a SaaS backend.**
  `when schema changes:` accepts `any | column add | column delete | column index change |
  column type change`, alongside conformance keys `when required column missing`,
  `when forbidden column present`, `when wrong column type`, `when wrong column index`
  ([docs](https://docs.soda.io/soda-v3/sodacl-reference/schema.md)). Same page: "In Soda Cloud,
  the first scan that evaluates a schema evolution check returns no results because it has
  nothing to compare against; the second scan produces a check result." Not usable in a
  self-contained OSS run. Soda v4 contracts are conformance-only (`allow_extra_columns` default
  `false`, `allow_other_column_order` default `false` —
  [docs](https://docs.soda.io/reference/contract-language-reference.md)); **[src]** the *file
  format* is versioned (`soda_data_contract_json_schema_1_0_0.json`) but a contract document
  carries no version key
  ([schema file](https://raw.githubusercontent.com/sodadata/soda-core/main/soda-core/src/soda_core/contracts/soda_data_contract_json_schema_1_0_0.json)).
- **dbt is the clear winner and the model to copy.** Versioned models: `versions:` with `v:`,
  `latest_version`, `defined_in`, `deprecation_date`, convention `<model>_v<v>`. And real
  compatibility rules enforced in CI: with `state:modified`, "dbt will detect changes to
  versioned model contracts, and raise an error if any of those changes could be breaking for
  downstream consumers." Breaking = removing a column, changing a column's `data_type`,
  removing/modifying constraints. Non-breaking = adding a column, adding constraints
  ([docs](https://docs.getdbt.com/reference/resource-properties/versions)). `contract:
  enforced: true` checks "`name` and `data_type` for every column" but explicitly does *not*
  compare `varchar(256)` vs `varchar(257)` or precision/scale
  ([docs](https://docs.getdbt.com/reference/resource-configs/contract)). For incremental models,
  `on_schema_change` ∈ `ignore | fail | append_new_columns | sync_all_columns`; note `ignore`
  **fails the run on a removed column**, and none of the modes backfill values in old records
  ([docs](https://docs.getdbt.com/docs/build/incremental-models)). Users are pushing back on the
  rigidity: "I want my contract to only enforce a subset of columns, but I want to allow for
  schema evolution" ([#12485](https://github.com/dbt-labs/dbt-core/issues/12485), open,
  maintainer-authored).
- **Dagster ships a schema-diff check.** **[src]** `build_column_schema_change_checks(*, assets,
  severity=AssetCheckSeverity.WARN)` — "asset checks that pass if the column schema of the asset's
  latest materialization is the same as the column schema of the asset's previous
  materialization", detecting added columns, removed columns, and type changes, reading
  `dagster/column_schema` metadata of type `TableSchema`
  ([schema_change_checks.py](https://raw.githubusercontent.com/dagster-io/dagster/master/python_modules/dagster/dagster/_core/definitions/asset_checks/asset_check_factories/schema_change_checks.py)).
  Marked `@beta`. This is diff-vs-previous, not a compatibility policy.

**How the layers that got it right define it:**

- **Iceberg** allows "type promotion or adding, deleting, renaming, or reordering fields in
  structs". Explicitly disallowed: regrouping fields into a nested struct, and primitive↔struct
  changes. Promotions: `int→long`, `float→double`, `decimal(P,S)→decimal(P',S)` where `P'>P`
  ("widen precision only"); v3 adds `date→timestamp`/`timestamp_ns` (but "Promotion to
  `timestamptz` ... is not allowed") and `unknown→any type`
  ([spec § Schema Evolution](https://github.com/apache/iceberg/blob/main/format/spec.md#schema-evolution)).
  Renames are free because "Columns in Iceberg data files are selected by field id"
  ([spec § Column Projection](https://github.com/apache/iceberg/blob/main/format/spec.md#column-projection)).
  Crucially, **Iceberg stamps schema identity on the data**: table metadata carries `schemas` (a
  list of objects with `schema-id`) and `current-schema-id`; each **snapshot** records the
  `schema-id` current when it was created; each **manifest** records the `schema-id` used to
  write it ([spec, Table Metadata / Snapshots / Manifests](https://github.com/apache/iceberg/blob/main/format/spec.md)).
  You can always ask "which schema version produced this file". There is no compatibility
  *policy* — the allowed evolutions are fixed by the spec.
- **Delta** `mergeSchema` is additive only: "Columns present in the source data but missing from
  the table are automatically added ... The added columns are appended to the end of the struct"
  ([docs](https://docs.delta.io/latest/delta-batch.html)). Enforcement otherwise raises: "All
  DataFrame columns must exist in the target table ... DataFrame column data types must match"
  (same page). Type widening is a separate, explicitly-gated table feature: `typeWidening` in
  both `readerFeatures` and `writerFeatures` plus `delta.enableTypeWidening = true`, with a fixed
  allowed set — `Byte→Short→Int→Long`, `Float→Double`, `Byte/Short/Int→Double`,
  `Date→Timestamp without timezone`, `Decimal(p,s)→Decimal(p+k1, s+k2)` with `k1>=k2>=0`,
  `Byte/Short/Int→Decimal(10+k1,k2)`, `Long→Decimal(20+k1,k2)`. Per-field history is recorded in
  `delta.typeChanges`
  ([PROTOCOL.md § Type Widening](https://github.com/delta-io/delta/blob/master/PROTOCOL.md#type-widening)).
  Interop trap from the same section: with `IcebergCompatV1/V2` on, writers must reject the
  widenings Iceberg lacks. Note that Databricks' docs claim broader support (arbitrary-position
  adds, reorders, renames —
  [docs](https://docs.databricks.com/aws/en/delta/update-schema)); OSS Delta and DBR are
  different capability sets.
- **Avro** defines compatibility as reader/writer schema resolution: fields match by name,
  writer-only fields are ignored, reader-only fields use the reader's `default` and "if no
  default is present, an error is signalled". Promotions: "int is promotable to long, float, or
  double; long is promotable to float or double; float is promotable to double; string is
  promotable to bytes; bytes is promotable to string"
  ([spec § Schema Resolution](https://avro.apache.org/docs/1.12.0/specification/#schema-resolution)).
  Note `long→float` is legal but lossy.
- **Confluent Schema Registry** is the only source with a *policy vocabulary*: BACKWARD
  ("consumers using the new schema can read data produced with the last schema"), FORWARD ("data
  produced with a new schema can be read by consumers using the last schema"), FULL, their
  `_TRANSITIVE` variants ("ensures compatibility between X-2 <==> X-1 and X-1 <==> X and
  X-2 <==> X"), and NONE. Default is BACKWARD. Upgrade order is part of the definition: BACKWARD
  → "upgrade all consumers before you start producing new events"; FORWARD → "first upgrade all
  producers"; FULL → "you can upgrade the producers and consumers independently"
  ([docs](https://docs.confluent.io/platform/current/schema-registry/fundamentals/schema-evolution.html)).
- **Protobuf** is wire-shape only: "Changing field numbers for any existing field is not safe";
  "Adding new fields is safe"; removals require reserving the number. Compatible type changes
  include `int32/uint32/int64/uint64/bool` mutually, `sint32↔sint64`, `string↔bytes` (valid
  UTF-8), `fixed32↔sfixed32`, `enum↔int32/uint32/int64/uint64`, and singular↔repeated for
  string/bytes/message
  ([docs](https://protobuf.dev/programming-guides/proto3/#updating)).

---

### 4. Partitioned / sharded validation — which constraints decompose

This is the axis with the clearest theory and the least tooling. **Deequ is the only
implementation of the right idea, and PyDeequ does not expose it.**

**Deequ's model, from source.** A `State` is defined as "A state (sufficient statistic) computed
from data, from which we can compute a metric. Must be combinable with other states of the same
type (= algebraic properties of a commutative semi-group)", with a single method `def sum(other:
S): S`
([Analyzer.scala](https://raw.githubusercontent.com/awslabs/deequ/master/src/main/scala/com/amazon/deequ/analyzers/Analyzer.scala)).
Analyzers split into `computeStateFrom(data) -> Option[S]` and `computeMetricFrom(state) -> M`.
`calculateMetric` loads prior state via `aggregateWith`, merges, persists via `saveStatesWith`,
then derives the metric. `aggregateStateTo(sourceA, sourceB, target)` is a pure state merge.

That decomposition — **scan → semigroup state → metric → assertion** — is the whole trick.
Worked examples from source:

| Constraint | State | Merge | Cost |
|---|---|---|---|
| row count (`Size`) | `NumMatches(numMatches: Long)` | integer add | O(1) |
| completeness / compliance / pattern match | `NumMatchesAndCount(numMatches, count)` | pairwise add | O(1) |
| sum / mean / min / max | scalar or `MeanState` | trivial | O(1) |
| stddev / variance / skewness / kurtosis | moment states | closed-form | O(1) |
| correlation | `CorrelationState(n, xAvg, yAvg, ck, xMk, yMk)` | pairwise-update formula | O(1) |
| approx distinct | `ApproxCountDistinctState(words: Array[Long])` | `DeequHyperLogLogPlusPlusUtils.merge` | O(sketch) |
| **uniqueness / distinctness / primary key** | `FrequenciesAndNumRows(frequencies: DataFrame, numRows: Long)` | **outer join on the grouping columns**, "Add up frequencies via an outer-join" | **O(distinct values)** |

Sources:
[Size.scala](https://raw.githubusercontent.com/awslabs/deequ/master/src/main/scala/com/amazon/deequ/analyzers/Size.scala),
[Analyzer.scala](https://raw.githubusercontent.com/awslabs/deequ/master/src/main/scala/com/amazon/deequ/analyzers/Analyzer.scala)
(`NumMatchesAndCount`),
[Correlation.scala](https://raw.githubusercontent.com/awslabs/deequ/master/src/main/scala/com/amazon/deequ/analyzers/Correlation.scala),
[ApproxCountDistinct.scala](https://raw.githubusercontent.com/awslabs/deequ/master/src/main/scala/com/amazon/deequ/analyzers/ApproxCountDistinct.scala),
[GroupingAnalyzers.scala](https://raw.githubusercontent.com/awslabs/deequ/master/src/main/scala/com/amazon/deequ/analyzers/GroupingAnalyzers.scala),
[Uniqueness.scala](https://raw.githubusercontent.com/awslabs/deequ/master/src/main/scala/com/amazon/deequ/analyzers/Uniqueness.scala).

**The load-bearing conclusion: uniqueness *is* decomposable, but only if the state is the full
frequency table.** There is no O(1) summary. Deequ pays O(distinct) and merges by outer join.
Anyone who claims "global uniqueness can't be sharded" is wrong; anyone who expects it to be
cheap is also wrong. Approximate variants (HLL) merge in O(sketch) but only answer
*cardinality*, not *which key duplicated*.

**Referential integrity** (`values in A must exist in B`) is decomposable only against a
broadcastable or pre-summarised B — the state is a membership structure over B's keys. Deequ
does not model it as a state; Soda expresses it directly as a cross-dataset check
(`- values in (department_group_name) must exist in dim_employee (department_name)`,
[docs](https://docs.soda.io/soda-v3/sodacl-reference/reference.md)) but evaluates it in one
query, not by merging shards. dbt's `relationships` test is likewise a single global query.

**What is fundamentally not decomposable** into a bounded per-shard state: exact quantiles /
medians (Deequ has `ExactQuantile` with a `Double` state but that is the *result*, not a
mergeable sufficient statistic — the persist path stores the computed quantile, which cannot be
correctly re-merged); order-dependent checks (row `n` relative to row `n-1`) without a declared
global sort key; and anything defined over an unbounded join.

**Persistence has a fixed catalogue.** **[src]** `HdfsStateProvider.persist` is a `match` over
concrete analyzer types and ends `case _ => throw new IllegalArgumentException(s"Unable to
persist state for analyzer $analyzer.")`
([StateProvider.scala](https://raw.githubusercontent.com/awslabs/deequ/master/src/main/scala/com/amazon/deequ/analyzers/StateProvider.scala)).
State identity is `MurmurHash3.stringHash(analyzer.toString, 42)` — content-addressed by the
*analyzer definition*, not by the data. Custom analyzers cannot be persisted.

**PyDeequ does not expose any of it.** **[src]** grepping `pydeequ/{verification,analyzers,
repository,checks}.py` for `StateProvider`, `aggregateWith`, `saveStates`, `runOnAggregated`,
`InMemoryState`, `HdfsState` returns nothing. PyDeequ exposes only `useRepository(repository)`
and `saveOrAppendResult(resultKey)`
([verification.py](https://raw.githubusercontent.com/awslabs/python-deequ/master/pydeequ/verification.py)).
**The best incremental-validation machinery in the ecosystem is unreachable from Python.**
PyDeequ's own maintenance status is an open question
([#270](https://github.com/awslabs/python-deequ/issues/270), "Is PyDeequ 2.0 still being actively
developed?").

**No other tool merges shard verdicts.** GX's `CheckpointResult.success` is a plain AND over
independent runs — **[src]** `run_results` is a flat dict keyed by `ValidationResultIdentifier`
with no cross-result reconciliation
([checkpoint.py](https://raw.githubusercontent.com/great-expectations/great_expectations/develop/great_expectations/checkpoint/checkpoint.py)).
GX expectations evaluate against a Batch, so uniqueness on a daily batch is uniqueness within
that day
([docs](https://docs.greatexpectations.io/docs/core/introduction/gx_overview)). dbt tests are
global by construction (**[src]** `default__test_unique` is `select {{ column_name }} ... from
{{ model }}` with no predicate) — the opposite tradeoff, correct but never incremental.

**Free per-partition state already sitting in the lakehouse.** Both major table formats keep
per-file statistics that can *decide certain constraints without reading data*:
- Delta `add.stats`: `numRecords`, `tightBounds`, `nullCount`, `minValues`, `maxValues`. The
  `nullCount` semantics under wide bounds are specified exactly: "If the `nullCount` for a column
  equals the physical number of records ... then all valid rows for this column must have `null`
  values ... If the `nullCount` for a column equals 0 then all valid rows are non-`null` in this
  column"
  ([PROTOCOL.md § Per-file Statistics](https://github.com/delta-io/delta/blob/master/PROTOCOL.md)).
  **A `not_null` check is therefore decidable from the log alone.**
- Iceberg manifests: `record_count`, `value_counts`, `null_value_counts`, `nan_value_counts`,
  `lower_bounds`, `upper_bounds`, all keyed by column id and all optional; v4 replaces them with
  a typed `content_stats` struct carrying `tight_bounds` — "When true, `lower_bound` and
  `upper_bound` must be equal to the min and max values"
  ([spec § Manifests / Content Stats](https://github.com/apache/iceberg/blob/main/format/spec.md#manifests)).
  Caveat from the same section: "Implementations are not required to write a stats struct for
  every table field ... If any field is missing from the struct, readers must assume that it is
  unknown."

No validation library reads either. That is free money left on the table.

---

### 5. Idempotency & determinism

**Verdicts are deterministic everywhere. Failure *reports* are not, anywhere.**

Sources of non-reproducibility, all confirmed:

- **Truncation without ordering.** **[src]** pandera truncates failure cases with
  `failure_cases.groupby(check_output).head(self.check.n_failure_cases)` and
  `failure_cases.drop_duplicates().head(self.check.n_failure_cases)`
  ([backends/pandas/checks.py](https://raw.githubusercontent.com/unionai-oss/pandera/main/pandera/backends/pandas/checks.py))
  — `head` over a repartitioned frame gives different rows per run. GX's
  `partial_unexpected_count` caps `partial_unexpected_list` with no documented ordering
  ([docs](https://docs.greatexpectations.io/docs/core/trigger_actions_based_on_results/choose_a_result_format/));
  an issue about the hardcoded limit was closed within hours
  ([#11745](https://github.com/fivetran/great_expectations/issues/11745)). Soda caps at 100 by
  default; dbt's `limit` "will only include the first 1000 failures" with no ordering guarantee
  ([docs](https://docs.getdbt.com/reference/resource-configs/limit)).
- **Environment-dependent validation depth.** **[src]** pandera reads
  `PANDERA_VALIDATION_ENABLED`, `PANDERA_VALIDATION_DEPTH` (`SCHEMA_ONLY | DATA_ONLY |
  SCHEMA_AND_DATA`), `PANDERA_CACHE_DATAFRAME`, `PANDERA_USE_NARWHALS_BACKEND` from the
  environment at import time
  ([config.py](https://raw.githubusercontent.com/unionai-oss/pandera/main/pandera/config.py)).
  Same code, same data, different verdict depending on an env var.
- **Frame *type* silently changes what is checked.** **[src]** in
  `pandera/api/polars/utils.py::get_validation_depth`, a `pl.LazyFrame` with no explicit config
  gets `SCHEMA_ONLY`; a `pl.DataFrame` gets `SCHEMA_AND_DATA`
  ([utils.py](https://raw.githubusercontent.com/unionai-oss/pandera/main/pandera/api/polars/utils.py)).
  Confirmed in docs: "it only does validations at the schema-level, e.g. column names and data
  types" for LazyFrames ([docs](https://pandera.readthedocs.io/en/stable/polars.html)).
  Adding a `.collect()` upstream changes your data quality guarantees.
- **Sampling.** pandera's pandas path takes `head`, `tail`, `sample`, `random_state`
  ([src, api/pandas/container.py](https://raw.githubusercontent.com/unionai-oss/pandera/main/pandera/api/pandas/container.py));
  its pyspark path redefines `sample` as a *fraction* delegated to `DataFrame.sample`, a Bernoulli
  sampler
  ([src, api/pyspark/container.py](https://raw.githubusercontent.com/unionai-oss/pandera/main/pandera/api/pyspark/container.py)).
  GX does not sample in the validation path.
- **Float non-associativity in merged aggregates.** **[src]** Deequ's `CorrelationState.sum`
  performs a pairwise-update with divisions
  ([Correlation.scala](https://raw.githubusercontent.com/awslabs/deequ/master/src/main/scala/com/amazon/deequ/analyzers/Correlation.scala)).
  Merging shards in a different order yields a slightly different value. For a threshold
  assertion near the boundary, that is a flapping verdict. Integer states (`NumMatches`,
  `NumMatchesAndCount`) are exactly associative and do not have this problem.
- **Spark's corrupt-record detection is not stable under column pruning.** "Note that Spark
  tries to parse only required columns in CSV under column pruning. Therefore, corrupt records
  can be different based on required set of fields. This behavior can be controlled by
  `spark.sql.csv.parser.columnPruning.enabled` (enabled by default)"
  ([docs](https://spark.apache.org/docs/latest/sql-data-sources-csv.html)). The *same file* under
  the *same schema* yields different reject sets depending on downstream projection.

**Content-addressability: nobody does it.** Deequ persists reports under
`ResultKey(dataSetDate: Long, tags: Map[String, String])` — time-keyed, not content-keyed
([src, MetricsRepository.scala](https://raw.githubusercontent.com/awslabs/deequ/master/src/main/scala/com/amazon/deequ/repository/MetricsRepository.scala)).
GX stores by `ValidationResultIdentifier`. dbt overwrites the failures table per run.

The orchestrators are ahead of the validation libraries here:
- **Prefect** can genuinely skip a re-validation: "If an unexpired record is found, this result
  is returned and the task does not run, but instead, enters a `Cached` state"
  ([docs](https://docs.prefect.io/v3/concepts/caching)). Policies **[src]**: `INPUTS`,
  `TASK_SOURCE`, `FLOW_PARAMETERS`, `RUN_ID`, `DEFAULT = INPUTS + TASK_SOURCE + RUN_ID`
  ([cache_policies.py](https://raw.githubusercontent.com/PrefectHQ/prefect/main/src/prefect/cache_policies.py)).
  Two traps: caching requires `persist_result` ("Any configuration which explicitly avoids result
  persistence will result in your task never using a cache"), and **[src]** `NO_CACHE + INPUTS`
  silently yields `INPUTS` because adding `_None` is a no-op.
- **Flyte's** remote cache key is "Project, Domain, Cache Version, Task Signature, and Inputs"
  ([docs](https://raw.githubusercontent.com/flyteorg/flyte/master/docs/user_guide/development_lifecycle/caching.md)).
  Critically for us: offloaded objects (DataFrames) do not contribute to the key unless the
  producing task annotates its output `typing.Annotated[..., HashMethod(...)]` (same page).
- **Airflow has nothing.** Retry re-runs the task body; the only mid-task resume is deferral, and
  "no state persists automatically ... the only way you can pass state from the old instance of
  the operator to the new one is with `method_name` and `kwargs`"
  ([docs](https://airflow.apache.org/docs/apache-airflow/stable/authoring-and-scheduling/deferring.html)).

---

### 6. Orchestrator integration — what they want back

**Dagster is the only orchestrator with a genuine errors-as-values check protocol**, and its
shape is the one to target.

**[src]** `AssetCheckResult` fields, verbatim
([asset_check_result.py](https://raw.githubusercontent.com/dagster-io/dagster/master/python_modules/dagster/dagster/_core/definitions/asset_checks/asset_check_result.py)):

```python
("passed",      PublicAttr[bool]),
("asset_key",   PublicAttr[AssetKey | None]),
("check_name",  PublicAttr[str | None]),
("metadata",    PublicAttr[Mapping[str, MetadataValue]]),
("severity",    PublicAttr[AssetCheckSeverity]),
("description", PublicAttr[str | None]),
```

Constructor is keyword-only, `severity` defaults to `AssetCheckSeverity.ERROR`.

The three-way decomposition matters and is worth copying:
- **[src]** `AssetCheckSeverity` is `WARN | ERROR`, and its own docstring says "Severity does not
  impact execution of the asset or downstream assets"
  ([asset_check_spec.py](https://raw.githubusercontent.com/dagster-io/dagster/master/python_modules/dagster/dagster/_core/definitions/asset_checks/asset_check_spec.py)).
  Severity is pure metadata.
- **[src]** `blocking` is the only control-flow lever: in `execute_step.py` an evaluation is
  collected as failing-blocking only when `not passed AND severity == ERROR AND blocking`, and
  only then does the step raise `DagsterAssetCheckFailedError` instead of emitting
  `step_success_event`
  ([execute_step.py](https://raw.githubusercontent.com/dagster-io/dagster/master/python_modules/dagster/dagster/_core/execution/plan/execute_step.py)).
  A failed non-blocking ERROR check leaves the step green.
- So: `passed` (fact) × `severity` (report) × `blocking` (policy) are three independent axes.

Other Dagster facts:
- **Partition-scoped checks are real.** `@asset_check` and `AssetCheckSpec` both take
  `partitions_def` (**[src]**,
  [asset_check_decorator.py](https://raw.githubusercontent.com/dagster-io/dagster/master/python_modules/dagster/dagster/_core/definitions/decorators/asset_check_decorator.py)).
  The persisted `AssetCheckEvaluation` carries `partition: str | None`, filled from
  `step_context.partition_key` only when `check_spec.partitions_def is not None`, with the source
  comment "Unpartitioned asset check can exist for partitioned asset"
  ([asset_check_evaluation.py](https://raw.githubusercontent.com/dagster-io/dagster/master/python_modules/dagster/dagster/_core/definitions/asset_checks/asset_check_evaluation.py)).
  `AssetCheckEvaluation` also carries `target_materialization_data` — a `(run_id, storage_id,
  timestamp)` pointer pinning the check to a specific asset version.
- **A failing-rows table is a first-class metadata type.** **[src]** the canonical example in
  `MetadataValue.table`'s own docstring is exactly a validation-failure table:
  `MetadataValue.table(records=[TableRecord(data={"code": "invalid-data-type", "row": 2, "col":
  "name"})], schema=TableSchema(columns=[TableColumn(name="code", type="string"), ...]))`
  ([metadata_value.py](https://raw.githubusercontent.com/dagster-io/dagster/master/python_modules/dagster/dagster/_core/definitions/metadata/metadata_value.py),
  [table.py](https://raw.githubusercontent.com/dagster-io/dagster/master/python_modules/dagster/dagster/_core/definitions/metadata/table.py)).
  `TableMetadataSet` gives `column_schema, column_lineage, row_count, partition_row_count,
  table_name, storage_kind`
  ([metadata_set.py](https://raw.githubusercontent.com/dagster-io/dagster/master/python_modules/dagster/dagster/_core/definitions/metadata/metadata_set.py)).
  UI-special keys are the `dagster/`-namespaced ones, and "Numerical metadata is treated as a
  time series in the Dagster UI"
  ([docs](https://docs.dagster.io/guides/build/assets/metadata-and-tags/)).
- **[src]** `MaterializeResult(asset_key, metadata, check_results: Sequence[AssetCheckResult],
  data_version, tags, value)` — an asset can return its data *and* a batch of check results in
  one value
  ([result.py](https://raw.githubusercontent.com/dagster-io/dagster/master/python_modules/dagster/dagster/_core/definitions/result.py)).
- **`dagster-pandera` exists but targets the legacy path.** **[src]**
  `pandera_schema_to_dagster_type(schema) -> DagsterType` (`@beta`), validates in lazy mode, and
  on failure returns a `TypeCheck` with `num_failures` and a `failure_sample` of the first ~10
  errors; inline comment says pandas-only
  ([dagster_pandera/__init__.py](https://raw.githubusercontent.com/dagster-io/dagster/master/python_modules/libraries/dagster-pandera/dagster_pandera/__init__.py)).
  **There is no pandera → `AssetCheckResult` bridge.** pandera's own integrations page lists
  FastAPI, Frictionless, Hypothesis, Mypy, Pydantic — no orchestrators
  ([docs](https://github.com/unionai-oss/pandera/blob/main/docs/source/integrations.md)).

**Airflow** is exception-driven with no result value type. States include no "partial"
([docs](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/tasks.html)).
The richest metadata channel in Airflow 3 is Asset extras — `yield Metadata(self, {"row_count":
len(df)})`, read back via `context["inlet_events"][asset][-1].extra[...]`; must be
JSON-serializable and is "stored in cleartext ... not encrypted"
([docs](https://airflow.apache.org/docs/apache-airflow/stable/authoring-and-scheduling/assets.html)).
The commonly-cited 48KB XCom cap is **not** a thing in Airflow 3: **[src]** the `xcom.value`
column is `JSON().with_variant(postgresql.JSONB, "postgresql")` with no length constraint and
`serialize_value` performs no size check
([xcom.py](https://raw.githubusercontent.com/apache/airflow/main/airflow-core/src/airflow/models/xcom.py));
the old `MAX_XCOM_SIZE = 49344` lived in `airflow/utils/xcom.py` in 2.x, was never enforced by
the model, and that module is gone in 3.x. Docs give only a qualitative warning: XComs "are only
designed for small amounts of data; do not use them to pass around large values, like dataframes"
([docs](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/xcoms.html)).

The best prior art in Airflow is the `common.sql` provider: **[src]** `@dataclass SQLCheckResult`
with fields `name, check_type, success, severity, column, table, expected, actual, content,
description, params` where `severity ∈ {"error", "warn", "info"}`, built and stored with the
comment "Save check results before raising exception, to be used by listeners", then emitted as
an OpenLineage `DataQualityAssertionsDatasetFacet`
([sql.py](https://raw.githubusercontent.com/apache/airflow/main/providers/common/sql/src/airflow/providers/common/sql/operators/sql.py)).
Structured results exist — but only as a side channel; the task still signals pass/fail by
raising. That is precisely the shape a Result type fixes.

**Prefect** wants a table artifact: **[src]** `create_table_artifact(table, key=None,
description=None)` where `table: dict[str, list] | list[dict] | list[list]`, JSON-serialised with
NaN→None sanitisation
([artifacts.py](https://raw.githubusercontent.com/PrefectHQ/prefect/main/src/prefect/artifacts.py)).
Artifacts appear on the Artifacts page **only if `key` is set**
([docs](https://docs.prefect.io/v3/concepts/artifacts)). There is no "completed with warnings"
state; the idiom is `Completed(name="CompletedWithWarnings")`
([docs](https://docs.prefect.io/v3/concepts/states)).

**Flyte** wants a Deck: `@task(enable_deck=True)`, `Deck(name, html)`, renderers including
`TopFrameRenderer` and (plugin) `TableRenderer`
([src](https://raw.githubusercontent.com/flyteorg/flytekit/master/flytekit/deck/deck.py)).
Usefully, `Deck.publish()` streams live and works even if the task fails
([docs](https://raw.githubusercontent.com/flyteorg/flyte/master/docs/user_guide/development_lifecycle/decks.md)).
`FlyteRecoverableException` is a one-branch mechanism: **[src]** in `entrypoint.py`, `if
isinstance(e.value, FlyteRecoverableException): kind = ContainerError.Kind.RECOVERABLE else
NON_RECOVERABLE`
([entrypoint.py](https://raw.githubusercontent.com/flyteorg/flytekit/master/flytekit/bin/entrypoint.py)).

**Ray Data** wants nothing — it has no reporting channel and no row-level isolation (see axis 2).

---

### 7. Lakehouse constraint enforcement

**Delta is the only storage layer that expresses semantic rules, and it is exactly the layer
that refuses partial success.**

- Delta **CHECK constraints** are stored in `Metadata.configuration` under
  `delta.constraints.{name}` with a boolean SQL expression, and the writer rules are
  all-or-nothing, verbatim: "When adding a CHECK constraint to a table, a writer must validate
  the existing data in the table and ensure every row satisfies the new CHECK constraint before
  committing the change. Otherwise, the write operation must fail and the table must stay
  unchanged" and "When writing to a table that contains CHECK constraints, every new row being
  written to the table must satisfy CHECK constraints in the table. Otherwise, the write
  operation must fail and the table must stay unchanged"
  ([PROTOCOL.md § CHECK Constraints](https://github.com/delta-io/delta/blob/master/PROTOCOL.md#check-constraints)).
- **Column Invariants** are the older per-column mechanism, stored in column metadata under
  `delta.invariants`, with subtly different null semantics: "Writers MUST abort any transaction
  that adds a row to the table, where an invariant evaluates to `false` or **`null`**"
  ([PROTOCOL.md § Column Invariants](https://github.com/delta-io/delta/blob/master/PROTOCOL.md#column-invariants)).
  CHECK constraints instead require `true`. Worth knowing if you generate either.
- **[src]** the error catalogue confirms the granularity is the transaction:
  `DELTA_VIOLATE_CONSTRAINT_WITH_VALUES` (sqlState `23001`),
  `DELTA_NOT_NULL_CONSTRAINT_VIOLATED` (`23502`),
  `DELTA_NEW_CHECK_CONSTRAINT_VIOLATION` ("`<numRows>` rows in `<tableName>` violate the new CHECK
  constraint", `23512`), `DELTA_NESTED_NOT_NULL_CONSTRAINT` ("Delta does not support NOT NULL
  constraints nested within arrays or maps")
  ([delta-error-classes.json](https://raw.githubusercontent.com/delta-io/delta/master/spark/src/main/resources/error/delta-error-classes.json)).
  The docs surface this as an `InvariantViolationException`
  ([docs](https://docs.delta.io/latest/delta-constraints.html)).
- **There is no row-level rejection in Delta.** Nothing in PROTOCOL.md defines a quarantine or
  reject destination. Quarantine must be built above the table format.
- **Iceberg defines no constraints at all.** Grepping the spec for `constraint` returns zero
  matches. `required` is a nullability marker: "Each field can be either optional or required,
  meaning that values can (or cannot) be null". Write-time obligations are narrow: "If the write
  default for a required field is not set, the writer must fail". And the spec explicitly punts
  semantics to the engine — on identifier fields: "uniqueness of rows by this identifier is not
  guaranteed or required by Iceberg and it is the responsibility of processing engines or data
  providers to enforce"
  ([spec](https://github.com/apache/iceberg/blob/main/format/spec.md)). Constraint support is an
  open proposal: [#14906 "Support check constraint"](https://github.com/apache/iceberg/issues/14906)
  (open, filed 2025-12-21, motivated by Spark 4.1 check-constraint support); an earlier
  [#5182 "Feature: adding constraint validation"](https://github.com/apache/iceberg/issues/5182)
  was closed as not planned.

**What the storage layer deliberately does not cover, and therefore what a library layer is for:**
cross-row and cross-table semantics (uniqueness, referential integrity, aggregate bounds),
partial success, reject routing, and any notion of a *report*. Delta gives you one bit and an
aborted transaction.

---

### 8. Where existing tools fall short — specific and fair

**pandera** — the best schema-definition ergonomics in Python, and we should not compete with it.
`DataFrameModel` with a typed `Config` (**[src]** `dtype, name, title, description, coerce,
drop_invalid_rows, unique, strict, ordered, unique_column_names, add_missing_columns, from_format,
to_format, metadata` and multiindex variants,
[model_config.py](https://raw.githubusercontent.com/unionai-oss/pandera/main/pandera/api/dataframe/model_config.py)),
lazy error accumulation with a well-specified `failure_cases` frame
(`["schema_context", "column", "check", "check_number", "failure_case", "index"]`,
[docs](https://pandera.readthedocs.io/en/stable/lazy_validation.html)), and backends for pandas,
polars, pyspark.sql, ibis, pyarrow, geopandas.

Shortfalls, all sourced above: drops instead of splits; no schema versions (closed #406); no
incremental/state concept (`incremental` returns zero issues on the tracker); LazyFrame silently
degrades to SCHEMA_ONLY; env vars can change the verdict; `unique` raises
`SchemaInitError("unique Field argument not yet implemented for pyspark")` (**[src]**,
[pyspark/model_components.py](https://raw.githubusercontent.com/unionai-oss/pandera/main/pandera/api/pyspark/model_components.py));
and "There is no support for lambda based vectorized checks" on pyspark
([docs](https://pandera.readthedocs.io/en/stable/pyspark_sql.html)).

Notably, **pandera is already errors-as-values internally** and converts to exceptions only at
the boundary: **[src]** `CoreCheckResult(passed, check, check_index, check_output, reason_code,
message, failure_cases, schema_error, original_exc)` and `CheckResult(check_output, check_passed,
checked_object, failure_cases)`
([backends/base/__init__.py](https://github.com/unionai-oss/pandera/blob/main/pandera/backends/base/__init__.py)).
And its **one** non-raising public path is the native pyspark.sql backend: "Instead of raising the
error, the errors are collected and can be accessed via the `dataframe.pandera.errors` attribute"
([docs](https://pandera.readthedocs.io/en/stable/pyspark_sql.html)). But **[src]** that accessor
is a Python attribute set via `object.__setattr__` on one specific DataFrame object
([pyspark_sql_accessor.py](https://raw.githubusercontent.com/unionai-oss/pandera/main/pandera/accessors/pyspark_sql_accessor.py))
— it is a side channel, not a return type, so no type checker can force you to handle it. It is
also lost under pandera's narwhals PySpark backend, which raises `SchemaErrors`.

**Great Expectations** — richest failing-row extraction (`unexpected_index_query` is a genuinely
good idea), stable JSON serialisation (**[src]** `to_json_dict()` plus Marshmallow schemas on
both result classes), and a clean `CheckpointResult.describe_dict()` giving
`{success, statistics{evaluated_validations, success_percent, ...}, validation_results[]}`.
Shortfalls: no suite versioning; no resume; per-Batch scope with no merge; index extraction
requires a user-declared key; heavyweight project/store configuration. Repo caveat: it now
resolves to `fivetran/great_expectations` and the tracker has been swept to ~20 open issues, so
absence of open issues is not evidence of absence of gaps.

**Soda Core** — best cross-dataset/referential story of the group (`values in ... must exist in`,
`row_count same as <dataset> in <datasource>`, plus reconciliation blocks,
[docs](https://docs.soda.io/soda-v3/sodacl-reference/metrics-and-checks.md)) and the only true
schema-*evolution* check. Shortfalls: the v3/v4 split is live and undeclared (docs.soda.io still
publishes v3 with no deprecation notice); **[src]** v4 result objects have no `to_dict()`/JSON
serialisation, only `build_soda_cloud_check_dict()`
([contract_verification.py](https://raw.githubusercontent.com/sodadata/soda-core/main/soda-core/src/soda_core/contracts/contract_verification.py));
the failed-rows routing hook regressed out of v4 (#2554); schema-evolution checks require Soda
Cloud; several open bugs in the failed-rows path (#1733, #2223, #2348).

**dbt tests** — the best schema-versioning story anywhere, and a real materialised failures
relation. Shortfalls: SQL-only; tests always scan the full relation (**[src]** generic test macros
have no predicate); the only incremental narrowing is a manual `where`; `--empty` and `--sample`
don't apply to tests
([docs](https://docs.getdbt.com/reference/commands/run)). The gap is maintainer-owned and open:
[#10877](https://github.com/dbt-labs/dbt-core/issues/10877) "new configuration to run tests on
only the 'new' data for snapshots and incremental models" — "Folks want to be able to test *just*
their 'new' data before it's inserted into their existing table."

**Deequ / PyDeequ** — the right theory (semigroup states, `runOnAggregatedStates`), the right
severity model (**[src]** `CheckLevel = {Error, Warning}`, `CheckStatus = {Success, Warning,
Error}`,
[Check.scala](https://raw.githubusercontent.com/awslabs/deequ/master/src/main/scala/com/amazon/deequ/checks/Check.scala)),
and row-level results. Shortfalls: Scala-first, Spark-only, and **the incremental API is not
exposed in PyDeequ at all**; persistable state types are a hardcoded catalogue; `ResultKey` is
time-keyed not content-keyed; maintenance status of the Python binding is uncertain (#270).

**Delta / Iceberg** — covered in axis 7. Delta: semantic CHECK, zero partial success. Iceberg:
schema identity and free per-file statistics, zero constraints.

**Pydantic** — the right error *shape*, the wrong data model. `ValidationError.errors()` returns
`ErrorDetails` with `type` (machine-readable), `loc` (tuple path, numeric index for list
elements), `msg`, `input`, `url`, `ctx`, plus `.error_count()` and `.json()`; it collects all
errors rather than stopping at the first
([docs](https://pydantic.dev/docs/validation/latest/errors/errors/)). That `type`/`loc` pair is
exactly the machine-readable identity a validation report needs. But Pydantic has no columnar
concept: validating a dataframe means one model instantiation per row, in Python, with a per-row
`loc`. It is the right model for a *record* at an API boundary — which is why `returnz_pydantic`
already uses it — and the wrong one for 10^8 rows.

---

## Capability matrix

Legend: ✅ supported · ◐ partial / with caveats · ❌ absent. Sources for every cell are the
links in the axis sections above; the key source is repeated inline.

| Capability | pandera | GX Core 1.x | Soda | dbt tests | Deequ (Scala) | PyDeequ | Delta | Iceberg | Pydantic |
|---|---|---|---|---|---|---|---|---|---|
| Declarative schema in Python | ✅ `DataFrameModel` | ◐ suites of expectations | ❌ YAML | ❌ YAML/SQL | ❌ Scala DSL | ◐ Python DSL | ❌ DDL | ❌ | ✅ `BaseModel` |
| Accumulate all errors (not fail-fast) | ✅ `lazy=True` | ✅ | ✅ | ◐ per-test | ✅ | ✅ | ❌ aborts txn | n/a | ✅ |
| Machine-readable error identity | ✅ `SchemaErrorReason` | ✅ `expectation_config` | ◐ v3 JSON; v4 none | ◐ `unique_id` | ✅ analyzer id | ✅ | ◐ error class | n/a | ✅ `type`+`loc` |
| Stable serialised report | ✅ `failure_cases` frame | ✅ `to_json_dict()` | ◐ v3 `get_scan_results()`; ❌ v4 | ✅ `run_results.json` | ✅ `*AsJson` | ✅ | ❌ | ❌ | ✅ `.json()` |
| Return **failing** rows | ◐ index only, then dropped | ✅ `COMPLETE` + index cols | ◐ capped samples | ✅ `store_failures` table | ✅ row-level bool cols | ✅ | ❌ | ❌ | ◐ `loc` index |
| Return **passing** subset separately | ❌ (drop, not split) | ❌ ([#11010](https://github.com/fivetran/great_expectations/issues/11010)) | ❌ ([#1555](https://github.com/sodadata/soda-core/issues/1555)) | ❌ | ◐ filter yourself | ◐ | ❌ | ❌ | ❌ |
| Route rejects to a quarantine sink | ❌ | ◐ query string, build it yourself | ◐ v3 `Sampler` hook; ❌ v4 | ✅ audit schema | ❌ | ❌ | ❌ | ❌ | ❌ |
| Per-partition scoping | ❌ | ◐ Batch Definitions (date only) | ◐ dataset `filter` + vars | ◐ `where` config | ✅ `where` + state | ◐ `where` only | n/a | n/a | ❌ |
| Merge per-shard state → global verdict | ❌ | ❌ (AND over runs) | ❌ | ❌ | ✅ `runOnAggregatedStates` | ❌ **not exposed** | ❌ | ❌ | ❌ |
| Persistable validation state (resume) | ❌ | ◐ audit log only | ❌ | ◐ dbt State, whole-test | ✅ `StatePersister` | ❌ | ◐ `txn` cursor | ❌ | ❌ |
| Global uniqueness across shards | ❌ | ❌ per-Batch | ◐ single query | ✅ global query | ✅ mergeable freq table | ❌ | ❌ | ❌ (spec disclaims) | ❌ |
| Referential integrity | ❌ | ◐ `...EqualOtherTable` | ✅ `values in ... must exist in` | ✅ `relationships` | ◐ | ◐ | ❌ | ❌ | ❌ |
| Schema **versions** with compat rules | ❌ ([#406](https://github.com/unionai-oss/pandera/issues/406)) | ❌ | ❌ (v3 evolution check needs Cloud) | ✅ `versions:` + breaking-change detection | ❌ | ❌ | ◐ log history, `typeWidening` | ◐ `schema-id` per snapshot, no policy | ❌ |
| Additive-column tolerance | ✅ `strict=False` | ✅ `...MatchSet` | ✅ `allow_extra_columns` | ✅ `on_schema_change` | ❌ | ❌ | ✅ `mergeSchema` | ✅ | ✅ `extra="ignore"` |
| Type widening rules | ◐ `coerce` | ❌ | ❌ | ◐ contract `data_type` | ❌ | ❌ | ✅ fixed table | ✅ fixed table | ◐ coercion |
| Severity levels (warn vs error) | ◐ `raise_warning` | ✅ `get_max_severity_failure()` | ✅ warn/fail | ✅ `severity` | ✅ `CheckLevel` | ✅ | ❌ | ❌ | ❌ |
| Deterministic failure sample | ❌ `.head(n)` | ❌ capped, unordered | ❌ capped | ❌ `limit` | ◐ | ◐ | n/a | n/a | ✅ |
| Content-addressed report (skip rerun) | ❌ | ❌ | ❌ | ❌ | ❌ time-keyed `ResultKey` | ❌ | ❌ | ❌ | ❌ |
| Reads free per-file stats (no scan) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ produces them | ✅ produces them | ❌ |
| Orchestrator result adapter | ❌ (no integrations) | ◐ actions | ◐ exit codes | ✅ `run_results.json` | ❌ | ❌ | n/a | n/a | ❌ |

---

## The genuine gaps

Ranked by how much pain they cause a team running resumable, sharded pipelines.

### 1. No tool returns the good rows and the bad rows as one value

Everyone hands back failures and expects you to recompute the complement. In a sharded pipeline
this is the difference between a one-line quarantine step and an anti-join you write, test, and
get subtly wrong (index alignment, duplicate keys, null-safe joins).

Evidence that this is a real want and not our invention: GX
[#11010](https://github.com/fivetran/great_expectations/issues/11010) (open, no design answer),
soda-core [#1555](https://github.com/sodadata/soda-core/issues/1555) (open since 2022, zero
comments), pandera [#1540](https://github.com/unionai-oss/pandera/issues/1540) (open, explicitly
asks to "dump into a different corrupt records database"). dbt has no such issue at all — because
in SQL you just write the complementary query, which tells you the gap is specific to the
dataframe world.

Cost when missing: every team writes the same partition-and-route step, and it silently breaks on
non-unique indices — a failure mode pandera itself documents.

### 2. No incremental / mergeable validation state reachable from Python

Deequ proved the design (semigroup states, `runOnAggregatedStates` computing a verdict from a
`StructType` plus persisted states, reading zero data). Then PyDeequ shipped without it — **[src]**
confirmed: no `StateProvider`, no `aggregateWith`, no `runOnAggregatedStates` anywhere in the
Python package.

Cost when missing: on resume, you re-scan validated partitions (money) or skip validation
entirely (risk). Global constraints — uniqueness, row-count totals, sum bounds — force a full
shuffle every run, so teams quietly drop them and validate per-partition only, which is a
different and weaker guarantee than they think they have.

### 3. No schema versions, so backfills and mixed-version streams are unvalidatable

pandera's maintainer closed the request with "let git handle it"; another pandera maintainer in
the same thread describes the exact case git cannot handle: mobile clients that never upgrade, so
"we will receive a mix of events on multiple version". GX has zero suite versioning. Only dbt has
compatibility rules, and only for SQL models.

Meanwhile Iceberg already stamps `schema-id` on every snapshot and manifest, and Confluent
already has a compatibility vocabulary. The pieces exist in adjacent layers and nobody has joined
them in the dataframe layer.

Cost when missing: reprocessing 2023 data with the 2026 schema either fails wholesale or passes
by accident. Nobody can answer "is this schema change safe for downstream consumers" without a
human reading a diff.

### 4. Failure reports are not reproducible, so they cannot be diffed or cached

`.head(n)` truncation with no ordering (pandera), unordered `partial_unexpected_list` (GX), 100
samples (Soda), first-1000 (dbt). Plus verdict-changing env vars and the LazyFrame-vs-DataFrame
depth switch in pandera. Plus float non-associativity in any merged aggregate.

Cost when missing: "did the data get worse, or did we just sample different rows?" is
unanswerable. No report can be content-addressed, so no rerun can be short-circuited — even
though Prefect and Flyte both *can* skip a task given a stable input hash.

### 5. Nobody reads the statistics the table format already computed

Delta writes `numRecords`, `nullCount`, `minValues`, `maxValues`, `tightBounds` per file. Iceberg
writes `record_count`, `null_value_counts`, `lower_bounds`, `upper_bounds` per file, and v4 adds
`tight_bounds`. Delta's spec makes `nullCount == 0 ⟹ all valid rows are non-null` an explicit
guarantee.

So a `not_null` check across a 10 TB table is answerable from the transaction log in
milliseconds. No validation library does this. Every one of them scans.

### 6. No adapter from a dataframe validation to an orchestrator's result type

`dagster-pandera` targets the legacy `DagsterType` path, is pandas-only, and produces a
`failure_sample` of ~10 errors — not an `AssetCheckResult`. pandera lists no orchestrator
integrations at all. Airflow's `common.sql` provider independently reinvented
`SQLCheckResult(..., severity ∈ {error, warn, info})` for SQL checks and has no dataframe
equivalent.

Cost when missing: every team hand-rolls the same translation from an exception into
`AssetCheckResult(passed=..., severity=..., metadata={...})`, and usually loses the failing rows
on the way.

---

## Implications for a Result-native package

### What to build

1. **`validate()` returns the partition, not just the verdict.** The type should be
   `Result[Validated[S], ValidationReport]` where `Validated` carries **both** frames — the
   accepted rows and the rejected rows *with their reasons attached as columns*. This is gap #1,
   it is unanimously missing, and it is the single most defensible reason for the package to
   exist. Model the reject frame on Deequ's `rowLevelResultsAsDataFrame` (append a boolean column
   per check) plus a `_rz_errors` struct/JSON column carrying the machine-readable reasons.

2. **Mergeable check state as a first-class, serialisable type.** Port Deequ's `State`/`sum`
   semigroup to Python with `RzResult`-shaped persistence. Each built-in check declares its state
   type and merge:
   - exactly-associative integer states for counts/completeness/compliance (safe to merge in any
     order);
   - frequency-table state for uniqueness / primary key (O(distinct), merged by outer join — be
     honest about the cost in the docs);
   - explicitly mark float-valued merges (mean/variance/correlation) as **order-sensitive** and
     make merge order deterministic (sort shard states by partition key before folding), so the
     verdict is reproducible.
   Expose `validate_partition() -> Result[PartitionReport, ...]` and
   `merge_reports(reports) -> Result[GlobalReport, ...]`. This is gap #2 and it is the thing
   nobody in Python has.

3. **Schema versions with an explicit compatibility policy.** Borrow the vocabulary wholesale
   from Confluent (`BACKWARD` / `FORWARD` / `FULL`, transitive variants) and the *breaking-change
   taxonomy* from dbt (remove column = breaking; add column = additive; change `data_type` =
   breaking). Provide `check_compatibility(old_schema, new_schema, policy) -> Result[(),
   IncompatibleChange]` as a pure function usable in CI. Stamp the schema version into
   `ValidationReport` so a report says *which* schema produced it, the way Iceberg stamps
   `schema-id` on a snapshot. This is gap #3.

4. **Content-addressed reports.** Hash `(schema fingerprint, check set fingerprint, input
   identity)` — where input identity is a caller-supplied token (Delta version / Iceberg
   snapshot-id / partition key + file list). Return it on the report. That single field lets
   Prefect (`cache_policy=INPUTS`) and Flyte (`Annotated[..., HashMethod(...)]`) skip
   re-validation for free, and lets a resumed run answer "already validated?" without a scan.
   Make failure samples deterministic: sort by the declared key before truncating, and record the
   truncation in the report. This is gap #4.

5. **A metadata-only fast path.** Given a Delta `add.stats` or Iceberg manifest summary, decide
   the checks that are decidable from statistics alone — `not_null` (Delta: `nullCount == 0`),
   row-count bounds, min/max range bounds when `tightBounds`/`tight_bounds` is true — and return
   `Ok` without touching the data. Fall back to a scan otherwise. This is gap #5 and it is a
   visible, benchmarkable win.

6. **Orchestrator adapters as thin, separate packages.** `returnz_dagster` mapping
   `ValidationReport → AssetCheckResult(passed, severity, description, metadata={...
   MetadataValue.table(records=[...], schema=TableSchema(...))})`, honouring the three
   independent axes Dagster established: `passed` (fact) × `severity` (report) × `blocking`
   (caller policy). Copy that decomposition into our own report type rather than conflating
   severity with control flow. This is gap #6.

### What NOT to build

- **A schema DSL.** pandera's `DataFrameModel` + `Config` is good, well-typed, serialisable
  (`to_yaml`/`to_json`), and has a `metadata: dict` escape hatch on both schema and column.
  **Interop, don't compete.** Accept a `pandera.DataFrameSchema` as an input and produce our
  report from it. If we need a native schema type, make it a thin thing with a lossless
  `from_pandera` / `to_pandera`.
- **A check library.** pandera and Deequ between them already cover the vocabulary. We need
  `state` and `merge` on top, not new predicates.
- **Backend implementations per dataframe library.** Use narwhals. pandera already made this bet
  — `pandera[narwhals]` since 0.32.0, and pyarrow is served *exclusively* by narwhals
  ([docs](https://pandera.readthedocs.io/en/stable/narwhals_backend.html)) — but as an opt-in
  second implementation alongside hand-written native backends. Starting fresh on narwhals gets
  the precedent without the dual-maintenance cost. Target `narwhals.stable.v2` (v1 carries the
  legacy interchange level). Constraints to design around, all documented:
  - **Row order.** `DataFrame` "has a well-defined row order which is preserved across
    `with_columns` and `select`" and `filter` "preserves original order"; `LazyFrame` "makes no
    assumptions about row-ordering"
    ([docs](https://narwhals-dev.github.io/narwhals/concepts/order_dependence/)). So **failing-row
    *indices* are eager-only**; lazily we need `with_row_index(order_by=<declared key>)` or we
    degrade to failing-row *predicates*. Require a key column for lazy backends. This mirrors GX's
    `unexpected_index_column_names` requirement — the constraint is intrinsic, not a narwhals
    quirk.
  - **`Expr.filter` is missing on dask/duckdb/ibis/spark-like**
    ([completeness matrix](https://narwhals-dev.github.io/narwhals/api-completeness/expr/)) — use
    frame-level `filter`. There is no `partition_by`; the portable good/bad split is
    `with_columns(<validity exprs>)` then two `filter` calls with `all_horizontal` /
    `~all_horizontal`.
  - `Expr.is_null / is_nan / is_between / is_in / is_duplicated / is_unique / is_finite / cast /
    over`, `group_by`, `join` are supported on every backend — the full validation vocabulary is
    available.
  - pandas null-vs-NaN conflation is a documented hazard: narwhals recommends "only handling null
    values in applications and leaving NaN values as an edge case"
    ([docs](https://raw.githubusercontent.com/narwhals-dev/narwhals/main/docs/concepts/null_handling.md)).
- **Row-by-row Pydantic validation of dataframes.** Keep Pydantic where `returnz_pydantic` already
  has it: the report envelope (`RzResult`, `TaggedError`) and API boundaries. Borrow the
  `type`/`loc`/`msg`/`input` error shape for `ValidationReport` entries — it is the right shape —
  but compute the errors columnar.

### Where a `Result` genuinely helps — and where it is only ergonomics

**Honest case for.**

1. **It survives process boundaries where exceptions don't.** Under Ray Data, a raising UDF is
   catastrophic: **[src]** `DEFAULT_MAX_ERRORED_BLOCKS = 0` means one bad row kills the job, and
   the only mitigation "drops" the whole block. Under Spark `mapInPandas`, an exception on an
   executor becomes a stack trace in a driver log, not data. An `Err` value that is a *row* or a
   *column* travels with the data through shuffles and writes. This is not ergonomics; it is the
   only representation that works. Note that pandera's pyspark backend independently arrived at
   errors-as-data (`df.pandera.errors`) — but as a mutable Python attribute on one frame object,
   which the type checker cannot enforce and which any transformation loses.

2. **Partial success has no exception encoding.** `BatchResult(succeeded: dict[K, T], failed:
   dict[K, E])` with `failed_keys` as a ready-made retry set is exactly the shape a resumable
   sharded run needs — validate N partitions, get back which ones passed and which to retry, in
   one value. `raise` gives you one bit for N partitions. Dagster reached the same conclusion
   independently: `MaterializeResult.check_results: Sequence[AssetCheckResult]` is a *batch* of
   returned results, not an exception.

3. **Exhaustive matching is a real defect class here.** The `Ok` / `Err` match forces the author
   to decide what happens to rejects. The common production bug is *silently dropping them* —
   which is exactly what pandera's `drop_invalid_rows` does by design and what
   `max_errored_blocks` does in Ray. A type that cannot be ignored is a better default than a
   convention.

4. **Reports become values, so they can be persisted, hashed, and merged.** An exception is not
   serialisable state. `RzResult`'s tagged envelope makes a `ValidationReport` round-trip, which
   is the precondition for gaps #2 and #4.

**Honest case against.**

1. **The verdict was never the expensive part.** Pass/fail is deterministic and cheap in every
   tool surveyed. The hard problems on this list — mergeable state, schema compatibility, reading
   file statistics, deterministic sampling — are *algorithmic*, and a `Result` type solves none of
   them. We could build all six items above with an exception-based API and lose little. Claiming
   otherwise would be dishonest.

2. **Python's ecosystem is exception-shaped and we pay at every boundary.** pandera raises.
   Airflow signals failure by raising. Flyte's recoverable/non-recoverable distinction is
   *literally* `isinstance(e, FlyteRecoverableException)`. Delta raises
   `InvariantViolationException`. We will be wrapping and unwrapping at every seam, and each
   wrapper is somewhere the error can get flattened.

3. **`returnz`'s partial-success combinator is async-only.** **[src]** `map_batch` is
   `async def` and runs via `asyncio.gather`
   (`packages/core/src/returnz/batch.py`). Dataframe
   validation is CPU-bound and synchronous. Either we add a sync `map_batch` or the flagship
   composition story does not apply to the flagship use case. `partition` and `collect` are sync
   and do apply.

4. **`@do` short-circuits, which is the wrong default here.** The whole point of this domain is
   *not* bailing on the first error. `@do` is right for the pipeline-of-stages layer (parse
   schema → resolve partition → validate → write) and wrong for the within-validation layer.
   We should say so plainly in the docs rather than implying `@do` is the composition story.

**Net:** the Result type is load-bearing for exactly two things — crossing executor boundaries
with errors intact, and representing partial success over N shards as one value. Everything else
is ergonomics, and good ergonomics, but we should not oversell it. The package's actual claim to
existence is gaps #1, #2, and #5; `Result` is the right vehicle, not the product.

---

## Open questions / unverified

- **Confluent's per-format allowed-change table.** I verified the compatibility-type definitions,
  the default (`BACKWARD`), and the upgrade-order prose from
  [the docs](https://docs.confluent.io/platform/current/schema-registry/fundamentals/schema-evolution.html),
  and a fetch of the `#compatibility-types` anchor reproduced the "add optional fields / remove
  fields" cells. But the page is now split into per-format (Avro / Protobuf / JSON Schema)
  tables and I could not confirm the exact per-format cell text verbatim. Treat the specific
  allowed-change wording as approximate.
- **Whether Iceberg engines are *required* to reject nulls in `required` fields.** The spec
  defines `required` and mandates writer failure when a required field has no write default, but
  I found no normative "engines MUST validate values" language. Enforcement appears to be left to
  writers.
- **Spark: absence of `mode` for Parquet/ORC/Avro** is inferred from the absence of the option in
  those format doc pages, not from an explicit statement that they lack it.
- **pandera `drop_invalid_rows` end-to-end behaviour on the narwhals backend.** I read the
  narwhals `drop_invalid_rows` implementation (it builds a pass-mask with `nw.all_horizontal` and
  filters) but did not run it, and did not verify whether the open bugs #1830 / #1737 reproduce
  there.
- **Dagster UI rendering of `MetadataValue.table` / `.md` / `.json`.** The docs explicitly
  document special rendering only for the `dagster/`-namespaced keys. The others render, but I
  could not find a doc statement saying so.
- **Airflow XCom / `AssetEvent.extra` size limits.** Source shows no constraint and docs give only
  a qualitative warning. I could not confirm any documented byte limit in Airflow 3, and did not
  test a large payload.
- **Flyte: whether non-recoverable user errors are never retried.** The flytekit side only sets
  the `ContainerError.Kind`; the consumer is FlytePropeller (Go), unread.
- **Theta sketch order-sensitivity.** The DataSketches page linked from the Theta docs
  (`ThetaSketchSetOpsOrderSensitivity.html`) 404s. I could not confirm the exact order-sensitivity
  guarantees for mergeable distinct-count sketches. The claim about float non-associativity in
  merged aggregates is confirmed independently from Deequ's `CorrelationState.sum` source.
- **Soda v4 CLI exit codes and result contract.** The v4 docs cover CLI usage only; I found no
  exit-code table and no `to_dict()` on the v4 result objects. Whether an equivalent of v3's
  `get_scan_results()` is planned is unknown.
- **narwhals: Daft coverage** (no column in any completeness matrix) and whether PySpark Connect
  and SQLFrame differ from the collapsed `spark-like` column.
- **PyDeequ maintenance status.** [#270](https://github.com/awslabs/python-deequ/issues/270) is
  open and unanswered as of reading; I did not attempt to infer activity from commit history.
