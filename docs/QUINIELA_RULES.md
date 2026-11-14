# Official Quiniela ticket constraints

Checked on 2026-11-14 for implementation defaults.

- SELAE's 2024 annual report lists La Quiniela at 0.75 EUR per simple bet, a minimum participation of two bets (1.50 EUR), and the game format as 14 + 1 matches.
- SELAE's official Quiniela rules describe the Pleno al 15 goal categories as 0, 1, 2 and M for each team, with M representing three or more goals.
- The optimizer therefore treats its budget as a maximum number of 14-match columns, enforces at least two columns, and reports an estimated ticket cost at 0.75 EUR per column.
- The price is configurable in TicketOptimizer; verify the current season's official rules before submitting a real ticket. The optimizer does not validate retailer/online acceptance, reduced-system restrictions, or Elige 8 participation.

Sources:
- SELAE, Estado de Información no financiera 2024, game portfolio and Quiniela price/minimum participation: https://www.selae.es/f/loterias/web_corporativa/Quienes_somos/CuentasAnuales/Estado-de-Informacion-no-financiera-SELAE-2024.pdf
- SELAE, Normas de la Quiniela, temporada 2015-2016, Pleno al 15 goal categories: https://www.selae.es/f/loterias/documentos/Quiniela/Normativa%20Quiniela/NORMAS%20DE%20LA%20QUINIELA%20T-2015-2016.pdf
