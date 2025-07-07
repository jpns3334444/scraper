#!/usr/bin/env python3
"""
Test script for multi-area Tokyo scraping functionality
This script tests the area discovery and distribution functions
"""

import os
import sys
import time
from datetime import datetime

# Add the current directory to Python path to import scrape module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import functions from the main scraper
from scrape import (
    discover_tokyo_areas, 
    get_daily_area_distribution,
    log_structured_message
)

def test_area_discovery():
    """Test the Tokyo area discovery function"""
    print("🔍 Testing Tokyo area discovery...")
    
    try:
        areas = discover_tokyo_areas()
        
        print(f"✅ Found {len(areas)} Tokyo areas:")
        for i, area in enumerate(areas, 1):
            print(f"   {i:2d}. {area}")
        
        return areas
    
    except Exception as e:
        print(f"❌ Area discovery failed: {e}")
        return []

def test_daily_distribution(areas):
    """Test the daily area distribution across sessions"""
    print(f"\n📅 Testing daily area distribution for {len(areas)} areas...")
    
    date_key = datetime.now().strftime('%Y-%m-%d')
    sessions = ['morning-1', 'morning-2', 'afternoon-1', 'afternoon-2', 
                'evening-1', 'evening-2', 'night-1', 'night-2']
    
    total_assigned = 0
    
    for session_id in sessions:
        assigned_areas = get_daily_area_distribution(areas, session_id, date_key)
        total_assigned += len(assigned_areas)
        
        print(f"   📍 {session_id}: {len(assigned_areas)} areas - {assigned_areas}")
    
    print(f"\n📊 Distribution Summary:")
    print(f"   Total Tokyo areas: {len(areas)}")
    print(f"   Total assigned: {total_assigned}")
    print(f"   Coverage: {total_assigned/len(areas)*100:.1f}%")
    
    # Test that all areas are covered
    all_assigned_areas = set()
    for session_id in sessions:
        assigned_areas = get_daily_area_distribution(areas, session_id, date_key)
        all_assigned_areas.update(assigned_areas)
    
    missed_areas = set(areas) - all_assigned_areas
    if missed_areas:
        print(f"   ⚠️  Missed areas: {missed_areas}")
    else:
        print(f"   ✅ All areas covered!")

def test_randomization_across_days():
    """Test that area assignments change across different days"""
    print(f"\n🎲 Testing randomization across days...")
    
    # Use a subset of areas for this test
    test_areas = ['shibuya-ku', 'shinjuku-ku', 'chofu-city', 'mitaka-city', 
                  'setagaya-ku', 'nerima-ku', 'minato-ku', 'chiyoda-ku']
    
    # Test assignments for 3 different dates
    test_dates = ['2025-01-01', '2025-01-02', '2025-01-03']
    
    for date in test_dates:
        print(f"\n   Date: {date}")
        for session in ['morning-1', 'afternoon-1']:
            assigned = get_daily_area_distribution(test_areas, session, date)
            print(f"     {session}: {assigned}")

def main():
    """Main test function"""
    print("🧪 Multi-Area Tokyo Scraper Test")
    print("=" * 40)
    
    # Test 1: Area Discovery
    areas = test_area_discovery()
    
    if not areas:
        print("❌ Cannot proceed with tests - no areas discovered")
        return
    
    # Test 2: Daily Distribution
    test_daily_distribution(areas)
    
    # Test 3: Randomization
    test_randomization_across_days()
    
    print(f"\n🎉 All tests completed!")
    print(f"\n💡 To test with stealth mode:")
    print(f"   export STEALTH_MODE=true")
    print(f"   export SESSION_ID=test-session")
    print(f"   export MAX_PROPERTIES=10")
    print(f"   python3 scrape.py")

if __name__ == "__main__":
    main()