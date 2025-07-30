"""
Basic condition inference from image filenames for Lean v1.3.

This is a simple stub implementation that infers property condition 
based on image filename patterns. More sophisticated image analysis
could be added later if needed.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import re

logger = logging.getLogger(__name__)


@dataclass
class VisionAnalysis:
    """Results of basic vision analysis from filenames."""
    positive_factors: List[str]
    negative_factors: List[str]
    condition_score: int  # 0-10 scale
    confidence: float     # 0-1 scale
    

class VisionStub:
    """Basic condition inference from image filename patterns."""
    
    # Keywords that suggest positive condition
    POSITIVE_KEYWORDS = {
        'renovated': 2,
        'new': 2,
        'modern': 2,
        'updated': 1,
        'clean': 1,
        'bright': 1,
        'spacious': 1,
        'luxury': 2,
        'premium': 2,
        'beautiful': 1,
        'furnished': 1,
        'kitchen': 1,  # Well-photographed kitchen often indicates good condition
        'living': 1    # Well-lit living space
    }
    
    # Keywords that suggest negative condition or issues
    NEGATIVE_KEYWORDS = {
        'damaged': -2,
        'old': -1,
        'worn': -1,
        'needs_work': -2,
        'repair': -2,
        'fix': -1,
        'crack': -2,
        'stain': -1,
        'dirty': -1,
        'dark': -1,
        'small': -1,
        'narrow': -1,
        'basement': -1,  # Basement units often less desirable
        'storage': -1    # Too many storage photos might indicate tight space
    }
    
    def analyze_from_filenames(self, image_urls: List[str]) -> VisionAnalysis:
        """
        Perform basic condition analysis from image filenames.
        Limited to first 3 images as per Lean v1.3 spec.
        
        Args:
            image_urls: List of S3 image URLs or filenames
            
        Returns:
            VisionAnalysis with inferred condition factors
        """
        if not image_urls:
            return VisionAnalysis(
                positive_factors=[],
                negative_factors=[],
                condition_score=5,  # Neutral default
                confidence=0.0
            )
        
        # Limit to first 3 images as per Lean v1.3 spec
        limited_image_urls = image_urls[:3]
        
        positive_factors = []
        negative_factors = []
        total_score = 0
        matches_found = 0
        
        logger.info(f"Analyzing {len(limited_image_urls)} image filenames for condition indicators (limited from {len(image_urls)} total)")
        
        for url in limited_image_urls:
            # Extract filename from URL
            filename = url.split('/')[-1].lower()
            # Remove file extensions and URL encoding
            clean_name = re.sub(r'\.(jpg|jpeg|png|gif|webp)$', '', filename)
            clean_name = clean_name.replace('%20', ' ').replace('_', ' ').replace('-', ' ')
            
            logger.debug(f"Analyzing filename: {clean_name}")
            
            # Check for positive indicators
            for keyword, score in self.POSITIVE_KEYWORDS.items():
                if keyword in clean_name:
                    factor = f"Positive: {keyword} in image filename"
                    if factor not in positive_factors:  # Avoid duplicates
                        positive_factors.append(factor)
                        total_score += score
                        matches_found += 1
                    break  # Only one positive per image
            
            # Check for negative indicators
            for keyword, score in self.NEGATIVE_KEYWORDS.items():
                if keyword in clean_name:
                    factor = f"Negative: {keyword} in image filename"
                    if factor not in negative_factors:  # Avoid duplicates
                        negative_factors.append(factor)
                        total_score += score  # score is already negative
                        matches_found += 1
                    break  # Only one negative per image
        
        # Calculate condition score (0-10 scale)
        if matches_found > 0:
            # Base score of 5, adjusted by findings
            base_score = 5
            adjustment = total_score / max(1, matches_found) * 2  # Scale adjustment
            condition_score = max(0, min(10, base_score + adjustment))
            confidence = min(1.0, matches_found / len(limited_image_urls))
        else:
            condition_score = 5  # Neutral if no indicators found
            confidence = 0.0
        
        # Cap the number of factors for LLM consumption
        positive_factors = positive_factors[:5]  # Max 5 positive
        negative_factors = negative_factors[:5]  # Max 5 negative
        
        analysis = VisionAnalysis(
            positive_factors=positive_factors,
            negative_factors=negative_factors,
            condition_score=int(condition_score),
            confidence=round(confidence, 2)
        )
        
        logger.info(f"Vision analysis complete: {len(positive_factors)} positive, "
                   f"{len(negative_factors)} negative factors. Score: {condition_score}/10")
        
        return analysis
    
    def analyze_room_types(self, image_urls: List[str]) -> Dict[str, int]:
        """
        Count different room types from image filenames.
        Limited to first 3 images as per Lean v1.3 spec.
        
        Args:
            image_urls: List of image URLs
            
        Returns:
            Dictionary with room type counts
        """
        room_types = {
            'living': 0,
            'bedroom': 0, 
            'kitchen': 0,
            'bathroom': 0,
            'dining': 0,
            'balcony': 0,
            'exterior': 0,
            'entrance': 0,
            'storage': 0,
            'other': 0
        }
        
        room_keywords = {
            'living': ['living', 'lounge', 'family_room'],
            'bedroom': ['bedroom', 'bed_room', 'master', 'guest_room'],
            'kitchen': ['kitchen', 'cooking', 'dining_kitchen'],
            'bathroom': ['bathroom', 'bath', 'toilet', 'wash', 'shower'],
            'dining': ['dining', 'dining_room'],
            'balcony': ['balcony', 'terrace', 'patio', 'outdoor'],
            'exterior': ['exterior', 'outside', 'building', 'entrance_hall'],
            'entrance': ['entrance', 'entry', 'foyer', 'genkan'],
            'storage': ['storage', 'closet', 'wardrobe', 'pantry']
        }
        
        # Limit to first 3 images as per Lean v1.3 spec
        limited_image_urls = image_urls[:3]
        
        for url in limited_image_urls:
            filename = url.split('/')[-1].lower()
            clean_name = re.sub(r'\.(jpg|jpeg|png|gif|webp)$', '', filename)
            clean_name = clean_name.replace('%20', ' ').replace('_', ' ')
            
            categorized = False
            for room_type, keywords in room_keywords.items():
                if any(keyword in clean_name for keyword in keywords):
                    room_types[room_type] += 1
                    categorized = True
                    break
            
            if not categorized:
                room_types['other'] += 1
        
        return room_types


# Convenience functions
def analyze_property_images(image_urls: List[str]) -> Dict[str, Any]:
    """
    Analyze property images and return vision analysis data.
    Limited to first 3 images as per Lean v1.3 spec.
    
    Args:
        image_urls: List of image URLs
        
    Returns:
        Dictionary with vision analysis results
    """
    # Limit to first 3 images as per Lean v1.3 spec
    limited_image_urls = image_urls[:3]
    
    vision = VisionStub()
    analysis = vision.analyze_from_filenames(limited_image_urls)
    room_counts = vision.analyze_room_types(limited_image_urls)
    
    return {
        'vision_analysis': {
            'positive_factors': analysis.positive_factors,
            'negative_factors': analysis.negative_factors,
            'condition_score': analysis.condition_score,
            'confidence': analysis.confidence
        },
        'room_analysis': room_counts,
        'total_images': len(image_urls),  # Report original count
        'analyzed_images': len(limited_image_urls)  # Report analyzed count
    }


def generate_vision_summary(property_data: Dict[str, Any], bucket: str, max_tokens: int = 80) -> str:
    """
    Generate a concise vision summary for lean prompt (≤80 tokens).
    
    Args:
        property_data: Property data with image information
        bucket: S3 bucket name (unused in stub, for compatibility)
        max_tokens: Maximum tokens to generate
        
    Returns:
        Brief vision summary string
    """
    # Get image URLs
    image_urls = (
        property_data.get('uploaded_image_urls', []) or
        property_data.get('image_urls', []) or
        property_data.get('interior_photos', []) or
        []
    )
    
    if not image_urls:
        return "No images available for condition assessment"
    
    # Limit to first 3 images as per Lean v1.3 spec
    limited_image_urls = image_urls[:3]
    
    # Perform quick analysis
    vision = VisionStub()
    analysis = vision.analyze_from_filenames(limited_image_urls)
    room_counts = vision.analyze_room_types(limited_image_urls)
    
    # Build concise summary
    parts = []
    
    # Image count (show limited count)
    if len(image_urls) > 3:
        parts.append(f"{len(limited_image_urls)} images (of {len(image_urls)} total)")
    else:
        parts.append(f"{len(limited_image_urls)} images")
    
    # Room diversity
    room_types_with_images = sum(1 for count in room_counts.values() if count > 0)
    if room_types_with_images >= 4:
        parts.append("good room coverage")
    elif room_types_with_images >= 2:
        parts.append("basic room coverage")
    
    # Condition indicators
    if len(analysis.positive_factors) > 0:
        parts.append("positive indicators")
    if len(analysis.negative_factors) > 0:
        parts.append("some concerns")
    
    # Overall condition assessment based on building age and analysis
    age = property_data.get('building_age_years', 30)
    if analysis.condition_score >= 7:
        parts.append("appears well-maintained")
    elif analysis.condition_score <= 3:
        parts.append("may need attention")
    elif age <= 10:
        parts.append("modern construction")
    elif age >= 30:
        parts.append("mature property")
    
    # Join parts and ensure we're under token limit
    summary = ", ".join(parts)
    
    # Rough token estimation and truncation (4 chars per token)
    max_chars = max_tokens * 4
    if len(summary) > max_chars:
        summary = summary[:max_chars-3] + "..."
    
    return summary


def basic_condition_from_images(filenames: List[str]) -> Dict[str, Any]:
    """
    Infer condition_category and damage_tokens from image filenames per Lean v1.3 spec.
    
    Rules:
    - If any filename contains 'kitchen_new' -> modern
    - If 'renovation' in any -> modern  
    - Else if 'kitchen' or 'bath' -> partial
    - Else dated
    - damage_tokens if filenames contain stain|mold|crack|wear|old etc.
    
    Args:
        filenames: List of image filenames (only first 3 are used)
        
    Returns:
        Dict with keys: condition_category, damage_tokens, summary, light
    """
    # Use only first 3 images as per Lean v1.3 spec
    limited_filenames = filenames[:3] if filenames else []
    
    if not limited_filenames:
        return {
            'condition_category': 'dated',
            'damage_tokens': [],
            'summary': 'No images available for condition assessment',
            'light': False
        }
    
    logger.debug(f"Analyzing {len(limited_filenames)} filenames for basic condition inference")
    
    # Extract and clean filenames
    clean_names = []
    for filename in limited_filenames:
        # Extract filename from URL/path and normalize
        clean_name = filename.split('/')[-1].lower()
        clean_name = re.sub(r'\.(jpg|jpeg|png|gif|webp)$', '', clean_name)
        clean_name = clean_name.replace('%20', ' ').replace('_', ' ').replace('-', ' ')
        clean_names.append(clean_name)
    
    # Determine condition_category using exact rules from spec
    condition_category = 'dated'  # default
    
    for name in clean_names:
        if 'kitchen_new' in name:
            condition_category = 'modern'
            break
        elif 'renovation' in name:
            condition_category = 'modern'
            break
    
    # If not modern, check for partial indicators
    if condition_category == 'dated':
        for name in clean_names:
            if 'kitchen' in name or 'bath' in name:
                condition_category = 'partial'
                break
    
    # Look for damage tokens
    damage_keywords = [
        'stain', 'mold', 'crack', 'wear', 'old', 'damaged', 'worn',
        'repair', 'fix', 'dirty', 'leak', 'scratch', 'dent', 'fade'
    ]
    
    damage_tokens = []
    for name in clean_names:
        for keyword in damage_keywords:
            if keyword in name and keyword not in damage_tokens:
                damage_tokens.append(keyword)
    
    # Infer lighting from filenames (for vision_positive calculation)
    light_keywords = ['bright', 'light', 'sunny', 'window', 'natural_light', 'spacious']
    light = any(keyword in name for name in clean_names for keyword in light_keywords)
    
    # Create summary
    if condition_category == 'modern':
        summary = f"Modern condition inferred from {len(limited_filenames)} images"
    elif condition_category == 'partial':
        summary = f"Partial renovation inferred from kitchen/bath images"
    else:
        summary = f"Dated condition inferred from {len(limited_filenames)} images"
    
    if damage_tokens:
        summary += f", {len(damage_tokens)} damage indicators found"
    if light:
        summary += ", good lighting detected"
    
    result = {
        'condition_category': condition_category,
        'damage_tokens': damage_tokens,
        'summary': summary,
        'light': light
    }
    
    logger.info(f"Basic condition analysis: {condition_category}, "
               f"{len(damage_tokens)} damage tokens: {damage_tokens}, light: {light}")
    
    return result


def get_vision_scores(vision_data: Dict[str, Any]) -> Dict[str, float]:
    """
    Calculate vision_positive and vision_negative scores from vision data.
    This implements the vision scoring logic from lean_scoring.py for compatibility.
    
    Args:
        vision_data: Vision analysis dict with condition_category, damage_tokens, light
        
    Returns:
        Dict with vision_positive and vision_negative scores
    """
    condition_category = vision_data.get('condition_category', 'dated')
    damage_tokens = vision_data.get('damage_tokens', [])
    light = vision_data.get('light', False)
    
    # Vision Positive: if condition=modern & light=True -> +5
    vision_positive = 5.0 if (condition_category == 'modern' and light) else 0.0
    
    # Vision Negative: severe defects
    num_damage = len(damage_tokens)
    has_stain = any('stain' in token.lower() for token in damage_tokens)
    has_mold = any('mold' in token.lower() for token in damage_tokens)
    
    if num_damage >= 2 or (has_stain and has_mold):
        vision_negative = -5.0
    elif num_damage >= 1:
        vision_negative = -2.0
    else:
        vision_negative = 0.0
    
    return {
        'vision_positive': vision_positive,
        'vision_negative': vision_negative
    }


def enrich_property_with_vision(property_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enrich property data with vision analysis from image URLs.
    
    Args:
        property_data: Property dictionary with image_urls or uploaded_image_urls
        
    Returns:
        Enhanced property dictionary with vision data
    """
    # Get image URLs from various possible fields
    image_urls = (
        property_data.get('uploaded_image_urls', []) or
        property_data.get('image_urls', []) or
        property_data.get('interior_photos', []) or
        []
    )
    
    if not image_urls:
        # Return minimal vision data if no images
        return {
            **property_data,
            'vision_analysis': {
                'positive_factors': [],
                'negative_factors': [],
                'condition_score': 5,
                'confidence': 0.0
            },
            'room_analysis': {},
            'total_images': 0,
            'analyzed_images': 0
        }
    
    # Perform analysis (analyze_property_images already limits to 3 images)
    vision_data = analyze_property_images(image_urls)
    
    # Merge with existing property data
    enhanced_property = property_data.copy()
    enhanced_property.update(vision_data)
    
    return enhanced_property