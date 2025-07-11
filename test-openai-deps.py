#!/usr/bin/env python3
import sys
sys.path.insert(0, '/opt/python')

try:
    import openai
    import requests
    import pythonjsonlogger
    print('[OK] openai-deps layer: All imports successful')
    print(f'  openai: {openai.__version__}')
    print(f'  requests: {requests.__version__}')
    
    # Test basic functionality
    resp = requests.get('https://httpbin.org/get')
    if resp.status_code == 200:
        print('[OK] requests functionality test passed')
    else:
        print('[WARNING] requests test returned non-200 status')
    
    # Test OpenAI client creation (without API key)
    client = openai.OpenAI(api_key='dummy')
    print('[OK] OpenAI client creation test passed')
    
except ImportError as e:
    print(f'[ERROR] openai-deps layer import failed: {e}')
    exit(1)
except Exception as e:
    print(f'[ERROR] openai-deps layer functionality test failed: {e}')
    exit(1)