# Reference service boundaries and HTTP contract

This records routes found in the supplied archive. They are **reference contracts**, not a claim that the destination APIs are implemented yet. Changes for authentication, approval, health checks, or read-only forecast access must update both clients and tests when implemented.

The Digital Twin service owns pandapower state for IEEE grids `39` and `118`. The AI Agent service is an HTTP client of the Twin; it must not import or modify Twin internals. Both may use `modules/event_store.py` for a co-located SQLite event history. A grid identifier is the string `"39"` or `"118"`; reject other identifiers rather than selecting a default grid silently for mutation requests. Bus and line identifiers are integer indices within the selected grid.

## Digital Twin reference routes

| Method | Route | Reference response or effect |
| --- | --- | --- |
| GET | `/` | Service message. |
| GET | `/grid_status?grid=39\|118` | `active_grid`, bus/line counts, demand/capacity MW, `resilience`, `security`, and per-bus `bus_loads`. |
| GET | `/topology?grid=39\|118` | Cytoscape `nodes` and `edges`; node data includes ID, label, load, type. |
| GET | `/rl_status` | Availability of the four grid/action policies. |
| GET | `/contingency/{grid}` | Cached N-1 line and generator security scan. |
| POST | `/validate_action/{grid}` | Non-mutating physics check; validation and resulting loading fields. |
| POST | `/optimize_action/{grid}` | Candidate action optimized by SAC or physics search. |
| POST | `/change_load/{bus_id}?new_mw=…&grid=…` | **Mutation:** set one simulated bus load. |
| POST | `/redispatch_gen/{bus_id}?delta_mw=…&grid=…` | **Mutation:** change generator dispatch. |
| POST | `/redistribute_load/{grid}?source_bus=…&destination_bus=…&mw_amount=…` | **Mutation:** move load between buses. |
| POST | `/inject_fault/{line_id}?grid=…` | **Mutation:** trip a simulated line. |
| POST | `/restore_line/{grid}/{line_id}` | **Mutation:** restore a simulated line. |
| POST | `/stress_test/{grid}` | **Mutation:** apply load and line-rating multipliers from JSON. |
| WS | `/ws/telemetry/{grid}` | Approximately one snapshot per second, including line and bus metrics. |

## AI Agent reference routes

| Method | Route | Reference response or effect |
| --- | --- | --- |
| GET | `/` | Service message and configured Twin target. |
| POST | `/propose/{grid}` | Reads Twin status, runs the agent graph on telemetry JSON, and returns `decision`, `operator_brief`, `proposed_action`, `validation_result`, `feature_importance`, and `forecast_bounds`. Source stores only the latest pending proposal per grid. |
| POST | `/execute/{grid}` | Executes that pending proposal through Twin HTTP write routes; returns `status`, `action`, and `twin_response`. Source has no proposal ID or operator binding. |
| GET | `/events/{grid}?source=…&limit=…` | `{grid, events}` from shared event history. |
| POST | `/chat/{grid}` | Accepts `message` and `history`; returns `{response}`. |

The archive's `@app` decorators were checked against this list. The startup scanner is a lifecycle hook, not an HTTP route. Planned `/health`, forecast read endpoints, authenticated approval/rejection, and stronger error contracts are additions; document their exact shapes when built. No public write endpoint may be deployed with the reference's unauthenticated behavior.
