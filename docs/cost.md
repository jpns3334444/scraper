# AI Real Estate Analysis - Cost Analysis

## Daily Cost Breakdown

### OpenAI API Costs (Primary Driver)

#### GPT-4.1 Vision Pricing (as of 2024)
- **Input tokens**: $2.50 per 1M tokens
- **Output tokens**: $10.00 per 1M tokens  
- **Images**: $0.00765 per image (low detail)

#### Daily Usage Estimate
```
Listings analyzed: 100 (top selections by price_per_m2)
Interior photos per listing: ~3 average
Total images: ~300 per day

Text input:
- System prompt: ~200 tokens
- Listing data: ~100 tokens × 100 listings = 10,000 tokens
- Total input: ~10,200 tokens

Expected output:
- JSON response: ~2,000 tokens

Cost calculation:
- Input: 10,200 tokens × $2.50/1M = $0.026
- Output: 2,000 tokens × $10.00/1M = $0.020  
- Images: 300 images × $0.00765 = $2.295
- Daily total: ~$2.34 (~¥350 at 150 JPY/USD)
```

#### Batch API Discount
- OpenAI Batch API offers 50% discount on standard prices
- **Estimated daily cost: $1.17 (~¥175)**

### AWS Infrastructure Costs

#### Lambda Functions
```
ETL Lambda:
- Duration: ~2 minutes average
- Memory: 1024 MB
- Monthly executions: 30
- Cost: ~$0.01/month

Prompt Builder Lambda:
- Duration: ~3 minutes average  
- Memory: 1024 MB
- Monthly executions: 30
- Cost: ~$0.02/month

LLM Batch Lambda:
- Duration: ~30 minutes average (mostly waiting)
- Memory: 1024 MB
- Monthly executions: 30
- Cost: ~$0.15/month

Report Sender Lambda:
- Duration: ~1 minute average
- Memory: 1024 MB  
- Monthly executions: 30
- Cost: ~$0.01/month

Total Lambda: ~$0.19/month (~$0.006/day)
```

#### Step Functions
```
State transitions: ~4 per execution
Monthly executions: 30
Cost: 30 × 4 × $0.000025 = $0.003/month
```

#### S3 Storage
```
Daily data generated:
- JSONL: ~500 KB
- Prompt JSON: ~2 MB (with image URLs)
- Results JSON: ~50 KB
- Markdown report: ~20 KB
Total per day: ~2.6 MB

Monthly storage: ~80 MB
Storage cost: ~$0.002/month
```

#### CloudWatch Logs
```
Log volume: ~10 MB/day
Monthly cost: ~$0.15/month
```

#### Other AWS Services
```
EventBridge: $0.00/month (free tier)
SSM Parameter Store: $0.00/month (standard parameters)
SES: $0.10 per 1,000 emails = ~$0.003/month
Total other: ~$0.003/month
```

### Total Daily Cost Summary

| Component | Daily Cost (USD) | Daily Cost (JPY) |
|-----------|------------------|------------------|
| OpenAI Batch API | $1.17 | ¥175 |
| AWS Lambda | $0.006 | ¥1 |
| AWS Other Services | $0.01 | ¥2 |
| **Total Daily** | **$1.19** | **¥178** |
| **Monthly Total** | **$35.70** | **¥5,355** |

## Cost Optimization Strategies

### Immediate Optimizations

1. **Photo Selection Filtering**
   ```python
   # Current: All interior photos (max 20)
   # Optimized: Filter by quality metrics
   - File size > 50KB (better quality)
   - Specific keywords: "living", "kitchen", "bedroom"
   - Max 10 photos per listing
   
   Potential savings: 30% reduction in image costs
   ```

2. **Listing Pre-filtering**
   ```python
   # Current: Top 100 by price_per_m2
   # Optimized: Add quality filters
   - Age < 30 years
   - Walk time < 20 minutes
   - Area > 25 m²
   
   Typical result: ~60-80 listings processed
   Potential savings: 20-40% in text token costs
   ```

3. **Batch Job Optimization**
   ```python
   # Use smaller response format
   response_format = {
       "type": "json_object",
       "schema": {
           "top_picks": {"maxItems": 5},
           "runners_up": {"maxItems": 10}
       }
   }
   
   Potential savings: 15% in output token costs
   ```

### Advanced Optimizations

1. **Two-Stage Analysis**
   ```
   Stage 1: Text-only pre-screening (cheaper)
   - Filter to top 30-50 listings
   - Use GPT-4o-mini for initial scoring
   
   Stage 2: Vision analysis (current process)
   - Only analyze pre-screened listings
   - Use full GPT-4.1 vision capabilities
   
   Estimated savings: 40-60% total cost
   ```

2. **Regional Batching**
   ```
   # Instead of daily analysis
   # Batch by ward/region every 2-3 days
   # Analyze 200-300 listings per batch
   
   Benefits:
   - Better batch efficiency
   - Volume discounts
   - Regional market insights
   ```

3. **Smart Photo Analysis**
   ```python
   # Pre-analyze photos with AWS Rekognition
   # Only send "interesting" photos to OpenAI
   # Filter out: exterior, empty rooms, poor lighting
   
   Potential image reduction: 50-70%
   ```

## Cost Monitoring & Alerts

### CloudWatch Custom Metrics

```python
# Daily cost tracking
def publish_cost_metrics():
    cloudwatch.put_metric_data(
        Namespace='AI-RealEstate/Costs',
        MetricData=[
            {
                'MetricName': 'DailyOpenAICost',
                'Value': daily_openai_cost,
                'Unit': 'None'
            },
            {
                'MetricName': 'ListingsAnalyzed',
                'Value': listings_count,
                'Unit': 'Count'
            }
        ]
    )
```

### Cost Alarms

1. **Daily Spend Alert**
   ```
   Threshold: $2.00/day
   Action: SNS notification to admin
   Purpose: Catch unexpected usage spikes
   ```

2. **Monthly Budget Alert**
   ```
   Threshold: $50.00/month
   Action: Email + Slack notification
   Purpose: Monthly budget monitoring
   ```

3. **Token Usage Alert**
   ```
   Threshold: 50,000 tokens/day
   Action: Log analysis trigger
   Purpose: Detect prompt inflation
   ```

## ROI Analysis

### Value Proposition
```
Target: Identify 1-2 high-value properties per month
Average property value: ¥30,000,000
Potential return: 5-10% improvement in selection quality

Monthly cost: ¥5,355
Potential monthly value: ¥1,500,000 - ¥3,000,000 in better deals
ROI: 28,000% - 56,000% (assuming even 1% improvement in deal quality)
```

### Break-even Analysis
```
Break-even point: Finding 1 property per 6 months with 0.02% value improvement
Current cost efficiency: Very high for real estate investment context
```

## Future Cost Scaling

### Linear Scaling Scenarios

| Daily Listings | Monthly Cost (USD) | Monthly Cost (JPY) |
|----------------|--------------------|--------------------|
| 100 (current) | $35.70 | ¥5,355 |
| 200 | $65.40 | ¥9,810 |
| 500 | $156.00 | ¥23,400 |
| 1,000 | $306.00 | ¥45,900 |

### Cost per Property Analyzed
- Current: $0.36 per property per day
- With optimizations: $0.20-0.25 per property per day
- Industry context: Extremely cost-effective for real estate analysis