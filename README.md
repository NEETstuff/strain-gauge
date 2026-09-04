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

- Dollar Stress: SOFR–IORB < 5bp and SWPT < $1B → CALM; 5–15bp or $1–10B → TIGHTENING; > 15bp or > $10B → STRAIN. No other rule touches this card.
- Liquidity Health: net-liq level + 4-week slope (FRED $M normalized to $B, shown as $T). Mild drain → TIGHTENING; STRAIN only on fast drain (≥ $150B/4w) or a new scarcity low.
- USD/JPY: yellow above 158; red on >2% 3-day yen rally or JGB 10y ≥ 3% with USDJPY > 157.
- Stale: daily series > 3 days old, weekly > 10 days, JGB (monthly/lagged) > 45 days → card STALE; stale inputs cap a card at TIGHTENING, never STRAIN.

## Notes

- FIMA repo has no clean daily FRED series; update the manual note from H.4.1 (Thursdays).
- Data can be late. Thresholds are starting points, not gospel.
