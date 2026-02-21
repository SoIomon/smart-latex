# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Smart-LaTeX is an AI-driven system that converts Word/PDF/Markdown documents into professional LaTeX documents with PDF compilation. Built with FastAPI backend + React frontend.

## Common Commands

### Development
```bash
./scripts/dev.sh              # Start both backend (port 8000) and frontend (port 5173) with hot reload
```

### Backend only
```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
pytest                        # Run tests
```

### Frontend only
```bash
cd frontend
npm run dev                   # Vite dev server at localhost:5173
npm run build                 # Production build → frontend/dist/
npm run lint                  # ESLint
```

### Installation
```bash
./install.sh                  # Creates venv, installs deps, builds frontend, creates .env
```

### Production
```bash
./start.sh                    # Serves frontend build via backend at localhost:8000
```

## Architecture

### Generation Pipeline (3 stages)
1. **Document Analysis** — LLM analyzes uploaded documents in parallel (batch=10)
2. **Outline Planning** — LLM creates document structure from analysis results
3. **Chapter Generation** — LLM generates LaTeX per chapter in parallel (batch=8), each validated with `xelatex -draftmode` and auto-fixed via LLM on error

### Backend (`backend/app/`)
- **`api/v1/`** — FastAPI routes: projects, documents, templates, generation, chat, compiler, selection
- **`api/schemas/`** — Pydantic request/response models
- **`core/compiler/`** — LaTeX compilation via latexmk, sandboxed in temp directories
- **`core/llm/`** — OpenAI-compatible client (`DoubaoClient`), prompt chains, tool calling. Prompts are Jinja2 templates in `core/llm/prompts/`
- **`core/parsers/`** — Document parsers (DOCX, PDF, Markdown, TXT) with `ParserRegistry` dispatch
- **`core/templates/`** — Template engine with `builtin/` and `custom/` templates. Each template has `meta.json` (id, name, variables, doc_class_type, support_dirs)
- **`services/`** — Business logic (generation, document, project, chat services)
- **`models/`** — SQLAlchemy async models: Project → Documents, ChatMessages (cascade delete)

### Frontend (`frontend/src/`)
- **`pages/`** — HomePage (project list), Workspace (editor + chat + docs), TemplateGallery
- **`stores/`** — Zustand stores: projectStore, editorStore, documentStore, chatStore
- **`api/`** — Axios client functions (baseURL: `/api/v1`, proxied to backend via Vite)
- **`components/Editor/`** — CodeMirror 6 with LaTeX syntax highlighting
- **`hooks/useSSE`** — Server-Sent Events for streaming generation/compilation progress

### Streaming Pattern
Both generation (`/generate`) and compilation (`/compile-and-fix`) endpoints use SSE. Frontend consumes via `useSSE` hook. Event types: `stage`, `outline`, `chunk`, `done`, `error`.

### Database
SQLite via async SQLAlchemy (`aiosqlite`). DB file at `storage/smart_latex.db`.

## Key Technical Details

### Jinja2 Template Delimiters
Custom delimiters to avoid LaTeX `{}` conflicts:
- Variables: `<< >>` (not `{{ }}`)
- Blocks: `<% %>` (not `{% %}`)
- Comments: `<# #>` (not `{# #}`)

Use `render_string()` from `app/core/templates/engine.py` for template rendering — never use regex substitution (it strips Jinja2 default values).

### Template System
- Templates in `backend/app/core/templates/builtin/` each have a `meta.json` and a `.tex.j2` file
- `support_dirs` in meta.json declares static directories (cls/sty/bst files) copied to build dir
- `doc_class_type` ("article", "report", "book") determines section command hierarchy

### LLM Client
`DoubaoClient` wraps `AsyncOpenAI` with OpenAI-compatible API. Config in `backend/.env`. Guard streaming responses: some models return empty `choices` array — always check `if not chunk.choices: continue`.

### Document Parsing
`python-docx`'s `doc.paragraphs` skips `<w:tbl>` elements — iterate `doc.element.body` to capture tables. `DocxParagraph(child, body)` fails because CT_Body lacks `.part` — use pre-fetched paragraphs with index instead.

### LaTeX on macOS
- TeX distribution: `/Library/TeX/texbin/` (texlive 2025basic)
- Install packages: `tlmgr --usermode install <pkg>`
- CJK fonts: STSong (宋体), Heiti SC (黑体) — no SimSun/SimHei available on macOS
- Template uses `fontset=none` in ctexrep to avoid font conflicts

## Configuration

All settings in `backend/.env` (loaded by `pydantic-settings`). Key vars: `DOUBAO_API_KEY`, `DOUBAO_BASE_URL`, `DOUBAO_MODEL`, `DATABASE_URL`, `STORAGE_DIR`, `LATEX_CMD`, `CORS_ORIGINS`.

## Tech Stack
- **Backend**: FastAPI, SQLAlchemy async, Jinja2, python-docx, PyMuPDF, openai SDK, sse-starlette
- **Frontend**: React 19, TypeScript, Vite, Zustand, Ant Design, CodeMirror 6, Axios
- **Compilation**: XeLaTeX + latexmk
- **Export**: Pandoc (optional, LaTeX → Word)