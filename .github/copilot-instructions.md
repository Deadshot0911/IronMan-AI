# Copilot instructions for IronMan AI

## Repository shape

This repo is a hybrid desktop + web assistant project:

- `jarvis_core.py` is the primary runtime. It owns the wake/listen flow, audio processing, model routing, websocket state updates, and the embedded PyWebView window that hosts the browser UI.
- `sentinel.py` is an offline Vosk wake-word listener. It pauses while the Jarvis backend uses the microphone and launches `Start_Jarvis.bat` after hearing "Jarvis".
- `hologram.py` is a separate PyQt hologram overlay used as a visual shell and input surface.
- `jarvis-ui/` is a standalone Next.js app that renders the browser UI. It communicates with the Python backend over a local websocket at `ws://localhost:8000`.
- `vosk-model/` and `vosk-model-small/` contain local speech-model assets. They are not normal application code and should only be touched when updating speech model packaging or assets.
- `jarvis_memory.json` stores assistant memory/history state between sessions.

## Build, lint, and validation commands

### Python runtime

There is no repository-level Python test or lint runner configured in the root. The practical startup commands are:

```bash
# from repo root
.\.venv\Scripts\python.exe jarvis_core.py
```

Or use the bundled Windows launchers:

```bat
Start_Jarvis.bat
Start_Sentinel.bat
```

Run `Install_Jarvis_Startup.bat` once to add the hidden wake listener to the current Windows account's Startup folder. The installer removes the legacy non-interactive `Jarvis Sentinel` scheduled task, which cannot open Jarvis's desktop window. After signing in, say "Jarvis" to start the production UI and assistant together. The bundled `vosk-model-small/` is required for offline wake detection. Closing Jarvis from the window controls or by saying/typing "Jarvis, terminate" closes the app and its UI server; the independent wake listener stays active and can relaunch it.

The frameless Jarvis window should use the Windows work area rather than cover the taskbar. Keep the minimize and close controls available in both expanded and minimized UI states.

Run the app with its project virtual-environment interpreter; the system-wide `python` may not have the audio and AI dependencies. If the launcher reports a missing `.venv`, create it and install the project’s Python dependencies before starting Jarvis.

If you need a quick syntax check for Python changes, use:

```bash
.\.venv\Scripts\python.exe -m py_compile jarvis_core.py
```

### UI app (`jarvis-ui/`)

This is the only project in the repo with an explicit Node toolchain and scripts.

```bash
cd jarvis-ui
npm install
npm run dev
```

Production build and lint:

```bash
cd jarvis-ui
npm run build
npm run lint
```

There is currently no `test` script in `jarvis-ui/package.json`, so there is no repo-standard single-test command to run today. If a test runner is introduced later, prefer the project’s established test command; for the current codebase, validation is done by `npm run build` and `npm run lint` rather than a unit test suite.

## Architecture notes that matter for edits

- The project is split between a Python backend and a separate web frontend. Do not assume that a UI change belongs to the Python process or vice versa; the boundary is explicit and intentional.
- The core AI loop lives in `jarvis_core.py`: listen -> transcribe -> classify intent -> route through model providers -> produce spoken or text output. Changes to the assistant behavior usually happen here rather than in the UI app.
- Model/provider switching is implemented in the Python backend with Gemini, Groq, and Ollama support. If you change provider logic, keep the backend routing and current state model (`online`, `silent`, `memory`, `output_pref`, `forced_engine`) in sync.
- The UI app is a thin state-display/interaction layer. It receives state and chat events from the backend over websocket messages and emits commands back to it using `jarvisCommand` and `jarvisAction` events.
- `jarvis_memory.json` is part of the runtime state. Memory toggles and persistence are handled in the Python code, not in the Next.js app.

## Key conventions and repo-specific patterns

- Keep API keys in `.env` and load them through `load_dotenv()`. Do not hardcode secrets into runtime code or commit `.env` values.
- The repo uses Windows batch launchers for the desktop assistant; prefer those scripts when validating or reproducing startup behavior.
- The Python app is stateful and event-driven. Many behaviors depend on shared globals such as `state`, `online`, `silent`, `memory_on`, and `output_pref`; when editing, check whether the change should update the websocket state payload or UI state as well.
- The Next.js app is not a generic template. The project includes a repo-specific warning in `jarvis-ui/AGENTS.md` stating that this is a breaking-change Next.js version and that developers should read the relevant docs in `node_modules/next/dist/docs/` before writing code.
- Prefer targeted validation over broad repo-wide checks. The codebase is split across a desktop Python app and a web app, so focused checks on the file or subsystem you changed are more useful than a monorepo-style full-suite pass.

## Important repo-specific guidance

- For UI work in `jarvis-ui/`, treat the app as a standalone Next.js project, not as a root-level app. Run commands from that directory and expect `next`/`eslint` commands to be scoped there.
- For backend work in the Python files, validate the affected script via direct startup or a small `compileall` pass rather than assuming a general test harness exists.
- Keep edits minimal and consistent with the present architecture: one runtime shell (`jarvis_core.py`), one wake listener (`sentinel.py`), one PyQt hologram UI (`hologram.py`), and one Next.js UI app (`jarvis-ui/`).
