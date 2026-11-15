# Official Quiniela ticket constraints

Checked on 2026-11-14 for implementation defaults.

- SELAE's 2024 annual report lists La Quiniela at 0.75 EUR per simple bet, a minimum participation of two bets (1.50 EUR), and the game format as 14 + 1 matches.
- SELAE's official Quiniela rules describe the Pleno al 15 goal categories as 0, 1, 2 and M for each team, with M representing three or more goals.
- For the **multiple-direct** method, the optimizer enforces the authorized double/triple table in SELAE's official rules (Anexo I): maximum triples by number of doubles are 0: 1–9; 1: 0–8; 2: 0–8; 3: 0–7; 4: 0–6; 5: 0–6; 6: 0–5; 7: 0–5; 8: 0–4; 9: 0–3; 10: 0–3; 11: 0–2; 12: 0–1; 13: 0–1; 14: 0. The maximum authorized 14-match direct combination is 31,104 columns (7 doubles and 5 triples).
- The optimizer treats budget as a maximum number of 14-match columns, enforces the two-column minimum, and rejects budgets above the authorized direct-system maximum. It returns explicit double/triple counts and estimates cost at 0.75 EUR per column.
- The current engine selects exactly one Pleno al 15 category pair, so the Pleno al 15 multiplier is 1. SELAE's rules state that selecting multiple categories for either team multiplies the 14-match combinations; multiple Pleno al 15 selections are not implemented. The optimizer does not implement reduced or conditioned systems, Elige8, retailer/online validation, or expected-prize calculations.
- The 2019 SELAE rules state that they remain in force for subsequent seasons until a new version is published. The current SELAE normative-games page still links to the Quiniela/Elige8 rules; verify the latest version before submitting a real ticket. The price is configurable in TicketOptimizer.

Sources:
- SELAE, Estado de Información no financiera 2024, game portfolio and Quiniela price/minimum participation: https://www.selae.es/f/loterias/web_corporativa/Quienes_somos/CuentasAnuales/Estado-de-Informacion-no-financiera-SELAE-2024.pdf
- SELAE, Normas de la Quiniela, temporada 2015-2016, Pleno al 15 goal categories: https://www.selae.es/f/loterias/documentos/Quiniela/Normativa%20Quiniela/NORMAS%20DE%20LA%20QUINIELA%20T-2015-2016.pdf
