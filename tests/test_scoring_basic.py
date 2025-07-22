"""
Basic tests for Lean v1.3 scoring system correctness.

Tests cover:
- Ward discount linearity and boundary conditions
- DQ penalties for missing data
- Size efficiency boundaries 
- Component weight verification
- Gating rule accuracy
"""

import json
import pytest
from pathlib import Path

from analysis.lean_scoring import (
    LeanScoring, 
    ScoringComponents, 
    Verdict,
    score_property,
    compute_base_and_adjustments
)


@pytest.fixture
def sample_properties():
    """Load sample properties from fixtures."""
    fixture_path = Path(__file__).parent / 'fixtures' / 'sample_properties.json'
    with open(fixture_path) as f:
        return json.load(f)


@pytest.fixture
def scorer():
    """Create scorer instance."""
    return LeanScoring()


class TestLeanScoringBasics:
    """Test basic scoring functionality."""
    
    def test_scorer_initialization(self, scorer):
        """Test scorer initializes correctly."""
        assert scorer is not None
    
    def test_ward_discount_calculation(self):
        """Test ward discount scoring linearity using compute_base_and_adjustments."""
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
        
        # Test no discount (at market)
        listing_market = {
            'price_per_sqm': 1000000,
            'current_price': 60000000,
            'total_sqm': 60.0,
            'size_sqm': 60.0
        }
        result_market = compute_base_and_adjustments(listing_market, 1000000, [], {}, None)
        assert result_market['components']['ward_discount'] == 0.0
        
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
        # Property within range should get 4 points
        in_range = {
            'price_per_sqm': 1000000,
            'current_price': 50000000,
            'total_sqm': 60.0,
            'size_sqm': 60.0
        }
        result = compute_base_and_adjustments(in_range, 1000000, [], {}, None)
        assert result['components']['size_efficiency'] == 4.0
        
        # Property too small should get 0 points
        too_small = {
            'price_per_sqm': 1000000,
            'current_price': 15000000,
            'total_sqm': 15.0,
            'size_sqm': 15.0
        }
        result_small = compute_base_and_adjustments(too_small, 1000000, [], {}, None)
        assert result_small['components']['size_efficiency'] == 0.0
        
        # Property too large should get 0 points
        too_large = {
            'price_per_sqm': 1000000,
            'current_price': 150000000,
            'total_sqm': 150.0,
            'size_sqm': 150.0
        }
        result_large = compute_base_and_adjustments(too_large, 1000000, [], {}, None)
        assert result_large['components']['size_efficiency'] == 0.0
    
    def test_data_quality_penalties(self):
        """Test data quality penalty calculations."""
        # Missing ward median: -4 penalty
        listing_no_ward = {
            'price_per_sqm': 1000000,
            'current_price': 50000000,
            'total_sqm': 60.0,
            'size_sqm': 60.0
        }
        result_no_ward = compute_base_and_adjustments(listing_no_ward, None, [], {}, None)
        assert result_no_ward['dq_penalty'] <= -4
        
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
    
    def test_comparables_consistency(self):
        """Test comparables consistency scoring."""
        listing = {
            'price_per_sqm': 900000,
            'current_price': 54000000,
            'total_sqm': 60.0,
            'size_sqm': 60.0
        }
        
        # 4+ comps with median above subject * 1.05 should get full 10 points
        good_comps = [
            {'price_per_sqm': 950000}, {'price_per_sqm': 960000},
            {'price_per_sqm': 970000}, {'price_per_sqm': 980000}
        ]
        result_good = compute_base_and_adjustments(listing, 1000000, good_comps, {}, None)
        assert result_good['components']['comps_consistency'] == 10.0
        
        # <4 comps should get 0 points
        few_comps = [{'price_per_sqm': 950000}, {'price_per_sqm': 960000}]
        result_few = compute_base_and_adjustments(listing, 1000000, few_comps, {}, None)
        assert result_few['components']['comps_consistency'] == 0.0
    
    def test_condition_scoring(self):
        """Test condition component using vision analysis."""
        listing = {
            'price_per_sqm': 1000000,
            'current_price': 50000000,
            'total_sqm': 60.0,
            'size_sqm': 60.0
        }
        
        # Modern condition should get 7 points
        modern_vision = {'condition_category': 'modern', 'damage_tokens': []}
        result_modern = compute_base_and_adjustments(listing, 1000000, [], modern_vision, None)
        assert result_modern['components']['condition'] == 7.0
        
        # Dated condition should get 3 points  
        dated_vision = {'condition_category': 'dated', 'damage_tokens': []}
        result_dated = compute_base_and_adjustments(listing, 1000000, [], dated_vision, None)
        assert result_dated['components']['condition'] == 3.0
        
        # Damage tokens should reduce score
        damaged_vision = {'condition_category': 'modern', 'damage_tokens': ['stain']}
        result_damaged = compute_base_and_adjustments(listing, 1000000, [], damaged_vision, None)
        assert result_damaged['components']['condition'] == 6.0  # 7 - 1 for damage
    
    def test_carry_cost_scoring(self):
        """Test carry cost component."""
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
        
        # Missing fees should assume best case (4 points)
        no_fees_listing = {
            'price_per_sqm': 1000000,
            'current_price': 50000000,
            'total_sqm': 60.0,
            'size_sqm': 60.0
        }
        result_no_fees = compute_base_and_adjustments(no_fees_listing, 1000000, [], {}, None)
        assert result_no_fees['components']['carry_cost'] == 4.0


class TestScoringIntegration:
    """Test complete scoring integration."""
    
    def test_complete_scoring_workflow(self, scorer, sample_properties):
        """Test complete scoring workflow on sample data."""
        for prop in sample_properties:
            components = scorer.calculate_score(prop)
            
            # Verify all components are calculated
            assert isinstance(components, ScoringComponents)
            assert 0 <= components.final_score <= 100
            assert components.verdict in [Verdict.BUY_CANDIDATE, Verdict.WATCH, Verdict.REJECT]
            
            # Verify scoring components are in expected ranges
            assert 0 <= components.ward_discount <= 25
            assert 0 <= components.building_discount <= 10
            assert 0 <= components.comps_consistency <= 10
            assert 0 <= components.condition <= 7
            assert 0 <= components.size_efficiency <= 4
            assert 0 <= components.carry_cost <= 4
    
    def test_convenience_functions(self, sample_properties):
        """Test convenience functions work correctly."""
        prop = sample_properties[0]
        
        # Test score_property function
        score, verdict, report = score_property(prop)
        
        assert isinstance(score, float)
        assert 0 <= score <= 100
        assert isinstance(verdict, Verdict)
        assert isinstance(report, str)
        assert "Final Score:" in report
        assert "Verdict:" in report
    
    def test_score_determinism(self, scorer, sample_properties):
        """Test that scoring is deterministic."""
        prop = sample_properties[0]
        
        # Score the same property multiple times
        components1 = scorer.calculate_score(prop)
        components2 = scorer.calculate_score(prop)
        components3 = scorer.calculate_score(prop)
        
        # Results should be identical
        assert components1.final_score == components2.final_score == components3.final_score
        assert components1.verdict == components2.verdict == components3.verdict
        assert components1.base_score == components2.base_score == components3.base_score


class TestGatingRules:
    """Test Lean v1.3 gating rules."""
    
    def test_buy_candidate_gating(self):
        """Test BUY_CANDIDATE gating criteria."""
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
    
    def test_watch_gating(self):
        """Test WATCH gating criteria."""
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
    
    def test_reject_gating(self):
        """Test REJECT gating criteria."""
        # Property with poor metrics should be REJECT
        poor_listing = {
            'price_per_sqm': 1200000,     # 20% premium (bad)
            'current_price': 72000000,
            'total_sqm': 15.0,            # Too small
            'size_sqm': 15.0,
            'hoa_fee_yen': 60000,
            'repair_fund_yen': 60000      # High fees
        }
        
        poor_vision = {'condition_category': 'original', 'damage_tokens': ['stain', 'mold']}
        
        result = compute_base_and_adjustments(
            poor_listing, 1000000, [], poor_vision, None
        )
        
        assert result['verdict'] == 'REJECT'


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_empty_property_data(self, scorer):
        """Test scoring with empty property data."""
        components = scorer.calculate_score({})
        
        assert isinstance(components, ScoringComponents)
        assert components.final_score == 0  # Should be forced to 0 for missing data
        assert components.verdict == Verdict.REJECT  # Should be rejected
        assert components.data_quality_penalty <= -6  # High penalty for missing critical data
    
    def test_missing_ward_median(self):
        """Test handling missing ward median."""
        listing = {
            'price_per_sqm': 1000000,
            'current_price': 50000000,
            'total_sqm': 60.0,
            'size_sqm': 60.0
        }
        
        result = compute_base_and_adjustments(listing, None, [], {}, None)
        assert result['components']['ward_discount'] == 0.0
        assert result['dq_penalty'] <= -4  # Penalty for missing ward median
    
    def test_extreme_values(self):
        """Test handling of extreme values."""
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
    pytest.main([__file__, "-v"])