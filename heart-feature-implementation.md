# Complete Implementation Prompt for Favorites Feature

I need you to implement a comprehensive favorites/heart feature for my Tokyo Real Estate Analysis system. This feature will allow users to favorite properties and automatically get detailed ChatGPT analysis. Here's the complete implementation requirement:

## Context
I have an existing real estate analysis system with:
- Property scraper that saves data to DynamoDB
- Dashboard displaying properties from DynamoDB via Lambda/API Gateway
- S3 bucket for storing images and data
- Existing property analysis using OpenAI

## Required Implementation

### 1. MODIFY EXISTING PROPERTY PROCESSOR LAMBDA

Update `lambda/property_processor/core_scraper.py` to save individual property JSONs:

```python
# In extract_property_details function, after successful scraping:
# Save complete scraped data to S3 as individual JSON
def save_property_json_to_s3(property_data, bucket, property_id):
    """Save complete property data as JSON to S3"""
    date_str = datetime.now().strftime('%Y-%m-%d')
    s3_key = f"raw/{date_str}/properties/{property_id}.json"
    
    s3_client.put_object(
        Bucket=bucket,
        Key=s3_key,
        Body=json.dumps(property_data, ensure_ascii=False, indent=2).encode('utf-8'),
        ContentType='application/json'
    )
    return s3_key

# Call this in extract_property_details after data is complete
```

### 2. CREATE NEW DYNAMODB TABLE - UserFavorites

Create CloudFormation resource in `ai-stack.yaml`:

```yaml
UserFavoritesTable:
  Type: AWS::DynamoDB::Table
  Properties:
    TableName: !Sub '${AWS::StackName}-user-favorites'
    BillingMode: PAY_PER_REQUEST
    AttributeDefinitions:
      - AttributeName: favorite_id
        AttributeType: S
      - AttributeName: user_id
        AttributeType: S
      - AttributeName: favorited_at
        AttributeType: S
      - AttributeName: property_id
        AttributeType: S
    KeySchema:
      - AttributeName: favorite_id
        KeyType: HASH
    GlobalSecondaryIndexes:
      - IndexName: user-favorites-index
        KeySchema:
          - AttributeName: user_id
            KeyType: HASH
          - AttributeName: favorited_at
            KeyType: RANGE
        Projection:
          ProjectionType: ALL
      - IndexName: property-favorites-index
        KeySchema:
          - AttributeName: property_id
            KeyType: HASH
        Projection:
          ProjectionType: ALL
```

Table schema:
```json
{
  "favorite_id": "user123_PROP#20240115_123456",
  "user_id": "user123",
  "property_id": "PROP#20240115_123456",
  "favorited_at": "2024-01-15T10:30:00Z",
  "analysis_status": "pending|processing|completed|failed",
  "analysis_requested_at": "2024-01-15T10:30:00Z",
  "analysis_completed_at": "2024-01-15T10:35:00Z",
  "analysis_result": {
    "summary": "...",
    "investment_score": 8.5,
    "key_insights": ["..."],
    "risks": ["..."],
    "recommendation": "BUY"
  },
  "retry_count": 0,
  "last_error": null
}
```

### 3. CREATE SQS QUEUE FOR ANALYSIS

Add to CloudFormation:

```yaml
FavoriteAnalysisQueue:
  Type: AWS::SQS::Queue
  Properties:
    QueueName: !Sub '${AWS::StackName}-favorite-analysis'
    VisibilityTimeoutSeconds: 900
    MessageRetentionPeriod: 1209600
    RedrivePolicy:
      deadLetterTargetArn: !GetAtt FavoriteAnalysisDLQ.Arn
      maxReceiveCount: 3

FavoriteAnalysisDLQ:
  Type: AWS::SQS::Queue
  Properties:
    QueueName: !Sub '${AWS::StackName}-favorite-analysis-dlq'
    MessageRetentionPeriod: 1209600
```

### 4. CREATE FAVORITES API LAMBDA

Create `lambda/favorites_api/app.py`:

```python
import json
import boto3
from datetime import datetime
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
sqs = boto3.client('sqs')

favorites_table = dynamodb.Table(os.environ['FAVORITES_TABLE'])
properties_table = dynamodb.Table(os.environ['PROPERTIES_TABLE'])
queue_url = os.environ['ANALYSIS_QUEUE_URL']

CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type,X-User-Id',
    'Access-Control-Allow-Methods': 'GET,POST,DELETE,OPTIONS'
}

def lambda_handler(event, context):
    method = event['httpMethod']
    path = event['path']
    
    if method == 'OPTIONS':
        return {'statusCode': 200, 'headers': CORS_HEADERS}
    
    # Extract user_id from header
    user_id = event['headers'].get('X-User-Id', 'anonymous')
    
    if method == 'POST' and path == '/favorites':
        return add_favorite(event, user_id)
    elif method == 'DELETE' and path.startswith('/favorites/'):
        return remove_favorite(event, user_id)
    elif method == 'GET' and path == f'/favorites/{user_id}':
        return get_user_favorites(user_id)
    elif method == 'GET' and '/analysis' in path:
        return get_analysis(event, user_id)
    
    return {'statusCode': 404, 'headers': CORS_HEADERS}

def add_favorite(event, user_id):
    body = json.loads(event['body'])
    property_id = body['property_id']
    
    # Check if already favorited
    favorite_id = f"{user_id}_{property_id}"
    existing = favorites_table.get_item(Key={'favorite_id': favorite_id})
    
    if 'Item' in existing:
        return {
            'statusCode': 200,
            'headers': CORS_HEADERS,
            'body': json.dumps({'message': 'Already favorited'})
        }
    
    # Get property details for thumbnail
    property_data = properties_table.get_item(
        Key={'property_id': property_id, 'sort_key': 'META'}
    ).get('Item', {})
    
    # Create favorite record
    favorite_item = {
        'favorite_id': favorite_id,
        'user_id': user_id,
        'property_id': property_id,
        'favorited_at': datetime.utcnow().isoformat(),
        'analysis_status': 'pending',
        'analysis_requested_at': datetime.utcnow().isoformat(),
        # Store essential property data for quick display
        'property_summary': {
            'price': property_data.get('price'),
            'ward': property_data.get('ward'),
            'size_sqm': property_data.get('size_sqm'),
            'station': property_data.get('closest_station'),
            'image_url': property_data.get('photo_filenames', '').split('|')[0] if property_data.get('photo_filenames') else None
        }
    }
    
    favorites_table.put_item(Item=favorite_item)
    
    # Send to analysis queue
    sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps({
            'favorite_id': favorite_id,
            'user_id': user_id,
            'property_id': property_id
        })
    )
    
    return {
        'statusCode': 200,
        'headers': CORS_HEADERS,
        'body': json.dumps({'success': True, 'favorite_id': favorite_id})
    }

def get_user_favorites(user_id):
    # Query GSI for user's favorites
    response = favorites_table.query(
        IndexName='user-favorites-index',
        KeyConditionExpression='user_id = :uid',
        ExpressionAttributeValues={':uid': user_id},
        ScanIndexForward=False  # Most recent first
    )
    
    favorites = response.get('Items', [])
    
    # Convert Decimal to float for JSON serialization
    for fav in favorites:
        if 'property_summary' in fav and 'price' in fav['property_summary']:
            fav['property_summary']['price'] = float(fav['property_summary']['price'])
    
    return {
        'statusCode': 200,
        'headers': CORS_HEADERS,
        'body': json.dumps({'favorites': favorites})
    }
```

### 5. CREATE FAVORITE ANALYZER LAMBDA

Create `lambda/favorite_analyzer/app.py`:

```python
import json
import boto3
import os
from datetime import datetime
from openai import OpenAI

dynamodb = boto3.resource('dynamodb')
s3_client = boto3.client('s3')
secrets_client = boto3.client('secretsmanager')

favorites_table = dynamodb.Table(os.environ['FAVORITES_TABLE'])
properties_table = dynamodb.Table(os.environ['PROPERTIES_TABLE'])
bucket = os.environ['DATA_BUCKET']

def lambda_handler(event, context):
    # Process SQS messages
    for record in event['Records']:
        message = json.loads(record['body'])
        try:
            analyze_favorite(message)
        except Exception as e:
            print(f"Error analyzing favorite: {str(e)}")
            # Message will return to queue if not deleted

def analyze_favorite(message):
    favorite_id = message['favorite_id']
    property_id = message['property_id']
    
    # Update status to processing
    favorites_table.update_item(
        Key={'favorite_id': favorite_id},
        UpdateExpression='SET analysis_status = :status',
        ExpressionAttributeValues={':status': 'processing'}
    )
    
    try:
        # Build comprehensive data package
        data_package = build_property_data_package(property_id)
        
        # Generate prompt
        prompt = generate_investment_analysis_prompt(data_package)
        
        # Get ChatGPT analysis
        analysis = get_chatgpt_analysis(prompt, data_package.get('image_urls', []))
        
        # Store analysis result
        favorites_table.update_item(
            Key={'favorite_id': favorite_id},
            UpdateExpression='''
                SET analysis_status = :status,
                    analysis_completed_at = :completed,
                    analysis_result = :result
            ''',
            ExpressionAttributeValues={
                ':status': 'completed',
                ':completed': datetime.utcnow().isoformat(),
                ':result': analysis
            }
        )
        
    except Exception as e:
        # Update with error status
        favorites_table.update_item(
            Key={'favorite_id': favorite_id},
            UpdateExpression='''
                SET analysis_status = :status,
                    last_error = :error,
                    retry_count = retry_count + :inc
            ''',
            ExpressionAttributeValues={
                ':status': 'failed',
                ':error': str(e),
                ':inc': 1
            }
        )
        raise

def build_property_data_package(property_id):
    # 1. Get enriched data from DynamoDB
    dynamo_response = properties_table.get_item(
        Key={'property_id': property_id, 'sort_key': 'META'}
    )
    enriched_data = dynamo_response.get('Item', {})
    
    # 2. Get raw scraped data from S3
    date_part = property_id.split('#')[1].split('_')[0]
    s3_key = f"raw/{date_part}/properties/{property_id}.json"
    
    try:
        response = s3_client.get_object(Bucket=bucket, Key=s3_key)
        raw_data = json.loads(response['Body'].read())
    except:
        raw_data = {}
    
    # 3. Get image URLs
    image_urls = []
    if enriched_data.get('photo_filenames'):
        for s3_key in enriched_data['photo_filenames'].split('|')[:5]:
            if s3_key.strip():
                url = s3_client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': bucket, 'Key': s3_key.strip()},
                    ExpiresIn=3600
                )
                image_urls.append(url)
    
    return {
        'enriched': enriched_data,
        'raw': raw_data,
        'image_urls': image_urls
    }

def generate_investment_analysis_prompt(data):
    enriched = data['enriched']
    raw = data.get('raw', {})
    
    prompt = f"""
    Analyze this Tokyo investment property for purchase potential:

    PROPERTY OVERVIEW:
    - ID: {enriched.get('property_id')}
    - Price: ¥{enriched.get('price', 0) * 10000:,}
    - Size: {enriched.get('size_sqm')} m²
    - Price/m²: ¥{enriched.get('price_per_sqm', 0):,.0f}
    - Location: {enriched.get('ward')}, {enriched.get('district')}
    - Station: {enriched.get('closest_station')} ({enriched.get('station_distance_minutes')} min)
    - Building: {enriched.get('building_age_years')} years, Floor {enriched.get('floor')}/{enriched.get('building_floors')}

    FINANCIAL DETAILS:
    - Monthly Costs: ¥{enriched.get('total_monthly_costs', 0):,}
    - Management Fee: ¥{enriched.get('management_fee', 0):,}
    - Repair Reserve: ¥{enriched.get('repair_reserve_fee', 0):,}

    ANALYSIS SCORING:
    - Final Score: {enriched.get('final_score')}/100
    - Base Score: {enriched.get('base_score')}
    - Ward Discount: {enriched.get('ward_discount_pct'):.1f}%
    - Verdict: {enriched.get('verdict')}
    
    ADDITIONAL RAW DATA:
    {format_raw_data(raw)}

    IMAGES: {len(data.get('image_urls', []))} property images provided

    PROVIDE COMPREHENSIVE ANALYSIS INCLUDING:
    1. Investment Rating (1-10) with detailed justification
    2. Estimated rental yield (gross and net)
    3. 5-year price appreciation forecast
    4. Renovation potential and estimated costs
    5. Target tenant profile and rental demand
    6. Key risks and red flags
    7. Comparison to market averages
    8. Specific action items if purchasing
    9. Exit strategy recommendations
    10. Final verdict: STRONG BUY / BUY / HOLD / PASS

    Format the response as a structured JSON with these sections.
    """
    return prompt

def get_chatgpt_analysis(prompt, image_urls):
    # Get OpenAI API key
    api_key = get_openai_api_key()
    client = OpenAI(api_key=api_key)
    
    # Build messages with images
    messages = [
        {
            "role": "system",
            "content": "You are an expert Tokyo real estate investment analyst. Provide detailed, actionable analysis."
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt}
            ]
        }
    ]
    
    # Add images to the user message
    for url in image_urls:
        messages[1]["content"].append({
            "type": "image_url",
            "image_url": {"url": url}
        })
    
    response = client.chat.completions.create(
        model="gpt-4-vision-preview",
        messages=messages,
        max_tokens=2000,
        temperature=0.7
    )
    
    # Parse response and structure it
    analysis_text = response.choices[0].message.content
    
    # Try to parse as JSON, fallback to structured text
    try:
        analysis_json = json.loads(analysis_text)
        return analysis_json
    except:
        # Structure the text response
        return {
            "raw_analysis": analysis_text,
            "structured": parse_analysis_text(analysis_text)
        }
```

### 6. UPDATE DASHBOARD API LAMBDA

Modify `lambda/dashboard_api/app.py` to include favorite status:

```python
# Add to lambda_handler
def lambda_handler(event, context):
    # Existing code...
    
    # Get user_id from headers
    user_id = event.get('headers', {}).get('X-User-Id', 'anonymous')
    
    # After getting properties, check favorites
    if user_id != 'anonymous':
        favorites = get_user_favorite_ids(user_id)
        for item in formatted_items:
            item['is_favorited'] = item['property_id'] in favorites
    
    # Rest of existing code...

def get_user_favorite_ids(user_id):
    """Get set of property IDs favorited by user"""
    favorites_table = dynamodb.Table(os.environ.get('FAVORITES_TABLE'))
    
    response = favorites_table.query(
        IndexName='user-favorites-index',
        KeyConditionExpression='user_id = :uid',
        ExpressionAttributeValues={':uid': user_id},
        ProjectionExpression='property_id'
    )
    
    return {item['property_id'] for item in response.get('Items', [])}
```

### 7. UPDATE API GATEWAY

Add to CloudFormation:

```yaml
# Favorites API Integration
FavoritesApiIntegration:
  Type: AWS::ApiGatewayV2::Integration
  Properties:
    ApiId: !Ref PropertiesApi
    IntegrationType: AWS_PROXY
    IntegrationUri: !Sub 'arn:aws:apigateway:${AWS::Region}:lambda:path/2015-03-31/functions/${FavoritesApiFunction.Arn}/invocations'
    PayloadFormatVersion: '2.0'

# Favorites Routes
FavoritesPostRoute:
  Type: AWS::ApiGatewayV2::Route
  Properties:
    ApiId: !Ref PropertiesApi
    RouteKey: 'POST /favorites'
    Target: !Sub 'integrations/${FavoritesApiIntegration}'

FavoritesGetRoute:
  Type: AWS::ApiGatewayV2::Route
  Properties:
    ApiId: !Ref PropertiesApi
    RouteKey: 'GET /favorites/{userId}'
    Target: !Sub 'integrations/${FavoritesApiIntegration}'

FavoritesDeleteRoute:
  Type: AWS::ApiGatewayV2::Route
  Properties:
    ApiId: !Ref PropertiesApi
    RouteKey: 'DELETE /favorites/{favoriteId}'
    Target: !Sub 'integrations/${FavoritesApiIntegration}'
```

### 8. UPDATE DASHBOARD HTML

Modify `dashboard/index.html`:

```javascript
// Add to existing JavaScript

// User ID management
function getUserId() {
    let userId = localStorage.getItem('user_id');
    if (!userId) {
        userId = 'user_' + Math.random().toString(36).substr(2, 9);
        localStorage.setItem('user_id', userId);
    }
    return userId;
}

// Update headers for API calls
async function loadNext() {
    // Existing code...
    const res = await fetch(url, {
        headers: {
            'X-User-Id': getUserId()
        }
    });
    // Rest of existing code...
}

// Add to renderRow function
function renderRow(property) {
    // Existing code...
    const isFavorited = property.is_favorited || false;
    
    return `
        <tr>
            <td>
                <button class="heart-btn ${isFavorited ? 'favorited' : ''}" 
                        onclick="toggleFavorite('${property.property_id}', this)"
                        data-property-id="${property.property_id}">
                    <span class="heart-icon">${isFavorited ? '♥' : '♡'}</span>
                </button>
            </td>
            <!-- Rest of existing columns -->
        </tr>
    `;
}

// Favorite functions
async function toggleFavorite(propertyId, button) {
    button.disabled = true;
    const isFavorited = button.classList.contains('favorited');
    
    try {
        if (isFavorited) {
            await fetch(`${API_URL}/favorites/${getUserId()}_${propertyId}`, {
                method: 'DELETE',
                headers: { 'X-User-Id': getUserId() }
            });
            button.classList.remove('favorited');
            button.querySelector('.heart-icon').textContent = '♡';
        } else {
            await fetch(`${API_URL}/favorites`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-User-Id': getUserId()
                },
                body: JSON.stringify({ property_id: propertyId })
            });
            button.classList.add('favorited');
            button.querySelector('.heart-icon').textContent = '♥';
        }
        updateFavoritesCount();
    } catch (error) {
        console.error('Failed to toggle favorite:', error);
    } finally {
        button.disabled = false;
    }
}

// Add tab functionality
function switchTab(tabName) {
    document.querySelectorAll('.tab-pane').forEach(pane => {
        pane.classList.remove('active');
    });
    document.querySelectorAll('.tab-button').forEach(btn => {
        btn.classList.remove('active');
    });
    
    document.getElementById(`${tabName}-tab`).classList.add('active');
    event.target.classList.add('active');
    
    if (tabName === 'favorites') {
        loadFavorites();
    }
}

// Load favorites view
async function loadFavorites() {
    const userId = getUserId();
    const response = await fetch(`${API_URL}/favorites/${userId}`, {
        headers: { 'X-User-Id': userId }
    });
    
    const data = await response.json();
    const grid = document.getElementById('favoritesGrid');
    
    grid.innerHTML = data.favorites.map(fav => `
        <div class="favorite-card ${fav.analysis_status}" onclick="viewProperty('${fav.property_id}')">
            <div class="favorite-image">
                ${fav.property_summary.image_url ? 
                    `<img src="${generatePresignedUrl(fav.property_summary.image_url)}" alt="Property">` :
                    '<div class="no-image">No Image</div>'
                }
            </div>
            <div class="favorite-details">
                <div class="price">¥${(fav.property_summary.price * 10000).toLocaleString()}</div>
                <div class="location">${fav.property_summary.ward} - ${fav.property_summary.station}</div>
                <div class="size">${fav.property_summary.size_sqm}m²</div>
                <div class="status status-${fav.analysis_status}">
                    ${fav.analysis_status === 'completed' ? 'Analysis Ready' : 
                      fav.analysis_status === 'processing' ? 'Analyzing...' : 
                      fav.analysis_status === 'failed' ? 'Analysis Failed' : 'Pending'}
                </div>
            </div>
        </div>
    `).join('');
}

// Add CSS
const style = document.createElement('style');
style.textContent = `
    .heart-btn {
        background: none;
        border: none;
        cursor: pointer;
        font-size: 20px;
        padding: 4px 8px;
        transition: all 0.2s;
    }
    
    .heart-btn.favorited .heart-icon {
        color: #e91e63;
    }
    
    .heart-btn:hover {
        transform: scale(1.1);
    }
    
    .tab-navigation {
        display: flex;
        gap: 20px;
        margin-bottom: 20px;
        border-bottom: 2px solid #e0e0e0;
    }
    
    .tab-button {
        padding: 10px 20px;
        border: none;
        background: none;
        cursor: pointer;
        position: relative;
    }
    
    .tab-button.active {
        border-bottom: 3px solid #3182ce;
    }
    
    .favorites-count {
        background: #e91e63;
        color: white;
        border-radius: 10px;
        padding: 2px 6px;
        font-size: 12px;
        margin-left: 5px;
    }
    
    .favorites-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
        gap: 20px;
        padding: 20px;
    }
    
    .favorite-card {
        border: 1px solid #e0e0e0;
        border-radius: 8px;
        overflow: hidden;
        cursor: pointer;
        transition: all 0.2s;
    }
    
    .favorite-card:hover {
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    }
    
    .favorite-image {
        height: 200px;
        background: #f5f5f5;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    
    .favorite-image img {
        width: 100%;
        height: 100%;
        object-fit: cover;
    }
    
    .favorite-details {
        padding: 15px;
    }
    
    .status {
        margin-top: 10px;
        padding: 5px 10px;
        border-radius: 4px;
        font-size: 12px;
        text-align: center;
    }
    
    .status-completed {
        background: #c6f6d5;
        color: #22543d;
    }
    
    .status-processing {
        background: #fef5e7;
        color: #744210;
    }
    
    .status-failed {
        background: #fed7d7;
        color: #742a2a;
    }
    
    .status-pending {
        background: #e2e8f0;
        color: #4a5568;
    }
`;
document.head.appendChild(style);
```

### 9. LAMBDA FUNCTIONS CONFIGURATION

Add environment variables to CloudFormation:

```yaml
FavoritesApiFunction:
  Type: AWS::Lambda::Function
  Properties:
    Environment:
      Variables:
        FAVORITES_TABLE: !Ref UserFavoritesTable
        PROPERTIES_TABLE: !Ref DynamoDBTable
        ANALYSIS_QUEUE_URL: !Ref FavoriteAnalysisQueue

FavoriteAnalyzerFunction:
  Type: AWS::Lambda::Function
  Properties:
    Environment:
      Variables:
        FAVORITES_TABLE: !Ref UserFavoritesTable
        PROPERTIES_TABLE: !Ref DynamoDBTable
        DATA_BUCKET: !Ref OutputBucket
        OPENAI_SECRET_NAME: !Ref OpenAISecretName
    ReservedConcurrentExecutions: 10  # Limit concurrent executions
    Events:
      SQSTrigger:
        Type: SQS
        Properties:
          Queue: !GetAtt FavoriteAnalysisQueue.Arn
          BatchSize: 1
```

### 10. IAM PERMISSIONS

Add necessary permissions to Lambda roles:

```yaml
FavoritesApiRole:
  Type: AWS::IAM::Role
  Properties:
    Policies:
      - PolicyName: FavoritesApiPolicy
        PolicyDocument:
          Statement:
            - Effect: Allow
              Action:
                - dynamodb:PutItem
                - dynamodb:GetItem
                - dynamodb:DeleteItem
                - dynamodb:Query
              Resource:
                - !GetAtt UserFavoritesTable.Arn
                - !Sub '${UserFavoritesTable.Arn}/index/*'
            - Effect: Allow
              Action:
                - dynamodb:GetItem
              Resource: !GetAtt DynamoDBTable.Arn
            - Effect: Allow
              Action:
                - sqs:SendMessage
              Resource: !GetAtt FavoriteAnalysisQueue.Arn

FavoriteAnalyzerRole:
  Type: AWS::IAM::Role
  Properties:
    Policies:
      - PolicyName: FavoriteAnalyzerPolicy
        PolicyDocument:
          Statement:
            - Effect: Allow
              Action:
                - dynamodb:UpdateItem
                - dynamodb:GetItem
              Resource:
                - !GetAtt UserFavoritesTable.Arn
                - !GetAtt DynamoDBTable.Arn
            - Effect: Allow
              Action:
                - s3:GetObject
              Resource: !Sub '${OutputBucket.Arn}/*'
            - Effect: Allow
              Action:
                - secretsmanager:GetSecretValue
              Resource: !Ref OpenAISecretArn
            - Effect: Allow
              Action:
                - sqs:ReceiveMessage
                - sqs:DeleteMessage
                - sqs:GetQueueAttributes
              Resource: !GetAtt FavoriteAnalysisQueue.Arn
```

This implementation provides:
1. Complete property data storage in S3
2. User favorites tracking with analysis status
3. Asynchronous ChatGPT analysis via SQS
4. Real-time status updates in the UI
5. Tabbed interface with thumbnail view
6. Proper error handling and retries
7. Scalable architecture with queue-based processing

We already have several legacy systems that do similar things, located in lambda/legacy/. I would recommend you check prompt builder and llm batch lambda functions, for example, for details on how to create and send a prompt to openai API. We already have an API secret created. However, make sure to create new lambda functions, just use those legacy systems for general implementation help.

The system will automatically analyze favorited properties, combining DynamoDB enriched data, S3 raw scraped data, and images to provide comprehensive investment analysis through ChatGPT.
































You are working on a real estate scraping and analysis platform using AWS. The architecture includes multiple Lambdas, an SQS-based async analyzer, and a front-end dashboard. Most features for the favorites and analyzer system are in place, but the implementation is incomplete.

Your task is to **apply the following four critical fixes**:

---

### ✅ Fix #1: Save Raw Property JSONs to S3

In the file `lambda/property_processor/core_scraper.py`, ensure that the `save_property_json_to_s3` function is correctly called after a successful scrape. Look around **lines 1842–1855**. The block is present but currently **commented out or bypassed**.

Update the block so that it actively saves the raw property data to the appropriate key format (`raw/{date}/properties/{property_id}.json`). The function already exists and is named `save_property_json_to_s3`.

```python
try:
    if output_bucket and property_id:
        s3_json_key = save_property_json_to_s3(data, output_bucket, property_id, logger)
        if s3_json_key:
            data['s3_json_key'] = s3_json_key
            if logger:
                logger.info(f"Property JSON saved to S3: {s3_json_key}")
except Exception as e:
    if logger:
        logger.warning(f"Failed to save property JSON to S3: {e}")
```

---

### ✅ Fix #2: Add Missing Parameters to `ai-stack.yaml`

In `ai-stack.yaml`, inside the top-level `Parameters:` section, add these two missing entries:

```yaml
Parameters:
  FavoritesAPICodeVersion:
    Type: String
    Default: latest
  FavoriteAnalyzerCodeVersion:
    Type: String
    Default: latest
```

These are needed for proper code deployment and Lambda versioning.

---

### ✅ Fix #3: Update `deploy-ai.sh` to Package New Lambdas

In the `deploy-ai.sh` script, update the `for` loop that packages and deploys Lambda functions. Currently, it is missing the new ones. Update it as follows:

```bash
for func in etl prompt_builder llm_batch report_sender dynamodb_writer snapshot_generator daily_digest url_collector property_processor property_analyzer dashboard_api favorites_api favorite_analyzer; do
    # existing packaging logic here...
done
```

Make sure `favorites_api` and `favorite_analyzer` are properly zipped and pushed to S3.

---

### ✅ Fix #4: Confirm Lambda Role Permissions for Favorites Table

Ensure the `favorites_api` and `favorite_analyzer` Lambda execution roles include the necessary DynamoDB permissions:

```yaml
- Effect: Allow
  Action:
    - dynamodb:GetItem
    - dynamodb:PutItem
    - dynamodb:DeleteItem
    - dynamodb:Query
    - dynamodb:UpdateItem
  Resource: !GetAtt UserFavoritesTable.Arn
```

This should already be in `ai-stack.yaml`, but double-check to confirm.

---

### ✅ Optional Improvement: Add Logging to Analyzer

In `lambda/favorite_analyzer/app.py`, add enhanced logging when a JSON file is missing to make debugging easier:

```python
logger.warning(f"Raw property data not found in S3: {expected_key}")
```

---

### 🧠 Objective

These fixes ensure:

* Property JSONs are stored and available to the analyzer
* New Lambdas are packaged and deployed
* CloudFormation parameters and permissions are complete

Once you implement these fixes, the favorites-to-analysis system will be fully functional end-to-end.
