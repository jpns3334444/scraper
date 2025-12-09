#!/usr/bin/env python3
"""
Property Analyzer Lambda - US market analysis
Calculates: price_per_acre, city_median_price_per_sqft, city_discount_pct
"""
import boto3
import time
import json
import statistics
import logging
import os
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
        if prices:
            city_stats[city] = {
                'median_price_per_sqft': statistics.median(prices),
                'property_count': len(prices)
            }

    return city_stats


def analyze_property(prop, city_stats, logger):
    """
    Analyze a single property:
    1. price_per_acre - price divided by lot size in acres
    2. city_median_price_per_sqft
    3. city_discount_pct
    """
    price = to_float(prop.get('price', 0))
    price_per_sqft = to_float(prop.get('price_per_sqft', 0))
    city = prop.get('city', '').strip()

    # Get city statistics
    city_data = city_stats.get(city, {})
    city_median = city_data.get('median_price_per_sqft', price_per_sqft)
    city_property_count = city_data.get('property_count', 1)

    # 1. Price per Acre
    price_per_acre = calculate_price_per_acre(prop, price)

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
        'price_per_acre': price_per_acre,
        'city_median_price_per_sqft': city_median_price_per_sqft,
        'city_discount_pct': round(city_discount_pct, 2),
        'city_property_count': city_property_count,
        'last_analyzed': now.isoformat(),
        'analysis_date': now.date().isoformat()
    }

    return enrichment


def calculate_price_per_acre(prop, price):
    """
    Calculate price per acre from lot size.
    Uses lot_size_acres if available, otherwise converts from lot_size_sqft.
    """
    if price <= 0:
        return None

    # 1. Use lot_size_acres if available
    lot_acres = to_float(prop.get('lot_size_acres', 0))
    if lot_acres > 0:
        return round(price / lot_acres, 2)

    # 2. Convert from lot_size_sqft (43560 sqft = 1 acre)
    lot_sqft = to_float(prop.get('lot_size_sqft', 0))
    if lot_sqft > 0:
        lot_acres = lot_sqft / 43560
        return round(price / lot_acres, 2)

    return None


def update_property(property_id, enrichment, logger):
    """Update property with enrichment data"""
    # Convert numeric values to Decimal for DynamoDB
    values = {}
    for k, v in enrichment.items():
        if isinstance(v, (int, float)):
            values[k] = to_dec(v)
        else:
            values[k] = v

    table.update_item(
        Key={'property_id': property_id, 'sort_key': 'META'},
        UpdateExpression="SET price_per_acre=:ppa, city_median_price_per_sqft=:cm, city_discount_pct=:cd, city_property_count=:cc, last_analyzed=:la, analysis_date=:ad",
        ExpressionAttributeValues={
            ':ppa': values.get('price_per_acre'),
            ':cm': values.get('city_median_price_per_sqft'),
            ':cd': values.get('city_discount_pct'),
            ':cc': values.get('city_property_count'),
            ':la': values.get('last_analyzed'),
            ':ad': values.get('analysis_date')
        }
    )


if __name__ == "__main__":
    # Local testing
    lambda_handler({}, None)
