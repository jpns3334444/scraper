
# GEMINI.md

## Project Overview

This project is a serverless web application for analyzing real estate data in Tokyo. It scrapes property listings from a website, processes the data, and provides a web interface for users to view and analyze the properties. The application uses a combination of AWS services for the backend and a vanilla JavaScript frontend.

The backend is built with AWS Lambda functions written in Python. It uses DynamoDB for data storage and S3 for storing data files. The entire infrastructure is defined as code using an AWS CloudFormation template (`ai-stack.yaml`).

The frontend is a single-page application (SPA) that allows users to view property listings, filter them, and manage their favorite properties. It interacts with the backend through a set of APIs.

## Building and Running

### Backend

The backend is deployed using AWS CloudFormation. The `ai-stack.yaml` file defines all the necessary resources, including:

*   **Lambda Functions:**
    *   `URLCollectorFunction`: Collects property listing URLs.
    *   `PropertyProcessorFunction`: Processes the collected URLs and scrapes property details.
    *   `PropertyAnalyzerFunction`: Analyzes the scraped property data.
    *   `FavoriteAnalyzerFunction`: Analyzes user's favorite properties.
    *   `DashboardAPIFunction`: Provides data for the main dashboard.
    *   `FavoritesAPIFunction`: Manages user's favorite properties.
    *   `RegisterUserFunction`: Handles user registration.
    *   `LoginUserFunction`: Handles user login.
*   **DynamoDB Tables:**
    *   `RealEstateAnalysisDB`: Stores the main property data.
    *   `URLTrackingDB`: Tracks the status of scraped URLs.
    *   `UsersTable`: Stores user authentication information.
    *   `UserPreferencesTable`: Stores user's favorite and hidden properties.
*   **S3 Buckets:**
    *   A deployment bucket for storing Lambda code.
    *   An output bucket for storing processed data.

To deploy the backend, you would typically use the AWS CLI to create or update the CloudFormation stack defined in `ai-stack.yaml`. The `deploy-ai.sh` script likely automates this process.

### Frontend

The frontend is a vanilla JavaScript application. It doesn't appear to have a complex build process. The `deploy-frontend.sh` script likely handles deploying the frontend by copying the static files (HTML, CSS, JavaScript) to an S3 bucket configured for static website hosting.

To run the frontend locally, you would typically serve the `front-end` directory using a simple HTTP server.

## Development Conventions

*   **Backend:**
    *   The backend code is written in Python 3.12.
    *   The Lambda functions use the `boto3` library to interact with AWS services.
    *   The code is organized into separate Lambda functions for different tasks.
    *   The `property_processor` Lambda function uses a thread pool to process multiple URLs in parallel, which is a good practice for I/O-bound tasks.
*   **Frontend:**
    *   The frontend code is written in vanilla JavaScript (ES6+).
    *   The code is organized into modules for different features (e.g., `AuthManager`, `PropertiesManager`, `FavoritesManager`).
    *   The application uses a global `app` object to manage the application state and components.
    *   The code uses a `Router` class to handle client-side routing.
