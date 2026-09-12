<!-- product: all | book: risk-gates | status: - | as_of: 2026-09-12 -->
# Risk gates — what stops each book

Automatic stops sit above the strategy and watch different stretches of time; only one of them can interrupt a day already running.

How to read this:
- The %: a % of that profile's own M2M base capital — not a % of your account
- The base: the profile's mark-to-market capital, else its trade-settings capital
- The count: rupees are added, then divided by the base
- Live one: daily M2M — checked every tick, can cut in mid-session
- Morning ones: weekly and monthly — read once, at startup; a morning gate never pulls you out of a running day, it refuses to start the next one

Profiles and their armed gates:
- NIFTY weekday HIGH-VIX: daily M2M at -27% (-₹4,050), checked every tick; weekly intraday floor at -59% (-₹8,850), checked every tick; weekly hard stop at -59% (-₹8,850), checked startup only
- NIFTY weekday LOW-VIX: daily M2M at -27% (-₹4,050), checked every tick; weekly intraday floor at -59% (-₹8,850), checked every tick; weekly hard stop at -59% (-₹8,850), checked startup only
- NIFTY expiry HIGH-VIX: daily M2M at -33% (-₹33,000), checked every tick; monthly stop at -50% (-₹50,000), checked startup only
- NIFTY expiry LOW-VIX: daily M2M at -25% (-₹25,000), checked every tick; monthly stop at -50% (-₹50,000), checked startup only
- SENSEX expiry: daily M2M at -50% (-₹37,500), checked every tick
- SENSEX weekday: daily M2M at -27% (-₹1,08,000), checked every tick; weekly hard stop at -60% (-₹2,40,000), checked startup only; weekly expiry gate at -38% (-₹1,52,000), checked startup only

What each gate cancels:
- Daily M2M: counts from that book, that day, blocks rest of today, open trades are force-exited
- Weekly intraday floor: counts from week-to-date at startup, blocks tightens today's cap, open trades are force-exited at the tighter cap
- Weekly hard stop: counts from the weekday book, blocks the rest of the week, open trades are untouched
- Monthly stop: counts from expiry sessions only, blocks the rest of the month, open trades are untouched
- R1S1 book M2M: counts from open R1S1 legs only, blocks new R1S1 entries, open trades are untouched — they ride their own SL

Present but inert:
- NIFTY weekday HIGH-VIX: Weekly expiry gate
- NIFTY weekday LOW-VIX: Weekly expiry gate
- NIFTY expiry HIGH-VIX: Weekly expiry gate, weekly hard stop
- NIFTY expiry LOW-VIX: Weekly expiry gate, weekly hard stop
- SENSEX expiry: Weekly expiry gate, weekly hard stop

Paper sub-book brakes:
- NIFTY weekday HIGH-VIX: book base ₹7,50,000, floor -27% (-₹2,02,500), worst day so far -₹5,625
- NIFTY weekday LOW-VIX: book base ₹7,50,000, floor -27% (-₹2,02,500), worst day so far -₹5,625
- SENSEX weekday: book base ₹12,00,000, floor -27% (-₹3,24,000), worst day so far -₹1,80,000

These gates will not save you from:
- A slow bleed — The daily cap bounds one session and the weekly one bounds a week that starts badly. A run of days each landing just inside the daily cap passes through the whole stack untouched.
- A wrong-way book — If every leg is on the wrong side of a trending market, no stop-loss layer fixes that. It only decides how fast you pay for it.
- A gate that cannot read its ledger — The weekly floor reads week-to-date once, at startup, from the persistent ledger. If that read fails the floor falls back to the day's own cap — it fails OPEN, not shut.
- A week that crosses the line today — Week-to-date is fixed at startup and does not update as today's trades close, so a week that breaches mid-session is still bounded only by the daily cap.
