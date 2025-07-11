#!/usr/bin/env python3
import sys
sys.path.insert(0, '/opt/python-deps/python')
sys.path.insert(0, '/opt/openai-deps/python')

try:
    # Test all packages together
    import pandas as pd
    import numpy as np
    import boto3
    import pytz
    import openai
    import requests
    
    print('[OK] Combined layer test: All imports successful')
    
    # Test that there are no conflicts
    df = pd.DataFrame({'data': np.array([1, 2, 3])})
    s3 = boto3.client('s3', region_name='us-east-1')
    client = openai.OpenAI(api_key='dummy')
    resp = requests.get('https://httpbin.org/get')
    
    print('[OK] Combined layer test: No conflicts detected')
    
except ImportError as e:
    print(f'[ERROR] Combined layer import failed: {e}')
    exit(1)
except Exception as e:
    print(f'[ERROR] Combined layer functionality test failed: {e}')
    exit(1)