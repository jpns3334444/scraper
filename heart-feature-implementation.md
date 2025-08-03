# Heart/Favorite Feature Implementation Plan

## Overview
This document outlines how to implement a "heart" feature that allows users to favorite apartments on the dashboard and automatically send them to ChatGPT for detailed analysis.

## Architecture Overview

### Current System
- **Dashboard**: HTML frontend displaying properties from DynamoDB
- **DashboardAPI**: Lambda function serving property data 
- **DynamoDB**: `RealEstateAnalysisDB` table storing property data
- **Property Analyzer**: Existing Lambda that uses OpenAI for property analysis

### New Components Needed
1. **Favorites Table**: New DynamoDB table to store user favorites
2. **Favorites API**: New Lambda function to handle favorite operations
3. **Analysis Queue**: SQS queue for processing favorite analysis requests
4. **Favorite Analyzer**: New Lambda to generate detailed ChatGPT analysis

## Implementation Details

### 1. Database Schema

#### New DynamoDB Table: `UserFavorites`
```json
{
  "favorite_id": "user123_prop456",  // PK: user_id + property_id
  "user_id": "user123",              // GSI partition key
  "property_id": "prop456", 
  "favorited_at": "2024-01-15T10:30:00Z",
  "analysis_status": "pending|completed|failed",
  "analysis_result": "...",          // ChatGPT analysis text
  "analysis_completed_at": "2024-01-15T10:35:00Z"
}
```

#### Global Secondary Index
- **GSI Name**: `user-favorites-index`
- **Partition Key**: `user_id`
- **Sort Key**: `favorited_at`

### 2. Frontend Changes (Dashboard)

#### HTML Modifications
Add heart button to each property row:
```html
<td style="text-align: center;">
    <button class="heart-button" onclick="toggleFavorite('${property.property_id}')" 
            data-property-id="${property.property_id}">
        <span class="heart-icon">♡</span>
    </button>
</td>
```

#### CSS Additions
```css
.heart-button {
    background: none;
    border: none;
    cursor: pointer;
    font-size: 18px;
    transition: all 0.2s ease;
}

.heart-button.favorited .heart-icon {
    color: #e91e63;
}

.heart-button:hover .heart-icon {
    transform: scale(1.2);
}
```

#### JavaScript Functions
```javascript
async function toggleFavorite(propertyId) {
    const userId = getUserId(); // Get from session/auth
    const button = document.querySelector(`[data-property-id="${propertyId}"]`);
    const isFavorited = button.classList.contains('favorited');
    
    try {
        if (isFavorited) {
            await removeFavorite(userId, propertyId);
            button.classList.remove('favorited');
            button.querySelector('.heart-icon').textContent = '♡';
        } else {
            await addFavorite(userId, propertyId);
            button.classList.add('favorited');
            button.querySelector('.heart-icon').textContent = '♥';
        }
    } catch (error) {
        console.error('Error toggling favorite:', error);
    }
}

async function addFavorite(userId, propertyId) {
    const response = await fetch(`${API_URL}/favorites`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, property_id: propertyId })
    });
    if (!response.ok) throw new Error('Failed to add favorite');
}
```

### 3. Backend API Changes

#### New Lambda Function: `favorites_api`
```python
import json
import boto3
import uuid
from datetime import datetime

def lambda_handler(event, context):
    method = event['httpMethod']
    
    if method == 'POST':
        return add_favorite(event)
    elif method == 'DELETE':
        return remove_favorite(event)
    elif method == 'GET':
        return get_user_favorites(event)

def add_favorite(event):
    body = json.loads(event['body'])
    user_id = body['user_id']
    property_id = body['property_id']
    
    favorite_id = f"{user_id}_{property_id}"
    
    # Store in DynamoDB
    favorites_table.put_item(Item={
        'favorite_id': favorite_id,
        'user_id': user_id,
        'property_id': property_id,
        'favorited_at': datetime.utcnow().isoformat(),
        'analysis_status': 'pending'
    })
    
    # Send to analysis queue
    sqs.send_message(
        QueueUrl=ANALYSIS_QUEUE_URL,
        MessageBody=json.dumps({
            'favorite_id': favorite_id,
            'user_id': user_id,
            'property_id': property_id
        })
    )
    
    return {
        'statusCode': 200,
        'headers': CORS_HEADERS,
        'body': json.dumps({'success': True})
    }
```

### 4. Analysis System

#### SQS Queue: `favorite-analysis-queue`
- **Visibility Timeout**: 15 minutes
- **Dead Letter Queue**: For failed analysis attempts

#### New Lambda Function: `favorite_analyzer`
```python
import json
import boto3
import openai
from datetime import datetime

def lambda_handler(event, context):
    for record in event['Records']:
        message = json.loads(record['body'])
        analyze_favorite(message)

def analyze_favorite(message):
    favorite_id = message['favorite_id']
    property_id = message['property_id']
    
    # Get property details from main table
    property_data = get_property_details(property_id)
    
    # Generate detailed analysis prompt
    prompt = generate_analysis_prompt(property_data)
    
    # Call OpenAI for analysis
    analysis = get_chatgpt_analysis(prompt)
    
    # Update favorites table with analysis
    favorites_table.update_item(
        Key={'favorite_id': favorite_id},
        UpdateExpression='SET analysis_result = :result, analysis_status = :status, analysis_completed_at = :completed',
        ExpressionAttributeValues={
            ':result': analysis,
            ':status': 'completed',
            ':completed': datetime.utcnow().isoformat()
        }
    )

def generate_analysis_prompt(property_data):
    return f"""
    Please provide a detailed investment analysis for this Tokyo apartment:
    
    **Property Details:**
    - Price: ¥{property_data.get('price', 0) * 10000:,}
    - Size: {property_data.get('size_sqm')} m²
    - Location: {property_data.get('ward')}, {property_data.get('closest_station')}
    - Building Age: {property_data.get('building_age_years')} years
    - Floor: {property_data.get('floor')}
    - Monthly Costs: ¥{property_data.get('total_monthly_costs', 0):,}
    
    **Analysis Request:**
    1. Investment potential (1-10 rating with explanation)
    2. Rental yield analysis and projections
    3. Location advantages and disadvantages
    4. Resale potential in 5-10 years
    5. Specific risks and red flags
    6. Comparison to area market conditions
    7. Renovation/improvement recommendations
    8. Final recommendation (Strong Buy/Buy/Hold/Pass)
    
    Please provide detailed reasoning for each point.
    """

def get_chatgpt_analysis(prompt):
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a Tokyo real estate investment expert with 15 years of experience."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=2000,
        temperature=0.7
    )
    return response.choices[0].message.content
```

### 5. Analysis Viewing Interface

#### New Page: Analysis Dashboard
Create `/dashboard/analysis.html` to view detailed analyses:

```html
<div class="analysis-container">
    <h2>My Favorite Properties Analysis</h2>
    <div id="favoritesList">
        <!-- Dynamically loaded favorite properties with analyses -->
    </div>
</div>
```

#### Analysis Card Component
```html
<div class="analysis-card">
    <div class="property-summary">
        <h3>Property #{property_id}</h3>
        <p>¥{price} | {ward} | {size_sqm}m²</p>
    </div>
    <div class="analysis-content">
        <pre class="analysis-text">{analysis_result}</pre>
    </div>
    <div class="analysis-actions">
        <button onclick="removeFromFavorites('{property_id}')">Remove</button>
        <a href="{listing_url}" target="_blank">View Listing</a>
    </div>
</div>
```

### 6. Infrastructure Updates

#### CloudFormation Additions to `ai-stack.yaml`
```yaml
# New DynamoDB Table
UserFavoritesTable:
  Type: AWS::DynamoDB::Table
  Properties:
    TableName: !Sub '${AWS::StackName}-user-favorites'
    AttributeDefinitions:
      - AttributeName: favorite_id
        AttributeType: S
      - AttributeName: user_id
        AttributeType: S
      - AttributeName: favorited_at
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

# SQS Queue for Analysis
FavoriteAnalysisQueue:
  Type: AWS::SQS::Queue
  Properties:
    QueueName: !Sub '${AWS::StackName}-favorite-analysis'
    VisibilityTimeoutSeconds: 900
    MessageRetentionPeriod: 1209600

# Lambda Functions
FavoritesAPIFunction:
  Type: AWS::Lambda::Function
  # ... function definition

FavoriteAnalyzerFunction:
  Type: AWS::Lambda::Function
  # ... function definition with SQS trigger
```

### 7. User Authentication Integration

#### Simple Session-Based Approach
```javascript
// Generate or retrieve user session ID
function getUserId() {
    let userId = localStorage.getItem('user_id');
    if (!userId) {
        userId = 'user_' + Math.random().toString(36).substr(2, 9);
        localStorage.setItem('user_id', userId);
    }
    return userId;
}
```

#### Future Enhancement: Cognito Integration
For production, integrate AWS Cognito for proper user authentication.

### 8. Deployment Process

#### Updated Deployment Script
```bash
#!/bin/bash
# Update deploy-ai.sh to include new Lambda functions

# Package favorites API
cd lambda/favorites_api
zip -r ../../favorites_api.zip .
cd ../..

# Package favorite analyzer
cd lambda/favorite_analyzer  
zip -r ../../favorite_analyzer.zip .
cd ../..

# Deploy updated CloudFormation stack
aws cloudformation deploy \
  --template-file ai-stack.yaml \
  --stack-name tokyo-real-estate-ai \
  --parameter-overrides \
    FavoritesAPICodeKey=favorites_api.zip \
    FavoriteAnalyzerCodeKey=favorite_analyzer.zip \
  --capabilities CAPABILITY_IAM
```

## Benefits of This Implementation

1. **User Experience**: Simple one-click favoriting
2. **Automated Analysis**: Detailed ChatGPT analysis without manual work
3. **Scalable**: Queue-based processing handles multiple requests
4. **Cost-Effective**: Only analyzes properties user is actually interested in
5. **Extensible**: Foundation for features like alerts, reports, sharing

## Next Steps

1. Implement favorites table and API first
2. Add heart buttons to dashboard
3. Build analysis system
4. Create analysis viewing interface
5. Add user authentication for production use

## Estimated Implementation Time
- **Phase 1** (Basic favoriting): 1-2 days
- **Phase 2** (Analysis system): 2-3 days  
- **Phase 3** (Analysis interface): 1-2 days
- **Total**: 4-7 days for complete implementation