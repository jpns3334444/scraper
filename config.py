"""
Super Simple Configuration Loader
Just use: get('key_name') to get any config value
"""

import yaml
import os
from pathlib import Path

# Load config once
_config_file = Path(__file__).parent / "config" / "config.yaml"
with open(_config_file, 'r') as f:
    _CONFIG = yaml.safe_load(f)

def get(key):
    """Get any config value by key name"""
    return _CONFIG.get(key)

# For backwards compatibility with environment variables
def env(key, default=None):
    """Get from environment first, then config, then default"""
    return os.environ.get(key, get(key) or default)

if __name__ == "__main__":
    print("=== Config Test ===")
    print(f"AWS Region: {get('aws_region')}")
    print(f"Properties Table: {get('properties_table')}")
    print(f"URL Collector Function: {get('url_collector_function')}")
    print(f"Buy Candidate Verdict: {get('verdict_buy_candidate')}")