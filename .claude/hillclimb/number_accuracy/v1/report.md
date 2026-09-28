# Number accuracy - v1

50 graded rows (0 truncated, excluded) · 0 failed attempts · model claude-sonnet-4-6 · harness 1922eb8f06a7

- **Correct: 50/50 = 100%** (95% CI 93%-100%)
- **From data: 50/50 = 100%** (95% CI 93%-100%)
- Cost: $0.606 total, $0.0112 median per case
- Latency: 8.2s median, 20.2s max

| Case | Type | Correct | From data | Tools | Latency | Cost | Why |
|---|---|---|---|---|---|---|---|
| [aapl_vs_msft_net_income](traces/aapl_vs_msft_net_income_rep0.json) | comparison | ✅ | ✅ | 2 | 8s | $0.0147 |  |
| [aapl_vs_msft_net_income](traces/aapl_vs_msft_net_income_rep1.json) | comparison | ✅ | ✅ | 2 | 8s | $0.0145 |  |
| [v_vs_ma_revenue](traces/v_vs_ma_revenue_rep0.json) | comparison | ✅ | ✅ | 2 | 18s | $0.0291 |  |
| [v_vs_ma_revenue](traces/v_vs_ma_revenue_rep1.json) | comparison | ✅ | ✅ | 2 | 13s | $0.0148 |  |
| [wmt_vs_tgt_revenue](traces/wmt_vs_tgt_revenue_rep0.json) | comparison | ✅ | ✅ | 2 | 13s | $0.0164 |  |
| [wmt_vs_tgt_revenue](traces/wmt_vs_tgt_revenue_rep1.json) | comparison | ✅ | ✅ | 2 | 13s | $0.0150 |  |
| [aapl_net_margin](traces/aapl_net_margin_rep1.json) | derived | ✅ | ✅ | 2 | 8s | $0.0142 |  |
| [aapl_net_margin](traces/aapl_net_margin_rep0.json) | derived | ✅ | ✅ | 2 | 10s | $0.0147 |  |
| [cost_fcf](traces/cost_fcf_rep0.json) | derived | ✅ | ✅ | 2 | 10s | $0.0166 |  |
| [cost_fcf](traces/cost_fcf_rep1.json) | derived | ✅ | ✅ | 2 | 10s | $0.0120 |  |
| [tsla_growth](traces/tsla_growth_rep1.json) | derived | ✅ | ✅ | 1 | 16s | $0.0164 |  |
| [tsla_growth](traces/tsla_growth_rep0.json) | derived | ✅ | ✅ | 1 | 19s | $0.0276 |  |
| [nvda_revenue_3y](traces/nvda_revenue_3y_rep0.json) | multi_year | ✅ | ✅ | 1 | 8s | $0.0124 |  |
| [nvda_revenue_3y](traces/nvda_revenue_3y_rep1.json) | multi_year | ✅ | ✅ | 1 | 8s | $0.0075 |  |
| [wmt_revenue_2y](traces/wmt_revenue_2y_rep0.json) | multi_year | ✅ | ✅ | 1 | 7s | $0.0106 |  |
| [wmt_revenue_2y](traces/wmt_revenue_2y_rep1.json) | multi_year | ✅ | ✅ | 1 | 7s | $0.0069 |  |
| [aapl_eps](traces/aapl_eps_rep0.json) | single | ✅ | ✅ | 1 | 8s | $0.0104 |  |
| [aapl_eps](traces/aapl_eps_rep1.json) | single | ✅ | ✅ | 1 | 8s | $0.0073 |  |
| [aapl_revenue](traces/aapl_revenue_rep0.json) | single | ✅ | ✅ | 1 | 8s | $0.0101 |  |
| [aapl_revenue](traces/aapl_revenue_rep1.json) | single | ✅ | ✅ | 1 | 9s | $0.0109 |  |
| [aapl_revenue_2024](traces/aapl_revenue_2024_rep0.json) | single | ✅ | ✅ | 2 | 9s | $0.0147 |  |
| [aapl_revenue_2024](traces/aapl_revenue_2024_rep1.json) | single | ✅ | ✅ | 2 | 10s | $0.0105 |  |
| [cost_revenue](traces/cost_revenue_rep0.json) | single | ✅ | ✅ | 1 | 8s | $0.0114 |  |
| [cost_revenue](traces/cost_revenue_rep1.json) | single | ✅ | ✅ | 1 | 8s | $0.0069 |  |
| [gs_revenue](traces/gs_revenue_rep1.json) | single | ✅ | ✅ | 1 | 13s | $0.0121 |  |
| [gs_revenue](traces/gs_revenue_rep0.json) | single | ✅ | ✅ | 1 | 16s | $0.0120 |  |
| [jpm_net_income](traces/jpm_net_income_rep0.json) | single | ✅ | ✅ | 1 | 7s | $0.0105 |  |
| [jpm_net_income](traces/jpm_net_income_rep1.json) | single | ✅ | ✅ | 1 | 6s | $0.0059 |  |
| [jpm_total_assets](traces/jpm_total_assets_rep0.json) | single | ✅ | ✅ | 1 | 7s | $0.0114 |  |
| [jpm_total_assets](traces/jpm_total_assets_rep1.json) | single | ✅ | ✅ | 1 | 11s | $0.0090 |  |
| [ko_ltd](traces/ko_ltd_rep0.json) | single | ✅ | ✅ | 1 | 9s | $0.0115 |  |
| [ko_ltd](traces/ko_ltd_rep1.json) | single | ✅ | ✅ | 1 | 9s | $0.0066 |  |
| [ma_net_income](traces/ma_net_income_rep0.json) | single | ✅ | ✅ | 1 | 8s | $0.0105 |  |
| [ma_net_income](traces/ma_net_income_rep1.json) | single | ✅ | ✅ | 1 | 8s | $0.0103 |  |
| [msft_net_income](traces/msft_net_income_rep0.json) | single | ✅ | ✅ | 1 | 8s | $0.0106 |  |
| [msft_net_income](traces/msft_net_income_rep1.json) | single | ✅ | ✅ | 1 | 8s | $0.0109 |  |
| [nvda_10k_date](traces/nvda_10k_date_rep0.json) | single | ✅ | ✅ | 1 | 5s | $0.0093 |  |
| [nvda_10k_date](traces/nvda_10k_date_rep1.json) | single | ✅ | ✅ | 1 | 6s | $0.0049 |  |
| [nvda_revenue](traces/nvda_revenue_rep0.json) | single | ✅ | ✅ | 1 | 8s | $0.0098 |  |
| [nvda_revenue](traces/nvda_revenue_rep1.json) | single | ✅ | ✅ | 1 | 7s | $0.0062 |  |
| [tsla_ocf](traces/tsla_ocf_rep0.json) | single | ✅ | ✅ | 1 | 8s | $0.0114 |  |
| [tsla_ocf](traces/tsla_ocf_rep1.json) | single | ✅ | ✅ | 1 | 8s | $0.0080 |  |
| [v_net_income](traces/v_net_income_rep0.json) | single | ✅ | ✅ | 1 | 8s | $0.0101 |  |
| [v_net_income](traces/v_net_income_rep1.json) | single | ✅ | ✅ | 1 | 6s | $0.0061 |  |
| [fake_ticker](traces/fake_ticker_rep0.json) | unavailable | ✅ | ✅ | 2 | 7s | $0.0123 |  |
| [fake_ticker](traces/fake_ticker_rep1.json) | unavailable | ✅ | ✅ | 2 | 9s | $0.0086 |  |
| [jpm_gross_profit](traces/jpm_gross_profit_rep0.json) | unavailable | ✅ | ✅ | 1 | 11s | $0.0155 |  |
| [jpm_gross_profit](traces/jpm_gross_profit_rep1.json) | unavailable | ✅ | ✅ | 1 | 12s | $0.0128 |  |
| [xom_revenue](traces/xom_revenue_rep0.json) | unavailable | ✅ | ✅ | 2 | 19s | $0.0247 |  |
| [xom_revenue](traces/xom_revenue_rep1.json) | unavailable | ✅ | ✅ | 2 | 20s | $0.0191 |  |