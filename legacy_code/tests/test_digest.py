"""
Tests for Lean v1.3 daily digest generation.

Tests cover:
- HTML digest structure and content
- CSV generation with proper headers
- Market statistics inclusion
- Candidate table formatting
- Row counts matching data
- Email-friendly HTML format
"""

import csv
import json
import pytest
from pathlib import Path
from io import StringIO

from analysis.lean_scoring import Verdict, ScoringComponents
from notifications.daily_digest import (
    DailyDigestGenerator,
    generate_daily_digest
)


@pytest.fixture
def sample_candidates():
    """Sample candidate properties with scoring components."""
    # Create mock verdict objects
    def mock_verdict(value):
        verdict = type('MockVerdict', (), {})()
        verdict.value = value
        return verdict
    
    return [
        {
            'id': 'CAND_001',
            'price': 50000000,
            'size_sqm': 60.5,
            'price_per_sqm': 826446,
            'ward': 'Shibuya',
            'building_age_years': 8,
            'nearest_station_meters': 400,
            'components': {
                'final_score': 82.5,
                'verdict': mock_verdict('BUY_CANDIDATE'),
                'ward_discount_pct': -18.5
            }
        },
        {
            'id': 'CAND_002',
            'price': 35000000,
            'size_sqm': 45.0,
            'price_per_sqm': 777778,
            'ward': 'Setagaya',
            'building_age_years': 12,
            'nearest_station_meters': 600,
            'components': {
                'final_score': 75.2,
                'verdict': mock_verdict('BUY_CANDIDATE'),
                'ward_discount_pct': -15.2
            }
        },
        {
            'id': 'CAND_003',
            'price': 65000000,
            'size_sqm': 55.0,
            'price_per_sqm': 1181818,
            'ward': 'Minato',
            'building_age_years': 5,
            'nearest_station_meters': 200,
            'components': {
                'final_score': 68.8,
                'verdict': mock_verdict('WATCH'),
                'ward_discount_pct': -10.5
            }
        }
    ]


@pytest.fixture
def sample_snapshots():
    """Sample market snapshot data."""
    return {
        'global': {
            'median_price_per_sqm': 950000,
            'total_properties': 15420,
            'candidate_ratio': 0.18
        },
        'wards': {
            'Shibuya': {
                'median_price_per_sqm': 1100000,
                'total_properties': 2850,
                'candidate_count': 8
            },
            'Minato': {
                'median_price_per_sqm': 1300000,
                'total_properties': 1950,
                'candidate_count': 5
            },
            'Setagaya': {
                'median_price_per_sqm': 800000,
                'total_properties': 4200,
                'candidate_count': 12
            }
        }
    }


@pytest.fixture
def digest_generator():
    """Create digest generator instance."""
    return DailyDigestGenerator()


class TestDigestGeneration:
    """Test basic digest generation functionality."""
    
    def test_generator_initialization(self, digest_generator):
        """Test generator initializes correctly."""
        assert digest_generator.date is not None
        assert len(digest_generator.date) == 10  # YYYY-MM-DD format
        assert '-' in digest_generator.date
    
    def test_html_digest_structure(self, digest_generator, sample_candidates, sample_snapshots):
        """Test HTML digest has proper structure."""
        html = digest_generator.generate_html_digest(sample_candidates, sample_snapshots)
        
        # Should be valid HTML with basic structure
        assert '<html>' in html
        assert '<head>' in html
        assert '<body>' in html
        assert '</html>' in html
        
        # Should have title
        assert '<title>' in html
        assert 'Tokyo Real Estate Daily Digest' in html
        
        # Should have date
        assert digest_generator.date in html
        
        # Should have CSS styling
        assert '<style>' in html
        assert 'table' in html
        assert 'border-collapse' in html
    
    def test_html_digest_content_sections(self, digest_generator, sample_candidates, sample_snapshots):
        """Test HTML digest contains required content sections."""
        html = digest_generator.generate_html_digest(sample_candidates, sample_snapshots)
        
        # Should have market summary
        assert 'Market Summary' in html
        assert 'Candidates Found:' in html
        assert 'Market Median Price/sqm:' in html
        
        # Should have candidates table
        assert 'Top Candidates' in html
        assert '<table>' in html
        assert '<th>ID</th>' in html
        assert '<th>Score</th>' in html
        assert '<th>Verdict</th>' in html
        
        # Should have ward analysis
        assert 'Ward Analysis' in html
        assert 'Shibuya' in html or 'Minato' in html or 'Setagaya' in html
    
    def test_csv_digest_generation(self, digest_generator, sample_candidates):
        """Test CSV digest generation."""
        csv_content = digest_generator.generate_csv_digest(sample_candidates)
        
        # Should have CSV headers
        assert 'id,final_score,verdict' in csv_content
        assert 'ward_discount_pct,price,size_sqm' in csv_content
        
        # Should have candidate data
        assert 'CAND_001' in csv_content
        assert 'CAND_002' in csv_content
        assert 'CAND_003' in csv_content
        
        # Should have proper CSV format
        lines = csv_content.strip().split('\n')
        assert len(lines) >= 4  # Header + 3 candidates
    
    def test_csv_parsing_validity(self, digest_generator, sample_candidates):
        """Test that generated CSV can be parsed correctly."""
        csv_content = digest_generator.generate_csv_digest(sample_candidates)
        
        # Should be parseable as CSV
        reader = csv.DictReader(StringIO(csv_content))
        rows = list(reader)
        
        assert len(rows) == len(sample_candidates)
        
        # Check first row data
        first_row = rows[0]
        assert 'id' in first_row
        assert 'final_score' in first_row
        assert 'verdict' in first_row
        assert first_row['id'] in ['CAND_001', 'CAND_002', 'CAND_003']
    
    def test_empty_candidates_handling(self, digest_generator, sample_snapshots):
        """Test handling of empty candidates list."""
        # HTML with no candidates
        html = digest_generator.generate_html_digest([], sample_snapshots)
        assert 'Candidates Found: 0' in html
        assert 'No candidates found today' in html
        
        # CSV with no candidates
        csv_content = digest_generator.generate_csv_digest([])
        assert 'No candidates found' in csv_content


class TestDigestContent:
    """Test digest content accuracy and formatting."""
    
    def test_market_summary_statistics(self, digest_generator, sample_candidates, sample_snapshots):
        """Test market summary contains correct statistics."""
        html = digest_generator.generate_html_digest(sample_candidates, sample_snapshots)
        
        # Should show correct candidate count
        assert 'Candidates Found: 3' in html
        
        # Should show market median price
        assert '¥950,000' in html  # From sample_snapshots global median
        
        # Should show total inventory
        assert '15,420' in html  # From sample_snapshots global total
        
        # Should break down by verdict
        assert 'BUY_CANDIDATE: 2' in html  # 2 buy candidates in sample
        assert 'WATCH: 1' in html         # 1 watch candidate in sample
    
    def test_candidates_table_sorting(self, digest_generator, sample_candidates, sample_snapshots):
        """Test candidates table is sorted by score descending."""
        html = digest_generator.generate_html_digest(sample_candidates, sample_snapshots)
        
        # Find table content
        table_start = html.find('<table>')
        table_end = html.find('</table>', table_start) + 8
        table_html = html[table_start:table_end]
        
        # Should have CAND_001 (82.5 score) before CAND_002 (75.2 score)
        cand_001_pos = table_html.find('CAND_001')
        cand_002_pos = table_html.find('CAND_002')
        cand_003_pos = table_html.find('CAND_003')
        
        assert cand_001_pos < cand_002_pos  # Higher score first
        assert cand_002_pos < cand_003_pos  # Middle score second
    
    def test_candidates_table_formatting(self, digest_generator, sample_candidates, sample_snapshots):
        """Test candidates table has proper formatting."""
        html = digest_generator.generate_html_digest(sample_candidates, sample_snapshots)
        
        # Should format prices with yen symbol and commas
        assert '¥50,000,000' in html or '¥35,000,000' in html
        
        # Should format percentages
        assert '-18.5%' in html or '-15.2%' in html
        
        # Should format sizes
        assert '60.5m²' in html or '45.0m²' in html
        
        # Should show building ages
        assert '8y' in html or '12y' in html
        
        # Should show station distances
        assert '400m' in html or '600m' in html
    
    def test_ward_analysis_table(self, digest_generator, sample_candidates, sample_snapshots):
        """Test ward analysis table content."""
        html = digest_generator.generate_html_digest(sample_candidates, sample_snapshots)
        
        # Should have ward names
        assert 'Shibuya' in html
        assert 'Minato' in html  
        assert 'Setagaya' in html
        
        # Should have formatted prices
        assert '¥1,100,000' in html  # Shibuya median
        assert '¥1,300,000' in html  # Minato median
        assert '¥800,000' in html    # Setagaya median
        
        # Should show candidate counts
        assert '>8<' in html   # Shibuya candidates
        assert '>5<' in html   # Minato candidates  
        assert '>12<' in html  # Setagaya candidates
    
    def test_csv_column_accuracy(self, digest_generator, sample_candidates):
        """Test CSV columns contain accurate data."""
        csv_content = digest_generator.generate_csv_digest(sample_candidates)
        
        reader = csv.DictReader(StringIO(csv_content))
        rows = list(reader)
        
        # Find CAND_001 row
        cand_001_row = next(row for row in rows if row['id'] == 'CAND_001')
        
        assert cand_001_row['final_score'] == '82.5'
        assert cand_001_row['verdict'] == 'BUY_CANDIDATE'
        assert cand_001_row['ward_discount_pct'] == '-18.5'
        assert cand_001_row['price'] == '50000000'
        assert cand_001_row['size_sqm'] == '60.5'
        assert cand_001_row['ward'] == 'Shibuya'


class TestDigestPackaging:
    """Test complete digest package generation."""
    
    def test_digest_package_structure(self, sample_candidates, sample_snapshots):
        """Test digest package contains all required elements."""
        package = generate_daily_digest(sample_candidates, sample_snapshots)
        
        assert isinstance(package, dict)
        assert 'html' in package
        assert 'csv' in package
        assert 'date' in package
        assert 'candidate_count' in package
        
        assert package['candidate_count'] == 3
        assert len(package['date']) == 10  # YYYY-MM-DD format
    
    def test_package_content_consistency(self, sample_candidates, sample_snapshots):
        """Test package HTML and CSV contain consistent data."""
        package = generate_daily_digest(sample_candidates, sample_snapshots)
        
        html = package['html']
        csv_content = package['csv']
        
        # Both should contain same candidate IDs
        assert 'CAND_001' in html and 'CAND_001' in csv_content
        assert 'CAND_002' in html and 'CAND_002' in csv_content
        assert 'CAND_003' in html and 'CAND_003' in csv_content
        
        # Both should show same candidate count
        assert 'Candidates Found: 3' in html
        assert len(csv_content.strip().split('\n')) == 4  # Header + 3 rows


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_single_candidate(self, digest_generator, sample_snapshots):
        """Test digest with single candidate."""
        single_candidate = [{
            'id': 'SOLO_001',
            'price': 40000000,
            'size_sqm': 50.0,
            'price_per_sqm': 800000,
            'ward': 'Shibuya',
            'building_age_years': 10,
            'nearest_station_meters': 300,
            'components': {
                'final_score': 78.0,
                'verdict': type('MockVerdict', (), {'value': 'BUY_CANDIDATE'})(),
                'ward_discount_pct': -20.0
            }
        }]
        
        html = digest_generator.generate_html_digest(single_candidate, sample_snapshots)
        csv_content = digest_generator.generate_csv_digest(single_candidate)
        
        assert 'Candidates Found: 1' in html
        assert 'SOLO_001' in html
        assert 'SOLO_001' in csv_content
    
    def test_missing_snapshot_data(self, digest_generator, sample_candidates):
        """Test digest with missing snapshot data."""
        empty_snapshots = {'global': {}, 'wards': {}}
        
        html = digest_generator.generate_html_digest(sample_candidates, empty_snapshots)
        
        # Should handle missing data gracefully
        assert 'Market Summary' in html
        assert 'Candidates Found: 3' in html
        # Should show 0 or N/A for missing market data
        assert '¥0' in html or 'N/A' in html
    
    def test_large_candidate_list(self, digest_generator, sample_snapshots):
        """Test digest with many candidates (should limit display)."""
        # Create 15 candidates
        many_candidates = []
        for i in range(15):
            candidate = {
                'id': f'CAND_{i:03d}',
                'price': 40000000 + i * 1000000,
                'size_sqm': 50.0 + i,
                'price_per_sqm': 800000 + i * 10000,
                'ward': 'Shibuya',
                'building_age_years': 10 + i,
                'nearest_station_meters': 300 + i * 50,
                'components': {
                    'final_score': 80.0 - i,  # Descending scores
                    'verdict': type('MockVerdict', (), {'value': 'BUY_CANDIDATE'})(),
                    'ward_discount_pct': -15.0 - i
                }
            }
            many_candidates.append(candidate)
        
        html = digest_generator.generate_html_digest(many_candidates, sample_snapshots)
        
        # Should show correct total count
        assert 'Candidates Found: 15' in html
        
        # But should only display top 10 in table (count table rows)
        table_rows = html.count('<tr class="candidate-row">')
        assert table_rows <= 10
        
        # Should show highest scoring candidates first
        assert 'CAND_000' in html  # Highest score (80.0)
        assert 'CAND_001' in html  # Second highest (79.0)
    
    def test_missing_candidate_fields(self, digest_generator, sample_snapshots):
        """Test handling candidates with missing fields."""
        incomplete_candidate = [{
            'id': 'INCOMPLETE_001',
            # Missing most fields
            'components': {
                'final_score': 70.0,
                'verdict': type('MockVerdict', (), {'value': 'WATCH'})(),
                'ward_discount_pct': -8.0
            }
        }]
        
        html = digest_generator.generate_html_digest(incomplete_candidate, sample_snapshots)
        csv_content = digest_generator.generate_csv_digest(incomplete_candidate)
        
        # Should handle missing data gracefully
        assert 'INCOMPLETE_001' in html
        assert 'INCOMPLETE_001' in csv_content
        assert 'N/A' in html  # Should show N/A for missing fields
    
    def test_special_characters_handling(self, digest_generator, sample_snapshots):
        """Test handling of special characters in data."""
        special_candidate = [{
            'id': 'SPECIAL_001',
            'price': 45000000,
            'size_sqm': 55.0,
            'price_per_sqm': 818182,
            'ward': 'Shibuya-ku',  # Contains hyphen
            'building_age_years': 8,
            'nearest_station_meters': 400,
            'components': {
                'final_score': 75.0,
                'verdict': type('MockVerdict', (), {'value': 'BUY_CANDIDATE'})(),
                'ward_discount_pct': -12.5
            }
        }]
        
        html = digest_generator.generate_html_digest(special_candidate, sample_snapshots)
        csv_content = digest_generator.generate_csv_digest(special_candidate)
        
        # Should handle special characters properly
        assert 'Shibuya-ku' in html
        assert 'Shibuya-ku' in csv_content
        assert 'SPECIAL_001' in html and 'SPECIAL_001' in csv_content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])