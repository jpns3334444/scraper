#!/usr/bin/env python3
"""
Load configuration from config.json for Python scripts
"""
import json
import os
import sys
from pathlib import Path

def load_config():
    """Load configuration from config.json and return as dict"""
    # Find repo root
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent
    config_file = repo_root / 'config.json'
    
    if not config_file.exists():
        print(f"Config file not found: {config_file}", file=sys.stderr)
        sys.exit(1)
    
    # Load JSON config
    with open(config_file, 'r') as f:
        json_config = json.load(f)
    
    # Flatten nested JSON structure into flat key-value pairs
    config = {}
    
    def flatten_config(obj, prefix=''):
        for key, value in obj.items():
            # Skip comment keys
            if key.startswith('_'):
                continue
                
            if isinstance(value, dict):
                # For nested objects, use the key as the variable name (not prefixed)
                flatten_config(value, '')
            else:
                config[key] = str(value)
    
    flatten_config(json_config)
    
    # Also set as environment variables
    for key, value in config.items():
        os.environ[key] = value
    
    return config

if __name__ == '__main__':
    # When run directly, print config as shell exports
    config = load_config()
    for key, value in config.items():
        print(f'export {key}="{value}"')