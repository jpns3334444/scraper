# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is a Tokyo Real Estate Analysis system combining web scraping and AI-powered investment analysis. The system consists of two complementary subsystems:

1.  **Data Collection System** (`/scraper/`): EC2-based web scraper that collects daily property data
2.  **AI Analysis System** (`/ai-infra/`, `/lambda/`): Serverless pipeline that processes data and generates investment reports using OpenAI GPT-4.1

## System Architecture

```mermaid
graph TB
    subgraph "Data Collection System (EC2)"
        WEB[Real Estate Websites] --> SCRAPER[Web Scraper<br/>scrape.py]
        SCRAPER --> S3[(S3 Bucket<br/>tokyo-real-estate-ai-data)]
        CRON1[Daily Cron] --> SCRAPER
    end
    
    subgraph "Data Storage"
        S3 --> CSV[Daily CSV<br/>raw/YYYY-MM-DD/listings.csv]
        S3 --> IMG[Property Images<br/>raw/YYYY-MM-DD/images/*.jpg]
    end
    
    subgraph "Daily AI Analysis Schedule"
        EB[EventBridge Rule<br/>cron: 0 18 * * ? *<br/>03:00 JST]
    end
    
    subgraph "AI Analysis Workflow"
        SF[Step Functions<br/>State Machine]
        
        subgraph "Lambda Functions"
            L1[ETL Lambda<br/>CSV → JSONL<br/>Feature Engineering]
            L2[Prompt Builder<br/>JSONL → Vision Prompt<br/>Interior Photo Selection]
            L3[LLM Batch Lambda<br/>OpenAI Batch API<br/>GPT-4.1 Analysis]
            L4[Report Sender<br/>Markdown Generation<br/>Slack + Email]
        end
    end
    
    subgraph "External Services"
        OAI[OpenAI<br/>Batch API<br/>GPT-4.1]
        SLACK[Slack<br/>Webhook]
        SES[Amazon SES<br/>Email]
    end
    
    subgraph "Generated Outputs"
        JSONL[clean/YYYY-MM-DD/<br/>listings.jsonl]
        PROMPT[prompts/YYYY-MM-DD/<br/>payload.json]
        RESULT[batch_output/YYYY-MM-DD/<br/>response.json]
        REPORT[reports/YYYY-MM-DD/<br/>report.md]
    end
    
    EB --> SF
    SF --> L1
    L1 --> L2
    L2 --> L3
    L3 --> L4
    
    CSV --> L1
    IMG --> L2
    L1 --> JSONL
    L2 --> PROMPT
    L2 --> OAI
    L3 --> OAI
    L3 --> RESULT
    L4 --> REPORT
    L4 --> SLACK
    L4 --> SES
    
    S3 -.-> CSV
    S3 -.-> IMG
    S3 --> JSONL
    S3 --> PROMPT
    S3 --> RESULT
    S3 --> REPORT
```

## Deployment Best Practices

- **Deployment Guidelines**:
  - We have deploy functions for anything that needs to be deployed. they will give us good logs, always use those, don't deploy manually unless it makes more sense. for example: deploy-ai.sh, deploy-compute.sh, deploy-all.sh.

## Important Principles

- We are ANTI SAM. we do not use SAM ever.

## Regional Configuration

- Remember, never use us-east-1 for anything. everything is in ap-northeast-1, tokyo