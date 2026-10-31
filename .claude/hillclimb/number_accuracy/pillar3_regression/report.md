# Number accuracy - pillar3_regression

50 graded rows (0 truncated, excluded) · 0 failed attempts · model claude-sonnet-4-6 · harness 85d8866b29a8

- **Correct: 46/50 = 92%** (95% CI 81%-97%)
- **From data: 46/50 = 92%** (95% CI 81%-97%)
- Cost: $0.534 total, $0.0099 median per case
- Latency: 5.0s median, 12.5s max

| Case | Type | Correct | From data | Tools | Latency | Cost | Why |
|---|---|---|---|---|---|---|---|
| [aapl_vs_msft_net_income](traces/aapl_vs_msft_net_income_rep0.json) | comparison | ✅ | ✅ | 2 | 5s | $0.0118 |  |
| [aapl_vs_msft_net_income](traces/aapl_vs_msft_net_income_rep1.json) | comparison | ✅ | ✅ | 2 | 5s | $0.0104 |  |
| [v_vs_ma_revenue](traces/v_vs_ma_revenue_rep0.json) | comparison | ✅ | ✅ | 2 | 8s | $0.0150 |  |
| [v_vs_ma_revenue](traces/v_vs_ma_revenue_rep1.json) | comparison | ✅ | ✅ | 2 | 8s | $0.0155 |  |
| [wmt_vs_tgt_revenue](traces/wmt_vs_tgt_revenue_rep1.json) | comparison | ✅ | ✅ | 2 | 7s | $0.0146 |  |
| [wmt_vs_tgt_revenue](traces/wmt_vs_tgt_revenue_rep0.json) | comparison | ✅ | ✅ | 2 | 9s | $0.0161 |  |
| [aapl_net_margin](traces/aapl_net_margin_rep0.json) | derived | ✅ | ✅ | 2 | 6s | $0.0120 |  |
| [aapl_net_margin](traces/aapl_net_margin_rep1.json) | derived | ✅ | ✅ | 2 | 6s | $0.0099 |  |
| [cost_fcf](traces/cost_fcf_rep0.json) | derived | ❌ | ❌ | 2 | 7s | $0.0139 | missing or wrong: Costco free cash flow |
| [cost_fcf](traces/cost_fcf_rep1.json) | derived | ❌ | ❌ | 2 | 6s | $0.0117 | missing or wrong: Costco free cash flow |
| [tsla_growth](traces/tsla_growth_rep0.json) | derived | ✅ | ✅ | 1 | 8s | $0.0177 |  |
| [tsla_growth](traces/tsla_growth_rep1.json) | derived | ✅ | ✅ | 1 | 9s | $0.0184 |  |
| [nvda_revenue_3y](traces/nvda_revenue_3y_rep1.json) | multi_year | ✅ | ✅ | 1 | 5s | $0.0099 |  |
| [nvda_revenue_3y](traces/nvda_revenue_3y_rep0.json) | multi_year | ✅ | ✅ | 1 | 5s | $0.0098 |  |
| [wmt_revenue_2y](traces/wmt_revenue_2y_rep0.json) | multi_year | ✅ | ✅ | 1 | 4s | $0.0079 |  |
| [wmt_revenue_2y](traces/wmt_revenue_2y_rep1.json) | multi_year | ✅ | ✅ | 1 | 4s | $0.0070 |  |
| [aapl_eps](traces/aapl_eps_rep0.json) | single | ✅ | ✅ | 1 | 4s | $0.0081 |  |
| [aapl_eps](traces/aapl_eps_rep1.json) | single | ✅ | ✅ | 1 | 4s | $0.0068 |  |
| [aapl_revenue](traces/aapl_revenue_rep0.json) | single | ✅ | ✅ | 1 | 5s | $0.0113 |  |
| [aapl_revenue](traces/aapl_revenue_rep1.json) | single | ✅ | ✅ | 1 | 6s | $0.0121 |  |
| [aapl_revenue_2024](traces/aapl_revenue_2024_rep0.json) | single | ✅ | ✅ | 2 | 6s | $0.0128 |  |
| [aapl_revenue_2024](traces/aapl_revenue_2024_rep1.json) | single | ✅ | ✅ | 2 | 7s | $0.0114 |  |
| [cost_revenue](traces/cost_revenue_rep0.json) | single | ❌ | ❌ | 1 | 4s | $0.0082 | missing or wrong: Costco revenue |
| [cost_revenue](traces/cost_revenue_rep1.json) | single | ❌ | ❌ | 1 | 4s | $0.0063 | missing or wrong: Costco revenue |
| [gs_revenue](traces/gs_revenue_rep0.json) | single | ✅ | ✅ | 1 | 5s | $0.0093 |  |
| [gs_revenue](traces/gs_revenue_rep1.json) | single | ✅ | ✅ | 1 | 5s | $0.0091 |  |
| [jpm_net_income](traces/jpm_net_income_rep0.json) | single | ✅ | ✅ | 1 | 5s | $0.0096 |  |
| [jpm_net_income](traces/jpm_net_income_rep1.json) | single | ✅ | ✅ | 1 | 4s | $0.0062 |  |
| [jpm_total_assets](traces/jpm_total_assets_rep1.json) | single | ✅ | ✅ | 1 | 5s | $0.0102 |  |
| [jpm_total_assets](traces/jpm_total_assets_rep0.json) | single | ✅ | ✅ | 1 | 5s | $0.0102 |  |
| [ko_ltd](traces/ko_ltd_rep0.json) | single | ✅ | ✅ | 1 | 5s | $0.0089 |  |
| [ko_ltd](traces/ko_ltd_rep1.json) | single | ✅ | ✅ | 1 | 6s | $0.0082 |  |
| [ma_net_income](traces/ma_net_income_rep1.json) | single | ✅ | ✅ | 1 | 4s | $0.0073 |  |
| [ma_net_income](traces/ma_net_income_rep0.json) | single | ✅ | ✅ | 1 | 4s | $0.0074 |  |
| [msft_net_income](traces/msft_net_income_rep0.json) | single | ✅ | ✅ | 1 | 4s | $0.0080 |  |
| [msft_net_income](traces/msft_net_income_rep1.json) | single | ✅ | ✅ | 1 | 4s | $0.0081 |  |
| [nvda_10k_date](traces/nvda_10k_date_rep0.json) | single | ✅ | ✅ | 1 | 3s | $0.0064 |  |
| [nvda_10k_date](traces/nvda_10k_date_rep1.json) | single | ✅ | ✅ | 1 | 3s | $0.0046 |  |
| [nvda_revenue](traces/nvda_revenue_rep0.json) | single | ✅ | ✅ | 1 | 6s | $0.0135 |  |
| [nvda_revenue](traces/nvda_revenue_rep1.json) | single | ✅ | ✅ | 1 | 4s | $0.0053 |  |
| [tsla_ocf](traces/tsla_ocf_rep1.json) | single | ✅ | ✅ | 1 | 5s | $0.0083 |  |
| [tsla_ocf](traces/tsla_ocf_rep0.json) | single | ✅ | ✅ | 1 | 6s | $0.0105 |  |
| [v_net_income](traces/v_net_income_rep0.json) | single | ✅ | ✅ | 1 | 4s | $0.0082 |  |
| [v_net_income](traces/v_net_income_rep1.json) | single | ✅ | ✅ | 1 | 4s | $0.0066 |  |
| [fake_ticker](traces/fake_ticker_rep0.json) | unavailable | ✅ | ✅ | 2 | 4s | $0.0092 |  |
| [fake_ticker](traces/fake_ticker_rep1.json) | unavailable | ✅ | ✅ | 1 | 4s | $0.0071 |  |
| [jpm_gross_profit](traces/jpm_gross_profit_rep0.json) | unavailable | ✅ | ✅ | 1 | 9s | $0.0143 |  |
| [jpm_gross_profit](traces/jpm_gross_profit_rep1.json) | unavailable | ✅ | ✅ | 1 | 9s | $0.0152 |  |
| [xom_revenue](traces/xom_revenue_rep1.json) | unavailable | ✅ | ✅ | 2 | 12s | $0.0215 |  |
| [xom_revenue](traces/xom_revenue_rep0.json) | unavailable | ✅ | ✅ | 2 | 12s | $0.0218 |  |