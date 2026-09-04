# Strain Gauge — Lorca Labs

Local liquidity-plumbing dashboard. Not financial advice. Not a trade signal.

## Run

pip install -r requirements.txt
streamlit run app.py

## FRED key (optional, free)

1. Create a free account at https://fred.stlouisfed.org and request an API key under "My Account → API Keys".
2. `export FRED_API_KEY=your_key_here` (or copy `.env.example` to `.env`).
3. Restart the app. Badge flips from DEMO to LIVE. Without a key the app runs on `data/demo.json` fixtures, clearly labeled DEMO.

## Thresholds (v1, edit in `src/gauges.py` THRESHOLDS)

- SOFR–IORB: green < 5bp, yellow 5–15bp, red > 15bp.
- ON RRP: near-zero = buffer gone (yellow only if TGA also elevated), not auto-red.
- TGA: yellow if rising fast week-over-week (> $30B); combined with net-liquidity slope.
- USD/JPY: yellow above 158; red on >2% 3-day yen rally or JGB 10y ≥ 3% with USDJPY > 157.
- SWPT (swap lines): yellow > $1B, red > $10B.

## Notes

- FIMA repo has no clean daily FRED series; update the manual note from H.4.1 (Thursdays).
- Data can be late. Thresholds are starting points, not gospel.
