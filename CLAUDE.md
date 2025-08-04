
# Agents.md

This document provides a comprehensive overview of the real-estate-scraper repository for future coding agents.

## Project Overview

This project is a serverless real estate data scraper and analyzer built on AWS. It collects property listings from a website, processes the data, analyzes it using an LLM, and displays the results on a dashboard. The project is composed of several Lambda functions, a DynamoDB database, and a static S3 website for the dashboard.

## Architecture

The architecture is event-driven and composed of the following main components:

*   **URL Collector:** A Lambda function that scrapes the real estate website for property listing URLs and stores them in a DynamoDB table.
*   **Property Processor:** A Lambda function that is triggered by new URLs in the DynamoDB table. It scrapes the detailed information for each property and stores it in another DynamoDB table.
*   **Property Analyzer:** A Lambda function that is triggered by new properties in the DynamoDB table. It uses an LLM to analyze the property data and enriches the data in the DynamoDB table with the analysis results.
*   **Dashboard API:** A Lambda function that serves as a backend for the dashboard, providing data from the DynamoDB table.
*   **Dashboard:** A static HTML/JavaScript website hosted on S3 that displays the property listings and analysis.
*   **Favorites API:** A Lambda function to manage user's favorite properties.
*   **Favorite Analyzer:** A Lambda function to analyze user's favorite properties.

## Lambdas

### `url_collector`

*   **Purpose:** Scrapes the real estate website for property listing URLs.
*   **Trigger:** Can be triggered manually or on a schedule.
*   **Dependencies:** `boto3`, `requests`, `beautifulsoup4`.
*   **Output:** Stores new URLs in the `url-collector-table` DynamoDB table.

### `property_processor`

*   **Purpose:** Scrapes the detailed information for each property.
*   **Trigger:** Triggered by new items in the `url-collector-table` DynamoDB table.
*   **Dependencies:** `boto3`, `requests`, `beautifulsoup4`.
*   **Output:** Stores detailed property information in the `property-details-table` DynamoDB table.

### `property_analyzer`

*   **Purpose:** Analyzes property data using an LLM.
*   **Trigger:** Triggered by new items in the `property-details-table` DynamoDB table.
*   **Dependencies:** `boto3`, `openai`.
*   **Output:** Updates the corresponding item in the `property-details-table` with the analysis results.

### `dashboard_api`

*   **Purpose:** Provides data to the dashboard.
*   **Trigger:** Triggered by HTTP requests from the dashboard.
*   **Dependencies:** `boto3`.
*   **Output:** Returns property data as JSON.

### `favorites_api`

*   **Purpose:** Manages user's favorite properties.
*   **Trigger:** Triggered by HTTP requests from the dashboard.
*   **Dependencies:** `boto3`.
*   **Output:** Manages favorites in the `favorites-table` DynamoDB table.

### `favorite_analyzer`

*   **Purpose:** Analyzes user's favorite properties.
*   **Trigger:** Triggered by new items in the `favorites-table` DynamoDB table.
*   **Dependencies:** `boto3`, `openai`.
*   **Output:** Stores analysis results in the `favorites-analysis-table` DynamoDB table.

## Deployment

The project is deployed using AWS SAM (Serverless Application Model).

*   **AI Stack (`ai-stack.yaml`):** Defines the core serverless application, including the Lambda functions, DynamoDB tables, and IAM roles.
*   **Dashboard Stack (`dashboard/dashboard-stack.yaml`):** Defines the resources for the dashboard, including the S3 bucket for hosting the static website and the CloudFront distribution.

## Important Commands

*   **Deploy AI Stack:** `./deploy-ai.sh`
*   **Deploy Dashboard:** `cd dashboard && ./deploy-dashboard.sh`
*   **Update a specific Lambda:** `./update-lambda.sh <lambda-name>` (e.g., `./update-lambda.sh url_collector`)
*   **Trigger a specific Lambda:** `./trigger-lambda.sh <lambda-name>` (e.g., `./trigger-lambda.sh url_collector`)
*   **Clear DynamoDB tables:** `python clear-dydb.py`
*   **Diagnose CORS issues:** `cd dashboard && ./cors_diagnose.sh`