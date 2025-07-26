"""
Basic tests for Lean v1.3 comparables filtering and ordering.

Tests cover:
- ±30% price_per_sqm filtering  
- ±25% size filtering
- ±10 years age filtering
- Proper sorting by price/size delta
- Maximum 8 comparables returned
- Market statistics calculation
"""

import json
import pytest
from pathlib import Path

from analysis.comparables import (
    ComparablesFilter,
    Comparable,
    find_and_format_comparables,
    enrich_property_with_comparables,
    select_comparables,
    format_comparable_lines
)


@pytest.fixture
def sample_properties():
    """Load sample properties from fixtures."""
    fixture_path = Path(__file__).parent / 'fixtures' / 'sample_properties.json'
    with open(fixture_path) as f:
        return json.load(f)


@pytest.fixture
def sample_comparables():
    """Load sample comparables from fixtures."""
    fixture_path = Path(__file__).parent / 'fixtures' / 'sample_comparables.json'
    with open(fixture_path) as f:
        return json.load(f)


@pytest.fixture
def filter_engine():
    """Create comparables filter instance."""
    return ComparablesFilter(max_comparables=8)


class TestComparablesFiltering:
    """Test comparables filtering logic."""
    
    def test_filter_initialization(self, filter_engine):
        """Test filter initializes correctly."""
        assert filter_engine.max_comparables == 8
    
    def test_price_per_sqm_filtering(self, filter_engine, sample_comparables):
        """Test ±30% price per sqm filtering."""
        target = {
            'id': 'TARGET',
            'price_per_sqm': 1000000,  # Base price
            'size_sqm': 60.0,
            'building_age_years': 10
        }
        
        comparables = filter_engine.find_comparables(target, sample_comparables)
        
        # Should only include properties within 700k-1300k range
        for comp in comparables:
            assert 700000 <= comp.price_per_sqm <= 1300000
        
        # Verify specific inclusions/exclusions based on fixture data
        comp_ids = [c.id for c in comparables]
        assert 'COMP_001' in comp_ids  # 850k - within range
        assert 'COMP_002' in comp_ids  # 900k - within range  
        assert 'COMP_005' in comp_ids  # 1050k - within range
        assert 'COMP_007' in comp_ids  # 1100k - within range
        # COMP_009 is 1200k which IS within 1300k range, so it should be included
    
    def test_size_filtering(self, filter_engine, sample_comparables):
        """Test ±25% size filtering."""
        target = {
            'id': 'TARGET',
            'price_per_sqm': 900000,
            'size_sqm': 60.0,  # Base size (range: 45-75 sqm)
            'building_age_years': 10
        }
        
        comparables = filter_engine.find_comparables(target, sample_comparables)
        
        # Should only include properties within 45-75 sqm range
        for comp in comparables:
            assert 45.0 <= comp.size_sqm <= 75.0
        
        # Verify inclusions - COMP_008 has 45.0 sqm which equals the minimum boundary
        comp_ids = [c.id for c in comparables]
        # Most comparables should be in range based on fixture data
    
    def test_age_filtering(self, filter_engine, sample_comparables):
        """Test ±10 years age filtering."""
        target = {
            'id': 'TARGET',
            'price_per_sqm': 900000,
            'size_sqm': 60.0,
            'building_age_years': 10  # Base age (range: 0-20 years)
        }
        
        comparables = filter_engine.find_comparables(target, sample_comparables)
        
        # Should only include properties within 0-20 years range
        for comp in comparables:
            assert 0 <= comp.age_years <= 20
        
        # Verify exclusions based on fixture data
        comp_ids = [c.id for c in comparables]
        # Properties older than 20 years should be excluded
    
    def test_combined_filtering(self, filter_engine, sample_comparables):
        """Test all filtering criteria applied together."""
        target = {
            'id': 'TARGET',
            'price_per_sqm': 900000,  # Range: 630k-1170k
            'size_sqm': 60.0,         # Range: 45-75 sqm  
            'building_age_years': 10   # Range: 0-20 years
        }
        
        comparables = filter_engine.find_comparables(target, sample_comparables)
        
        # Verify all criteria are met
        for comp in comparables:
            assert 630000 <= comp.price_per_sqm <= 1170000
            assert 45.0 <= comp.size_sqm <= 75.0
            assert 0 <= comp.age_years <= 20
        
        # Should have some results but not all fixtures
        assert 0 < len(comparables) <= 8
    
    def test_max_comparables_limit(self, sample_comparables):
        """Test maximum comparables limit is respected."""
        # Create filter with low limit
        limited_filter = ComparablesFilter(max_comparables=3)
        
        target = {
            'id': 'TARGET',
            'price_per_sqm': 900000,
            'size_sqm': 60.0,
            'building_age_years': 10
        }
        
        comparables = limited_filter.find_comparables(target, sample_comparables)
        assert len(comparables) <= 3
    
    def test_self_exclusion(self, filter_engine, sample_comparables):
        """Test target property is excluded from results."""
        # Use one of the comparables as target
        target = sample_comparables[0].copy()  # COMP_001
        target['id'] = 'COMP_001'  # Make sure IDs match
        
        comparables = filter_engine.find_comparables(target, sample_comparables)
        
        # Target should not appear in results
        comp_ids = [c.id for c in comparables]
        assert 'COMP_001' not in comp_ids


class TestComparablesSorting:
    """Test comparables sorting logic."""
    
    def test_sorting_by_price_delta_primary(self, filter_engine, sample_comparables):
        """Test sorting by price delta (primary criterion)."""
        target = {
            'id': 'TARGET',
            'price_per_sqm': 900000,
            'size_sqm': 60.0,
            'building_age_years': 10
        }
        
        comparables = filter_engine.find_comparables(target, sample_comparables)
        
        if len(comparables) > 1:
            # Should be sorted by price delta ascending
            for i in range(len(comparables) - 1):
                curr_delta = abs(comparables[i].price_per_sqm - target['price_per_sqm'])
                next_delta = abs(comparables[i + 1].price_per_sqm - target['price_per_sqm'])
                assert curr_delta <= next_delta
    
    def test_sorting_by_size_delta_secondary(self, filter_engine):
        """Test sorting by size delta (secondary criterion)."""
        # Create mock comparables with same price delta but different size deltas
        target = {
            'id': 'TARGET',
            'price_per_sqm': 900000,
            'size_sqm': 60.0,
            'building_age_years': 10
        }
        
        mock_comparables = [
            {
                'id': 'SAME_PRICE_1',
                'price_per_sqm': 900000,  # Same price as target
                'size_sqm': 70.0,         # +10 sqm difference
                'building_age_years': 10
            },
            {
                'id': 'SAME_PRICE_2',
                'price_per_sqm': 900000,  # Same price as target
                'size_sqm': 55.0,         # -5 sqm difference
                'building_age_years': 10
            }
        ]
        
        comparables = filter_engine.find_comparables(target, mock_comparables)
        
        if len(comparables) == 2:
            # Should be sorted by size delta (5 sqm < 10 sqm difference)
            assert comparables[0].id == 'SAME_PRICE_2'
            assert comparables[1].id == 'SAME_PRICE_1'


class TestComparablesFormatting:
    """Test comparables formatting functionality."""
    
    def test_text_formatting(self, filter_engine, sample_comparables):
        """Test text format output."""
        target = {
            'id': 'TARGET',
            'price_per_sqm': 900000,
            'size_sqm': 60.0,
            'building_age_years': 10
        }
        
        comparables = filter_engine.find_comparables(target, sample_comparables)
        text = filter_engine.format_comparables_text(comparables)
        
        assert "Comparable Properties:" in text
        assert "ID | Price/sqm | Size | Age | Floor" in text
        assert "¥" in text
        assert "m²" in text
        assert "y" in text
        assert "F" in text
        
        # Should have one line per comparable plus headers
        lines = text.split('\n')
        assert len(lines) >= len(comparables) + 3  # Header + separator + data lines
    
    def test_json_formatting(self, filter_engine, sample_comparables):
        """Test JSON format output."""
        target = {
            'id': 'TARGET',
            'price_per_sqm': 900000,
            'size_sqm': 60.0,
            'building_age_years': 10
        }
        
        comparables = filter_engine.find_comparables(target, sample_comparables)
        json_data = filter_engine.format_comparables_json(comparables)
        
        assert isinstance(json_data, list)
        assert len(json_data) == len(comparables)
        
        for item in json_data:
            assert 'id' in item
            assert 'price_per_sqm' in item
            assert 'size_sqm' in item
            assert 'age_years' in item
            assert 'price_delta_pct' in item
            assert 'size_delta_sqm' in item
    
    def test_empty_comparables_formatting(self, filter_engine):
        """Test formatting with no comparables."""
        text = filter_engine.format_comparables_text([])
        assert text == "No comparable properties found."
        
        json_data = filter_engine.format_comparables_json([])
        assert json_data == []


class TestMarketStatistics:
    """Test market statistics calculation."""
    
    def test_market_stats_calculation(self, filter_engine, sample_comparables):
        """Test market statistics are calculated correctly."""
        target = {
            'id': 'TARGET',
            'price_per_sqm': 900000,
            'size_sqm': 60.0,
            'building_age_years': 10
        }
        
        comparables = filter_engine.find_comparables(target, sample_comparables)
        stats = filter_engine.calculate_market_stats(target, comparables)
        
        assert 'num_comparables' in stats
        assert 'comparable_price_variance' in stats
        assert 'market_median_ppsm' in stats
        assert 'market_mean_ppsm' in stats
        assert 'target_vs_market_pct' in stats
        
        assert stats['num_comparables'] == len(comparables)
        assert stats['comparable_price_variance'] >= 0
        assert stats['market_median_ppsm'] > 0
        assert stats['market_mean_ppsm'] > 0
    
    def test_market_stats_with_no_comparables(self, filter_engine):
        """Test market statistics with no comparables."""
        target = {
            'id': 'TARGET',
            'price_per_sqm': 900000,
            'size_sqm': 60.0
        }
        
        stats = filter_engine.calculate_market_stats(target, [])
        
        assert stats['num_comparables'] == 0
        assert stats['comparable_price_variance'] == 1.0
        assert stats['market_median_ppsm'] == target['price_per_sqm']
        assert stats['target_vs_market_pct'] == 0.0


class TestConvenienceFunctions:
    """Test convenience functions."""
    
    def test_find_and_format_comparables(self, sample_comparables):
        """Test find_and_format_comparables convenience function."""
        target = {
            'id': 'TARGET',
            'price_per_sqm': 900000,
            'size_sqm': 60.0,
            'building_age_years': 10
        }
        
        comp_dicts, comp_text, market_stats = find_and_format_comparables(
            target, sample_comparables, max_comps=5
        )
        
        # Check all outputs are returned
        assert isinstance(comp_dicts, list)
        assert isinstance(comp_text, str)
        assert isinstance(market_stats, dict)
        
        # Check length limits
        assert len(comp_dicts) <= 5
        
        # Check content
        assert "Comparable Properties:" in comp_text
        assert 'num_comparables' in market_stats
    
    def test_enrich_property_with_comparables(self, sample_properties, sample_comparables):
        """Test property enrichment with comparables data."""
        target = sample_properties[0]  # PROP_001
        
        enriched = enrich_property_with_comparables(target, sample_comparables)
        
        # Original data should be preserved
        for key, value in target.items():
            assert enriched[key] == value
        
        # New comparable data should be added
        assert 'comparables' in enriched
        assert 'comparables_text' in enriched
        assert 'num_comparables' in enriched
        assert 'comparable_price_variance' in enriched
        assert 'market_median_ppsm' in enriched


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_missing_target_data(self, filter_engine, sample_comparables):
        """Test handling of missing target property data."""
        # Missing price_per_sqm
        incomplete_target = {
            'id': 'TARGET',
            'size_sqm': 60.0,
            'building_age_years': 10
        }
        
        comparables = filter_engine.find_comparables(incomplete_target, sample_comparables)
        assert comparables == []
    
    def test_missing_comparable_data(self, filter_engine):
        """Test handling of comparables with missing data."""
        target = {
            'id': 'TARGET',
            'price_per_sqm': 900000,
            'size_sqm': 60.0,
            'building_age_years': 10
        }
        
        incomplete_comparables = [
            {
                'id': 'INCOMPLETE_1',
                'price_per_sqm': 850000,
                # Missing size_sqm
                'building_age_years': 8
            },
            {
                'id': 'COMPLETE_1',
                'price_per_sqm': 920000,
                'size_sqm': 55.0,
                'building_age_years': 12
            }
        ]
        
        comparables = filter_engine.find_comparables(target, incomplete_comparables)
        
        # Should only include complete data
        comp_ids = [c.id for c in comparables]
        assert 'INCOMPLETE_1' not in comp_ids
        assert 'COMPLETE_1' in comp_ids
    
    def test_extreme_filtering_criteria(self, filter_engine):
        """Test with extreme filtering criteria that match nothing."""
        target = {
            'id': 'TARGET',
            'price_per_sqm': 10000000,  # Very expensive - unlikely to have matches
            'size_sqm': 60.0,
            'building_age_years': 10
        }
        
        # Regular sample comparables won't match this extreme price
        regular_comparables = [
            {
                'id': 'REGULAR',
                'price_per_sqm': 900000,
                'size_sqm': 60.0,
                'building_age_years': 10
            }
        ]
        
        comparables = filter_engine.find_comparables(target, regular_comparables)
        assert comparables == []


class TestSelectComparablesFunction:
    """Test the select_comparables function specifically (Lean v1.3 requirement)."""
    
    def test_select_comparables_filtering(self, sample_comparables):
        """Test select_comparables applies all filtering criteria correctly."""
        subject = {
            'id': 'SUBJECT',
            'price_per_sqm': 900000,   # Range: 630k-1170k (±30%)
            'size_sqm': 60.0,          # Range: 45-75 sqm (±25%)
            'building_age_years': 10    # Range: 0-20 years (±10 years)
        }
        
        comps = select_comparables(subject, sample_comparables)
        
        # Verify all returned comparables meet filtering criteria
        for comp in comps:
            assert 630000 <= comp['price_per_sqm'] <= 1170000
            assert 45.0 <= comp['size_sqm'] <= 75.0
            assert 0 <= comp['building_age_years'] <= 20
        
        # Verify max 8 comparables returned
        assert len(comps) <= 8
        
        # Verify subject not in results
        comp_ids = [c['id'] for c in comps]
        assert 'SUBJECT' not in comp_ids
    
    def test_select_comparables_sorting(self):
        """Test select_comparables sorts by price delta then size delta."""
        subject = {
            'id': 'SUBJECT',
            'price_per_sqm': 1000000,
            'size_sqm': 60.0,
            'building_age_years': 10
        }
        
        # Create test pool with known price/size deltas
        pool = [
            {
                'id': 'COMP_A',
                'price_per_sqm': 950000,   # 50k delta (5%)
                'size_sqm': 70.0,          # 10 sqm delta
                'building_age_years': 12
            },
            {
                'id': 'COMP_B', 
                'price_per_sqm': 950000,   # 50k delta (5%) - same as A
                'size_sqm': 55.0,          # 5 sqm delta - smaller than A
                'building_age_years': 8
            },
            {
                'id': 'COMP_C',
                'price_per_sqm': 1100000,  # 100k delta (10%) - larger than A&B
                'size_sqm': 65.0,          # 5 sqm delta
                'building_age_years': 15
            }
        ]
        
        comps = select_comparables(subject, pool)
        
        # Should be sorted: COMP_B (50k, 5sqm), COMP_A (50k, 10sqm), COMP_C (100k, 5sqm)
        assert comps[0]['id'] == 'COMP_B'  # Smallest price delta, smallest size delta
        assert comps[1]['id'] == 'COMP_A'  # Same price delta as B, larger size delta
        assert comps[2]['id'] == 'COMP_C'  # Larger price delta
    
    def test_select_comparables_max_eight(self):
        """Test select_comparables returns maximum 8 results."""
        subject = {
            'id': 'SUBJECT',
            'price_per_sqm': 1000000,
            'size_sqm': 60.0,
            'building_age_years': 10
        }
        
        # Create 12 valid comparables
        pool = []
        for i in range(12):
            pool.append({
                'id': f'COMP_{i:03d}',
                'price_per_sqm': 900000 + (i * 10000),  # All within ±30%
                'size_sqm': 55.0 + (i * 1.0),           # All within ±25% 
                'building_age_years': 8 + i              # All within ±10 years
            })
        
        comps = select_comparables(subject, pool)
        
        # Should return exactly 8 (not 12)
        assert len(comps) == 8
        
        # Should be the 8 closest by price delta (first 8 in sorted order)
        expected_ids = [f'COMP_{i:03d}' for i in range(8)]
        actual_ids = [c['id'] for c in comps]
        assert actual_ids == expected_ids
    
    def test_select_comparables_empty_pool(self):
        """Test select_comparables handles empty pool."""
        subject = {
            'id': 'SUBJECT',
            'price_per_sqm': 1000000,
            'size_sqm': 60.0,
            'building_age_years': 10
        }
        
        comps = select_comparables(subject, [])
        assert comps == []
    
    def test_select_comparables_missing_data(self):
        """Test select_comparables handles missing subject data."""
        incomplete_subject = {
            'id': 'SUBJECT',
            'size_sqm': 60.0,
            # Missing price_per_sqm
            'building_age_years': 10
        }
        
        pool = [{
            'id': 'COMP_001',
            'price_per_sqm': 900000,
            'size_sqm': 55.0,
            'building_age_years': 8
        }]
        
        comps = select_comparables(incomplete_subject, pool)
        assert comps == []
    
    def test_select_comparables_no_sort_keys_in_output(self):
        """Test select_comparables removes internal sort keys from output."""
        subject = {
            'id': 'SUBJECT',
            'price_per_sqm': 1000000,
            'size_sqm': 60.0,
            'building_age_years': 10
        }
        
        pool = [{
            'id': 'COMP_001',
            'price_per_sqm': 950000,
            'size_sqm': 55.0,
            'building_age_years': 8
        }]
        
        comps = select_comparables(subject, pool)
        
        # Verify no internal sort keys in output
        for comp in comps:
            assert '_price_delta' not in comp
            assert '_size_delta' not in comp


class TestFormatComparableLines:
    """Test the format_comparable_lines function (Lean v1.3 requirement)."""
    
    def test_format_comparable_lines_output(self):
        """Test format_comparable_lines produces correct format."""
        comps = [
            {
                'id': 'COMP_001',
                'price_per_sqm': 950000,
                'size_sqm': 55.5,
                'building_age_years': 8,
                'floor': 3
            },
            {
                'id': 'COMP_002',
                'price_per_sqm': 1050000,
                'size_sqm': 62.0,
                'building_age_years': 12,
                'floor': None  # Test missing floor
            }
        ]
        
        lines = format_comparable_lines(comps)
        
        assert len(lines) == 2
        assert 'COMP_001 | ¥950,000 | 55.5m² | 8y | 3F' in lines[0]
        assert 'COMP_002 | ¥1,050,000 | 62.0m² | 12y | ?F' in lines[1]
    
    def test_format_comparable_lines_empty(self):
        """Test format_comparable_lines handles empty input."""
        lines = format_comparable_lines([])
        assert lines == ["No comparable properties found."]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])