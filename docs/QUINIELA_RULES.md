# Official Quiniela ticket constraints

Checked on 2026-11-15 for implementation defaults.

- SELAE's 2024 annual report lists La Quiniela at 0.75 EUR per simple bet, a minimum participation of two bets (1.50 EUR), and the game format as 14 + 1 matches.
- SELAE's official Quiniela rules describe the Pleno al 15 goal categories as 0, 1, 2 and M for each team, with M representing three or more goals.
- For the **multiple-direct** method, the optimizer enforces the authorized double/triple table in SELAE's official rules (Anexo I): maximum triples by number of doubles are 0: 1–9; 1: 0–8; 2: 0–8; 3: 0–7; 4: 0–6; 5: 0–6; 6: 0–5; 7: 0–5; 8: 0–4; 9: 0–3; 10: 0–3; 11: 0–2; 12: 0–1; 13: 0–1; 14: 0. The maximum authorized 14-match direct combination is 31,104 columns (7 doubles and 5 triples).
- The optimizer treats budget as a maximum number of 14-match columns, enforces the two-column minimum, and rejects budgets above the authorized direct-system maximum. It returns explicit double/triple counts and estimates cost at 0.75 EUR per column.
- The current engine selects exactly one Pleno al 15 category pair, so the Pleno al 15 multiplier is 1. SELAE's rules state that selecting multiple categories for either team multiplies the 14-match combinations; multiple Pleno al 15 selections are not implemented. The optimizer does not implement reduced or conditioned systems, Elige8, retailer/online validation, or expected-prize calculations.
- The 2019 SELAE rules state that they remain in force for subsequent seasons until a new version is published. The current SELAE normative-games page still links to the Quiniela/Elige8 rules; verify the latest version before submitting a real ticket. The price is configurable in TicketOptimizer.

Sources:
- SELAE, Estado de Información no financiera 2024, game portfolio and Quiniela price/minimum participation: https://www.selae.es/f/loterias/web_corporativa/Quienes_somos/CuentasAnuales/Estado-de-Informacion-no-financiera-SELAE-2024.pdf
- SELAE, Normas de la Quiniela, temporada 2015-2016, Pleno al 15 goal categories: https://www.selae.es/f/loterias/documentos/Quiniela/Normativa%20Quiniela/NORMAS%20DE%20LA%20QUINIELA%20T-2015-2016.pdf

## Current official-source check — 2026-11-15

The current SELAE [Normativa de los juegos index](https://www.selae.es/es/web-corporativa/normativa/normativa-de-los-juegos/normativa-de-los-juegos-web-corporativa) still exposes the section **La Quiniela con Elige8**. The latest rules PDF surfaced by the SELAE normative listing is the 2019–2020 rules document; its final provision (norma 52.4) states that the rules apply from week 13 of 2019/20 and subsequent seasons until a new rule is published. No later Quiniela rules PDF was found in the current official listing during this check. This is a dated source check, not a guarantee that SELAE will not publish a later amendment.

The official PDF confirms:
- Norma 5: 0.75 EUR per Quiniela bet and 0.50 EUR per Elige 8 participation.
- Norma 18.2: selecting multiple Pleno al 15 goal categories multiplies the combinations of the first 14 matches. The current engine chooses exactly one category for each team, so its Pleno multiplier is 1.
- Norma 22: the multiple-direct method is restricted to the combinations in Anexo I. The implemented direct double/triple limits and 31,104-column maximum are based on that table.
- Norma 18.1 defines the Pleno al 15 categories as 0, 1, 2 and M (three or more goals).

The current optimizer therefore remains explicitly limited to **multiple-direct, one Pleno category per team**. It does not claim support for reduced/conditioned systems, multiple Pleno selections, Elige8, or retailer/online validation.

Sources:
- SELAE, current normative index: https://www.selae.es/es/web-corporativa/normativa/normativa-de-los-juegos/normativa-de-los-juegos-web-corporativa
- SELAE, Normas de La Quiniela (from 2019/20; see normas 5, 18, 22, 52.4 and Anexo I): https://testportal.selae.es/f/loterias/documentos/Quiniela/Normativa%20Quiniela/NORMAS_LA_QUINIELA_TEMPORADA_19_20.pdf
