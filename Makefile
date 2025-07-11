# AI Real Estate Analysis - Makefile
# Provides convenient commands for development and deployment

.PHONY: help install test lint format build deploy clean local-run

# Default target
help:
	@echo "AI Real Estate Analysis - Available Commands"
	@echo ""
	@echo "Development:"
	@echo "  install     Install all dependencies"
	@echo "  test        Run all tests"
	@echo "  lint        Run linting checks"
	@echo "  format      Format code with ruff"
	@echo "  type-check  Run type checking with mypy"
	@echo ""
	@echo "Build & Deploy:"
	@echo "  build       Package Lambda functions for CloudFormation"
	@echo "  deploy-dev  Deploy to development environment"
	@echo "  deploy-prod Deploy to production environment"
	@echo "  validate    Validate CloudFormation template"
	@echo ""
	@echo "Local Testing:"
	@echo "  local-run   Run local test with sample data"
	@echo "  clean       Clean build artifacts"
	@echo ""
	@echo "Examples:"
	@echo "  make local-run DATE=2025-07-07"
	@echo "  make deploy-dev BUCKET=my-sam-bucket OPENAI_KEY=sk-..."

# Variables
PYTHON := python3.8
LAMBDA_DIRS := lambda/etl lambda/prompt_builder lambda/llm_batch lambda/report_sender

# Development commands
install:
	@echo "Installing dependencies..."
	$(PYTHON) -m pip install --upgrade pip
	pip install ruff mypy pytest pytest-cov
	pip install -r tests/requirements.txt
	@for dir in $(LAMBDA_DIRS); do \
		if [ -f "$$dir/requirements.txt" ]; then \
			echo "Installing $$dir dependencies..."; \
			pip install -r "$$dir/requirements.txt"; \
		fi; \
	done

test:
	@echo "Running tests..."
	pytest tests/ -v --cov=lambda --cov-report=term-missing --cov-report=html

test-verbose:
	@echo "Running tests with verbose output..."
	pytest tests/ -v -s --cov=lambda --cov-report=term-missing

lint:
	@echo "Running linting checks..."
	ruff check lambda/ tests/ --select=E9,F63,F7,F82
	ruff check lambda/ tests/

format:
	@echo "Formatting code..."
	ruff format lambda/ tests/

format-check:
	@echo "Checking code formatting..."
	ruff format lambda/ tests/ --check

type-check:
	@echo "Running type checks..."
	@for dir in $(LAMBDA_DIRS); do \
		if [ -f "$$dir/app.py" ]; then \
			echo "Type checking $$dir..."; \
			mypy "$$dir/app.py" --ignore-missing-imports --check-untyped-defs; \
		fi; \
	done

# Build commands
build:
	@echo "Packaging Lambda functions for CloudFormation..."
	cd ai-infra && ./package-lambdas.sh

validate:
	@echo "Validating CloudFormation template..."
	aws cloudformation validate-template --template-body file://ai-infra/ai-stack-cfn.yaml

# Deployment commands
deploy-dev:
	@echo "Deploying to development environment..."
	cd ai-infra && ./deploy-cfn.sh --stack-name ai-scraper-dev

deploy-prod:
	@echo "Deploying to production environment..."
	cd ai-infra && ./deploy-cfn.sh --stack-name ai-scraper-prod

# Local testing
local-run:
ifndef DATE
	$(eval DATE := $(shell date +%Y-%m-%d))
endif
	@echo "Running local test for date: $(DATE)"
	@echo "Note: This requires sample data in sample_data/ directory"
	mkdir -p sample_data/raw/$(DATE)/images
	mkdir -p sample_data/clean/$(DATE)
	mkdir -p sample_data/prompts/$(DATE)
	mkdir -p sample_data/batch_output/$(DATE)
	mkdir -p sample_data/reports/$(DATE)
	
	# Create sample CSV if it doesn't exist
	@if [ ! -f "sample_data/raw/$(DATE)/listings.csv" ]; then \
		echo "Creating sample CSV data..."; \
		echo "id,headline,price_yen,area_m2,year_built,walk_mins_station,ward,photo_filenames" > sample_data/raw/$(DATE)/listings.csv; \
		echo "sample1,\"Test Apartment in Shibuya\",25000000,65.5,2015,8,Shibuya,\"living_room.jpg|bedroom.jpg|kitchen.jpg\"" >> sample_data/raw/$(DATE)/listings.csv; \
		echo "sample2,\"Cozy Studio in Harajuku\",18000000,35.2,2018,5,Shibuya,\"interior_view.jpg|balcony.jpg\"" >> sample_data/raw/$(DATE)/listings.csv; \
		echo "sample3,\"Family Home in Setagaya\",45000000,95.0,2010,15,Setagaya,\"living_area.jpg|dining_room.jpg|exterior.jpg\"" >> sample_data/raw/$(DATE)/listings.csv; \
	fi
	
	# Create sample image files
	@for img in living_room.jpg bedroom.jpg kitchen.jpg interior_view.jpg balcony.jpg living_area.jpg dining_room.jpg exterior.jpg; do \
		if [ ! -f "sample_data/raw/$(DATE)/images/$$img" ]; then \
			echo "fake_image_data" > "sample_data/raw/$(DATE)/images/$$img"; \
		fi; \
	done
	
	@echo "Sample data created. Note: For full local testing, you would need to:"
	@echo "1. Set up local S3 using localstack"
	@echo "2. Configure OpenAI API key for testing"
	@echo "3. Run each Lambda function individually with test data"

# Maintenance commands
clean:
	@echo "Cleaning build artifacts..."
	rm -rf ai-infra/.aws-sam
	rm -rf .pytest_cache
	rm -rf htmlcov
	rm -rf .coverage
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name ".DS_Store" -delete

# CloudFormation commands
cfn-package:
	@echo "Packaging Lambda functions for CloudFormation..."
	cd ai-infra && ./package-lambdas.sh

cfn-deploy-with-params:
	@echo "Deploying with custom parameters..."
ifndef EMAIL_FROM
	@echo "Error: EMAIL_FROM variable is required"
	@exit 1
endif
ifndef EMAIL_TO
	@echo "Error: EMAIL_TO variable is required"
	@exit 1
endif
	cd ai-infra && ./deploy-cfn.sh --email-from $(EMAIL_FROM) --email-to $(EMAIL_TO)

# Test individual Lambda functions locally
test-etl-local:
	cd lambda/etl && python app.py

test-prompt-builder-local:
	cd lambda/prompt_builder && python app.py

test-llm-batch-local:
	cd lambda/llm_batch && python app.py

test-report-sender-local:
	cd lambda/report_sender && python app.py

# Quick development workflow
dev-setup: install format lint type-check test
	@echo "Development setup complete!"

# Pre-commit checks
pre-commit: format-check lint type-check test
	@echo "Pre-commit checks passed!"

# CI/CD simulation
ci: install format-check lint type-check test validate cfn-package
	@echo "CI pipeline simulation complete!"