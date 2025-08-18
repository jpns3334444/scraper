import boto3

# Import centralized configuration
try:
    from config_loader import get_config
    config = get_config()
except ImportError:
    config = None  # Fallback to environment variables
import time
import json
import statistics
import logging
import os
from decimal import Decimal
from decimal_utils import to_float, to_dec
from datetime import datetime, timezone

dynamodb = boto3.resource('dynamodb', region_name=os.getenv('AWS_REGION', 'ap-northeast-1'))
table = dynamodb.Table(os.getenv('DYNAMODB_TABLE', 'tokyo-real-estate-ai-analysis-db'))

class SessionLogger:
    """Simple logger that automatically includes session_id in all messages"""
    
    def __init__(self, session_id, log_level='INFO'):
        self.session_id = session_id
        import logging
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
    session_id = event.get('session_id', 'property-analyzer-' + str(int(time.time())))
    logger = SessionLogger(session_id, log_level=os.getenv('LOG_LEVEL', 'INFO'))
    logger.info(f"Starting property analysis session: {session_id}")
    
    t0 = time.time()

    # 1️⃣ Pull every item where sort_key=='META'
    properties = scan_meta_items(logger)
    logger.info(f"Found {len(properties)} properties to analyze")
    
    # Check for property limit from event payload (--max-properties flag)
    property_limit = event.get('max_properties', 0)
    if property_limit > 0 and len(properties) > property_limit:
        properties = properties[:property_limit]
        logger.info(f"Limited to first {property_limit} properties (via --max-properties flag)")

    # 2️⃣ Compute ward medians (one pass)
    ward_stats = calc_ward_medians(properties, logger)
    logger.info(f"Calculated ward statistics for {len(ward_stats)} wards")

    # 3️⃣ Iterate + update
    errs = 0
    processed = 0
    
    for p in properties:
        try:
            enrich = analyze_one(p, ward_stats, properties)
            table.update_item(
                Key={'property_id': p['property_id'], 'sort_key': 'META'},
                UpdateExpression=build_update_expr(enrich),
                ExpressionAttributeValues=build_values(enrich),
                ExpressionAttributeNames=build_attr_names(enrich)
            )
            
            processed += 1
            if processed % 10 == 0:
                logger.info(f"Progress: {processed}/{len(properties)} properties processed")
                
        except Exception as e:
            logger.exception(f"{p['property_id']} failed: {str(e)}")
            errs += 1

    return {
        "statusCode": 200,
        "body": {
            "message": "Property analysis completed",
            "session_id": session_id,
            "properties_analyzed": len(properties),
            "errors": errs,
            "ward_medians_calculated": len(ward_stats),
            "duration_seconds": round(time.time() - t0, 1)
        }
    }

def scan_meta_items(logger):
    """Scan all items where sort_key == 'META'"""
    properties = []
    
    try:
        response = table.scan(
            FilterExpression=boto3.dynamodb.conditions.Attr('sort_key').eq('META')
        )
        properties.extend(response['Items'])
        
        while 'LastEvaluatedKey' in response:
            response = table.scan(
                FilterExpression=boto3.dynamodb.conditions.Attr('sort_key').eq('META'),
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
            properties.extend(response['Items'])
            
    except Exception as e:
        logger.error(f"Error scanning DynamoDB: {str(e)}")
        raise
    
    return properties

def calc_ward_medians(properties, logger):
    """Calculate ward median prices and statistics"""
    ward_groups = {}
    
    for prop in properties:
        ward = prop.get('ward', '').strip()
        if not ward:
            continue
            
        price_per_sqm = to_float(prop.get('price_per_sqm', 0))
        if price_per_sqm <= 0:
            continue
            
        if ward not in ward_groups:
            ward_groups[ward] = []
        ward_groups[ward].append(price_per_sqm)
    
    ward_stats = {}
    for ward, prices in ward_groups.items():
        if len(prices) >= 1:  # Calculate median for any ward with properties
            ward_stats[ward] = {
                'median_price_per_sqm': statistics.median(prices),
                'property_count': len(prices),
                'mean_price_per_sqm': statistics.mean(prices)
            }
            logger.debug(f"Ward {ward}: {len(prices)} properties, median ¥{ward_stats[ward]['median_price_per_sqm']:,.0f}/sqm")
    
    return ward_stats

def analyze_one(prop, ward_stats, all_props):
    """Analyze a single property and compute all enrichment fields"""
    
    # Extract basic property data
    price_per_sqm = to_float(prop.get('price_per_sqm', 0))
    size_sqm = to_float(prop.get('size_sqm', 0))
    building_age_years = to_float(prop.get('building_age_years', 0))
    station_distance_minutes = to_float(prop.get('station_distance_minutes', 0))
    floor = to_float(prop.get('floor', 0))
    building_floors = to_float(prop.get('building_floors', 0))
    management_fee = to_float(prop.get('management_fee', 0))
    repair_reserve_fee = to_float(prop.get('repair_reserve_fee', 0))
    price = to_float(prop.get('price', 0))
    ward = prop.get('ward', '').strip()
    address = prop.get('address', '').strip()
    
    # Initialize scoring components
    scoring_components = {}
    
    # Get ward statistics
    ward_data = ward_stats.get(ward, {})
    ward_median = ward_data.get('median_price_per_sqm', price_per_sqm)
    ward_property_count = ward_data.get('property_count', 1)
    
    # Calculate ward discount
    ward_discount_pct = (price_per_sqm - ward_median) / ward_median if ward_median > 0 else 0
    
    # 4.1 Ward Discount (0-35 pts)
    if ward_discount_pct >= 0:
        ward_discount_score = 0
    else:
        # New cap: -21% or deeper hits the 35-pt ceiling
        # Slope unchanged (25 pts at -15%)
        ward_discount_score = int(round(min(35, abs(ward_discount_pct) * 166.7)))
    scoring_components['ward_discount'] = ward_discount_score
    
    # 4.2 Building Discount (0-10 pts)
    building_discount_score = calc_building_discount(prop, properties_cache=all_props)
    scoring_components['building_discount'] = building_discount_score
    
    # 4.3 Comps Consistency (0-10 pts)
    comps_consistency_score = calc_comps_consistency(prop, all_props)
    scoring_components['comps_consistency'] = comps_consistency_score
    
    # 4.4 Condition (0-7 pts)
    if building_age_years <= 5:
        condition_score = 7
    elif building_age_years <= 10:
        condition_score = 6
    elif building_age_years <= 20:
        condition_score = 4
    elif building_age_years <= 30:
        condition_score = 2
    else:
        condition_score = 0
    scoring_components['condition'] = condition_score
    
    # 4.5 Size Efficiency (0-4 pts)
    if 40 <= size_sqm <= 90:
        size_efficiency_score = 4
    elif (30 <= size_sqm < 40) or (90 < size_sqm <= 110):
        size_efficiency_score = 2
    else:
        size_efficiency_score = 0
    scoring_components['size_efficiency'] = size_efficiency_score
    
    # 4.6 Carry Cost (0-4 pts)
    monthly_fees = management_fee + repair_reserve_fee
    price_man_en = to_float(prop.get('price', 0))
    carry_cost_score = calculate_carry_cost_score(monthly_fees, price_man_en)
    scoring_components['carry_cost'] = carry_cost_score
    
    # 4.7 Price Cut (0-5 pts)
    price_cut_pct = to_float(prop.get('price_cut_pct', 0.0)) or 0.0
    if price_cut_pct >= 15:
        price_cut_score = 5
    elif price_cut_pct >= 8:
        price_cut_score = 3
    elif price_cut_pct >= 3:
        price_cut_score = 1
    else:
        price_cut_score = 0
    scoring_components['price_cut'] = price_cut_score
    
    # 4.8 Renovation Potential (0-5 pts)
    condition_rating = prop.get('condition', 3)  # Assume 1-5 scale
    if condition_rating <= 2 and ward_discount_pct <= -0.10:
        renovation_score = 5
    elif condition_rating <= 2:
        renovation_score = 3
    else:
        renovation_score = 0
    scoring_components['renovation_potential'] = renovation_score
    
    # 4.9 Access (0-5 pts)
    if station_distance_minutes <= 5:
        access_score = 5
    elif station_distance_minutes >= 20:
        access_score = 0
    else:
        access_score = int(round(5 - 0.25 * (station_distance_minutes - 5)))
    scoring_components['access'] = access_score
    
    # 4.10 Vision Positive (0-5 pts) & Negative (-5→0 pts)
    view_score = to_float(prop.get('view_score', 0))
    view_obstructed = prop.get('view_obstructed', False)
    
    vision_positive = min(5, int(round(view_score)))
    vision_negative = -2 if view_obstructed else 0
    scoring_components['vision_positive'] = vision_positive
    scoring_components['vision_negative'] = vision_negative
    
    # 4.11 Data Quality Penalty (-8→0 pts)
    critical_fields = ['price_per_sqm', 'size_sqm', 'station_distance_minutes',
                      'building_age_years', 'floor', 'building_floors', 'primary_light']
    missing = sum(1 for f in critical_fields if prop.get(f) in (None, ''))
    data_quality_penalty = -2 * min(4, missing)
    scoring_components['data_quality_penalty'] = data_quality_penalty
    
    # 4.12 Overstated Discount Penalty (-8→0 pts)
    penalty = 0
    if size_sqm < 20 or size_sqm > 120:
        penalty -= 4
    if building_age_years >= 40:
        penalty -= 4
    overstated_discount_penalty = penalty
    scoring_components['overstated_discount_penalty'] = overstated_discount_penalty
    
    # Calculate final scores
    base_score = sum([
        ward_discount_score, building_discount_score, comps_consistency_score,
        condition_score, size_efficiency_score, carry_cost_score
    ])
    
    addon_score = sum([
        price_cut_score, renovation_score, access_score, vision_positive
    ])
    
    adjustment_score = sum([
        vision_negative, data_quality_penalty, overstated_discount_penalty
    ])
    
    final_score = max(0, min(100, base_score + addon_score + adjustment_score))
    
    # Determine verdict
    if final_score >= 50 and ward_discount_pct <= -0.10:
        verdict = 'BUY_CANDIDATE'
    elif 35 <= final_score < 50 or -0.10 < ward_discount_pct <= -0.05:
        verdict = 'WATCH'
    else:
        verdict = 'REJECT'
    
    # Calculate enrichment fields
    light_score = calculate_light_score(prop)
    sunlight_score = calculate_sunlight_score(prop)
    earthquake_score = calculate_earthquake_score(prop)
    days_on_market = calculate_days_on_market(prop)
    negotiability_score = calculate_negotiability_score(prop)
    # Get properties in same building for smallest unit calculation
    props_in_building = [p for p in all_props if p.get('address', '').strip() == address]
    is_smallest_unit = calculate_is_smallest_unit(prop, props_in_building)
    
    # Prepare enrichment data
    now = datetime.now(timezone.utc)
    enrichment = {
        'base_score': base_score,
        'addon_score': addon_score,
        'adjustment_score': adjustment_score,
        'final_score': final_score,
        'verdict': verdict,
        'scoring_components': scoring_components,
        'ward_median_price_per_sqm': ward_median,
        'ward_property_count': ward_property_count,
        'ward_discount_pct': ward_discount_pct * 100,  # Convert to percentage
        'num_ward_properties': ward_property_count,
        'view_score': view_score,
        'light_score': light_score,
        'sunlight_score': sunlight_score,
        'earthquake_score': earthquake_score,
        'days_on_market': days_on_market,
        'negotiability_score': negotiability_score,
        'renovation_score': renovation_score,
        'smallest_unit_penalty': is_smallest_unit,
        'last_analyzed': now.isoformat(),
        'analysis_date': now.date().isoformat()
    }
    
    return enrichment

def calc_building_discount(prop, properties_cache=None):
    """Calculate building discount score (0-10 pts)"""
    if properties_cache is None:
        # In a real implementation, we'd cache this or pass it down
        # For now, we'll do a simplified calculation
        return 0
    
    address = prop.get('address', '').strip()
    price_per_sqm = to_float(prop.get('price_per_sqm', 0))
    size_sqm = to_float(prop.get('size_sqm', 0))
    
    # Find other properties in same building with similar size (±20%)
    same_building = [p for p in properties_cache 
                    if p.get('address', '').strip() == address and 
                    p['property_id'] != prop['property_id'] and
                    0.8 * size_sqm <= to_float(p.get('size_sqm', 0)) <= 1.2 * size_sqm]
    
    if len(same_building) == 0:
        return 5  # info-vacuum bonus
    
    building_prices = [to_float(p.get('price_per_sqm', 0)) for p in same_building 
                      if to_float(p.get('price_per_sqm', 0)) > 0]
    
    if len(building_prices) < 1:
        return 5  # info-vacuum bonus
    
    building_median = statistics.median(building_prices)
    if building_median <= 0:
        return 0
        
    discount_pct = (price_per_sqm - building_median) / building_median
    
    if discount_pct >= 0:
        return 0
    elif discount_pct <= -0.20:
        return 10
    else:
        return min(10, int(round(abs(discount_pct) * 50)))

def calculate_carry_cost_score(monthly_fees: float, price_man_en: float) -> int:
    """Calculate carry cost score based on monthly fees as percentage of price"""
    price_yen = price_man_en * 10_000
    ratio = (monthly_fees / price_yen) if price_yen > 0 else 0
    if ratio <= 0.001:       # ≤0.1 % / month
        return 4
    elif ratio <= 0.002:     # ≤0.2 %
        return 2
    else:
        return 0

def calc_comps_consistency(prop, all_props):
    """Calculate comparables consistency score (0-10 pts)"""
    ward = prop.get('ward','').strip()
    size = to_float(prop.get('size_sqm',0))
    if size <= 0 or not ward:
        return 0
    comps = [to_float(x.get('price_per_sqm',0)) for x in all_props
             if x.get('ward','').strip()==ward
             and 0.8*size <= to_float(x.get('size_sqm',0)) <= 1.2*size
             and x.get('property_id') != prop.get('property_id')
             and to_float(x.get('price_per_sqm',0)) > 0]
    if len(comps) < 2: return 0
    cv = statistics.pstdev(comps) / statistics.mean(comps)
    # cv   0.00 →10 pts
    # cv ≥ 0.30 → 0 pts
    score = int(round(max(0.0, min(1.0, (0.30 - cv) / 0.30)) * 10))
    return score

def normalize_light(s):
    """Normalize Japanese and English light directions"""
    s = (s or '').strip().lower()
    jp_to_en = {'南':'south','南東':'southeast','南西':'southwest','東':'east','西':'west','北':'north'}
    return jp_to_en.get(s, s)

def calculate_light_score(prop):
    """Calculate light score based on primary_light direction"""
    primary_light = normalize_light(prop.get('primary_light'))
    mapping = {'south':10,'southeast':9,'southwest':8,'east':7,'west':6,'north':3}
    return mapping.get(primary_light, 5)

def calculate_sunlight_score(prop):
    """Calculate sunlight score as weighted combo of light direction and view"""
    light_component = 0.6 * calculate_light_score(prop)
    view_component = 0.4 * min(10, max(0, to_float(prop.get('view_score', 0))))
    return min(10, round(light_component + view_component))

def calculate_earthquake_score(prop):
    """Calculate earthquake resistance score"""
    building_age = to_float(prop.get('building_age_years', 0))
    
    if building_age <= 10:
        return 10
    elif building_age <= 20:
        return 8
    elif building_age <= 30:
        return 6
    elif building_age <= 40:
        return 4
    else:
        return 2

def parse_iso(dt):
    try:
        # Parse the datetime string
        parsed_dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
        # Ensure it's timezone-aware (convert to UTC if naive)
        if parsed_dt.tzinfo is None:
            parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
        return parsed_dt
    except Exception:
        return None

def calculate_days_on_market(prop):
    """Calculate days on market from first_seen_date"""
    first_seen = prop.get('first_seen_date')
    if first_seen:
        dt = parse_iso(first_seen)
        if dt:
            # Ensure both datetimes are timezone-aware before subtraction
            now_utc = datetime.now(timezone.utc)
            return max(0, (now_utc - dt).days)
    return None  # unknown → let data_quality_penalty handle it

def calculate_negotiability_score(prop):
    """Calculate negotiability score"""
    days_on_market = calculate_days_on_market(prop)
    price_cut_pct = to_float(prop.get('price_cut_pct', 0.0)) or 0.0
    
    if days_on_market is None:
        base_score = 2  # Default when unknown
    else:
        base_score = min(10, days_on_market / 18)  # 180 days = 10 points
    
    cut_bonus = min(5, price_cut_pct / 3)  # 15% cut = 5 bonus points
    
    return min(10, base_score + cut_bonus)

def calculate_is_smallest_unit(prop, props_in_building):
    """Check if this is the smallest unit in the building"""
    size = to_float(prop.get('size_sqm', 0))
    others = [to_float(p.get('size_sqm', 0)) for p in props_in_building if p['property_id'] != prop['property_id']]
    return bool(others) and size > 0 and size <= min(others)

def build_update_expr(enrich):
    """Build DynamoDB UpdateExpression"""
    fields = []
    for key in enrich.keys():
        fields.append(f"#{key.replace('_', '')} = :{key.replace('_', '')}")
    
    return "SET " + ", ".join(fields)

def build_values(enrich):
    """Build ExpressionAttributeValues for DynamoDB"""
    values = {}
    for key, value in enrich.items():
        attr_key = f":{key.replace('_', '')}"
        
        # Convert to appropriate DynamoDB type
        if isinstance(value, bool):
            values[attr_key] = value          # leave as BOOL type
        elif isinstance(value, (int, float)):
            values[attr_key] = to_dec(value)
        elif isinstance(value, dict):
            # Convert dict values to Decimal
            converted_dict = {}
            for k, v in value.items():
                if isinstance(v, (int, float)):
                    converted_dict[k] = to_dec(v)
                else:
                    converted_dict[k] = v
            values[attr_key] = converted_dict
        else:
            values[attr_key] = value
    
    return values

def build_attr_names(enrich):
    """Build ExpressionAttributeNames for DynamoDB"""
    names = {}
    for key in enrich.keys():
        names[f"#{key.replace('_', '')}"] = key
    
    return names