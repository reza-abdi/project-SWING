# Forecasting contract

## Inputs and provenance

The load/weather harmonizer joins load `datetime` and weather `Datetime` as hourly timestamps and preserves the source demand column spelling `Northen Region Hourly Demand`. Engineered predictors are ordered as `hour_sin`, `hour_cos`, `dayofweek`, `month`, `load_lag_1`, `load_lag_2`, `load_lag_24`, and `Northern_Region_Avg_T2M`.

The TFT helper currently builds its inference window from the tail of `data/processed_data/tft_ready_data.csv`. That window is a **historical proxy**, not live or operator-provided telemetry. A future live integration must supply timestamped load and covariate history explicitly and must not silently label historical values as live measurements.

## Forecast units and horizons

Both models predict `normalized_target`. Convert each normalized estimate to MW by multiplying it by the current grid baseline MW for the selected grid. Baseline validation must require a finite positive value. `GridForecaster.forecast_next_hour` returns the scalar MW bounds `{p10, p50, p90}` for the next hour.

`TFTForecaster.forecast_multi_horizon` returns three 24-element arrays, `{p10, p50, p90}`, in chronological hourly order. Array index 0 is hour 1, index 1 is hour 2, index 5 is hour 6, and index 23 is hour 24. The 1h, 2h, 6h, and 24h labels refer to those positions in one hourly forecast; they do not represent separate model runs or 15-minute forecasts.

The TFT helper returns normalized model-space values. Callers that display or compare them with physical demand must scale every horizon by the same current grid baseline and should preserve the quantile ordering. LightGBM's `forecast_next_hour` performs that conversion itself and returns MW.

## API and display boundary

The documented proposal API exposes a `forecast_bounds` object, but no frontend forecast consumer is present in this repository at this stage. Agent integration must publish explicit units and horizon labels and should use keys such as `p10_1h`, `p50_1h`, `p90_1h`, `p10_2h`, `p50_2h`, `p90_2h`, `p10_6h`, `p50_6h`, `p90_6h`, `p10_24h`, `p50_24h`, and `p90_24h`. If TFT is unavailable, only the 1h LightGBM values are populated; longer-horizon values remain null rather than being extrapolated.

Forecasts are advisory estimates. They do not establish regulatory compliance, guarantee physical feasibility, or authorize Twin actuation. Candidate actions continue through the separate validation and operator approval paths.
