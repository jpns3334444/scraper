#!/usr/bin/env python3
"""
Property Analyzer Lambda - Simplified US market analysis
Calculates 3 metrics: days_on_market, city_median_price_per_sqft, city_discount_pct
"""
import boto3
import time
import json
import statistics
import logging
import os
from decimal import Decimal
from decimal_utils import to_float, to_dec
from datetime import datetime, timezone


def get_aws_region():
    """Get AWS region from environment or default"""
    return os.environ.get('AWS_REGION', 'us-east-1')


# Setup DynamoDB
dynamodb = boto3.resource('dynamodb', region_name=get_aws_region())
table = dynamodb.Table(os.environ.get('DYNAMODB_TABLE', 'real-estate-ai-properties'))


class SessionLogger:
    """Simple logger that includes session_id in all messages"""

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

    def exception(self, message):
        self._logger.exception(f"[{self.session_id}] {message}")


def lambda_handler(event, context):
    """AWS Lambda handler"""
    session_id = event.get('session_id', f'analyzer-{int(time.time())}')
    logger = SessionLogger(session_id, log_level=os.environ.get('LOG_LEVEL', 'INFO'))
    logger.info(f"Starting property analysis session: {session_id}")

    t0 = time.time()

    # 1. Pull all property items
    properties = scan_meta_items(logger)
    logger.info(f"Found {len(properties)} properties to analyze")

    # Check for property limit from event payload
    property_limit = event.get('max_properties', 0)
    if property_limit > 0 and len(properties) > property_limit:
        properties = properties[:property_limit]
        logger.info(f"Limited to first {property_limit} properties")

    # 2. Calculate city statistics
    city_stats = calc_city_stats(properties, logger)
    logger.info(f"Calculated statistics for {len(city_stats)} cities")

    # 3. Analyze and update each property
    errors = 0
    processed = 0

    for prop in properties:
        try:
            enrichment = analyze_property(prop, city_stats, logger)
            update_property(prop['property_id'], enrichment, logger)

            processed += 1
            if processed % 10 == 0:
                logger.info(f"Progress: {processed}/{len(properties)} properties")

        except Exception as e:
            logger.exception(f"Failed to analyze {prop.get('property_id')}: {str(e)}")
            errors += 1

    duration = round(time.time() - t0, 1)
    logger.info(f"Analysis complete: {processed} processed, {errors} errors, {duration}s")

    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Property analysis completed",
            "session_id": session_id,
            "properties_analyzed": processed,
            "errors": errors,
            "cities_analyzed": len(city_stats),
            "duration_seconds": duration
        })
    }


def scan_meta_items(logger):
    """Scan all property items where sort_key == 'META'"""
    properties = []

    try:
        response = table.scan(
            FilterExpression=boto3.dynamodb.conditions.Attr('sort_key').eq('META')
        )
        properties.extend(response.get('Items', []))

        while 'LastEvaluatedKey' in response:
            response = table.scan(
                FilterExpression=boto3.dynamodb.conditions.Attr('sort_key').eq('META'),
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
            properties.extend(response.get('Items', []))

    except Exception as e:
        logger.error(f"Error scanning DynamoDB: {str(e)}")
        raise

    return properties


def calc_city_stats(properties, logger):
    """Calculate city-level statistics (median price per sqft)"""
    city_groups = {}

    for prop in properties:
        city = prop.get('city', '').strip()
        if not city:
            continue

        price_per_sqft = to_float(prop.get('price_per_sqft', 0))
        if price_per_sqft <= 0:
            continue

        if city not in city_groups:
            city_groups[city] = []
        city_groups[city].append(price_per_sqft)

    city_stats = {}
    for city, prices in city_groups.items():
        if len(prices) >= 1:
            city_stats[city] = {
                'median_price_per_sqft': statistics.median(prices),
                'mean_price_per_sqft': statistics.mean(prices),
                'property_count': len(prices)
            }
            logger.debug(f"City {city}: {len(prices)} properties, "
                        f"median ${city_stats[city]['median_price_per_sqft']:.2f}/sqft")

    return city_stats


def analyze_property(prop, city_stats, logger):
    """
    Analyze a single property - simplified to 3 metrics:
    1. days_on_market
    2. city_median_price_per_sqft
    3. city_discount_pct
    """
    price_per_sqft = to_float(prop.get('price_per_sqft', 0))
    city = prop.get('city', '').strip()

    # Get city statistics
    city_data = city_stats.get(city, {})
    city_median = city_data.get('median_price_per_sqft', price_per_sqft)
    city_property_count = city_data.get('property_count', 1)

    # 1. Days on Market
    days_on_market = calculate_days_on_market(prop)

    # 2. City Median (just store it for reference)
    city_median_price_per_sqft = city_median

    # 3. City Discount Percentage
    # Negative = below median (good), Positive = above median
    if city_median > 0 and price_per_sqft > 0:
        city_discount_pct = ((price_per_sqft - city_median) / city_median) * 100
    else:
        city_discount_pct = 0

    # Prepare enrichment data
    now = datetime.now(timezone.utc)

    enrichment = {
        'days_on_market': days_on_market,
        'city_median_price_per_sqft': city_median_price_per_sqft,
        'city_discount_pct': round(city_discount_pct, 2),
        'city_property_count': city_property_count,
        'last_analyzed': now.isoformat(),
        'analysis_date': now.date().isoformat()
    }

    return enrichment


def calculate_days_on_market(prop):
    """Calculate days on market from first_seen_date"""
    first_seen = prop.get('first_seen_date')
    if not first_seen:
        return None

    try:
        # Parse ISO format date
        dt = datetime.fromisoformat(first_seen.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        return max(0, (now - dt).days)

    except Exception:
        return None


def update_property(property_id, enrichment, logger):
    """Update property with enrichment data"""
    try:
        # Build update expression
        update_parts = []
        expr_values = {}
        expr_names = {}

        for key, value in enrichment.items():
            safe_key = key.replace('_', '')
            update_parts.append(f"#{safe_key} = :{safe_key}")
            expr_names[f"#{safe_key}"] = key

            # Convert values for DynamoDB
            if value is None:
                expr_values[f":{safe_key}"] = None
            elif isinstance(value, (int, float)):
                expr_values[f":{safe_key}"] = to_dec(value)
            else:
                expr_values[f":{safe_key}"] = value

        update_expression = "SET " + ", ".join(update_parts)

        table.update_item(
            Key={'property_id': property_id, 'sort_key': 'META'},
            UpdateExpression=update_expression,
            ExpressionAttributeValues=expr_values,
            ExpressionAttributeNames=expr_names
        )

    except Exception as e:
        logger.error(f"Error updating property {property_id}: {str(e)}")
        raise


if __name__ == "__main__":
    # Local testing
    lambda_handler({}, None)
