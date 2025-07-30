"""
Global and ward snapshot generation for Lean v1.3.

This module generates daily snapshots of market conditions:
- Global: Overall market medians and inventory counts
- Ward: Per-ward medians and inventory with percentiles

Snapshots are stored as JSON files in S3 at snapshots/current/
and are used for market analysis and daily reporting.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

# Configuration helper - handle both local and lambda execution
def get_config():
    """Get configuration - with fallback for local testing."""
    try:
        # Try to dynamically import from the hyphenated directory
        import sys
        import importlib.util
        
        # Build path to config module
        config_path = os.path.join(os.path.dirname(__file__), '..', 'ai-infra', 'lambda', 'util', 'config.py')
        config_path = os.path.abspath(config_path)
        
        if os.path.exists(config_path):
            spec = importlib.util.spec_from_file_location("config", config_path)
            config_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(config_module)
            return config_module.get_config()
    except Exception:
        pass
    
    # Fallback for testing - create a minimal config
    class MockConfig:
        def get_str(self, key, default=''):
            return os.getenv(key, default)
        def is_lean_mode(self):
            return os.getenv('LEAN_MODE', '0').lower() in ('1', 'true')
    return MockConfig()

logger = logging.getLogger(__name__)


class SnapshotGenerator:
    """Generate global and ward-level market snapshots."""

    def __init__(self, s3_bucket: Optional[str] = None):
        """
        Initialize the snapshot generator.
        
        Args:
            s3_bucket: S3 bucket name, defaults to config OUTPUT_BUCKET
        """
        self.config = get_config()
        self.s3_bucket = s3_bucket or self.config.get_str('OUTPUT_BUCKET')
        self.s3_client = boto3.client('s3', region_name=self.config.get_str('AWS_REGION'))
        
    def generate_all_snapshots(self, date_str: Optional[str] = None) -> Dict[str, Any]:
        """
        Generate all snapshots (global + all wards).
        
        Args:
            date_str: Date string (YYYY-MM-DD), defaults to today
            
        Returns:
            Dictionary with generation results and metrics
        """
        if not date_str:
            date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            
        logger.info(f"Starting snapshot generation for {date_str}")
        
        results = {
            'date': date_str,
            'global_snapshot': None,
            'ward_snapshots': [],
            'metrics': {
                'global_generated': False,
                'wards_processed': 0,
                'total_properties': 0,
                'error_count': 0
            }
        }
        
        try:
            # Load current active listings
            active_listings = self._load_active_listings(date_str)
            results['metrics']['total_properties'] = len(active_listings)
            
            if not active_listings:
                logger.warning(f"No active listings found for {date_str}")
                return results
                
            # Generate global snapshot
            global_snapshot = self._generate_global_snapshot(active_listings, date_str)
            self._save_snapshot(global_snapshot, 'global')
            results['global_snapshot'] = global_snapshot
            results['metrics']['global_generated'] = True
            
            # Generate ward snapshots
            wards_data = self._group_by_ward(active_listings)
            
            for ward, ward_listings in wards_data.items():
                try:
                    ward_snapshot = self._generate_ward_snapshot(ward_listings, ward, date_str)
                    self._save_snapshot(ward_snapshot, f'ward_{ward}')
                    results['ward_snapshots'].append(ward_snapshot)
                    results['metrics']['wards_processed'] += 1
                except Exception as e:
                    logger.error(f"Failed to generate snapshot for ward {ward}: {e}")
                    results['metrics']['error_count'] += 1
                    
            logger.info(f"Generated {results['metrics']['wards_processed']} ward snapshots")
            
        except Exception as e:
            logger.error(f"Error generating snapshots: {e}")
            results['metrics']['error_count'] += 1
            
        return results
        
    def _load_active_listings(self, date_str: str) -> List[Dict[str, Any]]:
        """Load current active listings from S3 processed data."""
        logger.info(f"Loading active listings for {date_str}")
        
        try:
            # Look for processed listings in multiple possible locations
            possible_keys = [
                f'processed/current/listings.jsonl',
                f'processed/{date_str}/listings.jsonl',
                f'clean/{date_str}/listings.jsonl'
            ]
            
            listings = []
            for key in possible_keys:
                try:
                    response = self.s3_client.get_object(Bucket=self.s3_bucket, Key=key)
                    content = response['Body'].read().decode('utf-8')
                    
                    # Parse JSONL format
                    for line in content.strip().split('\n'):
                        if line.strip():
                            listing = json.loads(line)
                            # Only include active listings with required fields
                            if (listing.get('status') == 'active' and 
                                listing.get('price_per_sqm') and
                                listing.get('total_sqm')):
                                listings.append(listing)
                    
                    if listings:
                        logger.info(f"Loaded {len(listings)} active listings from {key}")
                        break
                        
                except ClientError as e:
                    if e.response['Error']['Code'] != 'NoSuchKey':
                        logger.warning(f"Error loading from {key}: {e}")
                    continue
                    
            return listings
            
        except Exception as e:
            logger.error(f"Failed to load active listings: {e}")
            return []
            
    def _generate_global_snapshot(self, listings: List[Dict[str, Any]], date_str: str) -> Dict[str, Any]:
        """Generate global market snapshot."""
        logger.info("Generating global market snapshot")
        
        prices_per_sqm = [l['price_per_sqm'] for l in listings if l.get('price_per_sqm')]
        prices_per_sqm.sort()
        
        # Calculate seven-day change (mock for now - would need historical data)
        seven_day_change_pp = 0  # Percentage points change
        
        snapshot = {
            'date': date_str,
            'median_price_per_sqm': self._calculate_median(prices_per_sqm),
            'total_active': len(listings),
            'seven_day_change_pp': seven_day_change_pp,
            'percentiles': {
                'p25': self._calculate_percentile(prices_per_sqm, 25),
                'p50': self._calculate_percentile(prices_per_sqm, 50),
                'p75': self._calculate_percentile(prices_per_sqm, 75),
                'p90': self._calculate_percentile(prices_per_sqm, 90)
            },
            'summary_stats': {
                'min_price_per_sqm': min(prices_per_sqm) if prices_per_sqm else 0,
                'max_price_per_sqm': max(prices_per_sqm) if prices_per_sqm else 0,
                'avg_size_sqm': sum(l.get('total_sqm', 0) for l in listings) / len(listings) if listings else 0
            }
        }
        
        logger.info(f"Global snapshot: {len(listings)} properties, median ¥{snapshot['median_price_per_sqm']:,.0f}/sqm")
        return snapshot
        
    def _generate_ward_snapshot(self, listings: List[Dict[str, Any]], ward: str, date_str: str) -> Dict[str, Any]:
        """Generate ward-specific market snapshot."""
        logger.debug(f"Generating ward snapshot for {ward}")
        
        prices_per_sqm = [l['price_per_sqm'] for l in listings if l.get('price_per_sqm')]
        prices_per_sqm.sort()
        
        snapshot = {
            'date': date_str,
            'ward': ward,
            'median_price_per_sqm': self._calculate_median(prices_per_sqm),
            'inventory': len(listings),
            'percentiles': {
                'p25': self._calculate_percentile(prices_per_sqm, 25),
                'p50': self._calculate_percentile(prices_per_sqm, 50),  # Same as median
                'p75': self._calculate_percentile(prices_per_sqm, 75)
            },
            'summary_stats': {
                'min_price_per_sqm': min(prices_per_sqm) if prices_per_sqm else 0,
                'max_price_per_sqm': max(prices_per_sqm) if prices_per_sqm else 0,
                'avg_size_sqm': sum(l.get('total_sqm', 0) for l in listings) / len(listings) if listings else 0,
                'property_types': self._count_property_types(listings)
            }
        }
        
        return snapshot
        
    def _group_by_ward(self, listings: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Group listings by ward/district."""
        wards = {}
        
        for listing in listings:
            # Try multiple possible ward field names
            ward = None
            for field in ['ward', 'district', 'area', 'ku']:
                if listing.get(field):
                    ward = listing[field]
                    break
                    
            # Fallback to a portion of address if no ward field
            if not ward and listing.get('address'):
                # Extract ward from address (naive approach)
                address_parts = listing['address'].split(' ')
                for part in address_parts:
                    if part.endswith('区') or part.endswith('ku'):
                        ward = part
                        break
                        
            ward = ward or 'Unknown'
            
            if ward not in wards:
                wards[ward] = []
            wards[ward].append(listing)
            
        return wards
        
    def _count_property_types(self, listings: List[Dict[str, Any]]) -> Dict[str, int]:
        """Count property types in listings."""
        types = {}
        for listing in listings:
            prop_type = listing.get('property_type', 'Unknown')
            types[prop_type] = types.get(prop_type, 0) + 1
        return types
        
    def _calculate_median(self, values: List[float]) -> float:
        """Calculate median of a sorted list."""
        if not values:
            return 0
        n = len(values)
        if n % 2 == 0:
            return (values[n//2 - 1] + values[n//2]) / 2
        else:
            return values[n//2]
            
    def _calculate_percentile(self, values: List[float], percentile: int) -> float:
        """Calculate percentile of a sorted list."""
        if not values:
            return 0
        n = len(values)
        k = (percentile / 100) * (n - 1)
        f = int(k)
        c = k - f
        if f < n - 1:
            return values[f] * (1 - c) + values[f + 1] * c
        else:
            return values[f]
            
    def _save_snapshot(self, snapshot: Dict[str, Any], snapshot_type: str) -> None:
        """Save snapshot to S3."""
        key = f'snapshots/current/{snapshot_type}.json'
        
        try:
            self.s3_client.put_object(
                Bucket=self.s3_bucket,
                Key=key,
                Body=json.dumps(snapshot, indent=2, ensure_ascii=False),
                ContentType='application/json'
            )
            logger.debug(f"Saved snapshot to {key}")
            
        except Exception as e:
            logger.error(f"Failed to save snapshot {key}: {e}")
            raise


def generate_all_snapshots(event: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Lambda entry point for daily snapshot generation.
    
    Args:
        event: Lambda event (optional date parameter)
        
    Returns:
        Results dictionary with metrics
    """
    config = get_config()
    
    # Skip if not in LEAN_MODE
    if not config.is_lean_mode():
        logger.info("Snapshot generation skipped - LEAN_MODE disabled")
        return {'status': 'skipped', 'reason': 'LEAN_MODE disabled'}
    
    date_str = None
    if event and event.get('date'):
        date_str = event['date']
        
    generator = SnapshotGenerator()
    results = generator.generate_all_snapshots(date_str)
    
    # Emit metrics
    try:
        # Try to dynamically import metrics module
        import importlib.util
        metrics_path = os.path.join(os.path.dirname(__file__), '..', 'ai-infra', 'lambda', 'util', 'metrics.py')
        metrics_path = os.path.abspath(metrics_path)
        
        if os.path.exists(metrics_path):
            spec = importlib.util.spec_from_file_location("metrics", metrics_path)
            metrics_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(metrics_module)
            
            emit_metric = metrics_module.emit_metric
            emit_metric('Snapshots.GlobalGenerated', 1 if results['metrics']['global_generated'] else 0)
            emit_metric('Snapshots.WardsProcessed', results['metrics']['wards_processed'])
            emit_metric('Snapshots.ErrorCount', results['metrics']['error_count'])
            emit_metric('Snapshots.TotalProperties', results['metrics']['total_properties'])
        else:
            logger.warning("Metrics module not found - skipping metric emission")
    except Exception:
        logger.warning("Metrics module not available - skipping metric emission")
        
    return results


# Legacy compatibility
class SnapshotManager:
    """Legacy class for backward compatibility."""
    
    def __init__(self):
        self.generator = SnapshotGenerator()
        
    def create_snapshot(self, data):
        """Legacy method - use SnapshotGenerator instead."""
        return self.generator.generate_all_snapshots()
        
    def load_snapshot(self, snapshot_id):
        """Legacy method - implement if needed."""
        pass