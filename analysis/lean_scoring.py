"""
Deterministic scoring system for Lean v1.3 real estate analysis.

This module implements the complete scoring specification from LEAN_MIGRATIONPROMPT_V1.3:
- Base components: Ward Discount (25), Building Discount (10), Comps Consistency (10), 
  Condition (7), Size Efficiency (4), Carry Cost (4)
- Add-ons: Price Cut (5), Renovation Potential (5), Access (5)
- Adjustments: vision_positive (+0..+5), vision_negative (0..-5), 
  data_quality_penalty (0..-8), overstated_discount_penalty (0..-8)
- Gating: BUY_CANDIDATE, WATCH, REJECT based on final_score and ward_discount_pct

Exact implementation per migration spec Sections 3-4.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class Verdict(Enum):
    """Investment verdicts based on final score and gating rules per Lean v1.3 Section 3.6."""
    BUY_CANDIDATE = "BUY_CANDIDATE"  # final_score ≥75 AND ward_discount_pct ≤ -12% AND dq_penalty ≥ -4
    WATCH = "WATCH"  # final_score 60-74 OR ward_discount between -8% and -11.99%  
    REJECT = "REJECT"  # Everything else


@dataclass
class ScoringComponents:
    """Complete breakdown of scoring components per Lean v1.3."""
    # Base components (direct point values as per spec)
    ward_discount: float = 0.0        # max 25 points
    building_discount: float = 0.0    # max 10 points
    comps_consistency: float = 0.0    # max 10 points
    condition: float = 0.0            # max 7 points
    size_efficiency: float = 0.0      # max 4 points
    carry_cost: float = 0.0           # max 4 points
    
    # Add-on components (max 5 points each, 15 total)
    price_cut: float = 0.0
    renovation_potential: float = 0.0
    access: float = 0.0
    
    # Adjustments (can be positive or negative)
    vision_positive: float = 0.0      # +0..+5
    vision_negative: float = 0.0      # 0..-5
    data_quality_penalty: float = 0.0 # 0..-8
    overstated_discount_penalty: float = 0.0  # 0..-8
    
    # Calculated scores
    base_score: float = 0.0           # sum of base components (max 60)
    addon_score: float = 0.0          # sum of add-ons (max 15)
    adjustment_score: float = 0.0     # sum of adjustments
    final_score: float = 0.0          # clamped 0-100
    
    # Derived metrics for gating
    ward_discount_pct: float = 0.0    # For gating rules (negative = discount)
    
    # Data quality flag
    data_quality_issue: bool = False
    
    # Final verdict
    verdict: Verdict = Verdict.REJECT


def linear_points(value: float, start: float, end: float, max_points: int) -> float:
    """
    Map value from start (0 pts) to end (max_points).
    If value beyond end in direction of improvement -> max_points.
    """
    if start == end:
        return 0.0
    if value <= end:
        return float(max_points)
    if value >= start:
        return 0.0
    frac = (start - value) / (start - end)
    return frac * max_points


def compute_base_and_adjustments(listing: Dict[str, Any],
                                 ward_median_ppm2: Optional[float],
                                 comps: List[Dict[str, Any]],
                                 vision: Dict[str, Any],
                                 previous_price: Optional[int]) -> Dict[str, Any]:
    """
    Core scoring function implementing exact Lean v1.3 specification.
    
    Args:
        listing: Property data dict with required fields
        ward_median_ppm2: Ward median price per sqm (None if missing)
        comps: List of comparable properties (≤8)
        vision: Vision analysis dict with condition_category, damage_tokens, etc.
        previous_price: Previous price for price cut calculation (None if unavailable)
        
    Returns:
        Dict with keys:
        - base_score: int (sum of base components)
        - final_score: int (base + addons + adjustments, clamped 0-100)
        - components: dict breakdown
        - ward_discount_pct: float (negative = discount)
        - dq_penalty: int (negative)
        - data_quality_issue: bool
        - verdict: str (BUY_CANDIDATE/WATCH/REJECT)
    """
    # Initialize components
    components = ScoringComponents()
    
    # Extract key fields
    price_per_sqm = listing.get('price_per_sqm', 0)
    current_price = listing.get('price', 0)  # ETL normalizes raw price to 'price' field
    total_sqm = listing.get('total_sqm', listing.get('size_sqm', 0))
    building_age = listing.get('building_age_years', 0)
    
    # === BASE COMPONENTS (Section 3.2) ===
    
    # 1. Ward Discount (25 points)
    # Linear interpolation: 0 pts at discount ≥ 0%; 25 pts at discount ≤ -20%
    if ward_median_ppm2 and ward_median_ppm2 > 0 and price_per_sqm > 0:
        # Additional safety check to prevent division by zero
        if ward_median_ppm2 == 0:
            components.ward_discount = 0.0
            components.ward_discount_pct = 0.0
            components.data_quality_issue = True
        else:
            discount_pct = (price_per_sqm - ward_median_ppm2) / ward_median_ppm2
            if discount_pct >= 0:
                components.ward_discount = 0.0  # No discount or premium
            elif discount_pct <= -0.2:
                components.ward_discount = 25.0  # 20%+ discount gets full points
            else:
                # Linear between 0 and -20%
                components.ward_discount = 25.0 * abs(discount_pct) / 0.2
            
            components.ward_discount_pct = discount_pct * 100  # For gating
    else:
        components.ward_discount = 0.0
        components.ward_discount_pct = 0.0
        components.data_quality_issue = True
    
    # 2. Building Discount (10 points)  
    # Linear 0→10 at ≤ -10%; else 0 (no building data available yet in v1.3)
    building_median = listing.get('building_median_price_per_sqm')
    if building_median and building_median > 0 and price_per_sqm > 0:
        building_discount_pct = (price_per_sqm - building_median) / building_median
        if building_discount_pct >= 0:
            components.building_discount = 0.0
        elif building_discount_pct <= -0.1:
            components.building_discount = 10.0
        else:
            components.building_discount = 10.0 * abs(building_discount_pct) / 0.1
    else:
        components.building_discount = 0.0
    
    # 3. Comps Consistency (10 points)
    # If ≥4 comps and median(comps_ppm2) ≥ subject_ppm2 * 1.05 ⇒ 10
    # Else scale = clamp(((median_comp_ppm2 - subject_ppm2) / (0.05 * subject_ppm2)) * 10, 0, 10)
    if len(comps) >= 4 and price_per_sqm > 0:
        comp_ppm2_values = [
            comp.get('price_per_sqm', 0) for comp in comps 
            if comp.get('price_per_sqm', 0) > 0
        ]
        
        if comp_ppm2_values:
            comp_ppm2_values.sort()
            n = len(comp_ppm2_values)
            if n % 2 == 0:
                median_comp_ppm2 = (comp_ppm2_values[n//2 - 1] + comp_ppm2_values[n//2]) / 2
            else:
                median_comp_ppm2 = comp_ppm2_values[n//2]
            
            if median_comp_ppm2 >= price_per_sqm * 1.05:
                components.comps_consistency = 10.0
            else:
                scale = ((median_comp_ppm2 - price_per_sqm) / (0.05 * price_per_sqm)) * 10
                components.comps_consistency = max(0.0, min(10.0, scale))
        else:
            components.comps_consistency = 0.0
    else:
        components.comps_consistency = 0.0
    
    # 4. Condition (7 points)
    # Category mapping: modern=7, partial=5, dated=3, original=1
    # If any damage token -> subtract 1 (floor 0)
    condition_category = vision.get('condition_category', 'dated')
    damage_tokens = vision.get('damage_tokens', [])
    
    category_scores = {
        'modern': 7,
        'partial': 5,
        'dated': 3,
        'original': 1
    }
    
    base_condition = category_scores.get(condition_category, 3)
    if damage_tokens:
        base_condition -= 1
    components.condition = max(0.0, float(base_condition))
    
    # 5. Size Efficiency (4 points)
    # If 20 ≤ size ≤ 120 => 4 else 0
    if 20 <= total_sqm <= 120:
        components.size_efficiency = 4.0
    else:
        components.size_efficiency = 0.0
    
    # 6. Carry Cost (4 points)
    # If ratio = (hoa_fee+repair_fund)/(price/100) ≤0.12 =>4; 0.12–0.18 linear to 1; >0.18 =>0
    # If fees missing => assume 4
    hoa_fee = listing.get('hoa_fee_yen')
    repair_fund = listing.get('repair_fund_yen')
    
    if hoa_fee is None and repair_fund is None:
        components.carry_cost = 4.0  # Missing fees => assume best case
    elif current_price > 0:
        total_fees = (hoa_fee or 0) + (repair_fund or 0)
        ratio = total_fees / (current_price / 100)
        
        if ratio <= 0.12:
            components.carry_cost = 4.0
        elif ratio >= 0.18:
            components.carry_cost = 0.0
        else:
            # Linear interpolation between 0.12 and 0.18
            components.carry_cost = 4.0 - (3.0 * (ratio - 0.12) / (0.18 - 0.12))
    else:
        components.carry_cost = 0.0
    
    # Sum base components (max 60 points: 25+10+10+7+4+4)
    components.base_score = (
        components.ward_discount + components.building_discount + 
        components.comps_consistency + components.condition +
        components.size_efficiency + components.carry_cost
    )
    
    # === ADD-ON COMPONENTS (Section 3.3) ===
    
    # 1. Price Cut (5 points)
    # If previous_price and ((previous - current)/previous) ≥10% =>5; ≥5% =>3; else 0
    if previous_price and previous_price > 0 and current_price > 0:
        cut_pct = (previous_price - current_price) / previous_price
        if cut_pct >= 0.10:
            components.price_cut = 5.0
        elif cut_pct >= 0.05:
            components.price_cut = 3.0
        else:
            components.price_cut = 0.0
    else:
        components.price_cut = 0.0
    
    # 2. Renovation Potential (5 points)
    # If reno_needed flag true AND ward_discount ≤ -15% => 5 else 0
    reno_needed = listing.get('reno_needed', False)
    if reno_needed and components.ward_discount_pct <= -15.0:
        components.renovation_potential = 5.0
    else:
        components.renovation_potential = 0.0
    
    # 3. Access (5 points)
    # distance ≤500m =>5; ≤900m =>3; else 0; missing =>3
    distance_station_m = listing.get('distance_station_m')
    if distance_station_m is None:
        components.access = 3.0
    elif distance_station_m <= 500:
        components.access = 5.0
    elif distance_station_m <= 900:
        components.access = 3.0
    else:
        components.access = 0.0
    
    components.addon_score = (
        components.price_cut + components.renovation_potential + components.access
    )
    
    # === ADJUSTMENTS (Section 3.4) ===
    
    # 1. Vision Positive (+0..+5)
    # Exceptional combo: modern + strong light + good view
    # Stub: if condition=modern & light=True
    light = vision.get('light', False)
    if condition_category == 'modern' and light:
        components.vision_positive = 5.0
    else:
        components.vision_positive = 0.0
    
    # 2. Vision Negative (0..-5)
    # Severe defect (damage tokens ≥2 or "stain" + "mold" etc.)
    num_damage = len(damage_tokens)
    has_stain = any('stain' in token.lower() for token in damage_tokens)
    has_mold = any('mold' in token.lower() for token in damage_tokens)
    
    if num_damage >= 2 or (has_stain and has_mold):
        components.vision_negative = -5.0
    elif num_damage >= 1:
        components.vision_negative = -2.0
    else:
        components.vision_negative = 0.0
    
    # 3. Data Quality Penalty (0..-8) per Section 4
    dq_penalty = 0
    
    # Missing ward median: -4
    if not ward_median_ppm2 or ward_median_ppm2 == 0:
        dq_penalty += 4
        
    # <4 comps AND no building discount: -3  
    if len(comps) < 4 and (not building_median or building_median == 0):
        dq_penalty += 3
        
    # Critical null (price OR size): -6
    if not current_price or current_price == 0 or not total_sqm or total_sqm == 0:
        dq_penalty += 6
        components.data_quality_issue = True
    
    components.data_quality_penalty = -min(dq_penalty, 8)
    
    # 4. Overstated Discount Penalty (0..-8)
    # If discount explained mostly by being smallest size among comps or oldest
    overstated_penalty = 0
    
    if comps:
        # Check if subject significantly smaller than comparables
        comp_sizes = [comp.get('total_sqm', comp.get('size_sqm', 0)) 
                     for comp in comps if comp.get('total_sqm', comp.get('size_sqm', 0)) > 0]
        
        if comp_sizes and total_sqm > 0:
            min_comp_size = min(comp_sizes)
            if total_sqm < min_comp_size - 5:  # Small epsilon = 5 sqm
                overstated_penalty += 5
        
        # Check if subject significantly older than comparables
        comp_ages = [comp.get('building_age_years', 0) 
                    for comp in comps if comp.get('building_age_years', 0) > 0]
        
        if comp_ages and building_age > 0:
            max_comp_age = max(comp_ages)
            if building_age > max_comp_age:
                overstated_penalty += 5
    
    components.overstated_discount_penalty = -min(overstated_penalty, 8)
    
    components.adjustment_score = (
        components.vision_positive + components.vision_negative + 
        components.data_quality_penalty + components.overstated_discount_penalty
    )
    
    # === FINAL SCORE (Section 3.5) ===
    # base_score + addon_score + adjustment_score, clamped 0-100
    raw_final = components.base_score + components.addon_score + components.adjustment_score
    components.final_score = max(0, min(100, raw_final))
    
    # Force REJECT if critical data missing (price OR size null)
    if not current_price or current_price == 0 or not total_sqm or total_sqm == 0:
        components.final_score = 0
    
    # === VERDICT (Section 3.6) ===
    # BUY_CANDIDATE: final_score ≥75 AND ward_discount_pct ≤ -12% AND data_quality_penalty ≥ -4
    # WATCH: final_score 60–74 OR (ward_discount between -8% and -11.99%)
    # REJECT: Else
    
    if (components.final_score >= 75 and 
        components.ward_discount_pct <= -12 and 
        components.data_quality_penalty >= -4):
        components.verdict = Verdict.BUY_CANDIDATE
    elif (60 <= components.final_score <= 74 or 
          -11.99 <= components.ward_discount_pct <= -8):
        components.verdict = Verdict.WATCH
    else:
        components.verdict = Verdict.REJECT
    
    # Return result dict
    return {
        'base_score': int(components.base_score),
        'final_score': int(components.final_score),
        'components': {
            'ward_discount': components.ward_discount,
            'building_discount': components.building_discount,
            'comps_consistency': components.comps_consistency,
            'condition': components.condition,
            'size_efficiency': components.size_efficiency,
            'carry_cost': components.carry_cost,
            'price_cut': components.price_cut,
            'renovation_potential': components.renovation_potential,
            'access': components.access,
            'vision_positive': components.vision_positive,
            'vision_negative': components.vision_negative,
            'data_quality_penalty': components.data_quality_penalty,
            'overstated_discount_penalty': components.overstated_discount_penalty,
        },
        'ward_discount_pct': components.ward_discount_pct,
        'dq_penalty': int(components.data_quality_penalty),
        'data_quality_issue': components.data_quality_issue,
        'verdict': components.verdict.value
    }


class LeanScoring:
    """Deterministic scoring engine for real estate properties - Lean v1.3 compatible."""
    
    def calculate_score(self, property_data: Dict[str, Any]) -> ScoringComponents:
        """
        Calculate complete scoring breakdown for a property using Lean v1.3 spec.
        
        Args:
            property_data: Dictionary containing property attributes
            
        Returns:
            ScoringComponents with all calculations and final verdict
        """
        # Extract related data
        ward_median = property_data.get('ward_median_price_per_sqm')
        comparables = property_data.get('comparables', [])
        vision_analysis = property_data.get('vision_analysis', {})
        previous_price = property_data.get('previous_price')
        
        # Use the core scoring function
        result = compute_base_and_adjustments(
            property_data, ward_median, comparables, vision_analysis, previous_price
        )
        
        # Convert to ScoringComponents for compatibility
        components = ScoringComponents()
        components.base_score = result['base_score']
        components.final_score = result['final_score']
        components.ward_discount_pct = result['ward_discount_pct']
        components.data_quality_issue = result['data_quality_issue']
        components.verdict = Verdict(result['verdict'])
        
        # Set individual component values
        comp_dict = result['components']
        components.ward_discount = comp_dict['ward_discount']
        components.building_discount = comp_dict['building_discount']
        components.comps_consistency = comp_dict['comps_consistency']
        components.condition = comp_dict['condition']
        components.size_efficiency = comp_dict['size_efficiency']
        components.carry_cost = comp_dict['carry_cost']
        components.price_cut = comp_dict['price_cut']
        components.renovation_potential = comp_dict['renovation_potential']
        components.access = comp_dict['access']
        components.vision_positive = comp_dict['vision_positive']
        components.vision_negative = comp_dict['vision_negative']
        components.data_quality_penalty = comp_dict['data_quality_penalty']
        components.overstated_discount_penalty = comp_dict['overstated_discount_penalty']
        
        # Calculate derived scores
        components.addon_score = (
            components.price_cut + components.renovation_potential + components.access
        )
        components.adjustment_score = (
            components.vision_positive + components.vision_negative + 
            components.data_quality_penalty + components.overstated_discount_penalty
        )
        
        return components
    
    def format_score_report(self, components: ScoringComponents) -> str:
        """Format a detailed scoring report per Lean v1.3."""
        report = []
        report.append("=== Lean v1.3 Investment Score Analysis ===")
        report.append(f"Final Score: {components.final_score:.1f}/100")
        report.append(f"Verdict: {components.verdict.value}")
        report.append(f"Ward Discount: {components.ward_discount_pct:.1f}%")
        report.append("")
        
        report.append("Base Components (60 points max):")
        report.append(f"  Ward Discount:      {components.ward_discount:.1f}/25")
        report.append(f"  Building Discount:  {components.building_discount:.1f}/10")
        report.append(f"  Comps Consistency:  {components.comps_consistency:.1f}/10")
        report.append(f"  Condition:          {components.condition:.1f}/7")
        report.append(f"  Size Efficiency:    {components.size_efficiency:.1f}/4")
        report.append(f"  Carry Cost:         {components.carry_cost:.1f}/4")
        report.append(f"  Base Total: {components.base_score:.1f}/60")
        report.append("")
        
        report.append("Add-on Components (15 points max):")
        report.append(f"  Price Cut:           {components.price_cut:.1f}/5")
        report.append(f"  Renovation Potential: {components.renovation_potential:.1f}/5")
        report.append(f"  Access:              {components.access:.1f}/5")
        report.append(f"  Add-on Total: {components.addon_score:.1f}/15")
        report.append("")
        
        report.append("Adjustments:")
        report.append(f"  Vision Positive:     {components.vision_positive:+.1f}")
        report.append(f"  Vision Negative:     {components.vision_negative:+.1f}")
        report.append(f"  Data Quality Penalty: {components.data_quality_penalty:+.1f}")
        report.append(f"  Overstated Discount Penalty: {components.overstated_discount_penalty:+.1f}")
        report.append(f"  Adjustment Total: {components.adjustment_score:+.1f}")
        
        if components.data_quality_issue:
            report.append("")
            report.append("⚠️  Data Quality Issues Detected")
        
        return "\n".join(report)


# Convenience functions for backward compatibility
def score_property(property_data: Dict[str, Any]) -> Tuple[float, Verdict, str]:
    """
    Convenience function to score a single property using Lean v1.3.
    
    Args:
        property_data: Property attributes dictionary
        
    Returns:
        Tuple of (final_score, verdict, formatted_report)
    """
    scorer = LeanScoring()
    components = scorer.calculate_score(property_data)
    report = scorer.format_score_report(components)
    
    return components.final_score, components.verdict, report


def batch_score_properties(properties: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Score multiple properties and return sorted by score.
    
    Args:
        properties: List of property data dictionaries
        
    Returns:
        List of results sorted by score (highest first)
    """
    scorer = LeanScoring()
    results = []
    
    for prop in properties:
        components = scorer.calculate_score(prop)
        results.append({
            'property': prop,
            'score': components.final_score,
            'verdict': components.verdict,
            'components': components
        })
    
    # Sort by score descending
    results.sort(key=lambda x: x['score'], reverse=True)
    return results


# Legacy compatibility for existing tests
def get_verdict(score: float) -> Verdict:
    """Legacy function for backward compatibility - simplified thresholds."""
    if score >= 75:
        return Verdict.BUY_CANDIDATE
    elif score >= 60:
        return Verdict.WATCH
    else:
        return Verdict.REJECT


# Backward compatibility aliases
Verdict.STRONG_BUY = Verdict.BUY_CANDIDATE
Verdict.BUY = Verdict.BUY_CANDIDATE
Verdict.MODERATE_BUY = Verdict.WATCH
Verdict.HOLD = Verdict.WATCH
Verdict.PASS = Verdict.REJECT
Verdict.STRONG_PASS = Verdict.REJECT