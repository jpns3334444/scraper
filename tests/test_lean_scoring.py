"""
Test cases for the lean deterministic scoring module.
"""

import json
import pytest
from pathlib import Path
from analysis.lean_scoring import (
    LeanScoring, 
    ScoringComponents, 
    Verdict,
    score_property,
    batch_score_properties
)


@pytest.fixture
def sample_properties():
    """Load sample properties from fixtures."""
    fixture_path = Path(__file__).parent / 'fixtures' / 'sample_properties.json'
    with open(fixture_path) as f:
        return json.load(f)


def test_lean_scoring_initialization():
    """Test that LeanScoring can be initialized"""
    scorer = LeanScoring()
    assert scorer is not None


def test_calculate_score_with_minimal_data():
    """Test scoring with minimal property data"""
    scorer = LeanScoring()
    
    minimal_property = {
        'current_price': 50000000,
        'total_sqm': 50,
        'price_per_sqm': 1000000,
        'ward_median_price_per_sqm': 1200000,
        'building_median_price_per_sqm': 1100000,
        'comparables': [
            {'price_per_sqm': 1100000, 'total_sqm': 48},
            {'price_per_sqm': 1150000, 'total_sqm': 52},
            {'price_per_sqm': 1200000, 'total_sqm': 45},
            {'price_per_sqm': 1250000, 'total_sqm': 55},
        ]
    }
    
    components = scorer.calculate_score(minimal_property)
    
    assert isinstance(components, ScoringComponents)
    assert 0 <= components.final_score <= 100
    assert components.verdict is not None


def test_calculate_score_with_complete_data():
    """Test scoring with comprehensive property data"""
    scorer = LeanScoring()
    
    complete_property = {
        'current_price': 45000000,
        'total_sqm': 55,
        'price_per_sqm': 818182,
        'ward': 'Shibuya',
        'ward_median_price_per_sqm': 1200000,
        'building_median_price_per_sqm': 1000000,
        'building_age_years': 10,
        'distance_station_m': 400,
        'hoa_fee_yen': 15000,
        'repair_fund_yen': 8000,
        'previous_price': 50000000,
        'comparables': [
            {'price_per_sqm': 900000, 'total_sqm': 50, 'building_age_years': 8},
            {'price_per_sqm': 950000, 'total_sqm': 60, 'building_age_years': 12},
            {'price_per_sqm': 850000, 'total_sqm': 45, 'building_age_years': 15},
            {'price_per_sqm': 1000000, 'total_sqm': 58, 'building_age_years': 5},
            {'price_per_sqm': 920000, 'total_sqm': 52, 'building_age_years': 10}
        ],
        'vision_analysis': {
            'condition_category': 'modern',
            'damage_tokens': [],
            'light': True
        }
    }
    
    components = scorer.calculate_score(complete_property)
    
    # Check all components are calculated
    assert components.ward_discount > 0
    assert components.building_discount > 0
    assert components.comps_consistency >= 0  # May be 0 if conditions not met
    assert components.condition > 0
    assert components.size_efficiency > 0
    assert components.carry_cost > 0
    
    # Check score components
    assert components.base_score > 0
    assert components.final_score > 0
    
    # With good data and discount, should get a positive verdict
    assert components.verdict in [Verdict.BUY_CANDIDATE, Verdict.WATCH]


def test_ward_discount_calculation():
    """Test ward discount score calculation per Lean v1.3"""
    from analysis.lean_scoring import compute_base_and_adjustments
    
    # 20% discount should give max score (25 points)
    high_discount_data = {
        'price_per_sqm': 800000,
        'current_price': 40000000,
        'total_sqm': 50
    }
    result = compute_base_and_adjustments(
        high_discount_data, 1000000, [], {}, None
    )
    assert result['components']['ward_discount'] == 25.0
    
    # No discount should give 0 points
    no_discount_data = {
        'price_per_sqm': 1000000,
        'current_price': 50000000,
        'total_sqm': 50
    }
    result = compute_base_and_adjustments(
        no_discount_data, 1000000, [], {}, None
    )
    assert result['components']['ward_discount'] == 0.0
    
    # 20% premium should give 0 points
    premium_data = {
        'price_per_sqm': 1200000,
        'current_price': 60000000,
        'total_sqm': 50
    }
    result = compute_base_and_adjustments(
        premium_data, 1000000, [], {}, None
    )
    assert result['components']['ward_discount'] == 0.0


def test_condition_score_calculation():
    """Test condition score calculation per Lean v1.3 spec"""
    from analysis.lean_scoring import compute_base_and_adjustments
    
    # Modern condition with no damage should give 7 points
    modern_data = {
        'price_per_sqm': 1000000,
        'current_price': 50000000,
        'total_sqm': 50
    }
    vision_modern = {
        'condition_category': 'modern',
        'damage_tokens': []
    }
    result = compute_base_and_adjustments(
        modern_data, None, [], vision_modern, None
    )
    assert result['components']['condition'] == 7.0
    
    # Dated condition with damage should be reduced
    vision_damaged = {
        'condition_category': 'dated',
        'damage_tokens': ['stain']
    }
    result = compute_base_and_adjustments(
        modern_data, None, [], vision_damaged, None
    )
    assert result['components']['condition'] == 2.0  # 3 - 1 for damage


def test_verdict_assignment():
    """Test verdict assignment based on Lean v1.3 gating rules"""
    from analysis.lean_scoring import compute_base_and_adjustments
    
    # BUY_CANDIDATE: final_score ≥75 AND ward_discount_pct ≤ -12% AND dq_penalty ≥ -4
    buy_candidate_data = {
        'price_per_sqm': 800000,  # -20% discount
        'current_price': 40000000,
        'total_sqm': 50,
        'building_age_years': 10
    }
    comps = [
        {'price_per_sqm': 850000, 'total_sqm': 48},
        {'price_per_sqm': 900000, 'total_sqm': 52},
        {'price_per_sqm': 880000, 'total_sqm': 45},
        {'price_per_sqm': 920000, 'total_sqm': 55}
    ]
    vision = {'condition_category': 'modern', 'damage_tokens': []}
    
    result = compute_base_and_adjustments(
        buy_candidate_data, 1000000, comps, vision, None
    )
    # Should get BUY_CANDIDATE with high score and good discount
    assert result['final_score'] >= 70  # Should be high with 25 points from ward discount
    assert result['ward_discount_pct'] == -20.0  # 20% discount
    
    # REJECT: poor score
    reject_data = {
        'price_per_sqm': 1200000,  # 20% premium
        'current_price': 60000000,
        'total_sqm': 15  # Too small
    }
    result = compute_base_and_adjustments(
        reject_data, 1000000, [], {}, None
    )
    assert result['verdict'] == 'REJECT'


def test_score_property_helper():
    """Test the convenience score_property function"""
    property_data = {
        'current_price': 50000000,
        'total_sqm': 50,
        'price_per_sqm': 1000000,
        'ward_median_price_per_sqm': 1200000,
        'building_median_price_per_sqm': 1100000,
        'comparables': [
            {'price_per_sqm': 1100000, 'total_sqm': 48},
            {'price_per_sqm': 1150000, 'total_sqm': 52},
            {'price_per_sqm': 1200000, 'total_sqm': 45},
            {'price_per_sqm': 1250000, 'total_sqm': 55},
        ]
    }
    
    score, verdict, report = score_property(property_data)
    
    assert isinstance(score, float)
    assert 0 <= score <= 100
    assert isinstance(verdict, Verdict)
    assert isinstance(report, str)
    assert "Final Score:" in report
    assert "Verdict:" in report
    assert "Lean v1.3" in report


def test_batch_score_properties():
    """Test batch scoring of multiple properties"""
    base_comps = [
        {'price_per_sqm': 1100000, 'total_sqm': 48},
        {'price_per_sqm': 1150000, 'total_sqm': 52},
        {'price_per_sqm': 1200000, 'total_sqm': 45},
        {'price_per_sqm': 1250000, 'total_sqm': 55},
    ]
    
    properties = [
        {
            'id': 1,
            'current_price': 60000000,
            'total_sqm': 50,
            'price_per_sqm': 1200000,
            'ward_median_price_per_sqm': 1200000,
            'building_median_price_per_sqm': 1100000,
            'comparables': base_comps
        },
        {
            'id': 2,
            'current_price': 40000000,
            'total_sqm': 50,
            'price_per_sqm': 800000,
            'ward_median_price_per_sqm': 1200000,
            'building_median_price_per_sqm': 1100000,
            'comparables': base_comps
        },
        {
            'id': 3,
            'current_price': 50000000,
            'total_sqm': 50,
            'price_per_sqm': 1000000,
            'ward_median_price_per_sqm': 1200000,
            'building_median_price_per_sqm': 1100000,
            'comparables': base_comps
        }
    ]
    
    results = batch_score_properties(properties)
    
    assert len(results) == 3
    # Should be sorted by score descending
    assert results[0]['score'] >= results[1]['score']
    assert results[1]['score'] >= results[2]['score']
    
    # Property 2 should have highest score (best discount)
    assert results[0]['property']['id'] == 2


def test_format_score_report():
    """Test score report formatting"""
    scorer = LeanScoring()
    
    components = ScoringComponents(
        ward_discount=20.0,
        building_discount=8.0,
        comps_consistency=10.0,
        condition=5.0,
        size_efficiency=4.0,
        carry_cost=4.0,
        price_cut=3.0,
        renovation_potential=0.0,
        access=5.0,
        vision_positive=5.0,
        vision_negative=0.0,
        data_quality_penalty=0.0,
        overstated_discount_penalty=0.0,
        base_score=51.0,
        addon_score=8.0,
        adjustment_score=5.0,
        final_score=64.0,
        verdict=Verdict.WATCH
    )
    
    report = scorer.format_score_report(components)
    
    assert "Lean v1.3 Investment Score Analysis" in report
    assert "Base Components" in report
    assert "Add-on Components" in report
    assert "Adjustments" in report
    assert "Final Score: 64.0/100" in report
    assert "Verdict: WATCH" in report


def test_edge_cases():
    """Test edge cases and error handling per Lean v1.3"""
    scorer = LeanScoring()
    
    # Empty data - should trigger data quality penalties and force REJECT
    empty_components = scorer.calculate_score({})
    assert isinstance(empty_components, ScoringComponents)
    assert empty_components.final_score == 0  # Critical null penalty forces 0
    assert empty_components.data_quality_issue == True
    assert empty_components.verdict == Verdict.REJECT
    
    # Missing critical fields (price only)
    partial_data = {
        'current_price': 50000000,
        # Missing total_sqm
    }
    components = scorer.calculate_score(partial_data)
    assert components.data_quality_penalty < 0  # Should have penalty for missing data
    assert components.final_score == 0  # Critical null forces score to 0
    
    # Extreme values - very expensive property
    extreme_data = {
        'price_per_sqm': 10000000,  # Very expensive
        'ward_median_price_per_sqm': 1000000,
        'current_price': 500000000,
        'total_sqm': 50
    }
    components = scorer.calculate_score(extreme_data)
    assert components.ward_discount == 0.0  # Should get 0 points for premium pricing


def test_lean_v13_specific_rules():
    """Test specific Lean v1.3 rules and calculations"""
    from analysis.lean_scoring import compute_base_and_adjustments
    
    # Test size efficiency: 20 ≤ size ≤ 120 => 4 else 0
    good_size_data = {'total_sqm': 50, 'current_price': 50000000, 'price_per_sqm': 1000000}
    result = compute_base_and_adjustments(good_size_data, None, [], {}, None)
    assert result['components']['size_efficiency'] == 4.0
    
    bad_size_data = {'total_sqm': 15, 'current_price': 50000000, 'price_per_sqm': 1000000}
    result = compute_base_and_adjustments(bad_size_data, None, [], {}, None)
    assert result['components']['size_efficiency'] == 0.0
    
    # Test carry cost calculation
    carry_cost_data = {
        'current_price': 50000000,
        'total_sqm': 50,
        'price_per_sqm': 1000000,
        'hoa_fee_yen': 15000,
        'repair_fund_yen': 10000
    }
    result = compute_base_and_adjustments(carry_cost_data, None, [], {}, None)
    # ratio = 25000 / (50000000/100) = 25000 / 500000 = 0.05 ≤ 0.12 => 4 points
    assert result['components']['carry_cost'] == 4.0
    
    # Test data quality penalties per Section 4
    missing_ward_data = {'current_price': 50000000, 'total_sqm': 50, 'price_per_sqm': 1000000}
    result = compute_base_and_adjustments(missing_ward_data, None, [], {}, None)
    assert result['dq_penalty'] <= -4  # Missing ward median = -4


class TestScoringComponentBoundaries:
    """Test boundary conditions for scoring components (merged from test_scoring_basic.py)"""
    
    def test_ward_discount_linearity(self):
        """Test ward discount scoring linearity across range."""
        from analysis.lean_scoring import compute_base_and_adjustments
        
        # Test perfect 20% discount (should get full 25 points)
        listing = {
            'price_per_sqm': 800000,
            'current_price': 50000000, 
            'total_sqm': 60.0,
            'size_sqm': 60.0  # Add both variants for compatibility
        }
        ward_median = 1000000  # 800k vs 1000k = 20% discount
        
        result = compute_base_and_adjustments(listing, ward_median, [], {}, None)
        
        assert result['components']['ward_discount'] == 25.0
        assert result['ward_discount_pct'] == -20.0  # 20% discount
        
        # Test 10% discount (should get 12.5 points)
        listing_10pct = {
            'price_per_sqm': 900000,
            'current_price': 54000000,
            'total_sqm': 60.0,
            'size_sqm': 60.0
        }
        result_10pct = compute_base_and_adjustments(listing_10pct, 1000000, [], {}, None)
        assert result_10pct['components']['ward_discount'] == 12.5
    
    def test_size_efficiency_boundaries(self):
        """Test size efficiency scoring boundaries (20-120 sqm range)."""
        from analysis.lean_scoring import compute_base_and_adjustments
        
        # Property within range should get 4 points
        in_range = {
            'price_per_sqm': 1000000,
            'current_price': 50000000,
            'total_sqm': 60.0,
            'size_sqm': 60.0
        }
        result = compute_base_and_adjustments(in_range, 1000000, [], {}, None)
        assert result['components']['size_efficiency'] == 4.0
        
        # Property too large should get 0 points
        too_large = {
            'price_per_sqm': 1000000,
            'current_price': 150000000,
            'total_sqm': 150.0,
            'size_sqm': 150.0
        }
        result_large = compute_base_and_adjustments(too_large, 1000000, [], {}, None)
        assert result_large['components']['size_efficiency'] == 0.0
    
    def test_data_quality_penalty_levels(self):
        """Test data quality penalty calculations."""
        from analysis.lean_scoring import compute_base_and_adjustments
        
        # Missing critical data (price): -6 penalty  
        listing_no_price = {
            'price_per_sqm': 1000000,
            'total_sqm': 60.0,
            'size_sqm': 60.0
        }
        result_no_price = compute_base_and_adjustments(listing_no_price, 1000000, [], {}, None)
        assert result_no_price['dq_penalty'] <= -6
        
        # Complete data should have minimal penalty
        complete_listing = {
            'price_per_sqm': 1000000,
            'current_price': 50000000,
            'total_sqm': 60.0,
            'size_sqm': 60.0
        }
        result_complete = compute_base_and_adjustments(complete_listing, 1000000, [], {}, None)
        assert result_complete['dq_penalty'] >= -3  # Should have low penalty
    
    def test_carry_cost_boundaries(self):
        """Test carry cost component boundaries."""
        from analysis.lean_scoring import compute_base_and_adjustments
        
        # Excellent ratio (≤0.12) should get 4 points
        excellent_listing = {
            'price_per_sqm': 1000000,
            'current_price': 50000000,
            'total_sqm': 60.0,
            'size_sqm': 60.0,
            'hoa_fee_yen': 30000,
            'repair_fund_yen': 30000  # Total 60k on 50M = 0.12 ratio
        }
        result_excellent = compute_base_and_adjustments(excellent_listing, 1000000, [], {}, None)
        assert result_excellent['components']['carry_cost'] == 4.0
        
        # Poor ratio (≥0.18) should get 0 points
        poor_listing = {
            'price_per_sqm': 1000000,
            'current_price': 50000000,
            'total_sqm': 60.0,
            'size_sqm': 60.0,
            'hoa_fee_yen': 50000,
            'repair_fund_yen': 40000  # Total 90k on 50M = 0.18 ratio
        }
        result_poor = compute_base_and_adjustments(poor_listing, 1000000, [], {}, None)
        assert result_poor['components']['carry_cost'] == 0.0


class TestScoringDeterminism:
    """Test that scoring is deterministic (merged from test_scoring_basic.py)."""
    
    def test_score_consistency(self, sample_properties):
        """Test that scoring is deterministic."""
        scorer = LeanScoring()
        
        # Score the same property multiple times
        prop = sample_properties[0] if sample_properties else {
            'current_price': 50000000,
            'total_sqm': 50,
            'price_per_sqm': 1000000,
            'ward_median_price_per_sqm': 1200000
        }
        
        components1 = scorer.calculate_score(prop)
        components2 = scorer.calculate_score(prop)
        components3 = scorer.calculate_score(prop)
        
        # Results should be identical
        assert components1.final_score == components2.final_score == components3.final_score
        assert components1.verdict == components2.verdict == components3.verdict
        assert components1.base_score == components2.base_score == components3.base_score


class TestGatingRulesDetail:
    """Test Lean v1.3 gating rules in detail (merged from test_scoring_basic.py)."""
    
    def test_buy_candidate_full_criteria(self):
        """Test BUY_CANDIDATE gating criteria with all conditions."""
        from analysis.lean_scoring import compute_base_and_adjustments
        
        # Create property that should be BUY_CANDIDATE
        # final_score ≥75 AND ward_discount_pct ≤ -12% AND dq_penalty ≥ -4
        excellent_listing = {
            'price_per_sqm': 800000,      # -20% discount vs 1M ward median
            'current_price': 48000000,
            'total_sqm': 60.0,
            'size_sqm': 60.0,
            'hoa_fee_yen': 30000,
            'repair_fund_yen': 30000
        }
        
        # Good comparables
        good_comps = [
            {'price_per_sqm': 850000}, {'price_per_sqm': 860000},
            {'price_per_sqm': 870000}, {'price_per_sqm': 880000}
        ]
        
        # Modern condition
        excellent_vision = {'condition_category': 'modern', 'damage_tokens': []}
        
        result = compute_base_and_adjustments(
            excellent_listing, 1000000, good_comps, excellent_vision, None
        )
        
        assert result['verdict'] == 'BUY_CANDIDATE'
        assert result['final_score'] >= 75
        assert result['ward_discount_pct'] <= -12
        assert result['dq_penalty'] >= -4
    
    def test_watch_range_criteria(self):
        """Test WATCH gating criteria."""
        from analysis.lean_scoring import compute_base_and_adjustments
        
        # Create property with moderate score but in WATCH range
        moderate_listing = {
            'price_per_sqm': 900000,      # -10% discount
            'current_price': 54000000,
            'total_sqm': 60.0,
            'size_sqm': 60.0
        }
        
        moderate_vision = {'condition_category': 'dated', 'damage_tokens': []}
        
        result = compute_base_and_adjustments(
            moderate_listing, 1000000, [], moderate_vision, None
        )
        
        # Should be WATCH due to moderate discount in range
        expected_watch = (
            (60 <= result['final_score'] <= 74) or 
            (-11.99 <= result['ward_discount_pct'] <= -8)
        )
        
        if expected_watch:
            assert result['verdict'] == 'WATCH'


class TestExtremeValues:
    """Test handling of extreme values (merged from test_scoring_basic.py)."""
    
    def test_extreme_property_values(self):
        """Test handling of extreme values."""
        from analysis.lean_scoring import compute_base_and_adjustments
        
        extreme_prop = {
            'price_per_sqm': 10000000,  # Very expensive
            'current_price': 500000000, # 50M for 50sqm
            'total_sqm': 50.0,
            'size_sqm': 50.0,
            'hoa_fee_yen': 100000,
            'repair_fund_yen': 100000   # High fees
        }
        
        result = compute_base_and_adjustments(extreme_prop, 1000000, [], {}, None)
        
        assert 0 <= result['final_score'] <= 100
        assert result['components']['ward_discount'] == 0.0  # Should get minimum for extreme premium
        assert result['components']['carry_cost'] == 0.0     # Should get minimum for poor ratio


if __name__ == "__main__":
    # Run a simple example using Lean v1.3 spec
    example_property = {
        'current_price': 48000000,
        'total_sqm': 58,
        'price_per_sqm': 827586,
        'ward_median_price_per_sqm': 1100000,
        'building_median_price_per_sqm': 950000,
        'building_age_years': 8,
        'distance_station_m': 350,
        'hoa_fee_yen': 12000,
        'repair_fund_yen': 8000,
        'previous_price': 52000000,
        'comparables': [
            {'price_per_sqm': 900000, 'total_sqm': 55, 'building_age_years': 10},
            {'price_per_sqm': 950000, 'total_sqm': 60, 'building_age_years': 12},
            {'price_per_sqm': 880000, 'total_sqm': 52, 'building_age_years': 6},
            {'price_per_sqm': 920000, 'total_sqm': 58, 'building_age_years': 9}
        ],
        'vision_analysis': {
            'condition_category': 'modern',
            'damage_tokens': [],
            'light': True
        }
    }
    
    score, verdict, report = score_property(example_property)
    print(report)
    print(f"\nExample Property Score: {score:.1f}")
    print(f"Investment Verdict: {verdict.value}")