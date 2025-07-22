LEAN V1.3 MIGRATION – EXECUTION PROMPT FOR CODING AGENT
ROLE: Senior engineer + refactoring bot.
MISSION: Migrate current repository (survey provided) from “LLM‑only analysis” to Lean v1.3 deterministic gating + daily digest without breaking existing scraping.
STYLE: No speculative code. Reuse existing utilities. Write clear docstrings, type hints (Python 3.12).
ABSOLUTE RULE: Do NOT implement deferred / out‑of‑scope features (weekly report, building snapshots, renovation ROI, dashboard site, advanced throttle, complex adjustments).

0. BASELINE (From Survey – DO NOT RE‑DISCOVER)
Scraper entry: scraper/scrape.py:main

ETL / pipeline logic: ai-infra/lambda/etl/app.py

Prompt builder: ai-infra/lambda/prompt_builder/app.py

Batch LLM calls: ai-infra/lambda/llm_batch/app.py

Per-run report sender: ai-infra/lambda/report_sender/app.py

Dynamo table: RealEstateAnalysisDB (PK = property_id, SK = sort_key like ANALYSIS#YYYY-MM-DD)

Current S3 prefixes: raw/, clean/, batch_output/, reports/

No deterministic scoring, no comparables, no snapshots, no candidate gating.

Treat this as authoritative context.

1. TARGET FEATURES (LEAN V1.3 SCOPE)
Feature	Status	Implement?
Lean deterministic scoring (6 base + 3 add‑ons)	Missing	YES
Simple comparables (≤8)	Missing	YES
Ward median discount calc	Missing	YES
Minimal data quality penalties (3 rules)	Missing	YES
Candidate gating + daily cap	Missing	YES
Lean prompt structure (candidates only)	Needs refactor	YES
Limit images (first 3)	Needed	YES
Lean LLM output schema (minimal JSON)	Missing	YES (with fallback map)
Global + ward snapshots (daily)	Missing	YES
Daily digest (HTML + CSV)	Missing	YES
Minimal metrics (5 + suppressed)	Partial	EXTEND
Simple retry (1) + schema validate	Adjust	YES
Environment flags for rollback	Missing	YES
Minimal tests (5 new)	Partial	YES
Disable per-property immediate email under lean mode	Needed	YES

Out of Scope / DO NOT BUILD: weekly report, real‑time alerts, building snapshots, renovation ROI bands, advanced adjustments, backlog hysteresis, full scoring breakdown in LLM output, multi-city scaling, SQS queue (we keep Step Function path for now), dashboard static site.

2. NEW / MODIFIED ENV VARS
Add (document in README & code):

Var	Purpose	Default
LEAN_MODE	Master switch for lean pipeline features	1
LEAN_SCORING	Enable deterministic scoring	1
LEAN_PROMPT	Use lean prompt builder output	1
LEAN_SCHEMA_ENFORCE	Enforce lean evaluation schema	1
MAX_CANDIDATES_PER_DAY	Hard cap (integer)	120

If var absent → assume default above (fail open in “lean on” direction except LEAN_MODE which must default to 0 if not set—explicitly code that).

3. LEAN SCORING SPEC (IMPLEMENT EXACTLY)
3.1 Inputs (per listing)
Required fields (derivable from ETL output or post‑processing):
price_per_sqm (or price_per_m2), total_sqm (size), building_age_years, ward_name (district), previous_price (if available; else price cut component =0), current_price, optional hoa_fee_yen, repair_fund_yen, distance_station_m (if missing treat neutral).

3.2 Base Components
Component	Max	Rule
Ward Discount	25	Linear interpolation: 0 pts at discount ≥ 0%; 25 pts at discount ≤ -20%. Missing ward median => 0 pts + DQ penalty.
Building Discount	10	If building median present: linear 0→10 at ≤ -10%; else 0 (no reallocation). (You may not have this yet—set 0.)
Comps Consistency	10	If ≥4 comps and median(comps_ppm2) ≥ subject_ppm2 * 1.05 ⇒ 10; else scale = clamp(((median_comp_ppm2 - subject_ppm2) / (0.05 * subject_ppm2)) * 10, 0, 10). If <4 comps => 0.
Condition	7	Category mapping: modern=7, partial=5, dated=3, original=1. If any damage token -> subtract 1 (floor 0). (Vision stub sets category + damage_tokens list.)
Size Efficiency	4	If 20 ≤ size ≤ 120 => 4 else 0.
Carry Cost	4	If ratio = (hoa_fee+repair_fund)/(price/100) ≤0.12 =>4; 0.12–0.18 linear to 1; >0.18 =>0. If fees missing => assume 4 (document).

3.3 Add‑On Components
Component	Max	Rule
Price Cut	5	If previous_price and ((previous - current)/previous) ≥10% =>5; ≥5% =>3; else 0.
Renovation Potential (optional)	5	If reno_needed flag true AND ward_discount ≤ -15% => 5 else 0. (If no flag, treat as 0.)
Access	5	distance ≤500m =>5; ≤900m =>3; else 0; missing =>3.

3.4 Adjustments (Lean Subset)
Adjustment Var	Range	Rule
vision_positive	+0..+5	Exceptional combo: modern + strong light + good view (stub: if condition=modern & light=True)
vision_negative	0..-5	Severe defect (damage tokens ≥2 or “stain” + “mold” etc.)
data_quality_penalty	0..-8	Sum of DQ triggers (Section 4).
overstated_discount_penalty	0..-8	If discount explained mostly by being smallest size among comps (size z < -1) or oldest; subtract up to 8 (start simple: if size < min_size_comp + small_epsilon OR age > max_age_comp THEN -5).
strategic_premium (optional)	0..+3	Skip implementation initially (set always 0).

For v1.3: implement only vision_positive, vision_negative, data_quality_penalty, overstated_discount_penalty (strategic_premium constant 0).

3.5 Final Score
base_score = sum(base + add-on components)
final_score = clamp(base_score + (vision_positive + vision_negative + data_quality_penalty + overstated_discount_penalty), 0, 100)

3.6 Verdict
Verdict	Rule
BUY_CANDIDATE	final_score ≥75 AND ward_discount_pct ≤ -12% AND data_quality_penalty ≥ -4
WATCH	final_score 60–74 OR (ward_discount between -8% and -11.99%)
REJECT	Else

4. MINIMAL DATA QUALITY (DQ) RULES
Compute dq_penalty (sum; clamp ≥ -8):

Trigger	Penalty
Missing ward median	-4
<4 comps AND no building discount	-3
Critical null (price OR size)	-6 (and force REJECT by setting final_score=0 afterwards)

If any trigger -> attach data_quality_issue=true.

5. COMPARABLES (SIMPLE)
Function signature:

python
Copy
Edit
def select_comparables(subject: dict, pool: list[dict]) -> list[dict]:
    """
    Return up to 8 comparable listings filtered:
      ±30% price_per_sqm, ±25% size, ±10 years age (if age present).
    Sorted by absolute price_per_sqm delta then absolute size delta.
    """
Formatting for prompt: one line per comp:
<id> | <ppm2> | <size_m2> | <age_y?> | <floor?>

If <4 comps after filtering → DQ rule triggers (thin comps).

6. VISION STUB
New module not required (can inline in ETL) but recommended file:
analysis/vision_stub.py:

python
Copy
Edit
def basic_condition_from_images(filenames: list[str]) -> dict:
    """
    Infer condition_category and damage_tokens:
    - If any filename contains 'kitchen_new' -> modern
    - If 'renovation' in any -> modern
    - Else if 'kitchen' or 'bath' -> partial
    - Else dated
    - damage_tokens if filenames contain stain|mold
    Return {'condition_category': str, 'damage_tokens': [...], 'summary': str}
    """
Use only first 3 images.

7. PROMPT (LEAN FORMAT)
Order (when LEAN_PROMPT=1):

makefile
Copy
Edit
SYSTEM:
<<existing system intro (retain essential instructions)>>

GLOBAL:
MedianPPM2=<median_global>; Active=<count>; (optional 7dDelta=<pp_change>)

WARD:
Ward=<ward>; MedianPPM2=<median_ward>; Inventory=<inv_count>

COMPARABLES:
id | ppm2 | size | age | floor
...

PROPERTY:
{compact JSON subset: id, ward, price, price_per_sqm, size_m2, building_age_years, ward_discount_pct, base_score, comps_count}

VISION:
<short summary max ~60-80 tokens>

TASK:
Return ONLY JSON with keys:
property_id, base_score, final_score, verdict, upside[3], risks[3], justification (≤600 chars).
Ensure 3 distinct concise upside and risk phrases (≤60 chars each).
Token Controls:

Cap comps at 8.

If assembled token estimate >1200: drop comps to 6, else truncate vision summary to 60 tokens.

Never drop below 4 comps; if forced, set thin comps DQ flag.

8. LEAN LLM OUTPUT SCHEMA
JSON (no extra keys):

json
Copy
Edit
{
  "property_id": "...",
  "base_score": 0,
  "final_score": 0,
  "verdict": "BUY_CANDIDATE",
  "upside": ["","",""],
  "risks": ["","",""],
  "justification": "..."
}
Constraints:

Exactly 3 items each in upside & risks.

Each item ≤60 chars.

justification ≤600 chars.

base_score MUST match deterministic base (agent: verify after parse; if mismatch >2 points, override with deterministic base before storing).

If schema invalid on first attempt: 1 retry. Then mark failure log & skip.

Place schema file at: schemas/evaluation_min.json.

9. DAILY SNAPSHOTS
Script: snapshots/generate_snapshots.py

Output:

snapshots/current/global.json:

json
Copy
Edit
{"date":"YYYY-MM-DD","median_price_per_sqm":123456,"total_active":321,"seven_day_change_pp": -1.2}
snapshots/current/ward_<ward>.json:

json
Copy
Edit
{"date":"YYYY-MM-DD","ward":"調布市","median_price_per_sqm":654321,"inventory":42,"p25":..., "p75":...}
(If p25/p75 <4 listings, omit those keys.)

Cron at 08:55 JST (CloudWatch Event).

10. DAILY DIGEST
Lambda: notifications/daily_digest.py

Process:

Discover all candidates/YYYY-MM-DD/*.json

Filter verdict == BUY_CANDIDATE (limit 10).

HTML sections:

Header (date, global median)

BUY CANDIDATES table (id, ward, size, price, ppm2, ward_discount_pct, base_score, final_score)

WATCH summary (count only)

Generate CSV: reports/daily/YYYY-MM-DD/digest.csv.

Send single email (HTML; attach CSV optional).

Emit metric Digest.Sent.

11. METRICS (Emit These Only)
PropertiesProcessed

CandidatesEnqueued

CandidatesSuppressed (if cap reached)

LLM.Calls

Evaluator.SchemaFail

Digest.Sent (1 on success)

All as simple structured JSON logs OR CloudWatch EMF. Keep naming consistent.

12. LOGGING
Use existing JSON logging style. Add new log sample after gating:

json
Copy
Edit
{"component":"gating","properties_total":123,"candidates":19,"suppressed":0,"ratio":0.154}
On schema fail:

json
Copy
Edit
{"component":"llm_evaluator","event":"schema_fail","property_id":"1234567890","attempt":1}
13. GATING & DAILY CAP
Algorithm (in ETL stage, after scoring each listing):

yaml
Copy
Edit
if base_score >=70 and ward_discount_pct <= -8 and dq_penalty > -5:
    if candidates_today < MAX_CANDIDATES_PER_DAY:
        is_candidate = True
    else:
        is_candidate = False
        suppressed +=1
else:
    is_candidate = False
Maintain candidates_today by counting already selected in current batch + optionally reading count of existing candidate evaluation JSON for date (if batch restarts). (Simple: maintain an in-memory counter in current run.)

14. EVALUATION (llm_batch Modification)
Filter input list: only is_candidate == True.

For each candidate build lean prompt (if LEAN_PROMPT=1).

Call model once per candidate or keep existing batch pattern but ensure lean prompt slices.

After response:

Parse JSON.

If invalid: retry once.

If still invalid: log schema_fail & do not store (count Evaluator.SchemaFail).

Force base_score in output = deterministic base_score.

If final_score < base_score - 10 (nonsensical) => set final_score = base_score.

Store to: candidates/YYYY-MM-DD/{property_id}.json.

Update Dynamo item with base_score, final_score, verdict, ward_discount_pct.

15. TESTS (Add)
File	Purpose	Key Assertions
tests/test_scoring_basic.py	Scoring correctness	Ward discount linearity; DQ penalties; size boundary; price cut.
tests/test_comparables_basic.py	Filtering & ordering	≤8 comps, sorted by price diff.
tests/test_prompt_lean.py	Prompt assembly	Sections present; ≤8 comps; truncation to 6 triggers when forced.
tests/test_eval_schema.py	Validation logic	Good JSON passes; malformed triggers retry then failure.
tests/test_digest.py	Digest generation	HTML contains BUY CANDIDATE table headers; CSV row count matches.

Use minimal fixture listings under tests/fixtures/.

16. COMMIT PLAN (EXECUTE IN ORDER)
After each commit: run pytest -q (if tests exist), and show a short summary or diff chunk.

#	Commit Message	Summary of Changes
1	chore: add lean analysis scaffolding	Create dirs: analysis/, snapshots/, notifications/, schemas/; stub files.
2	feat(scoring): implement lean deterministic scoring module	Add analysis/lean_scoring.py with full compute logic & docstring; unit helpers.
3	feat(comparables): simple comparable selection & formatting	Add analysis/comparables.py; basic tests stub.
4	feat(etl): integrate scoring + comparables + gating + metrics	Modify etl/app.py; compute ward medians; gating & metrics logging.
5	feat(prompt): lean prompt path & image limit	Modify prompt_builder/app.py; new function build_lean_prompt(listing, context).
6	feat(prompt): candidate filtering in batch requests	Ensure only candidates passed forward; log counts.
7	feat(vision_stub): simple condition & damage token inference	Add analysis/vision_stub.py; integrate in ETL (first 3 images).
8	feat(snapshots): global & ward snapshot generator	Script & simple median calc; write JSON.
9	feat(digest): add daily digest lambda + HTML/CSV writers	New notifications/daily_digest.py.
10	infra: add snapshot & digest cron wiring (env flags)	Update CloudFormation templates; guard with LEAN_MODE.
11	feat(schema): add evaluation_min.json + validator util	Add schemas/evaluation_min.json + schemas/validate.py.
12	feat(llm_batch): enforce lean schema + 1 retry + mapping fallback	Update llm_batch/app.py; log schema_fail metric.
13	feat(gating): implement MAX_CANDIDATES_PER_DAY cap	Read env; track suppressed; metric CandidatesSuppressed.
14	feat(metrics): add LLM.Calls & Evaluator.SchemaFail	Add increments where appropriate.
15	feat(tests): add scoring & comparables tests	Implement first 2 test modules.
16	feat(tests): add prompt, evaluator schema, digest tests	Implement remaining tests.
17	chore(report): disable per-run immediate email under LEAN_MODE	Add guard to report sender lambda.
18	docs: update README with lean mode + env vars + usage	Add sections “Lean Mode” & “Scoring Overview”.
19	chore: add sample candidate JSON & sample digest artifacts	Put examples under examples/.
20	chore: cleanup + finalize migration notes	Add LEAN_NOTES.md summarizing changes & metrics checklist.

17. VALIDATION AFTER FINAL COMMIT
Agent must produce in output:

Scoring sample JSON (one listing) with: base_score, ward_discount_pct, dq_penalty, components breakdown.

Lean Prompt Example (redacted property id).

Candidate Ratio Log (line with ratio).

One stored candidate evaluation JSON (matching lean schema).

Digest HTML snippet (table header + one row).

Metrics lines for: PropertiesProcessed, CandidatesEnqueued, LLM.Calls, Evaluator.SchemaFail (0 acceptable), Digest.Sent.

Test run summary (counts passed).

Confirmation per-property immediate email disabled (show code diff or snippet condition).

If a check fails, create a new commit prefixed fix: immediately.

18. ROLLBACK / SAFETY FLAGS
Set LEAN_MODE=0 to revert to legacy prompt + per-run email path; new modules remain inert.

If scoring misbehaves: LEAN_SCORING=0 bypass logic (treat all as candidates but still log).

If schema strictness causes failures: LEAN_SCHEMA_ENFORCE=0 → map attempt from old output (if present) without failing batch.

Implement conditional checks once, centrally (e.g., small config.py utility).

19. IMPLEMENTATION GUIDELINES
No broad rewrites of existing modules.

No removal of existing successful LLM batch logic; only branch for lean mode.

All new functions must have docstrings with brief param typing if not using full type hints signature.

Keep dependencies minimal (prefer stdlib; avoid adding heavy libs for medians).

Use median calc: sort list, pick middle (odd) or average two (even).

Keep scoring pure (function receives primitives / dict; returns dict).

20. QUICK CODE SKELETONS (REFERENCE – COPY/ADAPT)
analysis/lean_scoring.py
python
Copy
Edit
from __future__ import annotations
from typing import Dict, Any, List, Optional

def linear_points(value: float, start: float, end: float, max_points: int) -> int:
    """
    Map value from start(0 pts) to end(max_points).
    If value beyond end in direction of improvement -> max_points.
    """
    if start == end:
        return 0
    if value <= end:
        return max_points
    if value >= start:
        return 0
    frac = (start - value) / (start - end)
    return int(round(frac * max_points))

def compute_base_and_adjustments(listing: Dict[str, Any],
                                 ward_median_ppm2: Optional[float],
                                 comps: List[Dict[str,Any]],
                                 vision: Dict[str,Any],
                                 previous_price: Optional[int]) -> Dict[str, Any]:
    """
    Returns {
      'base_score': int,
      'final_score': int,  # initial = base + adjustments
      'components': {...},
      'ward_discount_pct': float|None,
      'dq_penalty': int,
      'data_quality_issue': bool
    }
    """
    # Implement per spec...
    return result
analysis/comparables.py
python
Copy
Edit
from typing import List, Dict, Any

def select_comparables(subject: Dict[str,Any], pool: List[Dict[str,Any]]) -> List[Dict[str,Any]]:
    comps = []
    # filtering logic
    return comps[:8]

def format_comparable_lines(comps: List[Dict[str,Any]]) -> List[str]:
    lines = []
    for c in comps:
        lines.append(f"{c['id']} | {int(c['price_per_sqm'])} | {c['total_sqm']:.1f} | {c.get('building_age_years','?')} | {c.get('floor','?')}")
    return lines
Schema schemas/evaluation_min.json
json
Copy
Edit
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "LeanEvaluation",
  "type": "object",
  "required": ["property_id","base_score","final_score","verdict","upside","risks","justification"],
  "properties": {
    "property_id": {"type":"string"},
    "base_score": {"type":"integer"},
    "final_score": {"type":"integer"},
    "verdict": {"type":"string","enum":["BUY_CANDIDATE","WATCH","REJECT"]},
    "upside": {"type":"array","items":{"type":"string"},"minItems":3,"maxItems":3},
    "risks": {"type":"array","items":{"type":"string"},"minItems":3,"maxItems":3},
    "justification": {"type":"string","maxLength":700}
  },
  "additionalProperties": false
}
21. COMPLETION CONDITION
Declare SUCCESS only after all validation artifacts (Section 17) are printed.
If any acceptance item fails, re-open the relevant commit (suffix fix:) rather than silently amending multiple modules.

# EXECUTION WRAPPER & OUTPUT RULES
You have pre-approval to implement all steps in this prompt.

## Output / Patch Rules
- Emit patches in the EXACT block format below for each commit so my script can auto-apply:
  ===BEGIN COMMIT===
  Commit: <message>
  Diff:
  *** Start Patch
  <unified diff>
  *** End Patch
  ===END COMMIT===
- Do NOT ask for confirmation. Do NOT run shell commands. Just produce patches and short validation logs.
- Touch ONLY these paths (deny all others):
  analysis/**, snapshots/**, notifications/**, schemas/**, tests/**,
  ai-infra/lambda/etl/**, ai-infra/lambda/prompt_builder/**,
  ai-infra/lambda/llm_batch/**, ai-infra/lambda/report_sender/**,
  ai-infra/ai-stack.yaml, README.md, LEAN_NOTES.md, examples/**
- Never delete existing code unless required. Prefer branching logic with LEAN_* flags.

## Data Source Clarifications
- Ward medians & comps: First use the current batch of scraped/normalized listings. If batch too small (<4 listings in ward), fall back to a Dynamo scan of ACTIVE items for that ward (latest sort_key).
- Building discount: you may set 0 for v1.3 (no building snapshot yet).
- previous_price: if not stored, set price cut component = 0 (no attempt to infer).
- Carry cost fees missing -> assume best case (4 pts) and note that in code comments.

## Config Centralization
- Add ai-infra/lambda/util/config.py (or similar) with helpers:
  get_bool("LEAN_MODE", default=False)
  get_int("MAX_CANDIDATES_PER_DAY", default=120)
  etc.
- All Lambdas import from this file instead of reading os.getenv everywhere.

## LLM Call Mode
- Reuse existing batch mechanism but only include candidates in batch_requests.
- Keep one response per candidate in batch_output; continue to parse individually.

## End-of-Run Validation Block
After the final commit block, print ONE JSON object named `lean_validation` with:
{
  "sample_scoring": {...},
  "lean_prompt_example": "...",
  "candidate_ratio_log": "...",
  "sample_eval_json": {...},
  "digest_html_snippet": "<table>...</table>",
  "metrics_seen": ["PropertiesProcessed", ...],
  "tests_passed": true,
  "immediate_email_disabled": true
}
All values should be real (from code or mocked example), not placeholders.
If any cannot be produced, say why and add a FIX commit.

Do not exceed 300 lines per commit diff unless unavoidable.

(Agent: begin with Commit 1. Spin up many sub agents to speed up the work. Provide diff/summary per commit and wait for confirmation only if instructed. Otherwise proceed automatically to next commit after internal validation passes.)

# SUB-AGENT EXECUTION DIRECTIVE (compact)
Spin up 4 sub agents and have each one work on these seperate tasks:

A) scoring + comparables + gating + config  
B) lean prompt + schema/validator + llm_batch changes  
C) snapshots + daily_digest + metrics wiring  
D) tests + docs (README/LEAN_NOTES)


END OF EXECUTION PROMPT

