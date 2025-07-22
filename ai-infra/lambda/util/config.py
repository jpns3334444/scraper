"""
Centralized configuration helper for Lean v1.3.

This module provides a single point for reading environment variables
and configuration flags, ensuring consistent behavior across all lambdas.
"""

import logging
import os
from typing import Any, Dict, Optional, Union

logger = logging.getLogger(__name__)


class LeanConfig:
    """Centralized configuration management for Lean v1.3."""
    
    def __init__(self):
        """Initialize configuration with cached values."""
        self._cache = {}
        self._load_config()
    
    def _load_config(self):
        """Load and cache all configuration values."""
        logger.info("Loading Lean v1.3 configuration...")
        
        # Master flags
        self._cache['LEAN_MODE'] = self._get_bool_from_env('LEAN_MODE', default=False)
        self._cache['LEAN_SCORING'] = self._get_bool_from_env('LEAN_SCORING', default=True)
        self._cache['LEAN_PROMPT'] = self._get_bool_from_env('LEAN_PROMPT', default=True)
        self._cache['LEAN_SCHEMA_ENFORCE'] = self._get_bool_from_env('LEAN_SCHEMA_ENFORCE', default=True)
        
        # Limits and thresholds
        self._cache['MAX_CANDIDATES_PER_DAY'] = self._get_int_from_env('MAX_CANDIDATES_PER_DAY', default=120)
        self._cache['MAX_COMPARABLES'] = self._get_int_from_env('MAX_COMPARABLES', default=8)
        self._cache['MAX_IMAGES_PER_PROPERTY'] = self._get_int_from_env('MAX_IMAGES_PER_PROPERTY', default=3)
        
        # Scoring thresholds
        self._cache['BUY_CANDIDATE_SCORE_THRESHOLD'] = self._get_int_from_env('BUY_CANDIDATE_SCORE_THRESHOLD', default=75)
        self._cache['WATCH_SCORE_THRESHOLD'] = self._get_int_from_env('WATCH_SCORE_THRESHOLD', default=60)
        self._cache['WARD_DISCOUNT_BUY_THRESHOLD'] = self._get_float_from_env('WARD_DISCOUNT_BUY_THRESHOLD', default=-12.0)
        self._cache['WARD_DISCOUNT_WATCH_MIN'] = self._get_float_from_env('WARD_DISCOUNT_WATCH_MIN', default=-11.99)
        self._cache['WARD_DISCOUNT_WATCH_MAX'] = self._get_float_from_env('WARD_DISCOUNT_WATCH_MAX', default=-8.0)
        self._cache['DATA_QUALITY_PENALTY_THRESHOLD'] = self._get_int_from_env('DATA_QUALITY_PENALTY_THRESHOLD', default=-4)
        
        # LLM settings
        self._cache['LLM_MODEL'] = os.getenv('LLM_MODEL', 'gpt-4o-mini')
        self._cache['LLM_MAX_TOKENS'] = self._get_int_from_env('LLM_MAX_TOKENS', default=1000)
        self._cache['LLM_TEMPERATURE'] = self._get_float_from_env('LLM_TEMPERATURE', default=0.1)
        self._cache['LLM_RETRY_ATTEMPTS'] = self._get_int_from_env('LLM_RETRY_ATTEMPTS', default=1)
        
        # AWS settings
        self._cache['AWS_REGION'] = os.getenv('AWS_REGION', 'ap-northeast-1')
        self._cache['OUTPUT_BUCKET'] = os.getenv('OUTPUT_BUCKET', 'your-bucket-name')
        self._cache['DYNAMODB_TABLE'] = os.getenv('DYNAMODB_TABLE', '')
        
        # Email settings
        self._cache['EMAIL_FROM'] = os.getenv('EMAIL_FROM', '')
        self._cache['EMAIL_TO'] = os.getenv('EMAIL_TO', '')
        
        # OpenAI settings
        self._cache['OPENAI_SECRET_NAME'] = os.getenv('OPENAI_SECRET_NAME', 'ai-scraper/openai-api-key')
        self._cache['OPENAI_MODEL'] = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')
        
        # Logging and debugging  
        self._cache['LOG_LEVEL'] = os.getenv('LOG_LEVEL', 'INFO').upper()
        self._cache['DEBUG_MODE'] = self._get_bool_from_env('DEBUG_MODE', default=False)
        self._cache['TRUNCATE_LOGS_AT'] = self._get_int_from_env('TRUNCATE_LOGS_AT', default=1500)
        
        logger.info(f"Lean Mode: {'ENABLED' if self._cache['LEAN_MODE'] else 'DISABLED'}")
        logger.info(f"Max candidates per day: {self._cache['MAX_CANDIDATES_PER_DAY']}")
        logger.info(f"LLM Model: {self._cache['LLM_MODEL']}")
        
    def _get_bool_from_env(self, key: str, default: bool = False) -> bool:
        """Parse boolean from environment variable."""
        value = os.getenv(key, '').lower()
        if value in ('1', 'true', 'yes', 'on', 'enabled'):
            return True
        elif value in ('0', 'false', 'no', 'off', 'disabled'):
            return False
        else:
            return default
    
    def _get_int_from_env(self, key: str, default: int = 0) -> int:
        """Parse integer from environment variable."""
        try:
            return int(os.getenv(key, str(default)))
        except (ValueError, TypeError):
            logger.warning(f"Invalid integer value for {key}, using default: {default}")
            return default
    
    def _get_float_from_env(self, key: str, default: float = 0.0) -> float:
        """Parse float from environment variable."""
        try:
            return float(os.getenv(key, str(default)))
        except (ValueError, TypeError):
            logger.warning(f"Invalid float value for {key}, using default: {default}")
            return default
    
    def get_bool(self, key: str, default: Optional[bool] = None) -> bool:
        """
        Get boolean configuration value.
        
        Args:
            key: Configuration key
            default: Default value if not found in cache
            
        Returns:
            Boolean configuration value
        """
        if key in self._cache:
            return self._cache[key]
        elif default is not None:
            return default
        else:
            raise KeyError(f"Configuration key '{key}' not found and no default provided")
    
    def get_int(self, key: str, default: Optional[int] = None) -> int:
        """
        Get integer configuration value.
        
        Args:
            key: Configuration key
            default: Default value if not found in cache
            
        Returns:
            Integer configuration value
        """
        if key in self._cache:
            return self._cache[key]
        elif default is not None:
            return default
        else:
            raise KeyError(f"Configuration key '{key}' not found and no default provided")
    
    def get_float(self, key: str, default: Optional[float] = None) -> float:
        """
        Get float configuration value.
        
        Args:
            key: Configuration key
            default: Default value if not found in cache
            
        Returns:
            Float configuration value
        """
        if key in self._cache:
            return self._cache[key]
        elif default is not None:
            return default
        else:
            raise KeyError(f"Configuration key '{key}' not found and no default provided")
    
    def get_str(self, key: str, default: Optional[str] = None) -> str:
        """
        Get string configuration value.
        
        Args:
            key: Configuration key
            default: Default value if not found in cache
            
        Returns:
            String configuration value
        """
        if key in self._cache:
            return self._cache[key]
        elif default is not None:
            return default
        else:
            raise KeyError(f"Configuration key '{key}' not found and no default provided")
    
    def is_lean_mode(self) -> bool:
        """Check if Lean mode is enabled."""
        return self.get_bool('LEAN_MODE')
    
    def is_debug_mode(self) -> bool:
        """Check if debug mode is enabled."""
        return self.get_bool('DEBUG_MODE')
    
    def get_scoring_config(self) -> Dict[str, Any]:
        """Get all scoring-related configuration."""
        return {
            'buy_candidate_threshold': self.get_int('BUY_CANDIDATE_SCORE_THRESHOLD'),
            'watch_threshold': self.get_int('WATCH_SCORE_THRESHOLD'),
            'ward_discount_buy_threshold': self.get_float('WARD_DISCOUNT_BUY_THRESHOLD'),
            'ward_discount_watch_min': self.get_float('WARD_DISCOUNT_WATCH_MIN'),
            'ward_discount_watch_max': self.get_float('WARD_DISCOUNT_WATCH_MAX'),
            'data_quality_penalty_threshold': self.get_int('DATA_QUALITY_PENALTY_THRESHOLD'),
        }
    
    def get_llm_config(self) -> Dict[str, Any]:
        """Get all LLM-related configuration."""
        return {
            'model': self.get_str('LLM_MODEL'),
            'max_tokens': self.get_int('LLM_MAX_TOKENS'),
            'temperature': self.get_float('LLM_TEMPERATURE'),
            'retry_attempts': self.get_int('LLM_RETRY_ATTEMPTS'),
        }
    
    def get_limits_config(self) -> Dict[str, Any]:
        """Get all limit-related configuration."""
        return {
            'max_candidates_per_day': self.get_int('MAX_CANDIDATES_PER_DAY'),
            'max_comparables': self.get_int('MAX_COMPARABLES'),
            'max_images_per_property': self.get_int('MAX_IMAGES_PER_PROPERTY'),
        }
    
    def get_all_config(self) -> Dict[str, Any]:
        """Get all configuration as a dictionary."""
        return self._cache.copy()


# Global instance - initialized once per lambda container
_config_instance = None


def get_config() -> LeanConfig:
    """
    Get the global configuration instance.
    
    Returns:
        LeanConfig singleton instance
    """
    global _config_instance
    if _config_instance is None:
        _config_instance = LeanConfig()
    return _config_instance


# Convenience functions that match the original spec
def get_bool(key: str, default: bool = False) -> bool:
    """Get boolean configuration value."""
    return get_config().get_bool(key, default)


def get_int(key: str, default: int = 0) -> int:
    """Get integer configuration value."""
    return get_config().get_int(key, default)


def get_float(key: str, default: float = 0.0) -> float:
    """Get float configuration value."""
    return get_config().get_float(key, default)


def get_str(key: str, default: str = "") -> str:
    """Get string configuration value."""
    return get_config().get_str(key, default)


def is_lean_mode() -> bool:
    """Check if Lean mode is enabled."""
    return get_config().is_lean_mode()


def is_debug_mode() -> bool:
    """Check if debug mode is enabled."""
    return get_config().is_debug_mode()


# Example usage and testing
if __name__ == "__main__":
    # For local testing
    config = get_config()
    print("Configuration Summary:")
    print(f"- Lean Mode: {config.is_lean_mode()}")
    print(f"- Max Candidates: {config.get_int('MAX_CANDIDATES_PER_DAY')}")
    print(f"- LLM Model: {config.get_str('LLM_MODEL')}")
    print(f"- Buy Threshold: {config.get_int('BUY_CANDIDATE_SCORE_THRESHOLD')}")
    print(f"- Ward Discount Threshold: {config.get_float('WARD_DISCOUNT_BUY_THRESHOLD')}%")