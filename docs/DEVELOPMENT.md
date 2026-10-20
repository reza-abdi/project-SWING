# Development commands

The project has two Python APIs and two static HTML/JavaScript dashboards; it has no JavaScript build step. Use the Make targets to set up CPython 3.12, check imports and available artifacts, run unit or full test suites, inspect offline readiness, and launch all four local processes.

On macOS and Linux, create the environment and install project dependencies with `make setup`. If Python 3.12 is not the `python3.12` command, pass its executable with `make setup PYTHON=/path/to/python3.12`. Then run `make check`, `make test-unit`, or `make run`.

PowerShell equivalents:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pytest
.\.venv\Scripts\python.exe -m compileall -q main.py modules scripts
.\.venv\Scripts\python.exe scripts\check_runtime.py --offline
.\.venv\Scripts\python.exe -m pytest -q tests\unit
.\.venv\Scripts\python.exe -m pytest -q tests
.\.venv\Scripts\python.exe main.py
```

`test-api` runs the complete pytest tree so API tests are included as they are added. `build` checks Python syntax because the browser dashboards are served directly as static assets.
