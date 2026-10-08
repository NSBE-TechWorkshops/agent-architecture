# Internship Agent (NSBE Cloud Workshop)

A small AI agent that reads your email and tells you which internship updates need attention first.
It is built to teach four cloud-era ideas in one project:

| Idea | Where you see it |
|---|---|
| **AI agents** (LangChain tool calling + LangGraph loop) | `app/agent/tool_graph.py`, `app/agent/tools.py` |
| **REST APIs** (a server answering HTTP requests) | `app/main.py` |
| **Clients** (a terminal app that talks to the API) | `tui/app.py` |
| **Containers** (Docker: runs the same on every laptop) | `Dockerfile`, `docker-compose.yml` |

```
 You press "r"
      |
      v
 [ Terminal UI ]  --HTTP POST /agent/stream-->  [ FastAPI server ]  -->  [ LangGraph agent ]
   (Textual)    <--live step-by-step events--      (container)               |         |
                                                                              v         v
                                                                       [ Gmail / mock ] [ OpenAI ]
```

## Quick start (Docker, works on Mac, Windows, Linux)

**Step 1: run the setup script.** It checks that Docker is installed and running, offers to install or start it if not,
creates your `.env` file, checks that port 8000 is free, and builds the image.

| Your computer | Command |
|---|---|
| Mac / Linux | `./setup.sh` (if it says permission denied: `chmod +x setup.sh`) |
| Windows (PowerShell) | `powershell -ExecutionPolicy Bypass -File .\setup.ps1` |

Add `--yes` (`-Yes` on Windows) to accept installs without being asked, or `--no-build` (`-NoBuild`) to skip the build.

**Step 2: add an OpenAI key.** This version demonstrates true tool calling, so the model must be available to choose tools.
Open `.env` and set:

```bash
OPENAI_API_KEY=sk-...
```

**Step 3: start the API.**

```bash
docker compose up
```

Open **http://localhost:8000/docs** in your browser. That page lets you click "Try it out" on every endpoint.

**Step 4: in a second terminal, open the terminal UI.**

```bash
docker compose run --rm tui
```

Press **r** to run the agent. Press **q** to quit. Stop the server with `Ctrl+C`, then `docker compose down`.

Prefer to skip the script? Install [Docker Desktop](https://www.docker.com/products/docker-desktop/), run `cp .env.example .env`,
then `docker compose up --build`.

**The agent run needs an OpenAI key.** This version demonstrates true tool calling, so the LLM must be available to choose tools.
The sample email source still works without Gmail setup, and the individual tools use simple keyword rules once the LLM calls them.

## Run without Docker (for editing code)

```bash
python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

uvicorn app.main:app --reload     # terminal 1: the API
python -m tui.app                 # terminal 2: the UI
pytest                            # run the tests
```

## Turn on the LLM (OpenAI)

1. Create a key at https://platform.openai.com/api-keys
2. Put it in `.env`: `OPENAI_API_KEY=sk-...`
3. Restart the API (`docker compose up --build`). The UI header should now say `mode: llm`.

Never commit `.env`. It is already in `.gitignore`.

## Connect your real Gmail (optional)

The agent only ever asks for **read-only** access. Do this once, on your own computer (not in Docker, because it opens a browser):

1. Go to https://console.cloud.google.com and create a project.
2. **APIs & Services > Library**: enable the **Gmail API**.
3. **OAuth consent screen**: choose External, fill in the app name, and add **your own Gmail address as a Test user**.
4. **Credentials > Create credentials > OAuth client ID > Desktop app**. Download the JSON and save it as `secrets/credentials.json`.
5. Run the login script and click "Allow":
   ```bash
   pip install -r requirements.txt   # inside a venv, see above
   python scripts/gmail_auth.py
   ```
6. In `.env` set `EMAIL_SOURCE=gmail`, then restart the API.

Notes:
- While the Google app is in "Testing" status, the login expires after **7 days**. Re-run the script if it stops working.
- **Privacy:** with `EMAIL_SOURCE=gmail` plus an OpenAI key, the text of matching emails is sent to OpenAI. Use mock mode if you are not comfortable with that.
- `secrets/` is git-ignored. Never share `token.json`; it grants access to your inbox.

## How it works (the ideas)

### LangChain vs LangGraph
- **LangChain** is the toolbox: define tools, talk to the LLM, and bind those tools to the model with `bind_tools`.
- **LangGraph** is the loop runner: it sends messages to the LLM, executes requested tools, and sends tool results back until the LLM writes a final answer.

### The tool-calling agent graph
```
START -> agent -> tools -> agent -> END
```
| Part | Job |
|---|---|
| `agent` | The LLM decides whether to call a tool or write the final digest |
| `tools` | Python executes the exact tool call requested by the LLM |
| `fetch_emails_tool` | Pull emails from the mock file or Gmail |
| `filter_internship_candidates_tool` | Keep only emails that look internship-related |
| `classify_email_tool` | Extract category, company, role, deadline, urgency, and next action |
| `rank_internships_tool` | Drop false positives and sort by urgency then deadline |

The point: **the developer provides tools; the model decides which tools to call.** LangGraph manages the loop so students can watch each agent/tool step arrive live.

The tools still return structured Python data using the Pydantic models in `app/models.py`, so the REST API and UI receive predictable JSON instead of free text.

### The REST API
| Endpoint | What it does |
|---|---|
| `GET /health` | Is the server alive? (cloud load balancers call something like this constantly) |
| `GET /emails` | Raw emails from the current source |
| `POST /agent/run` | Run the agent, wait, return everything as JSON |
| `POST /agent/stream` | Run the agent and send each step as it finishes (newline-delimited JSON) |
| `GET /internships` | Results of the last run (kept in memory) |
| `GET /agent/graph` | The agent flowchart as Mermaid text (paste into https://mermaid.live) |

Try it from a terminal while the server is running:
```bash
curl http://localhost:8000/health
curl -X POST http://localhost:8000/agent/run
curl -N -X POST http://localhost:8000/agent/stream     # watch the steps arrive live
```

### Docker in one minute
- An **image** is a frozen recipe-plus-ingredients for running the app (`Dockerfile`).
- A **container** is a running copy of an image.
- **docker compose** starts several containers together and connects them (`docker-compose.yml`).
- The API container and the UI container find each other by name: the UI calls `http://api:8000`, not `localhost`.
- The healthcheck lets compose wait until the API is truly ready before it opens the UI.

## Project layout
```
app/
  main.py            REST API endpoints
  config.py          Settings from environment variables
  models.py          Data shapes (Pydantic)
  agent/tool_graph.py True tool-calling LangGraph agent loop
  agent/tools.py     LangChain tools the LLM can call
  agent/graph.py     Previous explicit workflow agent, kept for reference
  agent/heuristic.py Keyword-rule classifier (no-key fallback)
  sources/           mock.py (sample emails) and gmail.py (real inbox)
tui/app.py           Textual terminal UI (an API client)
data/sample_emails.json
scripts/gmail_auth.py  One-time Gmail login
tests/               pytest tests (run offline)
Dockerfile, docker-compose.yml, .env.example
setup.sh, setup.ps1     Environment checks for Mac/Linux and Windows
```

## Ideas to extend it (great workshop exercises)
1. Add a node that drafts a reply email for interview invitations.
2. Add a new category (for example `scholarship`) and see it flow through the UI.
3. Replace the in-memory `_last_result` with a database (SQLite, then Postgres).
4. Deploy the API container to the cloud (AWS App Runner, Azure Container Apps, or Google Cloud Run) and point the UI's `API_URL` at it.
5. Send yourself a daily digest with a scheduled job.

## Troubleshooting
- **Setup script says Docker is not running:** open Docker Desktop and wait until it shows "running", then re-run the script.
- **UI says OFFLINE:** the API is not running. Start it with `docker compose up` first.
- **Port 8000 already in use:** change the left side of `"8000:8000"` in `docker-compose.yml`.
- **UI looks garbled on Windows:** use Windows Terminal, not the old cmd window.
- **Gmail error "token.json not found":** run `python scripts/gmail_auth.py` (step 5 above).
- **Docker mounts `secrets/` as empty on Windows:** share the project folder in Docker Desktop settings (Resources > File sharing).
