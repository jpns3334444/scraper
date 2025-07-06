# Scraper Project Improvements & Recommendations

## Context Prompt for LLM Sessions

**Copy this prompt to start a new session:**

```
I'm working on a web scraper project that targets homes.co.jp (Japanese real estate website). The project consists of:

1. **scrape.py** - Python HTTP-based scraper using requests/BeautifulSoup that:
   - Scrapes property listings from homes.co.jp/mansion/chuko/tokyo/chofu-city/list
   - Uses session management and realistic browser headers to avoid detection
   - Extracts property details (title, price, specifications) from individual listing pages
   - Uses threading for parallel processing (2 threads max)
   - Saves results to CSV and uploads to S3
   - Implements structured JSON logging

2. **scraper-stack.yaml** - AWS CloudFormation template that creates:
   - EC2 instance (t3.small, Ubuntu 22.04) with scraper code
   - IAM roles with permissions for S3, CloudWatch, Secrets Manager
   - S3 bucket for storing scraped data
   - Lambda function for triggering scraper via SSM
   - EventBridge rule for daily scheduled runs (2 AM JST)
   - SNS notifications for job status
   - CloudWatch logging integration

3. **deploy.sh** - Deployment script that:
   - Retrieves GitHub token from AWS Secrets Manager
   - Validates CloudFormation template
   - Handles stack creation/updates with change sets
   - Streams deployment events in real-time
   - Manages IP whitelisting for SSH access

4. **ssm-scraper.sh** - Utility script for SSM session management to EC2 instance

The project is currently functional but needs improvements for production use. Please help me work on the specific improvements listed in the IMPROVEMENTS.md file.
```

## Overview
This document outlines recommended improvements and changes for the web scraper project targeting homes.co.jp. The project consists of a Python scraper, AWS CloudFormation infrastructure, and deployment scripts.

## High Priority Improvements

### 1. Security Issues
- ~~**CRITICAL**: GitHub Personal Access Token exposed in `deploy.sh:12`~~ ✅ **COMPLETED**
  - ~~Remove hardcoded token: `GITHUB_TOKEN="${GITHUB_TOKEN:-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}"`~~
  - ~~Use environment variables or AWS Secrets Manager instead~~ ✅ **Implemented AWS Secrets Manager**
  - ~~Revoke and regenerate the exposed token immediately~~ ✅ **Token revoked and regenerated**

### 2. Code Quality & Maintainability

#### scrape.py
- **Rate Limiting**: Add exponential backoff and better retry logic
- **Error Handling**: Improve exception handling in `extract_property_details:142`
- **Configuration**: Extract hardcoded values to environment variables or config file
  - Base URL, max pages, thread count, timeouts
- **Logging**: Replace print statements with proper logging framework
- **Data Validation**: Add validation for extracted property data
- **Resource Management**: Ensure proper cleanup of HTTP sessions

#### Infrastructure (scraper-stack.yaml)
- **AMI ID**: Hardcoded Ubuntu AMI (`ami-09013b9396188007c:148`) should be parameterized
- **Instance Type**: Make instance type configurable via parameter
- **Security Groups**: Add egress rules for better security posture
- **Error Handling**: Improve CloudFormation error handling and rollback scenarios

### 3. Monitoring & Observability
- **CloudWatch Metrics**: Add custom metrics for scraper performance
- **Alerting**: Set up alerts for scraper failures and performance issues
- **Structured Logging**: Implement proper JSON logging format consistently
- **Health Checks**: Add health check endpoints or status reporting

### 4. Reliability & Resilience
- **Circuit Breaker**: Implement circuit breaker pattern for external API calls
- **Dead Letter Queue**: Add SQS DLQ for failed scraper jobs
- **Graceful Shutdown**: Handle interruption signals properly
- **Data Persistence**: Add backup mechanisms for scraped data

## Medium Priority Improvements

### 5. Performance Optimization
- **Connection Pooling**: Implement HTTP connection pooling
- **Caching**: Add caching for repeated requests
- **Parallel Processing**: Optimize threading strategy and resource usage
- **Memory Management**: Monitor and optimize memory usage patterns

### 6. Data Quality
- **Schema Validation**: Define and validate data schemas
- **Data Deduplication**: Implement duplicate detection and removal
- **Data Enrichment**: Add data quality checks and enrichment
- **Export Formats**: Support multiple export formats (JSON, Parquet, etc.)

### 7. Operational Excellence
- **Deployment Pipeline**: Implement CI/CD pipeline
- **Environment Management**: Add staging/production environment separation
- **Configuration Management**: Centralize configuration management
- **Documentation**: Add comprehensive API and deployment documentation

## Low Priority Improvements

### 8. Feature Enhancements
- **Scheduling**: Make scraper schedule configurable
- **Data Filtering**: Add filtering capabilities for scraped data
- **Notifications**: Enhance notification system with multiple channels
- **Dashboard**: Create monitoring dashboard for scraper metrics

### 9. Code Organization
- **Modularization**: Split large functions into smaller, focused modules
- **Type Hints**: Add comprehensive type hints throughout the codebase
- **Testing**: Add unit tests and integration tests
- **Linting**: Set up code linting and formatting tools

## Implementation Priority

1. **IMMEDIATE**: Fix security vulnerabilities (GitHub token exposure)
2. **Week 1**: Implement proper logging and error handling
3. **Week 2**: Add monitoring and alerting
4. **Week 3**: Improve reliability and resilience
5. **Month 2**: Performance optimization and data quality improvements
6. **Month 3**: Operational excellence and feature enhancements

## Files Requiring Changes

### Critical Changes
- `deploy.sh` - Remove hardcoded GitHub token
- `scrape.py` - Improve error handling and logging
- `scraper-stack.yaml` - Parameterize AMI ID and improve security

### Recommended Changes
- Add `requirements.txt` for Python dependencies
- Add `config.yaml` for scraper configuration
- Add `tests/` directory for test files
- Add `.gitignore` to exclude sensitive files
- Add `README.md` with setup and usage instructions

## Security Recommendations
- Use AWS Secrets Manager for sensitive configuration
- Implement least privilege IAM policies
- Add VPC endpoint for S3 access
- Enable CloudTrail logging for audit trails
- Use encrypted S3 buckets for data storage

## Monitoring Strategy
- Set up CloudWatch dashboards for scraper metrics
- Implement custom metrics for scraping success/failure rates
- Add alerts for high error rates or long execution times
- Monitor EC2 instance health and resource utilization
- Track S3 storage costs and usage patterns