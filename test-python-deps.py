#!/usr/bin/env python3
import sys
sys.path.insert(0, '/opt/python')

try:
    import pandas as pd
    import numpy as np
    import boto3
    import pytz
    print('[OK] python-deps layer: All imports successful')
    print(f'  pandas: {pd.__version__}')
    print(f'  numpy: {np.__version__}')
    print(f'  boto3: {boto3.__version__}')
    print(f'  pytz: {pytz.__version__}')
    
    # Test basic functionality
    df = pd.DataFrame({'test': [1, 2, 3]})
    arr = np.array([1, 2, 3])
    s3 = boto3.client('s3', region_name='us-east-1')
    tz = pytz.timezone('UTC')
    print('[OK] Basic functionality tests passed')
    
except ImportError as e:
    print(f'[ERROR] python-deps layer import failed: {e}')
    exit(1)
except Exception as e:
    print(f'[ERROR] python-deps layer functionality test failed: {e}')
    exit(1)