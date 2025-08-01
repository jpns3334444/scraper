#!/usr/bin/env python3
"""
Test cases for the overview parser refactor
"""
import pytest
from bs4 import BeautifulSoup
import sys
import os

# Add the lambda directory to Python path so we can import the module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda', 'property_processor'))

from core_scraper import parse_overview_section, normalize_overview, parse_floor_info, ORI_MAP, OVERVIEW_FIELD_MAP

def test_parse_floor_info():
    """Test floor parsing with various Japanese formats"""
    # Test case from sample data: 5階 / 10階建 (地下1階)
    floor, total = parse_floor_info("5階 / 10階建 (地下1階)")
    assert floor == 5
    assert total == 10
    
    # Test other formats
    floor, total = parse_floor_info("3階/6階建")
    assert floor == 3
    assert total == 6
    
    floor, total = parse_floor_info("2階建")
    assert floor is None
    assert total == 2
    
    floor, total = parse_floor_info("7階")
    assert floor == 7
    assert total is None

def test_orientation_mapping():
    """Test orientation mapping from Japanese to English"""
    assert ORI_MAP["南"] == "south"
    assert ORI_MAP["北"] == "north"
    assert ORI_MAP["南東"] == "south-east"
    assert ORI_MAP["北西"] == "north-west"

def test_field_mapping():
    """Test field mapping constants"""
    assert OVERVIEW_FIELD_MAP["所在階 / 階数"] == "floor_info"
    assert OVERVIEW_FIELD_MAP["主要採光面"] == "orientation_ja"
    assert OVERVIEW_FIELD_MAP["専有面積"] == "size_text"
    assert OVERVIEW_FIELD_MAP["築年数"] == "built_text"

def test_parse_overview_section_css_grid():
    """Test parsing CSS Grid-based property overview"""
    # Create sample HTML with CSS Grid structure (similar to LIFULL HOME'S)
    html_content = """
    <div class="grid grid-cols-max1fr gap-x-2 gap-y-3">
        <span class="text-base">築年数</span>
        <div class="text-base">築56年</div>
        <span class="text-base">専有面積</span>
        <span class="text-base" data-component="occupiedArea">33.57㎡(内法)</span>
        <span class="text-base">バルコニー面積</span>
        <span class="text-base">5㎡</span>
        <span class="text-base">主要採光面</span>
        <span class="text-base">南</span>
        <span class="text-base">所在階 / 階数</span>
        <span class="text-base">5階 / 10階建</span>
    </div>
    """
    
    soup = BeautifulSoup(html_content, 'html.parser')
    overview = parse_overview_section(soup)
    
    # Verify extraction
    assert "築年数" in overview
    assert overview["築年数"] == "築56年"
    assert "専有面積" in overview
    assert overview["専有面積"] == "33.57㎡(内法)"
    assert "主要採光面" in overview
    assert overview["主要採光面"] == "南"
    assert "所在階 / 階数" in overview
    assert overview["所在階 / 階数"] == "5階 / 10階建"

def test_normalize_overview():
    """Test normalization of overview data"""
    overview = {
        "築年数": "築56年",
        "専有面積": "33.57㎡(内法)",
        "主要採光面": "南",
        "所在階 / 階数": "5階 / 10階建",
        "交通": "中野坂上駅徒歩5分"
    }
    
    mapped = normalize_overview(overview)
    
    # Check mapping
    assert mapped["built_text"] == "築56年"
    assert mapped["size_text"] == "33.57㎡(内法)"
    assert mapped["orientation_ja"] == "南"
    assert mapped["orientation"] == "south"
    assert mapped["floor_info"] == "5階 / 10階建"
    assert mapped["floor"] == 5
    assert mapped["building_floors"] == 10
    assert mapped["station_info"] == "中野坂上駅徒歩5分"

def test_empty_overview():
    """Test handling of empty overview data"""
    overview = {}
    mapped = normalize_overview(overview)
    assert isinstance(mapped, dict)
    assert len(mapped) == 0

def test_partial_data():
    """Test handling of incomplete data"""
    overview = {
        "専有面積": "33.57㎡",
        "築年数": "築56年"
    }
    
    mapped = normalize_overview(overview)
    assert mapped["size_text"] == "33.57㎡"
    assert mapped["built_text"] == "築56年"
    assert "orientation" not in mapped
    assert "floor" not in mapped

if __name__ == "__main__":
    # Run basic tests
    test_parse_floor_info()
    test_orientation_mapping()
    test_field_mapping()
    test_normalize_overview()
    test_empty_overview()
    test_partial_data()
    print("All tests passed!")