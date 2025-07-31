"""
Data models and schemas for Lean v1.3 pipeline.

This module defines data classes and validation schemas for:
- Property listings and analysis results
- Market snapshots (global and ward-level)
- Daily digest data structures
- LLM analysis outputs
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from analysis.lean_scoring import Verdict


@dataclass
class PropertyListing:
    """Property listing data structure."""
    property_id: str
    price: float
    total_sqm: float
    price_per_sqm: float
    address: str
    
    # Optional fields commonly available
    ward: Optional[str] = None
    district: Optional[str] = None
    building_age_years: Optional[int] = None
    property_type: Optional[str] = None
    num_bedrooms: Optional[int] = None
    station_distance_minutes: Optional[int] = None
    listing_url: Optional[str] = None
    image_urls: List[str] = field(default_factory=list)
    
    # Status and timestamps
    status: str = "active"
    scraped_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    # Additional attributes
    price_history: List[Dict[str, Any]] = field(default_factory=list)
    amenity_score: Optional[float] = None
    expected_monthly_rent: Optional[float] = None
    total_monthly_costs: Optional[float] = None


@dataclass
class PropertyAnalysis:
    """Complete property analysis result."""
    property_id: str
    analysis_date: str
    
    # Core scoring results
    final_score: float
    verdict: Verdict
    ward_discount_pct: float
    
    # Scoring breakdown
    base_score: float
    addon_score: float
    adjustment_score: float
    data_quality_penalty: float
    
    # Market context
    ward_avg_price_per_sqm: Optional[float] = None
    building_avg_price_per_sqm: Optional[float] = None
    num_comparables: int = 0
    comparable_price_variance: float = 0.0
    
    # LLM analysis (only for candidates)
    llm_analysis: Optional[Dict[str, Any]] = None
    
    # Source property data
    property_data: Optional[PropertyListing] = None


@dataclass
class LLMAnalysis:
    """LLM qualitative analysis output."""
    upsides: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    justification: str = ""
    
    # Metadata
    model_used: str = ""
    tokens_used: int = 0
    analysis_timestamp: Optional[datetime] = None
    schema_validated: bool = False


@dataclass
class GlobalSnapshot:
    """Global market snapshot."""
    date: str
    median_price_per_sqm: float
    total_active: int
    seven_day_change_pp: float = 0.0
    
    # Percentiles
    p25: float = 0.0
    p50: float = 0.0
    p75: float = 0.0
    p90: float = 0.0
    
    # Summary stats
    min_price_per_sqm: float = 0.0
    max_price_per_sqm: float = 0.0
    avg_size_sqm: float = 0.0


@dataclass
class WardSnapshot:
    """Ward-specific market snapshot."""
    date: str
    ward: str
    median_price_per_sqm: float
    inventory: int
    
    # Percentiles
    p25: float = 0.0
    p50: float = 0.0
    p75: float = 0.0
    
    # Summary stats
    min_price_per_sqm: float = 0.0
    max_price_per_sqm: float = 0.0
    avg_size_sqm: float = 0.0
    property_types: Dict[str, int] = field(default_factory=dict)


@dataclass
class DailyDigestData:
    """Daily digest data structure."""
    date: str
    
    # Candidate counts
    total_candidates: int
    buy_candidates: int
    watch_candidates: int
    
    # Market context
    global_snapshot: Optional[GlobalSnapshot] = None
    
    # Top candidates for email
    top_buy_candidates: List[PropertyAnalysis] = field(default_factory=list)
    watch_summary: Dict[str, Any] = field(default_factory=dict)
    
    # Generation metadata
    generated_at: Optional[datetime] = None
    email_sent: bool = False
    files_saved: List[str] = field(default_factory=list)


@dataclass
class PipelineMetrics:
    """Pipeline execution metrics."""
    date: str
    
    # Processing counts
    properties_processed: int = 0
    candidates_enqueued: int = 0
    candidates_suppressed: int = 0
    
    # LLM metrics
    llm_calls: int = 0
    llm_tokens_used: int = 0
    llm_schema_failures: int = 0
    llm_retries: int = 0
    
    # Snapshot metrics
    snapshots_generated: int = 0
    wards_processed: int = 0
    
    # Digest metrics
    digests_sent: int = 0
    email_recipients: int = 0
    
    # Error tracking
    error_count: int = 0
    warnings_count: int = 0
    
    # Timing
    execution_time_seconds: Optional[float] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# JSON Schema definitions for validation
PROPERTY_LISTING_SCHEMA = {
    "type": "object",
    "required": ["property_id", "price", "total_sqm", "price_per_sqm", "address"],
    "properties": {
        "property_id": {"type": "string"},
        "price": {"type": "number", "minimum": 0},
        "total_sqm": {"type": "number", "minimum": 0},
        "price_per_sqm": {"type": "number", "minimum": 0},
        "address": {"type": "string"},
        "ward": {"type": ["string", "null"]},
        "building_age_years": {"type": ["integer", "null"], "minimum": 0},
        "property_type": {"type": ["string", "null"]},
        "status": {"type": "string", "enum": ["active", "sold", "removed"]},
        "image_urls": {"type": "array", "items": {"type": "string"}}
    }
}

LLM_ANALYSIS_SCHEMA = {
    "type": "object",
    "required": ["upsides", "risks", "justification"],
    "properties": {
        "upsides": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 3
        },
        "risks": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 3
        },
        "justification": {
            "type": "string",
            "minLength": 10,
            "maxLength": 500
        }
    }
}

GLOBAL_SNAPSHOT_SCHEMA = {
    "type": "object",
    "required": ["date", "median_price_per_sqm", "total_active"],
    "properties": {
        "date": {"type": "string", "format": "date"},
        "median_price_per_sqm": {"type": "number", "minimum": 0},
        "total_active": {"type": "integer", "minimum": 0},
        "seven_day_change_pp": {"type": "number"},
        "p25": {"type": "number", "minimum": 0},
        "p50": {"type": "number", "minimum": 0},
        "p75": {"type": "number", "minimum": 0},
        "p90": {"type": "number", "minimum": 0}
    }
}

WARD_SNAPSHOT_SCHEMA = {
    "type": "object",
    "required": ["date", "ward", "median_price_per_sqm", "inventory"],
    "properties": {
        "date": {"type": "string", "format": "date"},
        "ward": {"type": "string"},
        "median_price_per_sqm": {"type": "number", "minimum": 0},
        "inventory": {"type": "integer", "minimum": 0},
        "p25": {"type": "number", "minimum": 0},
        "p50": {"type": "number", "minimum": 0},
        "p75": {"type": "number", "minimum": 0}
    }
}


# Validation functions
def validate_property_listing(data: Dict[str, Any]) -> bool:
    """Validate property listing data against schema."""
    import jsonschema
    try:
        jsonschema.validate(data, PROPERTY_LISTING_SCHEMA)
        return True
    except jsonschema.ValidationError:
        return False


def validate_llm_analysis(data: Dict[str, Any]) -> bool:
    """Validate LLM analysis output against schema."""
    import jsonschema
    try:
        jsonschema.validate(data, LLM_ANALYSIS_SCHEMA)
        return True
    except jsonschema.ValidationError:
        return False


def validate_snapshot(data: Dict[str, Any], snapshot_type: str = "global") -> bool:
    """Validate snapshot data against schema."""
    import jsonschema
    try:
        schema = GLOBAL_SNAPSHOT_SCHEMA if snapshot_type == "global" else WARD_SNAPSHOT_SCHEMA
        jsonschema.validate(data, schema)
        return True
    except jsonschema.ValidationError:
        return False


# Legacy compatibility classes
class Property:
    """Legacy class for backward compatibility."""
    
    def __init__(self, data: Optional[Dict[str, Any]] = None):
        if data:
            self.data = data
            # Convert to PropertyListing if needed
            self.listing = PropertyListing(**{
                k: v for k, v in data.items() 
                if k in PropertyListing.__dataclass_fields__
            })
        else:
            self.data = {}
            self.listing = PropertyListing(
                property_id="", price=0, total_sqm=0, 
                price_per_sqm=0, address=""
            )


class Analysis:
    """Legacy class for backward compatibility."""
    
    def __init__(self, data: Optional[Dict[str, Any]] = None):
        if data:
            self.data = data
            # Convert to PropertyAnalysis if needed
            self.analysis = PropertyAnalysis(
                property_id=data.get('property_id', ''),
                analysis_date=data.get('analysis_date', ''),
                final_score=data.get('final_score', 0),
                verdict=data.get('verdict', Verdict.REJECT),
                ward_discount_pct=data.get('ward_discount_pct', 0),
                base_score=data.get('base_score', 0),
                addon_score=data.get('addon_score', 0),
                adjustment_score=data.get('adjustment_score', 0),
                data_quality_penalty=data.get('data_quality_penalty', 0)
            )
        else:
            self.data = {}
            self.analysis = PropertyAnalysis(
                property_id="", analysis_date="", final_score=0,
                verdict=Verdict.REJECT, ward_discount_pct=0,
                base_score=0, addon_score=0, adjustment_score=0,
                data_quality_penalty=0
            )