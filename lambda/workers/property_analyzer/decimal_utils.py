# decimal_utils.py
from decimal import Decimal, ROUND_HALF_UP

def to_float(v):
    """Convert DynamoDB Decimal → float (or pass‐through)."""
    return float(v) if isinstance(v, Decimal) else v

def to_dec(v, ndigits=4):
    """Safely round float → Decimal for DynamoDB."""
    return Decimal(str(round(v, ndigits))).quantize(
        Decimal('1.' + '0' * ndigits), rounding=ROUND_HALF_UP
    )