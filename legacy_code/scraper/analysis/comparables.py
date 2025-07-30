"""
Comparable property selection and formatting for Lean v1.3.

This module implements simple filtering and formatting logic:
- Filter: ±30% price_per_sqm, ±25% size, ±10 years age
- Sort by price_per_sqm delta then size delta  
- Return ≤8 comps
- Format: "id | ppm2 | size | age | floor"
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class Comparable:
    """A comparable property for analysis."""
    id: str
    price_per_sqm: float
    size_sqm: float
    age_years: int
    floor: Optional[int] = None
    price_delta_pct: float = 0.0
    size_delta_sqm: float = 0.0


class ComparablesFilter:
    """Filter and format comparable properties for analysis."""
    
    def __init__(self, max_comparables: int = 8):
        """
        Initialize comparables filter.
        
        Args:
            max_comparables: Maximum number of comparables to return
        """
        self.max_comparables = max_comparables
    
    def find_comparables(self, target_property: Dict[str, Any], 
                        candidate_properties: List[Dict[str, Any]]) -> List[Comparable]:
        """
        Find and format comparable properties for the target.
        
        Filtering criteria:
        - Price per sqm: ±30% of target
        - Size: ±25% of target  
        - Age: ±10 years of target
        
        Args:
            target_property: Property to find comparables for
            candidate_properties: Pool of potential comparable properties
            
        Returns:
            List of up to 8 comparable properties, sorted by relevance
        """
        target_ppsm = target_property.get('price_per_sqm', 0)
        target_size = target_property.get('size_sqm', 0)
        target_age = target_property.get('building_age_years', 30)
        target_id = target_property.get('id', '')
        
        if not target_ppsm or not target_size:
            logger.warning(f"Target property {target_id} missing price_per_sqm or size_sqm")
            return []
        
        logger.info(f"Finding comparables for {target_id}: ppsm={target_ppsm}, size={target_size}, age={target_age}")
        
        # Calculate filtering thresholds
        ppsm_min = target_ppsm * 0.7   # -30%
        ppsm_max = target_ppsm * 1.3   # +30%
        size_min = target_size * 0.75  # -25%
        size_max = target_size * 1.25  # +25%
        age_min = max(0, target_age - 10)  # -10 years
        age_max = target_age + 10          # +10 years
        
        comparables = []
        
        for prop in candidate_properties:
            # Skip the target property itself
            if prop.get('id') == target_id:
                continue
            
            prop_ppsm = prop.get('price_per_sqm', 0)
            prop_size = prop.get('size_sqm', 0)
            prop_age = prop.get('building_age_years', 30)
            
            # Skip properties missing critical data
            if not prop_ppsm or not prop_size:
                continue
            
            # Apply filters
            if not (ppsm_min <= prop_ppsm <= ppsm_max):
                continue
            if not (size_min <= prop_size <= size_max):
                continue
            if not (age_min <= prop_age <= age_max):
                continue
            
            # Calculate deltas for sorting
            price_delta_pct = abs((prop_ppsm - target_ppsm) / target_ppsm * 100)
            size_delta_sqm = abs(prop_size - target_size)
            
            comparable = Comparable(
                id=prop.get('id', 'unknown'),
                price_per_sqm=prop_ppsm,
                size_sqm=prop_size,
                age_years=prop_age,
                floor=prop.get('floor'),
                price_delta_pct=price_delta_pct,
                size_delta_sqm=size_delta_sqm
            )
            
            comparables.append(comparable)
        
        # Sort by price delta first, then size delta
        comparables.sort(key=lambda c: (c.price_delta_pct, c.size_delta_sqm))
        
        # Return up to max_comparables
        selected_comps = comparables[:self.max_comparables]
        
        logger.info(f"Found {len(selected_comps)} comparables for {target_id} "
                   f"(filtered from {len(candidate_properties)} candidates)")
        
        return selected_comps
    
    def format_comparables_text(self, comparables: List[Comparable]) -> str:
        """
        Format comparables into text format for LLM consumption.
        
        Format: "id | ppm2 | size | age | floor"
        
        Args:
            comparables: List of comparable properties
            
        Returns:
            Formatted text string
        """
        if not comparables:
            return "No comparable properties found."
        
        lines = ["Comparable Properties:"]
        lines.append("ID | Price/sqm | Size | Age | Floor")
        lines.append("-" * 40)
        
        for comp in comparables:
            floor_str = str(comp.floor) if comp.floor is not None else "?"
            line = f"{comp.id} | ¥{comp.price_per_sqm:,.0f} | {comp.size_sqm:.1f}m² | {comp.age_years}y | {floor_str}F"
            lines.append(line)
        
        return "\n".join(lines)
    
    def format_comparables_json(self, comparables: List[Comparable]) -> List[Dict[str, Any]]:
        """
        Format comparables as JSON-serializable list.
        
        Args:
            comparables: List of comparable properties
            
        Returns:
            List of comparable dictionaries
        """
        return [
            {
                'id': comp.id,
                'price_per_sqm': comp.price_per_sqm,
                'size_sqm': comp.size_sqm,
                'age_years': comp.age_years,
                'floor': comp.floor,
                'price_delta_pct': round(comp.price_delta_pct, 1),
                'size_delta_sqm': round(comp.size_delta_sqm, 1)
            }
            for comp in comparables
        ]
    
    def calculate_market_stats(self, target_property: Dict[str, Any], 
                             comparables: List[Comparable]) -> Dict[str, Any]:
        """
        Calculate market statistics from comparables.
        
        Args:
            target_property: Target property data
            comparables: List of comparable properties
            
        Returns:
            Dictionary with market statistics
        """
        if not comparables:
            return {
                'num_comparables': 0,
                'comparable_price_variance': 1.0,
                'market_median_ppsm': target_property.get('price_per_sqm', 0),
                'target_vs_market_pct': 0.0
            }
        
        # Calculate price statistics
        comp_prices = [c.price_per_sqm for c in comparables]
        median_price = sorted(comp_prices)[len(comp_prices) // 2]
        mean_price = sum(comp_prices) / len(comp_prices)
        
        # Calculate price variance (coefficient of variation)
        if mean_price > 0:
            variance = sum((p - mean_price) ** 2 for p in comp_prices) / len(comp_prices)
            std_dev = variance ** 0.5
            price_variance = std_dev / mean_price
        else:
            price_variance = 1.0
        
        # Target vs market comparison
        target_ppsm = target_property.get('price_per_sqm', 0)
        if median_price > 0:
            target_vs_market = (target_ppsm - median_price) / median_price * 100
        else:
            target_vs_market = 0.0
        
        return {
            'num_comparables': len(comparables),
            'comparable_price_variance': round(price_variance, 3),
            'market_median_ppsm': round(median_price, 0),
            'market_mean_ppsm': round(mean_price, 0),
            'target_vs_market_pct': round(target_vs_market, 1)
        }


# Convenience functions
def find_and_format_comparables(target_property: Dict[str, Any], 
                               candidate_properties: List[Dict[str, Any]],
                               max_comps: int = 8) -> Tuple[List[Dict[str, Any]], str, Dict[str, Any]]:
    """
    Convenience function to find, format, and analyze comparables.
    
    Args:
        target_property: Property to find comparables for
        candidate_properties: Pool of potential comparable properties
        max_comps: Maximum number of comparables to return
        
    Returns:
        Tuple of (comparable_dicts, formatted_text, market_stats)
    """
    filter_engine = ComparablesFilter(max_comparables=max_comps)
    
    # Find comparables
    comparables = filter_engine.find_comparables(target_property, candidate_properties)
    
    # Format outputs
    comp_dicts = filter_engine.format_comparables_json(comparables)
    comp_text = filter_engine.format_comparables_text(comparables)
    market_stats = filter_engine.calculate_market_stats(target_property, comparables)
    
    return comp_dicts, comp_text, market_stats


def select_comparables(subject: Dict[str, Any], pool: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Return up to 8 comparable listings filtered by:
      ±30% price_per_sqm, ±25% size, ±10 years age (if age present).
    Sorted by absolute price_per_sqm delta then absolute size delta.
    
    Args:
        subject: Target property to find comparables for
        pool: Pool of potential comparable properties
        
    Returns:
        List of up to 8 comparable properties, sorted by relevance
    """
    subject_ppsm = subject.get('price_per_sqm', 0)
    subject_size = subject.get('size_sqm', 0) 
    subject_age = subject.get('building_age_years', 30)
    subject_id = subject.get('id', '')
    
    if not subject_ppsm or not subject_size:
        logger.warning(f"Subject property {subject_id} missing price_per_sqm or size_sqm")
        return []
    
    # Calculate filtering thresholds
    ppsm_min = subject_ppsm * 0.7   # -30%
    ppsm_max = subject_ppsm * 1.3   # +30%
    size_min = subject_size * 0.75  # -25%
    size_max = subject_size * 1.25  # +25%
    age_min = max(0, subject_age - 10)  # -10 years
    age_max = subject_age + 10          # +10 years
    
    comps = []
    
    for prop in pool:
        # Skip the subject property itself
        if prop.get('id') == subject_id:
            continue
            
        prop_ppsm = prop.get('price_per_sqm', 0)
        prop_size = prop.get('size_sqm', 0)
        prop_age = prop.get('building_age_years', 30)
        
        # Skip properties missing critical data
        if not prop_ppsm or not prop_size:
            continue
        
        # Apply filters
        if not (ppsm_min <= prop_ppsm <= ppsm_max):
            continue
        if not (size_min <= prop_size <= size_max):
            continue
        if not (age_min <= prop_age <= age_max):
            continue
        
        # Calculate deltas for sorting
        price_delta = abs(prop_ppsm - subject_ppsm)
        size_delta = abs(prop_size - subject_size)
        
        # Add property with sort keys
        comp_prop = prop.copy()
        comp_prop['_price_delta'] = price_delta
        comp_prop['_size_delta'] = size_delta
        comps.append(comp_prop)
    
    # Sort by absolute price_per_sqm delta first, then absolute size delta
    comps.sort(key=lambda c: (c['_price_delta'], c['_size_delta']))
    
    # Clean up sort keys and return up to 8
    for comp in comps:
        comp.pop('_price_delta', None)
        comp.pop('_size_delta', None)
    
    return comps[:8]


def format_comparable_lines(comps: List[Dict[str, Any]]) -> List[str]:
    """
    Format comparable properties into text lines for LLM consumption.
    
    Args:
        comps: List of comparable property dictionaries
        
    Returns:
        List of formatted strings, one per comparable
    """
    if not comps:
        return ["No comparable properties found."]
    
    lines = []
    for comp in comps:
        comp_id = comp.get('id', 'unknown')
        price_per_sqm = comp.get('price_per_sqm', 0)
        size_sqm = comp.get('size_sqm', 0)
        age_years = comp.get('building_age_years', 0)
        floor = comp.get('floor')
        
        floor_str = str(floor) if floor is not None else "?"
        line = f"{comp_id} | ¥{price_per_sqm:,.0f} | {size_sqm:.1f}m² | {age_years}y | {floor_str}F"
        lines.append(line)
    
    return lines


def enrich_property_with_comparables(target_property: Dict[str, Any], 
                                   candidate_properties: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Enrich a property with comparable data for scoring.
    
    Args:
        target_property: Property to enrich
        candidate_properties: Pool of potential comparable properties
        
    Returns:
        Enhanced property dict with comparable stats added
    """
    comp_dicts, comp_text, market_stats = find_and_format_comparables(
        target_property, candidate_properties
    )
    
    # Add comparable data to property
    enhanced_property = target_property.copy()
    enhanced_property.update({
        'comparables': comp_dicts,
        'comparables_text': comp_text,
        **market_stats  # num_comparables, comparable_price_variance, etc.
    })
    
    return enhanced_property