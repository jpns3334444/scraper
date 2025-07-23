# Tokyo Real Estate Lean Analysis System

This repository contains an automated pipeline for analysing Tokyo real estate listings using a deterministic workflow referred to as **Lean v1.3**.  The code is intended to be maintained entirely by coding agents.  The pipeline collects property data, scores and filters candidates and generates a daily digest email.

## Overview

The repository is split into two major parts:

- **scraper/** – an EC2 based scraper that downloads property listings and images to S3.
- **ai_infra/** – a collection of AWS Lambda functions orchestrated by Step Functions that process the scraped data.

Supporting modules live under `analysis/`, `snapshots/`, `notifications/` and `schemas/`.  Unit tests are located in `tests/`.

## Lean v1.3 Workflow

1. **ETL** – normalises raw listings and applies deterministic scoring defined in `analysis/lean_scoring.py`.
2. **Candidate gating** – properties meeting score and discount thresholds are kept for LLM analysis.  Only ~20% of listings become candidates.
3. **Prompt builder & LLM** – candidates are enriched with comparables and a short prompt is sent to the LLM to obtain qualitative notes (upsides, risks, justification).  Schema validation is enforced via `schemas/evaluation_min.json`.
4. **Snapshots & Digest** – daily market snapshots are generated and a single digest email summarising all candidates is produced.

The LLM is only used for short text generation on gated candidates.  All scoring logic and gating rules are implemented in Python for deterministic behaviour.

## Important Environment Variables

```
LEAN_MODE=1                 # Enable Lean pipeline (default 0)
LEAN_SCORING=1              # Use deterministic scoring
LEAN_PROMPT=1               # Use lean prompt structure
LEAN_SCHEMA_ENFORCE=1       # Enforce JSON schema on LLM output
MAX_CANDIDATES_PER_DAY=120  # Safety limit on daily candidates
OUTPUT_BUCKET=<s3-bucket>   # Destination for processed data
AWS_REGION=ap-northeast-1   # Deployment region (Tokyo only)
```

## Repository Layout

```
analysis/       Deterministic scoring and comparable selection modules
notifications/  Daily digest generation and notifier helpers
snapshots/      Market snapshot utilities
schemas/        JSON schema definitions and dataclasses
ai_infra/       Lambda functions and Step Functions definition
scraper/        EC2 scraper and deployment scripts
examples/       Sample candidate data and digest output
```

## Running Tests

Install Python 3.11 and the required packages then execute `pytest`:

```bash
pip install boto3 pandas requests responses moto==4.2.14 openai jsonschema
pytest -q
```

Tests cover scoring, comparable selection, prompt assembly and digest creation.  They can be used as a reference when modifying pipeline components.

## Notes for Coding Agents

- The system is deterministic by default.  Avoid sending all listings to the LLM.
- Limit new dependencies – Lambda functions rely on AWS provided runtimes.
- Keep modules small and unit testable.  When adding features create tests in `tests/`.
- Deployment scripts are located in `scraper/` and `ai_infra/`; SAM or Docker are not used.

