#!/usr/bin/env python3
"""
Test the extraction functions on the actual HTML document
"""
import sys
import os
sys.path.append('/home/azure/Projects/real-estate-scraper/lambda/property_processor')

from bs4 import BeautifulSoup
from core_scraper import (
    parse_overview_section, 
    normalize_overview,
    parse_floor_info,
    parse_station_distance,
    parse_closest_station,
    OVERVIEW_FIELD_MAP
)

def test_extraction_on_real_html():
    """Test extraction on the real HTML document"""
    
    # Read the HTML file
    with open('/home/azure/Projects/real-estate-scraper/individual-homes-listing.html', 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    soup = BeautifulSoup(html_content, 'html.parser')
    
    print("=== Testing Extraction on Real HTML ===\n")
    
    # First, let's examine the CSS grid structure manually
    print("1. Examining CSS grid structure...")
    
    # Look for the grid container
    grid_containers = soup.select('div.grid.grid-cols-max1fr')
    print(f"   Found {len(grid_containers)} grid containers")
    
    for i, container in enumerate(grid_containers):
        print(f"\n   Grid container {i+1}:")
        
        # Get all child elements
        children = container.find_all(['span', 'div'], recursive=False)
        print(f"     Found {len(children)} direct children")
        
        # Try to pair them as label-value pairs
        pairs = []
        for j in range(0, len(children) - 1, 2):
            if j + 1 < len(children):
                label_elem = children[j]
                value_elem = children[j + 1]
                
                label = label_elem.get_text(strip=True)
                value = value_elem.get_text(" ", strip=True)
                
                pairs.append((label, value))
                print(f"       {label}: {value[:100]}{'...' if len(value) > 100 else ''}")
        
        print(f"     Successfully extracted {len(pairs)} pairs")
    
    # Test the overview parser
    print("\n2. Testing parse_overview_section()...")
    overview = parse_overview_section(soup)
    print(f"   Found {len(overview)} overview fields:")
    for key, value in list(overview.items())[:15]:  # Show first 15
        print(f"     {key}: {value[:100]}{'...' if len(value) > 100 else ''}")
    if len(overview) > 15:
        print(f"     ... and {len(overview) - 15} more")
    
    print("\n2. Testing normalize_overview()...")
    mapped = normalize_overview(overview)
    print(f"   Mapped to {len(mapped)} normalized fields:")
    for key, value in mapped.items():
        print(f"     {key}: {value}")
    
    # Test specific field extraction
    print("\n3. Testing specific field extraction...")
    
    # Test floor info
    floor_sources = []
    if '所在階 / 階数' in overview:
        floor_sources.append(('所在階 / 階数', overview['所在階 / 階数']))
    if '所在階' in overview:
        floor_sources.append(('所在階', overview['所在階']))
    if 'floor_info' in mapped:
        floor_sources.append(('mapped_floor_info', mapped['floor_info']))
    
    print("\n   Floor Info Testing:")
    for source_name, floor_text in floor_sources:
        if floor_text:
            floor, building_floors = parse_floor_info(floor_text)
            print(f"     {source_name}: '{floor_text}' -> Floor: {floor}, Building floors: {building_floors}")
    
    # Test station info
    station_sources = []
    if '交通' in overview:
        station_sources.append(('交通', overview['交通']))
    if '備考' in overview:
        station_sources.append(('備考', overview['備考']))
    if 'station_info' in mapped:
        station_sources.append(('mapped_station_info', mapped['station_info']))
    
    print("\n   Station Info Testing:")
    for source_name, station_text in station_sources:
        if station_text:
            distance = parse_station_distance(station_text)
            station = parse_closest_station(station_text)
            print(f"     {source_name}: '{station_text[:100]}...' -> Distance: {distance} min, Station: {station}")
    
    # Test primary light
    light_sources = []
    if '主要採光面' in overview:
        light_sources.append(('主要採光面', overview['主要採光面']))
    if '向き' in overview:
        light_sources.append(('向き', overview['向き']))
    if 'primary_light' in mapped:
        light_sources.append(('mapped_primary_light', mapped['primary_light']))
    
    print("\n   Primary Light Testing:")
    for source_name, light_text in light_sources:
        if light_text:
            print(f"     {source_name}: '{light_text}'")
    
    # Check if we can find the data in other ways
    print("\n4. Searching for missing data in HTML...")
    
    # Search for floor-related text
    all_text = soup.get_text()
    floor_matches = []
    import re
    
    # Look for floor patterns in all text
    floor_patterns = [
        r'(\d+階\s*/\s*\d+階建)',
        r'(所在階[^:：]*[:：][^。\n]*)',
        r'(階数[^:：]*[:：][^。\n]*)'
    ]
    
    for pattern in floor_patterns:
        matches = re.findall(pattern, all_text)
        floor_matches.extend(matches)
    
    if floor_matches:
        print("   Floor-related text found in HTML:")
        for match in floor_matches[:5]:  # Show first 5
            print(f"     '{match}'")
    
    # Look for station patterns
    station_patterns = [
        r'(徒歩\d+分[^。\n]*)',
        r'(\d+分の場所に駅[^。\n]*)',
        r'(JR[^。\n]*徒歩\d+分)'
    ]
    
    station_matches = []
    for pattern in station_patterns:
        matches = re.findall(pattern, all_text)
        station_matches.extend(matches)
    
    if station_matches:
        print("\n   Station-related text found in HTML:")
        for match in station_matches[:5]:  # Show first 5
            print(f"     '{match}'")
    
    # Look for light patterns
    light_patterns = [
        r'(主要採光面[^。\n]*)',
        r'(向き[^。\n]*)',
        r'([東西南北][東西南北]?向き)'
    ]
    
    light_matches = []
    for pattern in light_patterns:
        matches = re.findall(pattern, all_text)
        light_matches.extend(matches)
    
    if light_matches:
        print("\n   Light-related text found in HTML:")
        for match in light_matches[:5]:  # Show first 5
            print(f"     '{match}'")

if __name__ == "__main__":
    test_extraction_on_real_html()