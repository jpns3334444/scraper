import json
import logging
import os
from datetime import datetime
import time
import decimal
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

# Import centralized config helper
try:
    from util.config import get_config
except ImportError:
    logging.warning("Centralized config not available, falling back to direct os.environ access")
    get_config = None

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
if get_config:
    table_name = get_config().get_str('DYNAMODB_TABLE')
    table = dynamodb.Table(table_name) if table_name else None
else:
    table = dynamodb.Table(os.environ['DYNAMODB_TABLE'])

def decimal_default(obj):
    """JSON serializer for Decimal types"""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError

def lambda_handler(event, context):
    """
    Processes LLM batch results and writes structured data to DynamoDB.
    Handles both META (snapshot) and HIST (price change) items.
    """
    batch_result = event.get('batch_result', {})
    if isinstance(batch_result, list):
        individual_results = batch_result
    else:
        individual_results = batch_result.get('individual_results', [])
    
    for result in individual_results:
        try:
            # The 'analysis' field contains the full JSON response from the LLM
            analysis_str = result.get('analysis', '{}')
            if not analysis_str.strip().startswith('{'):
                logger.warning(f"Skipping result with invalid analysis JSON: {result.get('custom_id')}")
                continue

            # Parse the analysis string to get the structured data
            analysis_json = json.loads(analysis_str)
            
            # In Lean v1.3, the LLM produces a flat JSON structure (evaluation_min.json schema)
            # Check if this is the lean format or legacy nested format
            if 'database_fields' in analysis_json:
                # Legacy nested format
                property_data = analysis_json.get('database_fields', {})
                logger.info(f"Processing legacy nested format for {result.get('custom_id')}")
            else:
                # Lean v1.3 flat format - use the analysis_json directly
                property_data = analysis_json
                logger.info(f"Processing lean flat format for {result.get('custom_id')}")
            
            if not property_data:
                logger.warning(f"Skipping result with no property data: {result.get('custom_id')}")
                continue

            raw_property_id = result.get('custom_id', '').split('-')[-1]
            if not raw_property_id:
                logger.warning(f"Skipping result with missing property ID in custom_id: {result.get('custom_id')}")
                continue

            # Construct the property_id for the table
            today_str = datetime.utcnow().strftime('%Y%m%d')
            property_id = f"PROP#{today_str}_{raw_property_id}"

            # Check for existing META item to see if price has changed
            existing_item = table.get_item(Key={'property_id': property_id, 'sort_key': 'META'}).get('Item')

            # Create the META item using the extracted property_data
            meta_item = create_meta_item(property_id, property_data, result)
            
            with table.batch_writer() as batch:
                batch.put_item(Item=meta_item)
                logger.info(f"Upserting META item for {property_id}")

                # If price has changed, create a HIST item
                if existing_item and existing_item.get('price') != meta_item.get('price'):
                    hist_item = create_hist_item(property_id, existing_item, meta_item)
                    batch.put_item(Item=hist_item)
                    logger.info(f"Creating HIST item for price change on {property_id}")

        except (ClientError, json.JSONDecodeError, TypeError) as e:
            logger.error(f"Failed to process or write result for {result.get('custom_id')}: {e}")
            continue
    return event

def safe_int(value, default=0):
    """Safely convert to int, returning default if conversion fails"""
    try:
        return int(value) if value is not None else default
    except (ValueError, TypeError):
        return default

def safe_float(value, default=0.0):
    """Safely convert to Decimal (DynamoDB compatible), returning default if conversion fails"""
    try:
        return Decimal(str(value)) if value is not None else Decimal(str(default))
    except (ValueError, TypeError, decimal.InvalidOperation):
        return Decimal(str(default))

def safe_bool(value, default=False):
    """Safely convert to boolean"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ('true', 'yes', '1', 'y')
    return default

def create_meta_item(property_id, analysis, full_result):
    """Creates the META item for a property. Handles both legacy and lean formats."""
    now = datetime.utcnow()
    
    # Check if this is lean format (evaluation_min.json schema)
    is_lean_format = ('verdict' in analysis and 'upside' in analysis and 'risks' in analysis)
    
    if is_lean_format:
        # Lean v1.3 format - minimal fields for lean evaluation
        item = {
            # Primary keys
            'property_id': property_id,
            'sort_key': 'META',
            
            # Core Information
            'listing_url': full_result.get('listing_url', ''),
            'analysis_date': now.isoformat(),
            'property_id_simple': analysis.get('property_id', ''),
            
            # Lean evaluation fields
            'base_score': safe_int(analysis.get('base_score')),
            'final_score': safe_int(analysis.get('final_score')),
            'verdict': analysis.get('verdict', 'REJECT'),
            'upside': analysis.get('upside', []),
            'risks': analysis.get('risks', []),
            'justification': analysis.get('justification', ''),
            
            # Investment Analysis (simplified)
            'investment_score': safe_int(analysis.get('final_score')),  # Use final_score as investment_score
            'invest_partition': 'INVEST',  # For GSI
            'recommendation': analysis.get('verdict', 'REJECT').lower().replace('_candidate', ''),
            
            # Metadata
            'llm_model_version': full_result.get('model', ''),
            'analysis_yymm': now.strftime('%Y-%m'),
            'data_format': 'lean_v1.3'
        }
    else:
        # Legacy comprehensive format
        item = {
            # Primary keys
            'property_id': property_id,
            'sort_key': 'META',
            
            # Core Property Information
            'listing_url': full_result.get('listing_url', ''),
            'scraped_date': full_result.get('scraped_date', now.isoformat()),
            'analysis_date': now.isoformat(),
            'property_type': analysis.get('property_type', 'apartment'),
            'listing_status': 'active',
            
            # Price & Financial Metrics (legacy comprehensive fields)
            'price': safe_int(analysis.get('price')),
            'price_per_sqm': safe_int(analysis.get('price_per_sqm')),
            'price_trend': analysis.get('price_trend', 'at_market'),
            'estimated_market_value': safe_int(analysis.get('estimated_market_value')),
            'price_negotiability_score': safe_int(analysis.get('price_negotiability_score'), 5),
            'monthly_management_fee': safe_int(analysis.get('monthly_management_fee')),
            'annual_property_tax': safe_int(analysis.get('annual_property_tax')),
            'reserve_fund_balance': safe_int(analysis.get('reserve_fund_balance')),
            'special_assessments': safe_int(analysis.get('special_assessments')),
            
            # Location & Building Details
            'address': analysis.get('address', ''),
            'district': analysis.get('district', ''),
            'district_key': f"DIST#{analysis.get('district', 'Unknown').replace(' ', '_')}",
            'nearest_station': analysis.get('nearest_station', ''),
            'station_distance_minutes': safe_int(analysis.get('station_distance_minutes')),
            'building_name': analysis.get('building_name', ''),
            'building_age_years': safe_int(analysis.get('building_age_years')),
            'total_units_in_building': safe_int(analysis.get('total_units_in_building')),
            'floor_number': safe_int(analysis.get('floor_number')),
            'total_floors': safe_int(analysis.get('total_floors')),
            'direction_facing': analysis.get('direction_facing', ''),
            'corner_unit': safe_bool(analysis.get('corner_unit')),
            
            # Property Specifications
            'total_sqm': safe_float(analysis.get('total_sqm')),
            'num_bedrooms': safe_int(analysis.get('num_bedrooms')),
            'num_bathrooms': safe_float(analysis.get('num_bathrooms')),
            'balcony_sqm': safe_float(analysis.get('balcony_sqm')),
            'storage_sqm': safe_float(analysis.get('storage_sqm')),
            'parking_included': safe_bool(analysis.get('parking_included')),
            'parking_type': analysis.get('parking_type', 'none'),
            'layout_efficiency_score': safe_int(analysis.get('layout_efficiency_score'), 5),
            
            # Investment Analysis
            'investment_score': safe_int(analysis.get('investment_score')),
            'invest_partition': 'INVEST',  # For GSI
            'rental_yield_estimate': safe_float(analysis.get('rental_yield_estimate')),
            'appreciation_potential': analysis.get('appreciation_potential', 'medium'),
            'liquidity_score': safe_int(analysis.get('liquidity_score'), 5),
            'target_tenant_profile': analysis.get('target_tenant_profile', ''),
            'renovation_roi_potential': safe_float(analysis.get('renovation_roi_potential')),
            
            # AI Assessment Fields
            'price_analysis': analysis.get('price_analysis', ''),
            'location_assessment': analysis.get('location_assessment', ''),
            'condition_assessment': analysis.get('condition_assessment', ''),
            'investment_thesis': analysis.get('investment_thesis', ''),
            'competitive_advantages': analysis.get('competitive_advantages', []),
            'risks': analysis.get('risks', []),
            'recommended_offer_price': safe_int(analysis.get('recommended_offer_price')),
            'recommendation': analysis.get('recommendation', 'pass'),
            'confidence_score': safe_float(analysis.get('confidence_score'), 0.5),
            'comparable_properties': analysis.get('comparable_properties', []),
            
            # Metadata
            'llm_model_version': full_result.get('model', ''),
            'image_analysis_model_version': analysis.get('image_analysis_model_version', ''),
            'full_llm_response': full_result.get('full_response', {}),
            'processing_errors': analysis.get('processing_errors', []),
            'data_quality_score': safe_float(analysis.get('data_quality_score'), 0.5),
            'analysis_yymm': now.strftime('%Y-%m'),
            'data_format': 'legacy'
        }
    
    return item

def create_hist_item(property_id, old_item, new_item):
    """Creates a HIST item for a price change."""
    now = datetime.utcnow()
    old_price = old_item.get('price', 0)
    new_price = new_item.get('price', 0)
    price_drop_pct = Decimal(str(round((old_price - new_price) / old_price * 100, 2))) if old_price > 0 else Decimal('0')

    return {
        'property_id': property_id,
        'sort_key': f"HIST#{now.strftime('%Y-%m-%d_%H:%M:%S')}",
        'price': new_price,
        'price_per_sqm': new_item.get('price_per_sqm', 0),
        'listing_status': new_item.get('listing_status', 'active'),
        'analysis_date': now.isoformat(),
        'price_change_amount': new_price - old_price,
        'price_drop_pct': price_drop_pct,
        'previous_price': old_price,
        'investment_score': new_item.get('investment_score', 0),
        'recommendation': new_item.get('recommendation', ''),
        'ttl_epoch': int(time.time()) + 60*60*24*365  # 1 year TTL
    }