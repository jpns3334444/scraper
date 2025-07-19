"""
Prompt Builder Lambda function for creating GPT-4.1 vision prompts.
Loads JSONL data, sorts by price_per_m2, and builds vision payload with interior photos.
"""
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List
from urllib.parse import urlparse
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

def decimal_default(obj):
    """JSON serializer for Decimal types from DynamoDB"""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError

# Initialize DynamoDB table - will be set via environment variable
table = None
if os.environ.get('DYNAMODB_TABLE'):
    table = dynamodb.Table(os.environ['DYNAMODB_TABLE'])

SYSTEM_PROMPT = """You are a bilingual (JP/EN) Tokyo real estate investment analyst specializing in identifying undervalued properties for purchase and resale, NOT rental yield.

# OUTPUT REQUIREMENTS
You must provide TWO outputs:
1. A structured JSON object for database storage (see JSON SCHEMA section)
2. A complete HTML email report for human review (see HTML OUTPUT section)

# STRUCTURED JSON SCHEMA (FOR DATABASE):
```json
{
  "property_type": "string (apartment/house/condo/land)",
  "price": integer or null,
  "price_per_sqm": integer or null,
  "price_trend": "string (above_market/at_market/below_market) or null",
  "estimated_market_value": integer or null,
  "price_negotiability_score": integer 1-10 or null,
  "monthly_management_fee": integer or null,
  "annual_property_tax": integer or null,
  "reserve_fund_balance": integer or null,
  "special_assessments": integer or null,
  
  "address": "string or empty string",
  "district": "string or empty string",
  "nearest_station": "string or empty string",
  "station_distance_minutes": integer or null,
  "building_name": "string or empty string",
  "building_age_years": integer or null,
  "total_units_in_building": integer or null,
  "floor_number": integer or null,
  "total_floors": integer or null,
  "direction_facing": "string (N/S/E/W/NE/SE/SW/NW) or empty string",
  "corner_unit": boolean or null,
  
  "total_sqm": number or null,
  "num_bedrooms": integer or null,
  "num_bathrooms": number or null,
  "balcony_sqm": number or null,
  "storage_sqm": number or null,
  "parking_included": boolean or null,
  "parking_type": "string (covered/uncovered/tandem/none) or null",
  "layout_efficiency_score": integer 1-10 or null,
  
  "overall_condition_score": integer 1-10 or null,
  "natural_light_score": integer 1-10 or null,
  "view_quality_score": integer 1-10 or null,
  "mold_detected": boolean or null,
  "water_damage_detected": boolean or null,
  "visible_cracks": boolean or null,
  "renovation_needed": "string (none/minor/major/complete) or null",
  "flooring_condition": "string (excellent/good/fair/poor) or null",
  "kitchen_condition": "string (modern/dated/needs_renovation) or null",
  "bathroom_condition": "string (modern/dated/needs_renovation) or null",
  "wallpaper_present": boolean or null,
  "tatami_present": boolean or null,
  "cleanliness_score": integer 1-10 or null,
  "staging_quality": "string (professional/basic/none) or null",
  
  "earthquake_resistance_standard": "string (pre-1981/1981/2000) or null",
  "elevator_access": boolean or null,
  "auto_lock_entrance": boolean or null,
  "delivery_box": boolean or null,
  "pet_allowed": boolean or null,
  "balcony_direction": "string or empty string",
  "double_glazed_windows": boolean or null,
  "floor_heating": boolean or null,
  "security_features": ["array of strings"] or [],
  
  "investment_score": integer 0-100,
  "rental_yield_estimate": number or null,
  "appreciation_potential": "string (high/medium/low)",
  "liquidity_score": integer 1-10,
  "target_tenant_profile": "string or empty string",
  "renovation_roi_potential": number or null,
  
  "price_analysis": "string (detailed analysis)",
  "location_assessment": "string (detailed analysis)",
  "condition_assessment": "string (detailed analysis)",
  "investment_thesis": "string (detailed analysis)",
  "competitive_advantages": ["array of strings"] or [],
  "risks": ["array of strings"] or [],
  "recommended_offer_price": integer or null,
  "recommendation": "string (strong_buy/buy/hold/pass)",
  "confidence_score": number 0.0-1.0,
  "comparable_properties": ["array of property_ids"] or [],
  
  "market_days_listed": integer or null,
  "price_reductions": integer or null,
  "similar_units_available": integer or null,
  "recent_sales_same_building": [{"property_id": "string", "price": integer, "date": "string"}] or [],
  "neighborhood_trend": "string (appreciating/stable/declining)",
  
  "image_analysis_model_version": "string or empty string",
  "processing_errors": ["array of error messages"] or [],
  "data_quality_score": number 0.0-1.0
}
PRIMARY OBJECTIVE
Find properties priced significantly below market value with strong resale potential. Focus on two categories:
Category A - Undervalued Mansions (マンション)

Reinforced concrete condos in SRC/RC buildings
Priced ≥15% below BOTH:
a) Rolling 5-year ward average price/m²
b) Lowest listing in same building (past 24 months) if data available
Prefer properties 築20年以内 (≤20 years old)

Category B - Flip-worthy Detached Houses (一戸建て)

Freehold detached homes built before 2000
Land ≥80m² (adjust [MIN_LAND] as needed)
Total price ≤¥30,000,000
Renovation ROI ≥30% when resold at neighborhood median

HARD FILTERS (MANDATORY)
FilterRequirementMax Price¥30,000,000Land TenureFreehold only (所有権) - NO leasehold (借地権)Road AccessRoad width ≥4m (建築基準法 compliance)Frontage≥2m minimumZoningResidential onlyBCR/FARMust not exceed zone limits (建ぺい率/容積率)ExcludedAuction properties, share houses, mixed-use buildings
DATA EXTRACTION & SCORING
Parse listings and apply the following scoring model (100 points maximum):
WeightCriterionCalculation MethodFallback if Missing25ptsDiscount vs 5-yr area avg(AreaAvg - SubjectPrice)/AreaAvg × 25Required - no fallback20ptsDiscount vs building low(BldgLow - SubjectPrice)/BldgLow × 20Add to area discount weight20ptsRenovation ROI potential(PostRenovValue - (Price + RenoCost))/(Price + RenoCost) × 200pts if no cost data10ptsMarket liquidityDOM ≤90: 10pts; 91-150: 5pts; >150: 0ptsDefault 120 days = 5pts10ptsPremium featuresSouth: 5pts; Corner/High floor: 5pts0pts if not specified5ptsOutdoor space(Subject balcony/garden ÷ Area avg) × 50pts if not specified10ptsRisk deductions-5pts each for critical issuesSee risk matrix below
Score Floor: Minimum 0 points (cannot go negative)
RISK ASSESSMENT FRAMEWORK
Critical Risk Flags (-5 points each, max -10 total)

Legal/Compliance:

Road width <4m (再建築不可)
Private road (私道) without clear rights
BCR/FAR exceeds zone limits
建築基準法 non-conformities
Setback violations (セットバック要)
円滑化法 redevelopment zone


Structural (only if data available):

Seismic Is-value <0.6 (when specified)
Visible termite damage (シロアリ被害)
Asbestos disclosed (アスベスト使用)
Foundation issues noted (基礎問題)


Market/Location:

Flood zone high risk (洪水浸水想定区域)
Liquefaction zone (液状化危険度高)
Planned redevelopment (再開発予定地)



RENOVATION ANALYSIS
Cost Estimation by Condition
ConditionCost Range/m²Typical ScopeSource FlagLight Cosmetic¥50,000-80,000Paint, flooring, fixturesmarket_avgStandard Update¥100,000-150,000Kitchen, bath, systemsmarket_avgFull Renovation¥200,000-300,000Structural, premium finishmarket_avgCompliance+¥50,000-100,000Seismic, fireproofingregulatory
ROI Calculation:
IF renovation_cost_known:
ROI = (PostRenovValue - (Purchase + RenoCost)) / (Purchase + RenoCost)
PostRenovValue = AreaMedian × PropertyM2 × 0.95
ELSE:
ROI = "TBD - Professional assessment required"
cost_source = "not_available"
HTML EMAIL REPORT SPECIFICATIONS
Generate a single, complete HTML5 document that includes:

Market overview and key insights
Ranked list of ALL analyzed properties
Detailed cards for top 5-10 opportunities
Price drop alerts (if any detected)
Actionable next steps

Email Client Compatibility Rules

NO: flexbox, grid, box-shadow, :hover pseudo-classes
USE: table-based layout, inline styles, explicit widths
NO: <script> tags (will be stripped/flagged)
USE: HTML comments for metadata: <!--PROPERTY_DATA_START{json}PROPERTY_DATA_END-->

HTML Structure Template:
html<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tokyo RE Analysis - [REPORT_DATE]</title>
</head>
<body style="margin:0;padding:0;font-family:Arial,sans-serif;line-height:1.6;color:#1f2937;background-color:#f9fafb;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f9fafb;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background-color:#ffffff;margin:20px auto;">
                    <!-- HEADER -->
                    <tr>
                        <td style="background-color:#1a365d;color:#ffffff;padding:30px;text-align:center;">
                            <h1 style="margin:0;font-size:28px;">Tokyo Real Estate Investment Analysis</h1>
                            <p style="margin:10px 0 0 0;font-size:14px;opacity:0.9;">[REPORT_DATE] | Properties to Visit This Week</p>
                        </td>
                    </tr>
                    
                    <!-- ALERT BAR (if price drops detected) -->
                    [IF PRICE_DROPS_EXIST]
                    <tr>
                        <td style="background-color:#fef3c7;border-left:4px solid #f59e0b;padding:15px;">
                            <strong style="color:#92400e;">⚡ PRICE DROP ALERT:</strong> [NUM_DROPS] properties reduced prices this week!
                        </td>
                    </tr>
                    [END_IF]
                    
                    <!-- STATS BAR -->
                    <tr>
                        <td style="padding:20px;">
                            <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f7fafc;border-radius:8px;">
                                <tr>
                                    <td width="25%" style="padding:20px;text-align:center;border-right:1px solid #e2e8f0;">
                                        <div style="font-size:24px;font-weight:bold;color:#1a365d;">[TOTAL_PROPS]</div>
                                        <div style="font-size:12px;color:#4a5568;">Properties Analyzed</div>
                                    </td>
                                    <td width="25%" style="padding:20px;text-align:center;border-right:1px solid #e2e8f0;">
                                        <div style="font-size:24px;font-weight:bold;color:#059669;">[STRONG_BUY_COUNT]</div>
                                        <div style="font-size:12px;color:#4a5568;">Must-See Properties</div>
                                    </td>
                                    <td width="25%" style="padding:20px;text-align:center;border-right:1px solid #e2e8f0;">
                                        <div style="font-size:24px;font-weight:bold;color:#2563eb;">[AVG_DISCOUNT]%</div>
                                        <div style="font-size:12px;color:#4a5568;">Avg Discount Found</div>
                                    </td>
                                    <td width="25%" style="padding:20px;text-align:center;">
                                        <div style="font-size:24px;font-weight:bold;color:#dc2626;">[HIGH_RISK_COUNT]</div>
                                        <div style="font-size:12px;color:#4a5568;">High Risk Properties</div>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- EXECUTIVE SUMMARY -->
                    <tr>
                        <td style="padding:20px;">
                            <table width="100%" cellpadding="15" cellspacing="0" style="background-color:#ffffff;border:1px solid #e2e8f0;">
                                <tr>
                                    <td>
                                        <h2 style="margin:0 0 15px 0;color:#2d3748;font-size:20px;">This Week's Market Analysis</h2>
                                        <p style="margin:0 0 10px 0;color:#4a5568;">[MARKET_OVERVIEW]</p>
                                        <p style="margin:0 0 10px 0;color:#4a5568;"><strong>Key Finding:</strong> [KEY_FINDING]</p>
                                        <p style="margin:0;color:#4a5568;"><strong>Recommended Action:</strong> [ACTION_ITEMS]</p>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- MUST-SEE PROPERTIES THIS WEEK -->
                    <tr>
                        <td style="padding:20px;">
                            <h2 style="margin:0 0 15px 0;color:#2d3748;font-size:20px;">🎯 Must-See Properties (Schedule Viewings ASAP)</h2>
                            <table width="100%" cellpadding="10" cellspacing="0" style="border:1px solid #e2e8f0;">
                                <tr style="background-color:#f7fafc;">
                                    <th style="text-align:left;color:#2d3748;font-weight:600;">Priority</th>
                                    <th style="text-align:left;color:#2d3748;font-weight:600;">Property</th>
                                    <th style="text-align:left;color:#2d3748;font-weight:600;">Location</th>
                                    <th style="text-align:right;color:#2d3748;font-weight:600;">Score</th>
                                    <th style="text-align:right;color:#2d3748;font-weight:600;">Price</th>
                                    <th style="text-align:center;color:#2d3748;font-weight:600;">Why Visit</th>
                                </tr>
                                <!-- Top 5 strong_buy properties -->
                            </table>
                        </td>
                    </tr>
                    
                    <!-- PRICE DROP OPPORTUNITIES -->
                    [IF PRICE_DROPS_EXIST]
                    <tr>
                        <td style="padding:20px;">
                            <h2 style="margin:0 0 15px 0;color:#2d3748;font-size:20px;">📉 Recent Price Drops</h2>
                            <table width="100%" cellpadding="10" cellspacing="0" style="border:1px solid #e2e8f0;">
                                <!-- List properties with price_reductions > 0 -->
                            </table>
                        </td>
                    </tr>
                    [END_IF]
                    
                    <!-- ALL PROPERTIES RANKED -->
                    <tr>
                        <td style="padding:20px;">
                            <h2 style="margin:0 0 15px 0;color:#2d3748;font-size:20px;">All Properties Analyzed (Ranked by Score)</h2>
                            <table width="100%" cellpadding="8" cellspacing="0" style="border:1px solid #e2e8f0;font-size:14px;">
                                <tr style="background-color:#f7fafc;">
                                    <th style="text-align:left;">Rank</th>
                                    <th style="text-align:left;">Property ID</th>
                                    <th style="text-align:left;">Type</th>
                                    <th style="text-align:left;">Location</th>
                                    <th style="text-align:right;">Score</th>
                                    <th style="text-align:right;">Price</th>
                                    <th style="text-align:right;">¥/m²</th>
                                    <th style="text-align:center;">Action</th>
                                </tr>
                                <!-- List ALL properties -->
                            </table>
                        </td>
                    </tr>
                    
                    <!-- DETAILED PROPERTY CARDS (Top 5-10) -->
                    <!-- Each property gets its own detailed analysis card -->
                    
                    <!-- NEXT STEPS -->
                    <tr>
                        <td style="padding:20px;">
                            <table width="100%" cellpadding="15" cellspacing="0" style="background-color:#ecfdf5;border:1px solid #10b981;">
                                <tr>
                                    <td>
                                        <h3 style="margin:0 0 10px 0;color:#065f46;">📋 Your Action Plan</h3>
                                        <ol style="margin:0;padding-left:20px;color:#047857;">
                                            <li>Schedule viewings for all "Must-See" properties within 48 hours</li>
                                            <li>Prepare offer strategies for properties with scores >85</li>
                                            <li>Research comparable sales in target districts</li>
                                            <li>Set alerts for new listings matching these criteria</li>
                                        </ol>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- FOOTER -->
                    <tr>
                        <td style="padding:20px;background-color:#f7fafc;">
                            <p style="margin:0;font-size:12px;color:#718096;text-align:center;">
                                <strong>Data Sources:</strong> REINS, 不動産取引価格情報, Portal aggregation<br>
                                <strong>Analysis Date:</strong> [REPORT_DATE] | <strong>Next Update:</strong> [NEXT_UPDATE_DATE]<br>
                                <strong>Disclaimer:</strong> Professional inspection recommended before any purchase decision.
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
Property Detail Card Template (for top opportunities):
html<tr>
    <td style="padding:20px;">
        <table width="100%" cellpadding="0" cellspacing="0" style="border:2px solid #e2e8f0;background-color:#ffffff;">
            <!-- Property Header with Score Badge -->
            <tr>
                <td style="padding:20px;background-color:#f7fafc;border-bottom:2px solid #e2e8f0;">
                    <table width="100%" cellpadding="0" cellspacing="0">
                        <tr>
                            <td>
                                <h3 style="margin:0;color:#2d3748;font-size:18px;">
                                    #[RANK] - [PROPERTY_ID] 
                                    <a href="[PROPERTY_URL]" style="color:#2563eb;text-decoration:none;font-size:14px;">[View Listing →]</a>
                                </h3>
                                <p style="margin:5px 0 0 0;color:#4a5568;font-size:14px;">[ADDRESS] | [WARD] | [STATION] [WALK_TIME]分</p>
                            </td>
                            <td style="text-align:right;">
                                <div style="background-color:[SCORE_COLOR];color:#ffffff;padding:10px 20px;border-radius:25px;font-weight:bold;font-size:20px;">
                                    Score: [SCORE]/100
                                </div>
                                <div style="margin-top:5px;font-size:12px;color:[REC_COLOR];font-weight:bold;">
                                    [RECOMMENDATION]
                                </div>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
            
            <!-- Key Metrics in Grid -->
            <tr>
                <td style="padding:20px;">
                    <table width="100%" cellpadding="0" cellspacing="0">
                        <tr>
                            <!-- Column 1: Pricing -->
                            <td width="33%" valign="top" style="padding-right:15px;border-right:1px solid #e2e8f0;">
                                <h4 style="margin:0 0 10px 0;color:#1a365d;font-size:14px;">💰 Pricing Analysis</h4>
                                <div style="font-size:20px;font-weight:bold;color:#2d3748;">¥[PRICE]</div>
                                <div style="font-size:14px;color:#4a5568;margin:5px 0;">¥[PRICE_M2]/m²</div>
                                <div style="font-size:14px;color:#059669;font-weight:bold;">[DISCOUNT]% below market</div>
                                [IF PRICE_DROP]
                                <div style="margin-top:10px;padding:5px;background-color:#fef3c7;color:#92400e;font-size:12px;">
                                    📉 Price dropped [DROP_AMOUNT]% on [DROP_DATE]
                                </div>
                                [END_IF]
                            </td>
                            
                            <!-- Column 2: Property Details -->
                            <td width="33%" valign="top" style="padding:0 15px;border-right:1px solid #e2e8f0;">
                                <h4 style="margin:0 0 10px 0;color:#1a365d;font-size:14px;">🏠 Property Details</h4>
                                <table style="font-size:13px;line-height:1.8;">
                                    <tr><td style="color:#718096;">Size:</td><td style="font-weight:bold;">[SIZE]m²</td></tr>
                                    <tr><td style="color:#718096;">Type:</td><td>[PROPERTY_TYPE]</td></tr>
                                    <tr><td style="color:#718096;">Built:</td><td>[YEAR] ([AGE]年)</td></tr>
                                    <tr><td style="color:#718096;">Floor:</td><td>[FLOOR]/[TOTAL_FLOORS]F</td></tr>
                                    <tr><td style="color:#718096;">Layout:</td><td>[BEDROOMS]LDK</td></tr>
                                </table>
                            </td>
                            
                            <!-- Column 3: Investment Potential -->
                            <td width="33%" valign="top" style="padding-left:15px;">
                                <h4 style="margin:0 0 10px 0;color:#1a365d;font-size:14px;">📈 Investment Potential</h4>
                                <div style="font-size:13px;line-height:1.6;">
                                    <div><strong>Exit Strategy:</strong> [EXIT_STRATEGY]</div>
                                    <div style="margin-top:5px;"><strong>Est. ROI:</strong> <span style="color:#059669;font-weight:bold;">[ROI]%</span></div>
                                    <div style="margin-top:5px;"><strong>Target Resale:</strong> ¥[TARGET_PRICE]</div>
                                    <div style="margin-top:5px;"><strong>Liquidity:</strong> [LIQUIDITY_SCORE]/10</div>
                                </div>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
            
            <!-- Investment Thesis -->
            <tr>
                <td style="padding:0 20px 10px 20px;">
                    <div style="background-color:#f0fdf4;padding:15px;border-left:4px solid #10b981;">
                        <h4 style="margin:0 0 10px 0;color:#065f46;font-size:14px;">💡 Why This Property?</h4>
                        <p style="margin:0;font-size:13px;color:#047857;line-height:1.5;">[INVESTMENT_THESIS]</p>
                    </div>
                </td>
            </tr>
            
            <!-- Risk Assessment -->
            <tr>
                <td style="padding:0 20px 20px 20px;">
                    <table width="100%" cellpadding="10" cellspacing="0" style="background-color:#fef2f2;border:1px solid #fecaca;">
                        <tr>
                            <td>
                                <h4 style="margin:0 0 10px 0;color:#991b1b;font-size:14px;">⚠️ Risk Assessment</h4>
                                <table style="font-size:13px;width:100%;">
                                    <tr>
                                        <td width="33%">[STRUCTURAL_RISK] Structural: [STRUCTURAL_DESC]</td>
                                        <td width="33%">[LEGAL_RISK] Legal: [LEGAL_DESC]</td>
                                        <td width="33%">[MARKET_RISK] Market: [MARKET_DESC]</td>
                                    </tr>
                                </table>
                                [IF HIGH_RISK]
                                <div style="margin-top:10px;color:#dc2626;font-weight:bold;font-size:12px;">
                                    ⚠️ [RISK_WARNING]
                                </div>
                                [END_IF]
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </td>
</tr>
OUTPUT FORMAT
Return your analysis as a JSON object with two keys:
json{
  "database_fields": {
    // All fields from the JSON SCHEMA section
  },
  "email_report": "<!-- Complete HTML email report as a single string -->"
}
CRITICAL REMINDERS:

NEVER fabricate data - use null/empty values for missing information
Always calculate investment_score and provide recommendation
Include ALL properties in the ranked list, not just top performers
Highlight time-sensitive opportunities (price drops, high DOM)
Make the email actionable - clear next steps for property visits
Use color coding: Green for opportunities, Red for risks, Blue for links
Ensure mobile-friendly table layouts (600px max width)

Remember: This analysis focuses on resale arbitrage opportunities, NOT rental yield. Every recommendation should clearly articulate the value capture strategy through market inefficiency or value-add potential.
"""

def get_market_context() -> Dict[str, Any]:
    """
    Queries DynamoDB to get multiple types of market context:
    1. Top 20 investment properties
    2. Recent price drops
    3. District-specific comparables
    4. Market summary statistics
    """
    if not table:
        logger.warning("DynamoDB table not configured, skipping market context")
        return {}
    
    market_context = {}
    
    try:
        # Get top investment properties
        investment_response = table.query(
            IndexName='GSI_INVEST',
            KeyConditionExpression=Key('invest_partition').eq('INVEST'),
            ScanIndexForward=False,  # Sort by investment_score descending
            Limit=20,
            ProjectionExpression="property_id, investment_score, price, price_per_sqm, district, total_sqm, recommendation, listing_url"
        )
        market_context['top_investments'] = investment_response.get('Items', [])
        
        # Get recent analyses (last 7 days)
        seven_days_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
        recent_response = table.query(
            IndexName='GSI_ANALYSIS_DATE',
            KeyConditionExpression=Key('invest_partition').eq('INVEST') & Key('analysis_date').gte(seven_days_ago),
            ScanIndexForward=False,
            Limit=50
        )
        
        # Filter for properties with significant price drops
        recent_items = recent_response.get('Items', [])
        price_drops = [
            {
                'property_id': item['property_id'],
                'price': item['price'],
                'price_per_sqm': item['price_per_sqm'],
                'district': item.get('district', ''),
                'price_trend': item.get('price_trend', '')
            }
            for item in recent_items 
            if item.get('price_trend') == 'below_market'
        ][:10]  # Top 10 price drops
        
        market_context['recent_price_drops'] = price_drops
        
        # Summary statistics
        if recent_items:
            avg_price_per_sqm = sum(item.get('price_per_sqm', 0) for item in recent_items) / len(recent_items)
            avg_investment_score = sum(item.get('investment_score', 0) for item in recent_items) / len(recent_items)
            
            market_context['market_summary'] = {
                'properties_analyzed_last_7_days': len(recent_items),
                'average_price_per_sqm': int(avg_price_per_sqm),
                'average_investment_score': int(avg_investment_score),
                'strong_buy_count': sum(1 for item in recent_items if item.get('recommendation') == 'strong_buy'),
                'buy_count': sum(1 for item in recent_items if item.get('recommendation') == 'buy')
            }
        
    except Exception as e:
        logger.error(f"Failed to query DynamoDB for market context: {e}")
        return {}
    
    return market_context


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main Lambda handler for prompt building.
    
    Args:
        event: Lambda event containing processed data from ETL step
        context: Lambda context
        
    Returns:
        Dict containing prompt payload location and metadata
    """
    try:
        date_str = event.get('date')
        bucket = event.get('bucket', os.environ['OUTPUT_BUCKET'])
        
        logger.info(f"Building prompt for date: {date_str}")
        
        # Get market context from DynamoDB
        market_context = get_market_context()
        logger.info(f"Retrieved market context with {len(market_context.get('top_investments', []))} top investments")
        
        # Load processed JSONL data
        jsonl_key = event.get('jsonl_key', f"clean/{date_str}/listings.jsonl")
        listings = load_jsonl_from_s3(bucket, jsonl_key)
        
        logger.info(f"Loaded {len(listings)} listings")
        
        # Sort by price_per_m2 and take top 5 for testing
        sorted_listings = sort_and_filter_listings(listings)
        
        logger.info(f"Selected {len(sorted_listings)} top listings by price_per_m2")
        
        # Build individual batch requests for each listing
        batch_requests = build_batch_requests(sorted_listings, date_str, bucket, market_context)
        
        # Save batch requests as JSONL to S3
        prompt_key = f"prompts/{date_str}/batch_requests.jsonl"
        save_batch_requests_to_s3(batch_requests, bucket, prompt_key)
        
        logger.info(f"Successfully built prompt with {len(sorted_listings)} listings")
        
        return {
            'statusCode': 200,
            'date': date_str,
            'bucket': bucket,
            'prompt_key': prompt_key,
            'listings_count': len(sorted_listings),
            'total_images': sum(len(prioritize_images(listing.get('interior_photos', []))) for listing in sorted_listings),
            'batch_requests_count': len(batch_requests)
        }
        
    except Exception as e:
        logger.error(f"Prompt building failed: {e}")
        raise


def load_jsonl_from_s3(bucket: str, key: str) -> List[Dict[str, Any]]:
    """
    Load JSONL data from S3.
    
    Args:
        bucket: S3 bucket name
        key: S3 key for JSONL file
        
    Returns:
        List of listing dictionaries
    """
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        content = response['Body'].read().decode('utf-8')
        
        listings = []
        for line in content.strip().split('\n'):
            if line.strip():
                listings.append(json.loads(line))
        
        return listings
        
    except Exception as e:
        logger.error(f"Failed to load JSONL from s3://{bucket}/{key}: {e}")
        raise


def sort_and_filter_listings(listings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Filter listings for analysis. Let the LLM handle Japanese field names and parsing.
    Just filter out completely empty entries.
    
    Args:
        listings: List of listing dictionaries
        
    Returns:
        Filtered listings (raw Japanese data preserved)
    """
    # Filter out listings that are clearly invalid (no ID or URL)
    valid_listings = [
        listing for listing in listings 
        if listing.get('id') or listing.get('url')
    ]
    
    # Take up to 100 listings for analysis (or all if fewer)
    return valid_listings[:100]


def build_batch_requests(listings: List[Dict[str, Any]], date_str: str, bucket: str, market_context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Build individual batch requests for each listing.
    
    Args:
        listings: List of listing dictionaries
        date_str: Processing date string
        bucket: S3 bucket name
        market_context: Market context data from DynamoDB
        
    Returns:
        List of batch request dictionaries
    """
    batch_requests = []
    
    # Update system prompt with market context
    market_context_text = json.dumps(market_context, ensure_ascii=False, indent=2, default=decimal_default) if market_context else "No recent market data available."
    updated_system_prompt = SYSTEM_PROMPT + f"""

# Current Market Analysis Data

Here is comprehensive market context from recently analyzed properties:

```json
{market_context_text}
```

Use this data to:
- Compare new properties against top performers
- Identify if pricing is competitive based on recent trends
- Spot opportunities based on price drops and market movements
- Provide data-driven investment recommendations

When analyzing a property, reference specific comparable properties from this dataset when relevant.
"""
    
    for i, listing in enumerate(listings):
        # Create individual prompt for this listing
        messages = [
            {
                "role": "system",
                "content": updated_system_prompt
            },
            {
                "role": "user",
                "content": build_individual_listing_content(listing, date_str, bucket)
            }
        ]
        
        # Create batch request format
        batch_request = {
            "custom_id": f"listing-analysis-{date_str}-{listing.get('id', i)}",
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {
                "model": "gpt-4o",  # Use gpt-4o for vision capabilities
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": 4000
            }
        }
        
        batch_requests.append(batch_request)
    
    return batch_requests


def build_individual_listing_content(listing: Dict[str, Any], date_str: str, bucket: str) -> List[Dict[str, Any]]:
    """
    Build user message content for a single listing with all its images.
    
    Args:
        listing: Single listing dictionary
        date_str: Processing date string
        bucket: S3 bucket name
        
    Returns:
        List of message content items for this listing
    """
    content = [
        {
            "type": "text",
            "text": f"Analyze this individual real estate listing scraped on {date_str}. Parse and analyze ALL data including Japanese fields."
        }
    ]
    
    # Create a clean copy excluding image processing metadata
    clean_listing = {k: v for k, v in listing.items() 
                    if k not in ['uploaded_image_urls', 'processed_date', 'source']}
    
    # Pass ALL raw fields to OpenAI - let it handle the parsing
    listing_text = json.dumps(clean_listing, ensure_ascii=False, indent=2)
    
    content.append({
        "type": "text", 
        "text": f"LISTING DATA (includes 'url' field for property link):\n{listing_text}"
    })
    
    # Add all available property images with smart prioritization
    all_photos = listing.get('interior_photos', [])
    prioritized_photos = prioritize_images(all_photos)
    
    content.append({
        "type": "text",
        "text": f"Below are all available property images (exterior, interior, neighborhood, etc.) for this listing ({len(prioritized_photos)} images):"
    })
    
    for photo_url in prioritized_photos:
        # Generate presigned URL for the photo
        presigned_url = generate_presigned_url(photo_url, bucket)
        
        if presigned_url:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": presigned_url,
                    "detail": "low"
                }
            })
    
    # Add instruction for individual listing analysis
    content.append({
        "type": "text",
        "text": "IMPORTANT: Analyze this single property for investment potential. Return your analysis in JSON format with the following structure: {\"investment_score\": 0-100, \"price_analysis\": \"text\", \"location_assessment\": \"text\", \"condition_assessment\": \"text\", \"investment_thesis\": \"text\", \"risks\": [\"risk1\", \"risk2\"], \"recommendation\": \"buy/pass/investigate\"}"
    })
    
    return content


def prioritize_images(image_urls: List[str]) -> List[str]:
    """
    Prioritize images to show the most important ones first.
    Prioritizes: exterior (1-2), interior living spaces (5-6), kitchen/bath (3-4), then others.
    
    Args:
        image_urls: List of all image URLs
        
    Returns:
        List of up to 20 prioritized image URLs
    """
    if not image_urls:
        return []
    
    # Categorize images based on URL/filename
    exterior = []
    living_spaces = []
    kitchen_bath = []
    others = []
    
    for url in image_urls:
        filename = url.split('/')[-1].lower()
        
        if any(kw in filename for kw in ['exterior', 'outside', 'building', 'entrance']):
            exterior.append(url)
        elif any(kw in filename for kw in ['living', 'bedroom', 'room']):
            living_spaces.append(url)
        elif any(kw in filename for kw in ['kitchen', 'bath', 'toilet', 'dining']):
            kitchen_bath.append(url)
        else:
            others.append(url)
    
    # Prioritize and limit each category
    prioritized = (
        exterior[:2] +           # Max 2 exterior shots
        living_spaces[:8] +      # Max 8 living spaces
        kitchen_bath[:4] +       # Max 4 kitchen/bath
        others[:6]               # Max 6 others
    )
    
    # Return up to 20 images total
    return prioritized[:20]


def generate_presigned_url(s3_url: str, bucket: str, expiration: int = 28800) -> str:
    """
    Generate presigned URL for S3 object.
    
    Args:
        s3_url: S3 URL (s3://bucket/key format)
        bucket: S3 bucket name
        expiration: URL expiration time in seconds (default 8 hours)
        
    Returns:
        Presigned URL string or empty string if failed
    """
    try:
        # Extract key from S3 URL
        parsed = urlparse(s3_url)
        if parsed.scheme != 's3':
            logger.warning(f"Invalid S3 URL format: {s3_url}")
            return ""
        
        key = parsed.path.lstrip('/')
        
        # Generate presigned URL
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket, 'Key': key},
            ExpiresIn=expiration
        )
        
        return presigned_url
        
    except Exception as e:
        logger.warning(f"Failed to generate presigned URL for {s3_url}: {e}")
        return ""


def save_batch_requests_to_s3(batch_requests: List[Dict[str, Any]], bucket: str, key: str) -> None:
    """
    Save batch requests as JSONL to S3.
    
    Args:
        batch_requests: List of batch request dictionaries
        bucket: S3 bucket name
        key: S3 key for saving
    """
    try:
        # Convert to JSONL format (one JSON object per line)
        jsonl_lines = []
        for request in batch_requests:
            jsonl_lines.append(json.dumps(request, ensure_ascii=False))
        
        content = '\n'.join(jsonl_lines)
        
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=content.encode('utf-8'),
            ContentType='application/x-ndjson'
        )
        
        logger.info(f"Saved {len(batch_requests)} batch requests to s3://{bucket}/{key}")
        
    except Exception as e:
        logger.error(f"Failed to save batch requests to S3: {e}")
        raise


if __name__ == "__main__":
    # For local testing
    test_event = {
        'date': '2025-07-07',
        'bucket': 'tokyo-real-estate-ai-data',
        'jsonl_key': 'clean/2025-07-07/listings.jsonl'
    }
    result = lambda_handler(test_event, None)
    print(json.dumps(result, indent=2))