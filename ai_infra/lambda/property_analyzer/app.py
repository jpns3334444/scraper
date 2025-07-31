#!/usr/bin/env python3
"""
Property Analyzer Lambda - Calculates scores and comparables for properties
No HTTP requests - only DynamoDB operations and calculations
"""
import os
import json
import time
from datetime import datetime, timedelta
import boto3
from boto3.dynamodb.conditions import Key, Attr
import logging

# Import analysis modules from property_processor
import sys
sys.path.append('/opt/python/lib/python3.9/site-packages')
sys.path.append('/var/task')
sys.path.append('../property_processor')

try:
    from analysis.lean_scoring import LeanScoring, Verdict
    from analysis.comparables import ComparablesFilter, enrich_property_with_comparables
    from util.metrics import emit_pipeline_metrics, emit_properties_processed, emit_candidates_enqueued
    ANALYSIS_MODULES_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Failed to import analysis modules: {e}")
    ANALYSIS_MODULES_AVAILABLE = False
    LeanScoring = None
    ComparablesFilter = None
    enrich_property_with_comparables = lambda x, y: x

class SessionLogger:
    """Simple logger that automatically includes session_id in all messages"""
    
    def __init__(self, session_id, log_level='INFO'):
        self.session_id = session_id
        self._logger = logging.getLogger(__name__)
        self._logger.setLevel(getattr(logging, log_level.upper()))
    
    def info(self, message):
        self._logger.info(f"[{self.session_id}] {message}")
    
    def warning(self, message):
        self._logger.warning(f"[{self.session_id}] {message}")
    
    def error(self, message):
        self._logger.error(f"[{self.session_id}] {message}")
    
    def debug(self, message):
        self._logger.debug(f"[{self.session_id}] {message}")

def setup_dynamodb_client(logger=None):
    """Setup DynamoDB client and table"""
    try:
        dynamodb = boto3.resource('dynamodb')
        table_name = os.environ.get('DYNAMODB_TABLE', 'tokyo-real-estate-ai-analysis-db')
        table = dynamodb.Table(table_name)
        
        if logger:
            logger.info(f"Connected to DynamoDB table: {table_name}")
        
        return dynamodb, table
    except Exception as e:
        if logger:
            logger.error(f"Failed to setup DynamoDB: {str(e)}")
        raise

def load_properties_from_dynamodb(table, days_back=7, logger=None):
    """Load properties from DynamoDB for the last N days"""
    try:
        # Calculate cutoff date
        cutoff_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
        
        # Scan for META items with recent analysis_date
        response = table.scan(
            FilterExpression=Attr('sort_key').eq('META') & 
                           Attr('analysis_date').gte(cutoff_date)
        )
        
        properties = response.get('Items', [])
        
        # Handle pagination
        while 'LastEvaluatedKey' in response:
            response = table.scan(
                FilterExpression=Attr('sort_key').eq('META') & 
                               Attr('analysis_date').gte(cutoff_date),
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
            properties.extend(response.get('Items', []))
        
        if logger:
            logger.info(f"Loaded {len(properties)} properties from last {days_back} days")
        
        return properties
    
    except Exception as e:
        if logger:
            logger.error(f"Failed to load properties: {str(e)}")
        return []

def load_all_properties_from_dynamodb(table, logger=None):
    """Load all properties from DynamoDB"""
    try:
        # Scan for all META items
        response = table.scan(
            FilterExpression=Attr('sort_key').eq('META')
        )
        
        properties = response.get('Items', [])
        
        # Handle pagination
        while 'LastEvaluatedKey' in response:
            response = table.scan(
                FilterExpression=Attr('sort_key').eq('META'),
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
            properties.extend(response.get('Items', []))
        
        if logger:
            logger.info(f"Loaded {len(properties)} total properties")
        
        return properties
    
    except Exception as e:
        if logger:
            logger.error(f"Failed to load all properties: {str(e)}")
        return []

def calculate_ward_medians(properties, logger=None):
    """Calculate ward median price per sqm from properties"""
    from decimal import Decimal
    ward_data = {}
    
    for prop in properties:
        ward = prop.get('ward')
        price_per_sqm = prop.get('price_per_sqm')
        
        if ward and price_per_sqm:
            # Convert Decimal to float if needed
            if isinstance(price_per_sqm, Decimal):
                price_per_sqm = float(price_per_sqm)
            else:
                price_per_sqm = float(price_per_sqm)
                
            if price_per_sqm > 0:
                if ward not in ward_data:
                    ward_data[ward] = []
                ward_data[ward].append(price_per_sqm)
    
    ward_medians = {}
    for ward, prices in ward_data.items():
        if len(prices) >= 2:  # Need at least 2 data points
            sorted_prices = sorted(prices)
            median_idx = len(sorted_prices) // 2
            median_price = sorted_prices[median_idx]
            
            ward_medians[ward] = {
                'ward_median_price_per_sqm': median_price,
                'ward_property_count': len(prices)
            }
    
    if logger:
        logger.info(f"Calculated medians for {len(ward_medians)} wards")
    
    return ward_medians

def find_comparables_for_property(target_property, all_properties, logger=None):
    """Find comparable properties for scoring"""
    try:
        if not ANALYSIS_MODULES_AVAILABLE:
            return []
        
        # Use the existing comparables logic
        comparables = enrich_property_with_comparables(target_property, all_properties)
        
        # Extract comparables data from the enriched property
        if 'comparables' in comparables:
            return comparables['comparables']
        
        return []
        
    except Exception as e:
        if logger:
            logger.debug(f"Failed to find comparables: {str(e)}")
        return []

def calculate_property_score(property_data, ward_medians, all_properties, logger=None):
    """Calculate score for a single property"""
    try:
        if not ANALYSIS_MODULES_AVAILABLE:
            return None
        
        # Add ward median data
        ward = property_data.get('ward')
        if ward and ward in ward_medians:
            property_data.update(ward_medians[ward])
        
        # Find comparables
        comparables = find_comparables_for_property(property_data, all_properties, logger)
        property_data['comparables'] = comparables
        property_data['num_comparables'] = len(comparables)
        
        # Initialize scorer and calculate
        scorer = LeanScoring()
        scoring_components = scorer.calculate_score(property_data)
        
        return {
            'final_score': scoring_components.final_score,
            'base_score': scoring_components.base_score,
            'addon_score': scoring_components.addon_score,
            'adjustment_score': scoring_components.adjustment_score,
            'verdict': scoring_components.verdict.value,
            'ward_discount_pct': scoring_components.ward_discount_pct,
            'data_quality_penalty': scoring_components.data_quality_penalty,
            'scoring_components': {
                'ward_discount': scoring_components.ward_discount,
                'building_discount': scoring_components.building_discount,
                'comps_consistency': scoring_components.comps_consistency,
                'condition': scoring_components.condition,
                'size_efficiency': scoring_components.size_efficiency,
                'carry_cost': scoring_components.carry_cost,
                'price_cut': scoring_components.price_cut,
                'renovation_potential': scoring_components.renovation_potential,
                'access': scoring_components.access,
                'vision_positive': scoring_components.vision_positive,
                'vision_negative': scoring_components.vision_negative,
                'overstated_discount_penalty': scoring_components.overstated_discount_penalty
            },
            'comparables': comparables,
            'num_comparables': len(comparables)
        }
        
    except Exception as e:
        if logger:
            logger.error(f"Failed to calculate score for property {property_data.get('property_id', 'unknown')}: {str(e)}")
        return None

def update_property_in_dynamodb(table, property_id, scoring_data, ward_medians, logger=None):
    """Update property record with scoring data"""
    try:
        ward = scoring_data.get('ward') if 'ward' in scoring_data else None
        ward_median_data = ward_medians.get(ward, {}) if ward else {}
        
        # Prepare update expression
        update_expr = "SET "
        expr_attr_values = {}
        update_parts = []
        
        # Add scoring data
        if scoring_data:
            fields_to_update = [
                'final_score', 'base_score', 'addon_score', 'adjustment_score',
                'verdict', 'ward_discount_pct', 'data_quality_penalty',
                'scoring_components', 'comparables', 'num_comparables'
            ]
            
            for field in fields_to_update:
                if field in scoring_data:
                    update_parts.append(f"{field} = :{field}")
                    expr_attr_values[f":{field}"] = scoring_data[field]
        
        # Add ward median data
        if ward_median_data:
            for field, value in ward_median_data.items():
                update_parts.append(f"{field} = :{field}")
                expr_attr_values[f":{field}"] = value
        
        # Add analysis timestamp
        update_parts.append("last_analyzed = :last_analyzed")
        expr_attr_values[":last_analyzed"] = datetime.now().isoformat()
        
        if not update_parts:
            if logger:
                logger.warning(f"No data to update for property {property_id}")
            return False
        
        update_expr += ", ".join(update_parts)
        
        # Execute update
        table.update_item(
            Key={
                'property_id': property_id,
                'sort_key': 'META'
            },
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_attr_values
        )
        
        return True
        
    except Exception as e:
        if logger:
            logger.error(f"Failed to update property {property_id}: {str(e)}")
        return False

def analyze_properties(table, properties, logger=None):
    """Analyze all properties with scoring and comparables"""
    if not ANALYSIS_MODULES_AVAILABLE:
        logger.error("Analysis modules not available")
        return {'analyzed': 0, 'errors': 0}
    
    logger.info(f"Starting analysis of {len(properties)} properties")
    
    # Calculate ward medians from all properties
    ward_medians = calculate_ward_medians(properties, logger)
    
    analyzed_count = 0
    error_count = 0
    
    for i, property_data in enumerate(properties):
        try:
            property_id = property_data.get('property_id')
            if not property_id:
                logger.warning(f"Property {i} missing property_id, skipping")
                error_count += 1
                continue
            
            # Calculate scoring data
            scoring_data = calculate_property_score(property_data, ward_medians, properties, logger)
            
            if scoring_data:
                # Update DynamoDB record
                success = update_property_in_dynamodb(table, property_id, scoring_data, ward_medians, logger)
                
                if success:
                    analyzed_count += 1
                    if analyzed_count % 10 == 0:
                        logger.info(f"Progress: {analyzed_count}/{len(properties)} properties analyzed")
                else:
                    error_count += 1
            else:
                error_count += 1
                
        except Exception as e:
            logger.error(f"Error analyzing property {i}: {str(e)}")
            error_count += 1
    
    logger.info(f"Analysis complete: {analyzed_count} analyzed, {error_count} errors")
    
    return {
        'analyzed': analyzed_count,
        'errors': error_count,
        'ward_medians_calculated': len(ward_medians)
    }

def parse_lambda_event(event):
    """Parse lambda event with environment variable fallbacks"""
    return {
        'session_id': event.get('session_id', os.environ.get('SESSION_ID', f'property-analyzer-{int(time.time())}')),
        'dynamodb_table': event.get('dynamodb_table', os.environ.get('DYNAMODB_TABLE', 'tokyo-real-estate-ai-analysis-db')),
        'days_back': event.get('days_back', int(os.environ.get('DAYS_BACK', '7'))),
        'analyze_all': event.get('analyze_all', os.environ.get('ANALYZE_ALL', 'false').lower() == 'true'),
        'log_level': event.get('log_level', os.environ.get('LOG_LEVEL', 'INFO'))
    }

def main(event=None):
    """Main property analyzer function"""
    if event is None:
        event = {}
    
    args = parse_lambda_event(event)
    logger = SessionLogger(args['session_id'], log_level=args['log_level'])
    
    job_start_time = datetime.now()
    
    logger.info(f"Starting Property Analyzer - Session: {args['session_id']}")
    logger.info(f"DynamoDB table: {args['dynamodb_table']}")
    logger.info(f"Days back: {args['days_back']}, Analyze all: {args['analyze_all']}")
    
    try:
        # Setup DynamoDB
        _, table = setup_dynamodb_client(logger)
        
        # Load properties
        if args['analyze_all']:
            properties = load_all_properties_from_dynamodb(table, logger)
        else:
            properties = load_properties_from_dynamodb(table, args['days_back'], logger)
        
        if not properties:
            logger.info("No properties found to analyze")
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'No properties found to analyze',
                    'session_id': args['session_id'],
                    'analyzed': 0,
                    'errors': 0
                })
            }
        
        # Analyze properties
        results = analyze_properties(table, properties, logger)
        
        # Calculate duration
        duration = (datetime.now() - job_start_time).total_seconds()
        
        logger.info(f"Property analysis completed in {duration:.1f} seconds")
        logger.info(f"Results: {results['analyzed']} analyzed, {results['errors']} errors")
        
        # Emit metrics if available
        if ANALYSIS_MODULES_AVAILABLE:
            try:
                emit_properties_processed(results['analyzed'])
                candidates_found = len([p for p in properties if p.get('verdict') == 'BUY_CANDIDATE'])
                emit_candidates_enqueued(candidates_found)
                logger.info(f"Emitted metrics: {results['analyzed']} processed, {candidates_found} candidates")
            except Exception as e:
                logger.warning(f"Failed to emit metrics: {e}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Property analysis completed successfully',
                'session_id': args['session_id'],
                'duration_seconds': duration,
                'properties_loaded': len(properties),
                'analyzed': results['analyzed'],
                'errors': results['errors'],
                'ward_medians_calculated': results.get('ward_medians_calculated', 0),
                'timestamp': datetime.now().isoformat()
            })
        }
        
    except Exception as e:
        logger.error(f"Property analyzer failed: {str(e)}")
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'session_id': args['session_id'],
                'timestamp': datetime.now().isoformat()
            })
        }

def lambda_handler(event, context):
    """AWS Lambda handler"""
    session_id = event.get('session_id', f'property-analyzer-{int(time.time())}')
    log_level = event.get('log_level', 'INFO')
    logger = SessionLogger(session_id, log_level=log_level)
    
    logger.info("Property Analyzer Lambda execution started")
    logger.debug(f"Event: {json.dumps(event, indent=2)}")
    
    try:
        result = main(event)
        return result
        
    except Exception as e:
        logger.error(f"Property Analyzer Lambda failed: {str(e)}")
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            })
        }

if __name__ == "__main__":
    main()