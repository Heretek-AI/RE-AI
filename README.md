# RE-AI

**Reverse Engineering AI Assistant** — a local-first desktop application that pairs an AI agent with a structured project management methodology (GSD) to help you reverse-engineer, document, and modernize legacy codebases. RE-AI combines a FastAPI backend with a React frontend, providing a real-time collaborative workspace with WebSocket-based communication, RAG-powered code search via ChromaDB, and a state-machine-driven task execution engine.

## Prerequisites

- **Python** 3.11 or later
- **Node.js** 18 or later
- **npm** (ships with Node.js)
- A modern web browser (Chrome, Edge, or Firefox)

## Quickstart

1. **Clone the repository**

   ```bash
   git clone https://github.com/your-org/re-ai.git
   cd re-ai
   ```

2. **Run the startup script**

   ```batch
   start.bat
   ```

   This will:
   - Create a Python virtual environment (`.venv/`)
   - Install Python dependencies from `backend/requirements.txt`
   - Install and build the React frontend
   - Start the FastAPI server on `http://127.0.0.1:8000`
   - Open the application in your default browser

3. **Complete the setup wizard** — On first launch, RE-AI guides you through configuring your AI provider (OpenAI or Anthropic) and any tool integrations.

4. **Use the app** — Create a project milestone, define slices of work, and let RE-AI's agent loop execute tasks autonomously. Monitor progress through the Kanban-style board and chat with the agent via the built-in WebSocket interface.

> **Windows only.** `start.bat` and `dev.bat` are designed for Windows. Linux/macOS users can follow the manual steps under **Development**.

## Architecture

RE-AI follows a two-process architecture:

```
┌─────────────────────────────────────────────┐
│                  Browser                     │
│  React SPA (Vite)  ←──→  WebSocket / HTTP   │
└──────────────────┬──────────────────────────┘
                   │  /api/*, /ws, /ws/chat
                   ▼
┌─────────────────────────────────────────────┐
│           FastAPI Backend (uvicorn)           │
│                                              │
│  ┌──────────┐  ┌──────────┐  ┌────────────┐ │
│  │  API      │  │  Agent   │  │  Engine     │ │
│  │  Routers  │  │  Loop    │  │  State Mach │ │
│  ├──────────┤  ├──────────┤  ├────────────┤ │
│  │  RAG      │  │  Registry│  │  DB Layer   │ │
│  │  (Chroma) │  │  (MCP)   │  │  (SQLite)   │ │
│  └──────────┘  └──────────┘  └────────────┘ │
└─────────────────────────────────────────────┘
```

- **Backend:** Python FastAPI application served via uvicorn. Handles REST API requests, WebSocket connections, AI provider orchestration, RAG indexing/retrieval, MCP tool registry, and the GSD state machine that drives task execution.
- **Frontend:** React single-page application built with Vite. Communicates with the backend over HTTP (`/api/*`) and WebSocket (`/ws`, `/ws/chat`). The production build is served as static files from the FastAPI backend.
- **Database:** SQLite via aiosqlite (async) for project data, milestones, slices, and tasks.
- **Vector Store:** ChromaDB for embedding-based code search and RAG retrieval.
- **WebSocket:** Bidirectional real-time communication for chat, task execution updates, and live UI state synchronization.

## Development

### Using the dev script

```batch
dev.bat
```

This starts both the backend (uvicorn on port 8000) and the Vite dev server (port 5173) with hot module replacement. Open `http://127.0.0.1:5173` in your browser.

### Manual start

```bash
# Backend
python -m venv .venv
.venv\Scripts\activate
pip install -r backend\requirements.txt
uvicorn backend.main:app --host 127.0.0.1 --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

### Running tests

```bash
# Activate virtual environment first
.venv\Scripts\activate

# Run all tests
pytest

# Run with verbose output
pytest -v

# Run a specific test file
pytest tests/test_rag.py -v
```

### Building the frontend for production

```bash
cd frontend
npm run build
```

The built assets are written to `backend/static/` and served automatically by the FastAPI backend.

## Project Structure

```
re-ai/
├── start.bat                  # One-click startup script
├── dev.bat                    # Development startup with HMR
├── .env.example               # Environment variable reference
├── pyproject.toml             # Python project metadata
│
├── backend/                   # FastAPI application
│   ├── main.py                # App entry point
│   ├── core/
│   │   ├── config.py          # pydantic-settings configuration
│   │   └── config_store.py    # Persistent config storage
│   ├── api/                   # REST and WebSocket routes
│   │   ├── health.py          # Health check endpoint
│   │   ├── chat_ws.py         # Chat WebSocket handler
│   │   ├── ws.py              # General WebSocket handler
│   │   ├── config.py          # Configuration API
│   │   ├── milestones.py      # Milestone CRUD
│   │   ├── slices.py          # Slice CRUD
│   │   ├── tasks.py           # Task CRUD
│   │   ├── rag.py             # RAG search endpoint
│   │   ├── registry.py        # MCP tool registry API
│   │   └── tools.py           # Tool execution API
│   ├── agent/                 # AI agent orchestration
│   │   ├── loop.py            # Agent execution loop
│   │   ├── provider.py        # LLM provider abstraction
│   │   └── tools.py           # Agent tool definitions
│   ├── engine/                # GSD state machine
│   │   ├── models.py          # Domain models
│   │   ├── planning.py        # Planning engine
│   │   └── state_machine.py   # Task execution state machine
│   ├── rag/                   # RAG / vector search
│   │   ├── base.py            # Abstract vector store
│   │   ├── chroma_store.py    # ChromaDB implementation
│   │   └── schemas.py         # Pydantic schemas
│   ├── registry/              # MCP tool registry
│   │   ├── registry.py        # Tool registry
│   │   ├── models.py          # Registry data models
│   │   ├── mcp_lifecycle.py   # MCP server lifecycle
│   │   └── skill_loader.py    # Skill file loader
│   ├── db/                    # Database layer
│   │   └── database.py        # SQLite async connection
│   └── static/                # Built frontend assets
│
├── frontend/                  # React SPA (Vite)
│   ├── index.html             # HTML entry point
│   ├── vite.config.ts         # Vite configuration
│   ├── src/
│   │   ├── main.tsx           # React entry point
│   │   ├── App.tsx            # Root component / router
│   │   ├── pages/             # Page components
│   │   ├── components/        # Shared UI components
│   │   ├── hooks/             # React hooks (data fetching, WebSocket)
│   │   ├── lib/               # Utility functions
│   │   └── index.css          # Global styles
│   └── public/                # Static assets
│
├── tests/                     # Python test suite (pytest)
│   ├── test_rag.py
│   ├── test_agent_loop.py
│   ├── test_planning_engine.py
│   ├── test_e2e_routers.py
│   ├── test_registry.py
│   ├── test_tools.py
│   └── fixtures/              # Test fixtures and helpers
│
└── skills/                    # Agent skill definitions
    ├── example.md
    └── shell.md
```

## Configuration

Environment variables are documented in [`.env.example`](.env.example). To configure RE-AI:

1. Copy `.env.example` to `.env`
2. Edit `.env` with your preferred values
3. Restart the server

The first-run setup wizard persists configuration values through the application's config store (`backend/core/config_store.py`), which uses a JSON file in the project root. Settings from `.env` take precedence during development; the config store is used for runtime-persistent settings such as API keys entered through the UI.

> **Security note:** Never commit `.env` to version control. It contains sensitive values like API keys. Only `.env.example` (without secrets) should be tracked.

## License

MIT — see the [LICENSE](LICENSE) file for details.
