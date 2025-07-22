# CLAUDE.md

> **Lean v1.3 Notice (2025-07)**  
> The pipeline is now **deterministic‑first**. Python code computes discounts, scores, candidate gating, snapshots, and the daily digest.  
> The LLM is used **only** for concise qualitative text (3 upsides, 3 risks, short justification) on **gated candidates**.  
> If anything in this file conflicts with the Lean v1.3 spec or env flags, **Lean v1.3 wins**.

---

## How to Work in This Repo (for Claude Code)

- **Do NOT re-introduce “send every listing to the LLM”.**  
- **Honor feature flags** (see below) and route logic through deterministic modules when `LEAN_MODE=1`.  
- **Touch only relevant paths** unless explicitly asked:  
  `analysis/**, snapshots/**, notifications/**, schemas/**, tests/**, ai-infra/lambda/**, README.md, LEAN_NOTES.md, examples/**, ai-infra/ai-stack.yaml`.

### Environment Flags (read via a central config helper, not scattered `os.getenv`)
LEAN_MODE=1 # Master switch for lean pipeline
LEAN_SCORING=1 # Enable deterministic scoring/gating
LEAN_PROMPT=1 # Use lean prompt structure
LEAN_SCHEMA_ENFORCE=1 # Strict JSON schema for LLM output
MAX_CANDIDATES_PER_DAY=120

pgsql
Copy
Edit
If a flag is absent, defaults apply (LEAN_MODE defaults to 0 for safety; others to 1).

---

## Deterministic vs LLM Responsibilities

| Area/Metric                      | Deterministic (Python) | LLM |
|----------------------------------|-------------------------|-----|
| price_per_m², discounts, medians | ✅                       |     |
| base_score, dq_penalty, verdict gate | ✅                  |     |
| comparables (filter/sort ≤8)     | ✅                       |     |
| snapshots (global/ward)          | ✅                       |     |
| daily digest tables/CSV          | ✅                       |     |
| upsides/risks/justification text |                         | ✅  |

---

## Current Architecture (Lean v1.3)

```mermaid
graph TB
    subgraph "Data Collection (EC2)"
        WEB[Real Estate Sites] --> SCRAPER[scraper/scrape.py]
        CRON1[Daily Cron] --> SCRAPER
        SCRAPER --> S3[(S3 Bucket)]
    end

    subgraph "Data Storage"
        S3 --> RAW[raw/YYYY-MM-DD/...]
        S3 --> CLEAN[clean/YYYY-MM-DD/listings.jsonl]
        S3 --> IMAGES[raw/YYYY-MM-DD/images/*.jpg]
    end

    subgraph "Analysis Workflow (Serverless)"
        EB[EventBridge cron]
        SF[Step Functions]

        subgraph "Lambdas"
            L1[ETL Lambda\nNormalize + Deterministic Scoring/Gating]
            L2[Prompt Builder (Lean)\nCandidates only, ≤8 comps, ≤3 images]
            L3[LLM Batch Lambda\nStrict JSON schema; 1 retry]
            L4[Snapshot Lambda\nGlobal/Ward medians JSON]
            L5[Daily Digest Lambda\nHTML + CSV email]
        end
    end

    subgraph "External Services"
        OAI[OpenAI LLM API (o3/GPT-4.1)]
        SES[Amazon SES]
        SLACK[Slack (optional)]
    end

    subgraph "Outputs"
        PROCESSED[processed/current/{property_id}.json]
        CANDS[candidates/YYYY-MM-DD/{property_id}.json]
        SNAP_G[snapshots/current/global.json]
        SNAP_W[snapshots/current/ward_*.json]
        DIGEST_H[reports/daily/YYYY-MM-DD/digest.html]
        DIGEST_C[reports/daily/YYYY-MM-DD/digest.csv]
    end

    EB --> SF
    SF --> L1 --> L2 --> L3
    L4 --> SNAP_G
    L4 --> SNAP_W
    L5 --> DIGEST_H
    L5 --> DIGEST_C
    L5 --> SES
    L5 --> SLACK

    L3 --> CANDS
    L1 --> PROCESSED
    SCRAPER --> RAW
    SCRAPER --> IMAGES
    L1 --> CLEAN
Key Files & Responsibilities
scraper/scrape.py: Collect raw listings & images → S3.

ai-infra/lambda/etl/app.py: Normalize, compute deterministic scores/discounts, select comps, gate candidates, persist to Dynamo/S3.

analysis/lean_scoring.py: Pure functions for scoring & DQ penalties.

analysis/comparables.py: Filter & format comparables (≤8).

analysis/vision_stub.py (optional): Crude condition inference from filenames.

snapshots/generate_snapshots.py: Daily global/ward medians & inventory.

ai-infra/lambda/prompt_builder/app.py: Lean prompt assembly (only candidates).

ai-infra/lambda/llm_batch/app.py: LLM call, strict JSON schema validation, one retry.

notifications/daily_digest.py: Build & email HTML + CSV digest.

schemas/evaluation_min.json: Lean LLM output schema.

Deployment & Region
Use existing deploy scripts (deploy-ai.sh, deploy-compute.sh, deploy-all.sh).

We are ANTI-SAM. Do not use SAM.

Region: ap-northeast-1 (Tokyo) ONLY. Never us-east-1.

When Editing Code
Prefer new modules over huge diffs in legacy ones.

Keep scoring/comparables pure & unit-testable.

Emit only the minimal metrics listed in Lean v1.3 (PropertiesProcessed, CandidatesEnqueued, CandidatesSuppressed, LLM.Calls, Evaluator.SchemaFail, Digest.Sent).

Truncate logged prompts/outputs >1500 chars.

Conflict Resolution
If older docs/comments say “send every property to LLM” or “per-property emails,” ignore them.
Lean v1.3 supersedes legacy behavior whenever LEAN_MODE=1.

Success Checklist (For Big Changes)
Deterministic fields (base_score, ward_discount_pct, etc.) stored in Dynamo/S3.

Candidate ratio ≤ ~20% of total (tunable).

Daily digest created & emailed once/day; per-property emails disabled.

Lean prompt size ≤ ~1200 tokens; ≤8 comps, ≤3 images.

LLM output passes evaluation_min.json schema or is retried once.

Minimal tests added & passing.