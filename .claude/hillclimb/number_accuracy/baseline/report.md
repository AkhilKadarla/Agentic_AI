# Number accuracy - baseline

50 graded rows (0 truncated, excluded) · 0 failed attempts · model claude-sonnet-4-6 · harness 16d4f3a416c1

- **Correct: 50/50 = 100%** (95% CI 93%-100%)
- **From data: 50/50 = 100%** (95% CI 93%-100%)
- Cost: $0.623 total, $0.0113 median per case
- Latency: 8.9s median, 67.8s max

| Case | Type | Correct | From data | Tools | Latency | Cost | Why |
|---|---|---|---|---|---|---|---|
| [aapl_vs_msft_net_income](traces/aapl_vs_msft_net_income_rep0.json) | comparison | ✅ | ✅ | 2 | 9s | $0.0150 |  |
| [aapl_vs_msft_net_income](traces/aapl_vs_msft_net_income_rep1.json) | comparison | ✅ | ✅ | 2 | 9s | $0.0104 |  |
| [v_vs_ma_revenue](traces/v_vs_ma_revenue_rep0.json) | comparison | ✅ | ✅ | 2 | 20s | $0.0263 |  |
| [v_vs_ma_revenue](traces/v_vs_ma_revenue_rep1.json) | comparison | ✅ | ✅ | 2 | 15s | $0.0195 |  |
| [wmt_vs_tgt_revenue](traces/wmt_vs_tgt_revenue_rep0.json) | comparison | ✅ | ✅ | 2 | 14s | $0.0183 |  |
| [wmt_vs_tgt_revenue](traces/wmt_vs_tgt_revenue_rep1.json) | comparison | ✅ | ✅ | 2 | 12s | $0.0129 |  |
| [aapl_net_margin](traces/aapl_net_margin_rep0.json) | derived | ✅ | ✅ | 2 | 9s | $0.0149 |  |
| [aapl_net_margin](traces/aapl_net_margin_rep1.json) | derived | ✅ | ✅ | 2 | 9s | $0.0106 |  |
| [cost_fcf](traces/cost_fcf_rep0.json) | derived | ✅ | ✅ | 2 | 68s | $0.0154 |  |
| [cost_fcf](traces/cost_fcf_rep1.json) | derived | ✅ | ✅ | 2 | 9s | $0.0155 |  |
| [tsla_growth](traces/tsla_growth_rep0.json) | derived | ✅ | ✅ | 1 | 17s | $0.0233 |  |
| [tsla_growth](traces/tsla_growth_rep1.json) | derived | ✅ | ✅ | 1 | 17s | $0.0206 |  |
| [nvda_revenue_3y](traces/nvda_revenue_3y_rep0.json) | multi_year | ✅ | ✅ | 1 | 37s | $0.0131 |  |
| [nvda_revenue_3y](traces/nvda_revenue_3y_rep1.json) | multi_year | ✅ | ✅ | 1 | 9s | $0.0123 |  |
| [wmt_revenue_2y](traces/wmt_revenue_2y_rep1.json) | multi_year | ✅ | ✅ | 1 | 7s | $0.0113 |  |
| [wmt_revenue_2y](traces/wmt_revenue_2y_rep0.json) | multi_year | ✅ | ✅ | 1 | 10s | $0.0112 |  |
| [aapl_eps](traces/aapl_eps_rep0.json) | single | ✅ | ✅ | 1 | 7s | $0.0112 |  |
| [aapl_eps](traces/aapl_eps_rep1.json) | single | ✅ | ✅ | 1 | 8s | $0.0066 |  |
| [aapl_revenue](traces/aapl_revenue_rep0.json) | single | ✅ | ✅ | 1 | 35s | $0.0105 |  |
| [aapl_revenue](traces/aapl_revenue_rep1.json) | single | ✅ | ✅ | 1 | 9s | $0.0098 |  |
| [aapl_revenue_2024](traces/aapl_revenue_2024_rep0.json) | single | ✅ | ✅ | 2 | 10s | $0.0154 |  |
| [aapl_revenue_2024](traces/aapl_revenue_2024_rep1.json) | single | ✅ | ✅ | 2 | 11s | $0.0114 |  |
| [cost_revenue](traces/cost_revenue_rep0.json) | single | ✅ | ✅ | 1 | 7s | $0.0101 |  |
| [cost_revenue](traces/cost_revenue_rep1.json) | single | ✅ | ✅ | 1 | 16s | $0.0076 |  |
| [gs_revenue](traces/gs_revenue_rep0.json) | single | ✅ | ✅ | 1 | 8s | $0.0113 |  |
| [gs_revenue](traces/gs_revenue_rep1.json) | single | ✅ | ✅ | 1 | 8s | $0.0075 |  |
| [jpm_net_income](traces/jpm_net_income_rep0.json) | single | ✅ | ✅ | 1 | 8s | $0.0116 |  |
| [jpm_net_income](traces/jpm_net_income_rep1.json) | single | ✅ | ✅ | 1 | 7s | $0.0063 |  |
| [jpm_total_assets](traces/jpm_total_assets_rep0.json) | single | ✅ | ✅ | 1 | 8s | $0.0118 |  |
| [jpm_total_assets](traces/jpm_total_assets_rep1.json) | single | ✅ | ✅ | 1 | 7s | $0.0117 |  |
| [ko_ltd](traces/ko_ltd_rep0.json) | single | ✅ | ✅ | 1 | 8s | $0.0112 |  |
| [ko_ltd](traces/ko_ltd_rep1.json) | single | ✅ | ✅ | 1 | 9s | $0.0069 |  |
| [ma_net_income](traces/ma_net_income_rep1.json) | single | ✅ | ✅ | 1 | 7s | $0.0104 |  |
| [ma_net_income](traces/ma_net_income_rep0.json) | single | ✅ | ✅ | 1 | 9s | $0.0115 |  |
| [msft_net_income](traces/msft_net_income_rep0.json) | single | ✅ | ✅ | 1 | 8s | $0.0101 |  |
| [msft_net_income](traces/msft_net_income_rep1.json) | single | ✅ | ✅ | 1 | 34s | $0.0089 |  |
| [nvda_10k_date](traces/nvda_10k_date_rep0.json) | single | ✅ | ✅ | 1 | 6s | $0.0093 |  |
| [nvda_10k_date](traces/nvda_10k_date_rep1.json) | single | ✅ | ✅ | 1 | 5s | $0.0051 |  |
| [nvda_revenue](traces/nvda_revenue_rep0.json) | single | ✅ | ✅ | 1 | 10s | $0.0099 |  |
| [nvda_revenue](traces/nvda_revenue_rep1.json) | single | ✅ | ✅ | 1 | 10s | $0.0105 |  |
| [tsla_ocf](traces/tsla_ocf_rep0.json) | single | ✅ | ✅ | 1 | 7s | $0.0114 |  |
| [tsla_ocf](traces/tsla_ocf_rep1.json) | single | ✅ | ✅ | 1 | 7s | $0.0073 |  |
| [v_net_income](traces/v_net_income_rep0.json) | single | ✅ | ✅ | 1 | 7s | $0.0106 |  |
| [v_net_income](traces/v_net_income_rep1.json) | single | ✅ | ✅ | 1 | 7s | $0.0076 |  |
| [fake_ticker](traces/fake_ticker_rep0.json) | unavailable | ✅ | ✅ | 2 | 7s | $0.0126 |  |
| [fake_ticker](traces/fake_ticker_rep1.json) | unavailable | ✅ | ✅ | 2 | 7s | $0.0088 |  |
| [jpm_gross_profit](traces/jpm_gross_profit_rep0.json) | unavailable | ✅ | ✅ | 1 | 10s | $0.0159 |  |
| [jpm_gross_profit](traces/jpm_gross_profit_rep1.json) | unavailable | ✅ | ✅ | 1 | 12s | $0.0175 |  |
| [xom_revenue](traces/xom_revenue_rep0.json) | unavailable | ✅ | ✅ | 2 | 17s | $0.0213 |  |
| [xom_revenue](traces/xom_revenue_rep1.json) | unavailable | ✅ | ✅ | 2 | 18s | $0.0230 |  |