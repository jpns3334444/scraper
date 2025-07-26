"""
Basic tests for the basic_condition_from_images function.
"""

import pytest
from analysis.vision_stub import basic_condition_from_images, get_vision_scores


def test_basic_condition_from_images_modern_kitchen_new():
    """Test that kitchen_new filename results in modern condition."""
    filenames = ['property_123/kitchen_new_renovation.jpg']
    result = basic_condition_from_images(filenames)
    
    assert result['condition_category'] == 'modern'
    assert result['damage_tokens'] == []
    assert 'Modern condition' in result['summary']
    assert result['light'] == False


def test_basic_condition_from_images_modern_renovation():
    """Test that renovation filename results in modern condition."""
    filenames = ['property_456/living_room_renovation_complete.jpg']
    result = basic_condition_from_images(filenames)
    
    assert result['condition_category'] == 'modern'
    assert result['damage_tokens'] == []
    assert 'Modern condition' in result['summary']


def test_basic_condition_from_images_partial_kitchen():
    """Test that kitchen filename without 'new' results in partial condition."""
    filenames = ['property_789/kitchen_area_bright.jpg']
    result = basic_condition_from_images(filenames)
    
    assert result['condition_category'] == 'partial'
    assert result['damage_tokens'] == []
    assert 'Partial renovation' in result['summary']
    assert result['light'] == True  # 'bright' keyword


def test_basic_condition_from_images_partial_bath():
    """Test that bath filename results in partial condition."""
    filenames = ['property_012/bathroom_clean.jpg']
    result = basic_condition_from_images(filenames)
    
    assert result['condition_category'] == 'partial'
    assert result['damage_tokens'] == []
    assert 'Partial renovation' in result['summary']


def test_basic_condition_from_images_dated_default():
    """Test that other filenames default to dated condition."""
    filenames = ['property_345/living_room_standard.jpg']
    result = basic_condition_from_images(filenames)
    
    assert result['condition_category'] == 'dated'
    assert result['damage_tokens'] == []
    assert 'Dated condition' in result['summary']


def test_basic_condition_from_images_damage_tokens():
    """Test extraction of damage tokens from filenames."""
    filenames = [
        'property_678/kitchen_stain_visible.jpg',
        'property_678/bathroom_old_wear.jpg', 
        'property_678/living_mold_issue.jpg'
    ]
    result = basic_condition_from_images(filenames)
    
    assert 'stain' in result['damage_tokens']
    assert 'old' in result['damage_tokens'] 
    assert 'wear' in result['damage_tokens']
    assert 'mold' in result['damage_tokens']
    assert len(result['damage_tokens']) == 4
    assert 'damage indicators found' in result['summary']


def test_basic_condition_from_images_light_detection():
    """Test detection of lighting keywords."""
    filenames = ['property_901/living_room_bright_window.jpg']
    result = basic_condition_from_images(filenames)
    
    assert result['light'] == True
    assert 'good lighting detected' in result['summary']


def test_basic_condition_from_images_max_3_images():
    """Test that only first 3 images are processed."""
    filenames = [
        'kitchen_new.jpg',  # modern condition
        'extra1.jpg',
        'extra2.jpg', 
        'bathroom_stain.jpg'  # this would add damage token if processed
    ]
    result = basic_condition_from_images(filenames)
    
    # Should be modern from first image, and shouldn't have stain damage token from 4th image
    assert result['condition_category'] == 'modern'
    assert 'stain' not in result['damage_tokens']


def test_basic_condition_from_images_empty_list():
    """Test handling of empty filename list."""
    result = basic_condition_from_images([])
    
    assert result['condition_category'] == 'dated'
    assert result['damage_tokens'] == []
    assert result['light'] == False
    assert 'No images available' in result['summary']


def test_get_vision_scores_modern_with_light():
    """Test vision scoring for modern condition with good lighting."""
    vision_data = {
        'condition_category': 'modern',
        'damage_tokens': [],
        'light': True
    }
    scores = get_vision_scores(vision_data)
    
    assert scores['vision_positive'] == 5.0
    assert scores['vision_negative'] == 0.0


def test_get_vision_scores_damage_tokens():
    """Test vision scoring with damage tokens."""
    vision_data = {
        'condition_category': 'partial',
        'damage_tokens': ['stain', 'mold'],
        'light': False
    }
    scores = get_vision_scores(vision_data)
    
    assert scores['vision_positive'] == 0.0
    assert scores['vision_negative'] == -5.0  # stain + mold = severe defect


def test_get_vision_scores_single_damage():
    """Test vision scoring with single damage token."""
    vision_data = {
        'condition_category': 'dated',
        'damage_tokens': ['wear'],
        'light': False
    }
    scores = get_vision_scores(vision_data)
    
    assert scores['vision_positive'] == 0.0
    assert scores['vision_negative'] == -2.0  # single damage token


def test_filename_normalization():
    """Test that various filename formats are normalized correctly."""
    filenames = [
        '/path/to/kitchen%20new%20renovation.jpg',
        'bathroom-old-stain.png',
        'living_room_bright_window.jpeg'
    ]
    result = basic_condition_from_images(filenames)
    
    assert result['condition_category'] == 'modern'  # from kitchen_new
    assert 'old' in result['damage_tokens']
    assert 'stain' in result['damage_tokens'] 
    assert result['light'] == True  # from bright