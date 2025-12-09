# Property Analyzer Lambda Function

This Lambda function analyzes real estate properties in the US Real Estate AI system by computing investment scores and verdicts based on market data and property characteristics.

## IAM Policy Requirements

The Lambda function requires the following DynamoDB permissions:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "dynamodb:Scan",
                "dynamodb:UpdateItem"
            ],
            "Resource": "arn:aws:dynamodb:us-east-1:*:table/real-estate-ai-properties"
        }
    ]
}
```

## Environment Variables

- `DYNAMODB_TABLE`: DynamoDB table name (default: `real-estate-ai-properties`)
- `AWS_REGION`: AWS region (default: `us-east-1`)
- `LOG_LEVEL`: Logging level (default: `INFO`)

## Function Overview

The function performs these steps:
1. Scans all property records with `sort_key='META'` from DynamoDB
2. Calculates ward-level median prices and statistics
3. Analyzes each property using 12 scoring components
4. Determines investment verdict (BUY_CANDIDATE/WATCH/REJECT)
5. Updates each property record with enrichment data

## Scoring Components

- **Ward Discount (0-25 pts)**: Price vs ward median
- **Building Discount (0-10 pts)**: Price vs same building median
- **Comps Consistency (0-10 pts)**: Price consistency in ward
- **Condition (0-7 pts)**: Building age assessment
- **Size Efficiency (0-4 pts)**: Optimal size range scoring
- **Carry Cost (0-4 pts)**: Monthly fees vs price ratio
- **Price Cut (0-5 pts)**: Historical price reductions
- **Renovation Potential (0-5 pts)**: Improvement opportunity
- **Access (0-5 pts)**: Station distance scoring
- **Vision Positive (0-5 pts)**: View quality bonus
- **Vision Negative (-5-0 pts)**: View obstruction penalty
- **Data Quality Penalty (-8-0 pts)**: Missing field penalty
- **Overstated Discount Penalty (-8-0 pts)**: Size/age adjustments