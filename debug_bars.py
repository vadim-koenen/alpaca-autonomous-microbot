"""
debug_bars.py — Run once to diagnose the crypto bars API response.
Usage: python debug_bars.py
"""
import os, sys
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest, CryptoLatestBarRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

key = os.getenv("ALPACA_API_KEY")
secret = os.getenv("ALPACA_SECRET_KEY")

if not key or not secret:
    print("ERROR: ALPACA_API_KEY / ALPACA_SECRET_KEY not set in .env")
    sys.exit(1)

client = CryptoHistoricalDataClient(api_key=key, secret_key=secret)
symbol = "BTC/USD"

print(f"\n{'='*60}")
print(f"Testing crypto bars API for {symbol}")
print(f"{'='*60}\n")

# Test 1: Latest single bar
print("--- Test 1: CryptoLatestBarRequest ---")
try:
    from alpaca.data.requests import CryptoLatestBarRequest
    req = CryptoLatestBarRequest(symbol_or_symbols=symbol)
    result = client.get_crypto_latest_bar(req)
    bar = result.get(symbol)
    print(f"  Latest bar: {bar}")
except Exception as e:
    print(f"  ERROR: {e}")

# Test 2: Bars with 6-hour window
print("\n--- Test 2: CryptoBarsRequest (last 6h, limit=50) ---")
try:
    start = datetime.now(timezone.utc) - timedelta(hours=6)
    req = CryptoBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame(5, TimeFrameUnit.Minute),
        start=start,
        limit=50,
    )
    bars = client.get_crypto_bars(req)
    print(f"  Response type: {type(bars)}")
    print(f"  Has data attr: {hasattr(bars, 'data')}")
    if hasattr(bars, 'data'):
        print(f"  Keys in .data: {list(bars.data.keys())}")
    in_bars = symbol in bars
    print(f"  '{symbol}' in bars: {in_bars}")
    if in_bars:
        b = bars[symbol]
        print(f"  Bar count: {len(b)}")
        if b:
            print(f"  First: t={b[0].timestamp} c={b[0].close}")
            print(f"  Last:  t={b[-1].timestamp} c={b[-1].close}")
    else:
        print(f"  Attempting bars['{symbol}']...")
        try:
            b = bars[symbol]
            print(f"  Got: {b}")
        except Exception as e2:
            print(f"  KeyError: {e2}")
        # Try iterating
        print(f"  Iterating response directly...")
        try:
            for k, v in bars:
                print(f"    key={k} len={len(v)}")
        except Exception as e3:
            print(f"  Can't iterate: {e3}")
except Exception as e:
    print(f"  ERROR: {e}")
    import traceback; traceback.print_exc()

# Test 3: Bars without start (just limit)
print("\n--- Test 3: CryptoBarsRequest (no start, limit=50) ---")
try:
    req = CryptoBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame(5, TimeFrameUnit.Minute),
        limit=50,
    )
    bars = client.get_crypto_bars(req)
    in_bars = symbol in bars
    print(f"  '{symbol}' in bars: {in_bars}")
    if in_bars:
        b = bars[symbol]
        print(f"  Bar count: {len(b)}")
except Exception as e:
    print(f"  ERROR: {e}")

# Test 4: 1-day bars (simpler)
print("\n--- Test 4: 1-Day bars (last 30 days) ---")
try:
    start = datetime.now(timezone.utc) - timedelta(days=30)
    req = CryptoBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame(1, TimeFrameUnit.Day),
        start=start,
    )
    bars = client.get_crypto_bars(req)
    in_bars = symbol in bars
    print(f"  '{symbol}' in bars: {in_bars}")
    if in_bars:
        b = bars[symbol]
        print(f"  Bar count: {len(b)}")
        if b:
            print(f"  Last daily bar: t={b[-1].timestamp} c={b[-1].close}")
except Exception as e:
    print(f"  ERROR: {e}")

print(f"\n{'='*60}")
print("Done.")
