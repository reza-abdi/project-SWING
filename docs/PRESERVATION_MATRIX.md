# Reference preservation and acceptance inventory

The read-only `Project_SWING.zip` contains **80 application files** after excluding directories, `.git/`, and `node_modules/`. This matrix tracks source-equivalent reconstruction; a listed item is not claimed complete until the destination file, verification, and any deviation are recorded. The owner has confirmed public redistribution permission for the supplied materials. Keep source attributions and applicable third-party notices.

| Source category | Archive contents | Destination acceptance check | Current state |
| --- | --- | --- | --- |
| Core launcher and dependencies | `main.py`, `requirements.txt`; source `package.json` and `package-lock.json` are empty manifests | Local four-process launch and reproducible install; document any manifest replacement | Manifests and scripts present; full Python runtime install/suite not verified in this pass |
| Physics Twin and shared events | `modules/physics_engine/{api,scenario_engine,grid_metrics,twin_model}.py`, `modules/event_store.py` | Both IEEE cases, metrics, scenario validation, API, telemetry, event persistence; mutation rollback and authenticated writes | Implementation present; full Python regression and live persistence not verified in this pass |
| AI Agent | `modules/ai_agents/{agent_core,agent_api,rag_builder}.py` | HTTP-only Twin client, proposal and operator approval workflow, chat, regulatory retrieval | Implementation present; full Python regression pending; bundled FAISS pickle excluded from deployment image pending trusted-index review |
| Forecast and optimization code | `modules/forecasting/{grid_forecaster,tft_forecaster,fetch_weather}.py`, `modules/optimization_engine/{rl_env,rl_optimizer}.py` | Source-equivalent predictions, controlled model loading, RL and physics fallbacks | Implementation and artifacts present; real model inference acceptance pending |
| Digital Twin UI | 3 HTML pages, `app.js`, `style.css`, `digital_twin.png`, 15 files in `Digital_Twin_UI/icons/` | Original interactive grid views and telemetry against stable API | Same-origin deployment routes present; browser regression coverage passed (3 Twin tests) |
| Agent dashboard UI | 5 HTML pages, 4 JS files, `style.css`, `project_swing.png`, `swing_logo.png` | Proposal, chat, forecast, and RL views against stable API | Same-origin API fallbacks present; browser regression coverage passed (4 Agent tests); remote login flow pending |
| Raw and processed data | `hourlyLoadDataIndia.csv`, `Northern_Region_Hourly_Weather_2019_2024.csv`, `tft_ready_data.csv` | Source hashes and schemas, including the source's `Northen Region Hourly Demand` spelling | All three source SHA-256 digests verified; schema acceptance not rerun in this pass |
| Regulatory corpus and index | `IEGC_Code.pdf`, `faiss_index/index.faiss`, `faiss_index/index.pkl` | PDF provenance and complete text; index rebuilt or verified before any deserialization | Source digests verified; independent PDF terms unresolved; pickle not deserialized and is excluded from deployment image |
| Pretrained inference assets | 3 LightGBM `.txt`, 4 SAC `.zip`, `tft_best_model.ckpt`, `training_dataset.pkl` | Exact hashes, safe-load policy, real inference checks | 19 dataset/model/regulatory artifact hashes match source archive; real CPU inference remains unverified |
| Research artifacts | 4 RL reward CSVs, 2 notebooks, 4 TFT importance PNGs | Preserve supplied data and plots; notebooks remain optional training workflows | Pending |
| Scripts and root visual | `scripts/evaluate_metrics.py`, `scripts/train_rl_agent.py`, `Project_SWING.png` | CLI behavior, metrics, and original visual | Pending |
| Repository text | Source `.gitignore` and `README.md` | Extend ignore rules; create destination README near delivery | Ignore rules and destination README present; attribution/license boundaries documented |

The full per-file archive list and SHA-256 comparison are available through `scripts/check_source_manifest.py`. Record deliberate edits with its `--transformations` map and in this matrix as work proceeds. Byte-for-byte hashes matter for curated data and original binary assets; reviewed source fixes may intentionally differ from the archive.

## Phase N/O delivery status

- Dockerfiles, Compose wiring, Nginx routes/TLS template, secret guidance, rollback instructions, manual deployment workflow, deployment contract checks, final README, changelog, attribution notes, and a deployment report are implemented.
- Same-origin public API/WebSocket fallbacks are implemented. The Digital Twin frontend test harness was corrected to exercise `/api/twin/...`; all seven Playwright tests pass in this environment when Chromium is granted its required macOS process permissions.
- `scripts/validate_deployment.py`, JavaScript syntax checks, YAML syntax parsing, `git diff --check`, and the tracked secret audit pass. The secret audit reports zero findings; pip advisory status is not checked because `pip-audit` is unavailable.
- Docker/Nginx builds, Compose schema validation, full Python tests, trusted model inference, live SQLite persistence/rollback, and any host deployment remain unverified. This execution environment has no Docker/Nginx and its checked-in Python 3.12 venv has lost its standard library; system Python 3.9 is insufficient for the project suite.
- A remote dashboard login flow is still absent. Static bearer-token API auth exists, but OIDC/session configuration variables are reserved. Public write-enabled browser use is therefore a release gate.
- The supplied archive owner's public redistribution permission is recorded. Third-party commercial-use terms for the PDF, data, models, and media have not been independently established.

The 19 curated dataset, model, and regulatory artifacts listed in `docs/ARTIFACT_MANIFEST.json` matched their SHA-256 values in the supplied source archive during reconstruction. This establishes byte parity only; it does not establish third-party licensing, trust in pickle deserialization, or inference compatibility.

## Intentional omissions and deviations

- Never import the archive's `.git/` history, `node_modules/` metadata, Python caches, local SQLite databases, logs, or secrets.
- The destination retains its existing MIT `LICENSE`; the source archive had no top-level license. The destination README explains that upstream material keeps its own terms.
- Destination `.gitignore` extends the source rules to protect runtime state and secrets.
- Package marker files, central configuration, tests, and safety documentation are new reconstruction infrastructure, not claimed source files.
- No scientific or runtime behavior deviation has been accepted yet. Add a specific entry here before any such change is described as complete.
- The deployment image omits the provided FAISS index and pickle until a trusted manifest and rebuilt/verified artifact are available; retrieval may be unavailable in the container profile.
- Remote browser clients do not yet acquire or send the configured static bearer token. This is an intentional fail-closed limitation pending an identity/login design, not an assertion that remote dashboard writes work.
- Remote browser asset URLs now use same-origin `/api/twin`, `/api/agent`, and `/ws/twin` routes when explicit browser URLs are absent; local loopback defaults are retained.
- The server-side Twin client attaches `SWING_INTERNAL_TWIN_TOKEN` to protected Twin simulation mutation calls. It remains distinct from the browser operator token and Twin administrator token.
