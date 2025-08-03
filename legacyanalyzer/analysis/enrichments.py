"""
Property enrichment functions for non-predictive quantitative analysis.
Adds various computed scores and metrics to property data.
"""

from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from decimal import Decimal


def to_float(value: Any) -> float:
    """Convert value to float, handling Decimal types from DynamoDB."""
    if isinstance(value, Decimal):
        return float(value)
    elif value is None:
        return 0.0
    return float(value)


def calculate_view_score(property_data: Dict[str, Any]) -> float:
    """
    Calculate view score based on floor height and obstruction.
    Base = 10 × (floor / building_floors), subtract 3 if view_obstructed.
    Clamp between 0 and 10.
    """
    floor = to_float(property_data.get('floor', 0))
    building_floors = to_float(property_data.get('building_floors', 0))
    view_obstructed = property_data.get('view_obstructed', False)
    
    if building_floors <= 0 or floor <= 0:
        return 0.0
    
    # Calculate base score from floor ratio
    base_score = 10.0 * (floor / building_floors)
    
    # Penalize if view obstructed
    if view_obstructed:
        base_score -= 3.0
    
    # Clamp between 0 and 10
    return max(0.0, min(10.0, base_score))


def calculate_light_score(property_data: Dict[str, Any]) -> float:
    """
    Calculate light score based on primary_light.
    南 (south) = 10, 東 (east) or 西 (west) = 7, 北 (north) = 3.
    Bonus +1 if light=True from vision analysis (max 10).
    """
    primary_light = property_data.get('primary_light', '')
    light_from_vision = property_data.get('light', False) or property_data.get('vision_light', False)
    
    # Base score from primary_light (Japanese values)
    if '南' in primary_light:
        base_score = 10.0
    elif '東' in primary_light or '西' in primary_light:
        base_score = 7.0
    elif '北' in primary_light:
        base_score = 3.0
    else:
        # Default if no primary_light data
        base_score = 5.0
    
    # Add bonus for good light from vision
    if light_from_vision and base_score < 10.0:
        base_score += 1.0
    
    return min(10.0, base_score)


def calculate_sunlight_score(light_score: float, view_score: float) -> float:
    """
    Combine light and view scores using weighted average.
    sunlight_score = (light_score * 0.6 + view_score * 0.4)
    """
    return round(light_score * 0.6 + view_score * 0.4, 1)






def calculate_earthquake_score(property_data: Dict[str, Any]) -> float:
    """
    Calculate earthquake resistance score based on building year.
    - Before 1981: score = 0
    - 1981-2000: score = 5
    - After 2000: score = 10
    """
    building_year = to_float(property_data.get('building_year', 0))
    
    if building_year < 1981:
        return 0.0
    elif building_year <= 2000:
        return 5.0
    else:
        return 10.0


def calculate_time_on_market_enrichments(property_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calculate days on market and negotiability score.
    - days_on_market = today - first_seen_date
    - negotiability_score: >90 days = 10, 30-90 = 5, <30 = 2
    """
    first_seen_date = property_data.get('first_seen_date')
    
    if not first_seen_date:
        return {
            'days_on_market': 0,
            'negotiability_score': 2.0
        }
    
    # Parse date and calculate days
    try:
        if isinstance(first_seen_date, str):
            first_seen = datetime.fromisoformat(first_seen_date.replace('Z', '+00:00'))
        else:
            first_seen = first_seen_date
            
        today = datetime.now()
        days_on_market = (today - first_seen).days
        
        # Calculate negotiability score
        if days_on_market > 90:
            negotiability_score = 10.0
        elif days_on_market >= 30:
            negotiability_score = 5.0
        else:
            negotiability_score = 2.0
            
        return {
            'days_on_market': days_on_market,
            'negotiability_score': negotiability_score
        }
        
    except Exception:
        return {
            'days_on_market': 0,
            'negotiability_score': 2.0
        }


def calculate_renovation_score(property_data: Dict[str, Any]) -> float:
    """
    Bonus: renovation_score = 10 if condition = original AND ward_discount_pct < -15
    """
    condition_category = property_data.get('condition_category', '')
    ward_discount_pct = to_float(property_data.get('ward_discount_pct', 0))
    
    if condition_category == 'original' and ward_discount_pct < -15:
        return 10.0
    return 0.0


def calculate_smallest_unit_penalty(property_data: Dict[str, Any], comparables: list) -> bool:
    """
    Check if unit is significantly smaller than all comparables.
    Returns True if smallest by more than 5 sqm margin.
    """
    if not comparables:
        return False
        
    unit_size = to_float(property_data.get('size_sqm', 0))
    if unit_size <= 0:
        return False
        
    comp_sizes = []
    for comp in comparables:
        comp_size = to_float(comp.get('size_sqm', 0))
        if comp_size > 0:
            comp_sizes.append(comp_size)
            
    if not comp_sizes:
        return False
        
    min_comp_size = min(comp_sizes)
    
    # Check if significantly smaller (5 sqm margin)
    return unit_size < (min_comp_size - 5)


def enrich_property(property_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main enrichment function that adds all computed fields to property data.
    Returns enriched property data dictionary.
    """
    enriched = property_data.copy()
    
    # 1. View Score
    enriched['view_score'] = calculate_view_score(property_data)
    
    # 2. Light Score
    enriched['light_score'] = calculate_light_score(property_data)
    
    # 3. Sunlight Score (combination of light and view)
    enriched['sunlight_score'] = calculate_sunlight_score(
        enriched['light_score'], 
        enriched['view_score']
    )
    
    # 4. (Removed efficiency ratio and balcony score)
    
    # 5. Earthquake Score
    enriched['earthquake_score'] = calculate_earthquake_score(property_data)
    
    # 6. Time on Market Enrichments
    time_data = calculate_time_on_market_enrichments(property_data)
    enriched['days_on_market'] = time_data['days_on_market']
    enriched['negotiability_score'] = time_data['negotiability_score']
    
    # 7. Bonus: Renovation Score
    enriched['renovation_score'] = calculate_renovation_score(property_data)
    
    # 8. Bonus: Smallest Unit Penalty
    comparables = property_data.get('comparables', [])
    enriched['smallest_unit_penalty'] = calculate_smallest_unit_penalty(property_data, comparables)
    
    return enriched


def batch_enrich_properties(properties: list) -> list:
    """
    Enrich multiple properties at once.
    Returns list of enriched property dictionaries.
    """
    return [enrich_property(prop) for prop in properties]