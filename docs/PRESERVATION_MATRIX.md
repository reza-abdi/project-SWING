# Reference preservation and acceptance inventory

The read-only `Project_SWING.zip` contains **80 application files** after excluding directories, `.git/`, and `node_modules/`. This matrix tracks source-equivalent reconstruction; a listed item is not claimed complete until the destination file, verification, and any deviation are recorded. The owner has confirmed public redistribution permission for the supplied materials. Keep source attributions and applicable third-party notices.

| Source category | Archive contents | Destination acceptance check | Current state |
| --- | --- | --- | --- |
| Core launcher and dependencies | `main.py`, `requirements.txt`; source `package.json` and `package-lock.json` are empty manifests | Local four-process launch and reproducible install; document any manifest replacement | Pending |
| Physics Twin and shared events | `modules/physics_engine/{api,scenario_engine,grid_metrics,twin_model}.py`, `modules/event_store.py` | Both IEEE cases, metrics, scenario validation, API, telemetry, event persistence; mutation rollback and authenticated writes | Pending |
| AI Agent | `modules/ai_agents/{agent_core,agent_api,rag_builder}.py` | HTTP-only Twin client, proposal and operator approval workflow, chat, regulatory retrieval | Pending |
| Forecast and optimization code | `modules/forecasting/{grid_forecaster,tft_forecaster,fetch_weather}.py`, `modules/optimization_engine/{rl_env,rl_optimizer}.py` | Source-equivalent predictions, controlled model loading, RL and physics fallbacks | Pending |
| Digital Twin UI | 3 HTML pages, `app.js`, `style.css`, `digital_twin.png`, 15 files in `Digital_Twin_UI/icons/` | Original interactive grid views and telemetry against stable API | Pending |
| Agent dashboard UI | 5 HTML pages, 4 JS files, `style.css`, `project_swing.png`, `swing_logo.png` | Proposal, chat, forecast, and RL views against stable API | Pending |
| Raw and processed data | `hourlyLoadDataIndia.csv`, `Northern_Region_Hourly_Weather_2019_2024.csv`, `tft_ready_data.csv` | Source hashes and schemas, including the source's `Northen Region Hourly Demand` spelling | Pending |
| Regulatory corpus and index | `IEGC_Code.pdf`, `faiss_index/index.faiss`, `faiss_index/index.pkl` | PDF provenance and complete text; index rebuilt or verified before any deserialization | Pending |
| Pretrained inference assets | 3 LightGBM `.txt`, 4 SAC `.zip`, `tft_best_model.ckpt`, `training_dataset.pkl` | Exact hashes, safe-load policy, real inference checks | Pending |
| Research artifacts | 4 RL reward CSVs, 2 notebooks, 4 TFT importance PNGs | Preserve supplied data and plots; notebooks remain optional training workflows | Pending |
| Scripts and root visual | `scripts/evaluate_metrics.py`, `scripts/train_rl_agent.py`, `Project_SWING.png` | CLI behavior, metrics, and original visual | Pending |
| Repository text | Source `.gitignore` and `README.md` | Extend ignore rules; create destination README near delivery | Ignore rules done; README pending |

The full per-file archive list and SHA-256 comparison are available through `scripts/check_source_manifest.py`. Record deliberate edits with its `--transformations` map and in this matrix as work proceeds. Byte-for-byte hashes matter for curated data and original binary assets; reviewed source fixes may intentionally differ from the archive.

## Intentional omissions and deviations

- Never import the archive's `.git/` history, `node_modules/` metadata, Python caches, local SQLite databases, logs, or secrets.
- The destination already has its own MIT `LICENSE` and placeholder `README.md`; the source archive had no top-level license. Preserve legally required attributions during review. The final README is planned near delivery.
- Destination `.gitignore` extends the source rules to protect runtime state and secrets.
- Package marker files, central configuration, tests, and safety documentation are new reconstruction infrastructure, not claimed source files.
- No scientific or runtime behavior deviation has been accepted yet. Add a specific entry here before any such change is described as complete.
