# Real Estate Dashboard

A simple, single-page web dashboard for viewing and filtering Tokyo real estate property data stored in AWS DynamoDB.

## Features

- **Property Table**: Display properties with key information including location, price, size, and investment verdict
- **Advanced Filtering**: Filter by price, location, property characteristics, and investment criteria
- **Sorting**: Sort by price, size, age, station distance, score, or date
- **Pagination**: View 50 properties per page with navigation
- **Persistent Filters**: Filter selections are saved in browser localStorage
- **Responsive Design**: Works on desktop and mobile devices

## Architecture

The dashboard consists of:
1. **Frontend**: Single HTML file with vanilla JavaScript (no frameworks)
2. **API**: AWS Lambda function that queries DynamoDB
3. **Infrastructure**: API Gateway, S3 static hosting, CloudFormation

## Prerequisites

Before deploying the dashboard, ensure:
1. The AI infrastructure stack is deployed (`tokyo-real-estate-ai`)
2. DynamoDB table contains property data
3. AWS CLI is configured with appropriate credentials
4. You have deployment permissions for Lambda, API Gateway, S3, and IAM

## Deployment

1. Navigate to the dashboard directory:
   ```bash
   cd dashboard
   ```

2. Run the deployment script:
   ```bash
   ./deploy-dashboard.sh
   ```

   The script will:
   - Package the Lambda function
   - Deploy the CloudFormation stack
   - Update the HTML with your API endpoint
   - Upload the dashboard to S3
   - Output the dashboard URL

3. Access your dashboard at the provided URL

## Configuration

### Environment Variables
- `AWS_REGION`: AWS region (default: ap-northeast-1)
- `STACK_NAME`: CloudFormation stack name (default: tokyo-real-estate-dashboard)
- `AI_STACK_NAME`: AI infrastructure stack name (default: tokyo-real-estate-ai)

### Filter Parameters

The API supports the following query parameters:

**Price Filters:**
- `min_price`: Minimum property price
- `max_price`: Maximum property price
- `min_price_per_sqm`: Minimum price per square meter
- `max_price_per_sqm`: Maximum price per square meter

**Location Filters:**
- `ward`: Tokyo ward name
- `district`: District within ward
- `max_station_distance`: Maximum walking minutes to station

**Property Filters:**
- `property_type`: Type of property (apartment, house, etc.)
- `min_bedrooms`: Minimum number of bedrooms
- `max_bedrooms`: Maximum number of bedrooms
- `min_sqm`: Minimum property size in square meters
- `max_sqm`: Maximum property size in square meters
- `max_building_age`: Maximum age of building in years

**Investment Filters:**
- `verdict`: Comma-separated verdicts (BUY,WATCH,REJECT)
- `min_score`: Minimum investment score

**Sorting:**
- `sort_by`: Sort field and direction (e.g., price_desc, score_asc)

**Pagination:**
- `page`: Page number (default: 1)
- `limit`: Results per page (default: 50, max: 100)

## Usage

1. **Filtering**: Enter filter criteria and click "Apply Filters"
2. **Clearing**: Click "Clear Filters" to reset all filters
3. **Sorting**: Select sort option from dropdown
4. **Navigation**: Use Previous/Next buttons to navigate pages
5. **Property Details**: Click "View" to open the original listing

## Troubleshooting

### No Data Displayed
- Check that DynamoDB table has property data
- Verify API endpoint is correct in browser console
- Check CloudWatch logs for Lambda function errors

### CORS Errors
- Ensure API Gateway CORS is properly configured
- Check browser console for specific CORS error messages

### Performance Issues
- Large datasets may take time to load
- Consider adjusting pagination limit
- Check Lambda function memory allocation

## Development

To modify the dashboard:

1. Edit `index.html` for UI changes
2. Edit `ai_infra/lambda/dashboard_api/app.py` for API changes
3. Redeploy using `./deploy-dashboard.sh`

## API Response Format

```json
{
  "properties": [
    {
      "property_id": "PROP#20250125_12345",
      "listing_url": "https://...",
      "price": 45000000,
      "total_sqm": 75.5,
      "ward": "Shibuya",
      "district": "Ebisu",
      "num_bedrooms": 2,
      "station_distance_minutes": 8,
      "verdict": "BUY",
      "investment_score": 85,
      "analysis_date": "2025-01-25T10:30:00Z"
    }
  ],
  "total_count": 250,
  "page": 1,
  "limit": 50,
  "total_pages": 5,
  "filters": {
    "wards": ["Shibuya", "Shinjuku", ...],
    "districts": ["Ebisu", "Roppongi", ...],
    "property_types": ["apartment", "house", ...]
  }
}
```

## Security Notes

- The dashboard is publicly accessible (no authentication)
- API Gateway has no authorization configured
- Suitable for personal use only
- For production use, add authentication and authorization

## Cleanup

To remove the dashboard:
```bash
aws cloudformation delete-stack --stack-name tokyo-real-estate-dashboard --region ap-northeast-1
```

This will delete all resources including the S3 bucket and its contents.