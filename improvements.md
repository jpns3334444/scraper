# CODEBASE REFACTOR & FEATURE IMPLEMENTATION PLAN – PROMPT FOR CODING AGENT

> **Use this document *as the system/task prompt* for an autonomous coding agent ("Quad Code").** It must transform the existing Tokyo real estate scraper + analyzer into the layered architecture described. Follow ALL requirements exactly. When ambiguity exists, choose conservative, maintainable defaults. Produce changes as small, reviewable PR-sized commits in logical order.

---

## 0. HIGH-LEVEL OBJECTIVES

1. **Decouple ingestion, enrichment, scoring, LLM evaluation, and reporting.**
2. **Eliminate per‑property emails** → implement real‑time alert (rare) + daily digest + weekly trend report.
3. **Replace full historical context prompts** with *precomputed multi-resolution snapshot blocks*.
4. **Introduce deterministic numeric scoring layer** (cheap triage) feeding selective LLM evaluation.
5. **Summarize images once per property** (vision feature extraction) and store structured + text summary.
6. **Implement comparable selection function** (deterministic) producing compact lines.
7. **Add market & ward & building snapshot generation tasks (daily)**.
8. **Add candidate selection + queue processing** for LLM evaluation.
9. **Persist all artifacts** (raw, processed, snapshots, LLM outputs) with clear S3 key conventions.
10. **Implement HTML email templates & static dashboard site** fed by generated JSON snapshots.
11. **Logging, metrics, cost controls, test coverage, idempotency** baked in.

---

## 1. ASSUMED CURRENT STACK (ADJUST IN README IF DIFFERENT)

* Language: Python 3.11/3.12
* AWS: Lambda, Step Functions (optional), DynamoDB, S3, SES, CloudWatch Logs & Events, Parameter Store/Secrets Manager.
* Current behavior: Scrape multiple properties → send each property individually (with images) to LLM → email each result.
* Images: Stored or temporarily downloaded.

If assumptions differ, generate a PREPARE.md describing delta & required adaptation before coding changes.

---

## 2. TARGET COMPONENTS (NEW / REFACTORED)

| Layer              | Component                                                                                       | Description                                                              |
| ------------------ | ----------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| Raw Ingestion      | `scraper/`                                                                                      | Fetch listing JSON + image URLs; write raw JSON & original images to S3. |
| Processing         | `processor/normalizer.py`                                                                       | Normalize raw → canonical fields.                                        |
| Metrics & Scoring  | `analysis/scoring.py`                                                                           | Deterministic feature derivations + base\_score calculation.             |
| Vision             | `vision/feature_extractor.py`                                                                   | Batch summarize images once → JSON features + text summary.              |
| Snapshots          | `snapshots/generate_snapshots.py`                                                               | Daily global + ward + building snapshots (compact text & JSON).          |
| Comparables        | `analysis/comparables.py`                                                                       | Deterministic comparable selection + compressed lines.                   |
| LLM Prompt Builder | `llm/prompt_builder.py`                                                                         | Assemble context + property data → evaluation prompt.                    |
| LLM Evaluator      | `llm/evaluator.py`                                                                              | Calls model only for candidates; stores JSON output.                     |
| Queue              | `queues/candidate_queue` (SQS or Dynamo flag)                                                   | Buffer of property\_ids needing LLM evaluation.                          |
| Notifications      | `notifications/real_time.py`, `notifications/daily_digest.py`, `notifications/weekly_report.py` | Email generation & dispatch.                                             |
| Dashboard          | `dashboard/build_site.py`                                                                       | Builds static site assets from snapshot & candidate JSON.                |
| Infra IaC          | `infrastructure/`                                                                               | CloudFormation/SAM/CDK templates update for new resources.               |
| Tests              | `tests/unit/`, `tests/integration/`                                                             | Coverage for scoring, comparables, snapshots, prompt assembly.           |
| CLI Tools          | `cli/`                                                                                          | Helper commands for backfilling, recomputing, manual evaluation.         |

---

## 3. DATA STORAGE & SCHEMA

### 3.1 S3 Key Conventions

```
s3://{bucket}/raw/{YYYY}/{MM}/{DD}/{run_id}/{property_id}.json
s3://{bucket}/raw/{YYYY}/{MM}/{DD}/{run_id}/{property_id}/images/{original_filename}
s3://{bucket}/processed/current/{property_id}.json              # canonical + derived numeric fields (no LLM)
s3://{bucket}/processed/history/{YYYY}/{MM}/{DD}/{property_id}.json
s3://{bucket}/vision/{property_id}.json                         # vision feature JSON + textual summary
s3://{bucket}/snapshots/{date}/global_snapshot.json
s3://{bucket}/snapshots/{date}/ward_{ward}.json
s3://{bucket}/snapshots/{date}/building_{building_id}.json
s3://{bucket}/snapshots/current/global_snapshot.json            # pointer copy
s3://{bucket}/candidates/{date}/candidate_{property_id}.json    # post scoring + LLM output
s3://{bucket}/reports/daily/{date}/digest.html
s3://{bucket}/reports/weekly/{iso_week}.html
s3://{bucket}/dashboard/market_snapshot.json
s3://{bucket}/dashboard/candidates.json
```

All JSON UTF-8, minified. Provide helper functions for key generation.

### 3.2 DynamoDB Table (Refactor)

**Table Name:** `RealEstateActive`

* **PK:** `PK` (partition) values: `CITY#tokyo`, `WARD#<ward>`, `BUILDING#<building_id>`
* **SK:** `property_id`
* Store current active listing metrics + summary fields (NOT large text). Include: `listing_price_yen`, `unit_size_m2`, `price_per_m2`, `building_age_years`, `ward_name`, `score.base_score`, `score.final_score` (if available), `status`, `updated_at` (ISO8601), `candidate_rank` (nullable), `vision_version`.
* **GSIs:**

  * `GSI1` (partition `ward_name`, sort `price_per_m2`)
  * `GSI2` (partition `status`, sort `score.final_score`) for quick candidate retrieval.

### 3.3 Candidate Status Lifecycle

`raw` → `processed` → `scored` (base\_score) → if qualifies: enqueue → `evaluated` (LLM output) → `alerted` (if real-time alert sent).

Persist status transitions atomically (conditional update to avoid races).

---

## 4. DETERMINISTIC SCORING MODULE

Implement `analysis/scoring.py` with function:

```python
def compute_scores(core: dict, derived: dict) -> dict:
    """Return {
        'ward_discount_pct': float|None,
        'building_discount_pct': float|None,
        'delta_vs_building_low_pct': float|None,
        'recent_price_cut_pct': float|None,
        'component_points': {...},
        'base_score': int,
        'prelim_verdict': 'candidate'|'reject'|'watch',
        'flags': {...}
    }"""
```

Follow numeric rules from provided evaluation prompt doc (already created) for point weights, but DO NOT include LLM-only adjustments. Include defensive handling for missing medians. 100% deterministic, pure function + unit tests with edge cases.

Add `analysis/derived.py` for shared derivations (discounts, turnovers, ratios). Ensure idempotency and simple numeric rounding (1 decimal for percentages before scoring; store full floats internally).

---

## 5. VISION FEATURE EXTRACTION

Create `vision/feature_extractor.py`:

* Input: list of image S3 URIs.
* Process: (Placeholder) If local vision model not available, stub with deterministic mock reading EXIF / file names. Provide interface expecting future multi-modal API integration.
* Output JSON structure:

```json
{
  "property_id": "...",
  "features": {
     "renovation_level": "modern"|"dated"|"original"|"partial",
     "kitchen_updated": true,
     "bath_updated": false,
     "flooring_type": "wood"|"tile"|"carpet"|null,
     "natural_light_score": 0-10,
     "view_quality": "open"|"obstructed"|"city"|"none",
     "damage_signs": ["stain", ...],
     "clutter_level": "low"|"medium"|"high",
     "layout_flags": ["open_living", "narrow_kitchen"],
     "needs_full_renovation": bool
  },
  "summary_text": "Short 60-100 token textual summary ...",
  "version": "v1"
}
```

* Provide `extract_features(property_id, image_paths) -> dict`.
* Cache check: if existing vision JSON present and `version` unchanged, skip.
* Unit tests: confirm idempotency, schema presence, skip logic.

---

## 6. SNAPSHOT GENERATION

`snapshots/generate_snapshots.py`:

* Queries DynamoDB (and/or processed parquet) to compute:

  * Global median price/m² by type, inventory counts, 7d & 30d deltas.
  * Ward-level medians, p25, p75, inventory.
  * Building snapshots (only for buildings containing at least 2 active units or historical records >2). Include median, low, high (24m window), turnover rate.
* Writes JSON plus compact textual summaries (for LLM context). Provide compression: remove extra whitespace; limit global text ≤ 500 tokens.
* Provide CLI: `python -m snapshots.generate_snapshots --date YYYY-MM-DD --write-current-symlinks`.
* Unit tests for sample fixtures.

---

## 7. COMPARABLE SELECTION

`analysis/comparables.py`:

```python
def select_comparables(subject: dict, pool: list[dict], limit: int=12) -> list[dict]:
    """Filter + rank by Euclidean distance on normalized (size, age, floor, distance_station_m) then price proximity.
    Return list of comp dicts."""

def compress_comparables(comps: list[dict]) -> list[str]:
    """Return lines 'id | price_per_m2 | size | age | floor | ward_discount% | bldg_discount%'."""
```

Rules: same ward & type; price ±30%; size ±25%; age ±10 yrs; exclude outliers by z-score >2 in size/price. Provide unit tests with deterministic expected ordering.

---

## 8. CANDIDATE PIPELINE LOGIC

Add `pipeline/candidate_selector.py`:

* After scoring each property, if `base_score >= 70` **AND** ward discount ≤ -8% (or building discount ≤ -5%) enqueue for LLM evaluation.
* If `base_score >= 85` and ward discount ≤ -15% mark `priority=true` for potential real-time alert after LLM confirmation.
* Use SQS queue `DealCandidateQueue` (create in infra) with message body `{property_id, priority}`.

Add `pipeline/evaluator_lambda.py` (triggered by SQS):

1. Fetch property processed JSON + vision summary + snapshots + comparables.
2. Build prompt using existing system prompt doc (sourced from a template file).
3. Call LLM; parse JSON; validate schema (fail fast & retry up to 2). Store output to S3 & update DynamoDB item with `final_score`, `verdict`, adjustments.
4. If `final_score >= 88` & discount gate satisfied: publish to `RealTimeAlertTopic` (SNS) or directly call notifications module.

---

## 9. NOTIFICATIONS

### 9.1 Real-Time Alert (Rare)

* Template: minimal plaintext + link to dashboard + 3 comps inline.
* Trigger: See evaluator logic.

### 9.2 Daily Digest

`notifications/daily_digest.py`:

* Trigger: CloudWatch Event at fixed time (e.g., 09:00 JST daily) AFTER snapshots job.
* Gather new `evaluated` candidates from last 24h, sort by final\_score desc, limit 10.
* Build HTML with inline CSS, sections: Market Overview, Top Deals Table, Watchlist (verdict=WATCH final\_score≥70), Price Cuts (properties with price\_momentum positive points), Summary Stats.
* Attach CSV `daily_candidates_{date}.csv` (columns: property\_id, ward, price\_yen, unit\_size\_m2, price\_per\_m2, discount\_vs\_ward\_pct, base\_score, final\_score, verdict).

### 9.3 Weekly Report

* Aggregates weekly medians vs prior week, distribution histograms (prepare simple ASCII fallback), top 5 new BUY\_CANDIDATEs, attrition (removed listings), risk pattern stats.
* HTML output to S3 + email.

Implement SES sender identity config doc (README update) if not present.

---

## 10. DASHBOARD STATIC SITE

`dashboard/build_site.py`:

* Generate two JSON files: `market_snapshot.json` (merge global + ward metrics + timestamp) and `candidates.json` (array of current BUY\_CANDIDATE + WATCH with key fields & S3 links to vision summary & images).
* Provide simple `site/index.html` template with lightweight client-side table (vanilla JS). Include sorting, filtering by ward, verdict, min discount, min score.
* Deploy: Sync `site/` and JSON to `s3://{bucket}/dashboard/` (public-read behind CloudFront if configured).

---

## 11. INFRASTRUCTURE CHANGES

Update CloudFormation/SAM/CDK templates to add:

* SQS Queue: `DealCandidateQueue` (+ DLQ)
* Lambda functions: `ScoringLambda`, `VisionLambda`, `SnapshotLambda`, `CandidateEvaluatorLambda`, `DailyDigestLambda`, `WeeklyReportLambda`, `DashboardBuilderLambda`.
* IAM Policies (principle of least privilege): S3 read/write prefixes, DynamoDB CRUD on table, SQS send/receive, SES send, CloudWatch logs/events.
* CloudWatch Event Rules (cron JST) for: snapshots (daily 07:30 JST), dashboard build (07:40 JST), daily digest (07:45 JST), weekly report (Mon 08:00 JST).
* Parameter Store entries: `LLM_API_KEY`, `DAILY_DIGEST_RECIPIENTS`, `REALTIME_ALERT_THRESHOLD_JSON`.

Provide `infrastructure/README.md` describing deployment order.

---

## 12. ENVIRONMENT VARIABLES (Per Lambda)

| Lambda        | Vars                                                           |
| ------------- | -------------------------------------------------------------- |
| *All*         | `APP_ENV`, `LOG_LEVEL`                                         |
| Scoring       | `ACTIVE_TABLE`, `S3_BUCKET`                                    |
| Vision        | `S3_BUCKET`, `VISION_VERSION=v1`                               |
| Snapshot      | `ACTIVE_TABLE`, `S3_BUCKET`                                    |
| Evaluator     | `S3_BUCKET`, `ACTIVE_TABLE`, `PROMPT_S3_KEY`, `LLM_MODEL_NAME` |
| Digest/Weekly | `S3_BUCKET`, `RECIPIENTS_PARAM`                                |
| Dashboard     | `S3_BUCKET`                                                    |

Centralize env validation in `util/env.py`.

---

## 13. LOGGING & METRICS

Implement `util/logging.py` wrapper configuring structured JSON logs (`timestamp, level, component, msg, property_id`).
Add custom CloudWatch Metrics via Embedded Metric Format for:

* `Scoring.PropertiesProcessed`
* `Scoring.CandidatesEnqueued`
* `Evaluator.Success`, `Evaluator.SchemaFail`, `Evaluator.Retry`
* `Notifications.AlertsSent`, `Notifications.DigestCount`
* `Snapshots.Generated`
  Provide alarms (out of scope to code if complex: stub definitions in IaC template).

---

## 14. COST CONTROLS

* Evaluate candidate ratio (# candidates / total) log daily.
* Add guard: hard cap LLM evaluations per run (config param), queue excess as deferred.
* Skip vision extraction if existing & unchanged.
* Compress textual snapshots (strip redundant wording).

---

## 15. TESTING STRATEGY

### 15.1 Unit Tests

* `tests/unit/test_scoring.py` (≥15 scenarios: missing medians, extreme discount, micro-unit, high HOA, old wood detached, renovation heuristic, price cut, data quality penalty).
* `tests/unit/test_comparables.py` (filters, ordering, size/age constraints, outlier removal).
* `tests/unit/test_prompt_builder.py` (ensures context assembly includes required blocks, excludes duplicates, token length ceiling < 1600 tokens for typical case—mock tokenizer with simple word count approximation).
* `tests/unit/test_snapshot_generation.py`.

### 15.2 Integration Tests

* Simulated mini dataset (10 properties) end-to-end: ingestion → scoring → enqueue 2 candidates → evaluator produces final JSON → digest builder includes them.

### 15.3 Schema Validation

Add JSON Schema file `schemas/llm_output.schema.json`. Validate every LLM output prior to persistence.

---

## 16. PROMPT BUILDER INTEGRATION

* Store system prompt (already authored) at `llm/system_prompt_v1.txt`.
* Insert dynamic blocks in order: Global, Ward, Building (optional), Comparables, Property JSON, Vision summary.
* Enforce token budgets: Truncate comparables beyond 12 lines; truncate vision summary > 120 tokens.
* Provide `assemble_prompt(property_id) -> str` & unit test.

---

## 17. MIGRATION / BACKFILL PLAN

1. Deploy new infra resources (queues, new lambdas) disabled (no event rules yet).
2. Migrate existing Dynamo records to new table schema script: `cli/migrate_active_table.py`.
3. Backfill vision summaries: iterate active properties; create missing vision JSON.
4. Generate first snapshots manually.
5. Enable Scoring Lambda + Queue.
6. Validate candidate volume < expected threshold (log & manual inspect).
7. Enable Evaluator Lambda (low concurrency 1–2 initially).
8. After stable, enable snapshot + digest scheduled events.
9. Cut over: disable old per-property email Lambda.

Create `MIGRATION.md` with enumerated steps + rollback guidelines (e.g., re-enable legacy email path if digest fails).

---

## 18. CODING STYLE & QUALITY

* Use `ruff` + `black` formatting; add config to repo.
* Type hints mandatory; run `mypy` (strict optional) on new modules.
* Small functions; pure where possible (scoring, comparables) for testability.
* Central `exceptions.py` for domain-specific errors (e.g., `SchemaValidationError`).
* Avoid silent except; log + re-raise or handle gracefully with explicit path.

---

## 19. SECURITY & SECRETS

* Never log full API keys or raw LLM outputs (truncate >2k chars).
* Parameter Store for secrets; lazy load once per container reuse.
* Validate incoming SQS messages schema.

---

## 20. ACCEPTANCE CRITERIA (MUST ALL PASS)

1. Running integration test script produces daily digest HTML (contains top deals) with zero schema validation errors.
2. Average LLM calls reduced to <20% of property count (report metric after sample run of ≥50 properties).
3. Prompt assembly token count median <1200 (approx word count \*1.3) for candidate run.
4. Daily digest email includes: market overview, top deals table rows ≤10, each with property\_id, discount\_vs\_ward\_pct, final\_score, 3 upsides, 3 risks.
5. Vision summaries cached (second run unchanged properties triggers no new extraction log entries).
6. Invalid LLM output (simulated) triggers single retry then moves message to DLQ.
7. Code coverage for `analysis/` and `snapshots/` modules ≥85% line coverage.
8. Dashboard JSONs built and uploaded (check presence & updated timestamps).
9. Real-time alert triggers only when simulated property final\_score >= 90 and discount gate met.
10. All Pylint/Ruff critical errors resolved; mypy passes.

---

## 21. TASK / COMMIT ORDER (SUGGESTED)

1. **chore:** add tooling (ruff, mypy, pytest setup)
2. **feat(storage):** implement S3 key helpers + updated Dynamo schema
3. **feat(scoring):** add derived + scoring modules + tests
4. **feat(vision):** add vision extractor (stub) + caching logic
5. **feat(snapshots):** implement snapshot generator + tests
6. **feat(comparables):** selection + compression + tests
7. **feat(prompt):** prompt builder referencing system\_prompt\_v1.txt
8. **feat(pipeline):** candidate selector + SQS enqueue
9. **feat(evaluator):** evaluator lambda + schema validation
10. **feat(notifications):** daily digest + alert templates
11. **feat(dashboard):** static site builder + JSON export
12. **feat(weekly):** weekly report generator
13. **infra:** CloudFormation updates, event rules (staged enable)
14. **feat(migration):** migration + backfill scripts
15. **test(integration):** end-to-end scenario
16. **docs:** README, MIGRATION, architecture diagram (ASCII + mermaid)
17. **perf:** token length guard, LLM call limiter
18. **ops:** metrics emission & alarms (basic)

---

## 22. DOCUMENTATION OUTPUTS TO GENERATE

* `README.md` updated architecture section + quickstart.
* `ARCHITECTURE.md` (component diagram, data flow sequence diagrams mermaid).
* `MIGRATION.md` steps.
* `PROMPTS.md` referencing system prompt + assembly rules.
* `OPERATIONS.md` (metrics, runbooks for failures: queue backlog, snapshot failure, evaluator schema errors).

---

## 23. EDGE CASE HANDLING & FALLBACKS

| Failure                                        | Action                                                                                        |
| ---------------------------------------------- | --------------------------------------------------------------------------------------------- |
| Snapshot job fails                             | Do not block daily digest; digest uses last successful snapshot; include warning banner.      |
| Evaluator schema invalid twice                 | Send to DLQ; log metric; exclude from digest.                                                 |
| Candidate queue backlog > threshold (config)   | Temporarily raise candidate threshold (base\_score) by +5 automatically until backlog clears. |
| Missing ward median for many properties (>30%) | Log single warning, degrade scoring gracefully (ward discount points=0).                      |
| Vision extraction error                        | Mark vision summary "unavailable"; still proceed with scoring (reduced condition points).     |

Implement guardrails in code with clear log messages.

---

## 24. QUALITY ENFORCEMENT CHECKLIST (PRE-PR)

* [ ] No TODO placeholders left (except future vision model integration tagged `# FUTURE:`)
* [ ] All new modules have unit tests.
* [ ] Public functions docstring summarizing inputs/outputs.
* [ ] `make lint test` passes CI script (provide template Makefile).
* [ ] Sample daily digest HTML manually inspected (store example under `examples/`).

---

## 25. MAKEFILE (GENERATE)

Provide targets: `lint`, `typecheck`, `test`, `test-unit`, `test-integration`, `build-dashboard`, `run-snapshots`, `run-daily-digest`, `migrate-active`, `backfill-vision`.

---

## 26. PROMPT BUILDER TOKEN GUARDS

Add approximate tokenizer function (simple whitespace split ×1.3) to estimate tokens. If >1500 tokens, truncate comparables first, then trim ward snapshot extraneous sentences, then reduce building snapshot to median + low/high only.

---

## 27. LLM PROVIDER ABSTRACTION

Implement `llm/provider.py` with interface:

```python
class LLMClient:
    def __init__(self, model: str, api_key: str): ...
    def evaluate_property(self, prompt: str) -> str: ...  # raw JSON string
```

Allow easy swap for different providers (OpenAI, Anthropic) via env.

---

## 28. FUTURE EXTENSION HOOKS (STUBS)

* Add `analysis/vector_store.py` stub (embedding index) with no-op functions for now.
* Add placeholder for multi-city scaling (prefix partition key with `CITY#`).

---

## 29. DELIVERABLE

When complete, produce a final summary file `DELIVERABLES.md` enumerating implemented features, skipped items (if any) with justification, and next steps.

---

## 30. EXECUTION INSTRUCTIONS FOR CODING AGENT

1. Validate assumptions; if mismatched, create `PREPARE.md` first & halt.
2. Execute commit sequence in Section 21; after each commit run `make lint test`.
3. After integration test pass, simulate 50 property run with pseudo data; output metrics summary to log.
4. Provide final artifact list in `DELIVERABLES.md`.

---

**END OF IMPLEMENTATION PROMPT**
