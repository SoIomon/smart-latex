# Smart-LaTeX

AI-powered LaTeX document generation system — upload documents, auto-typeset, generate professional PDFs in one click.

AI 驱动的 LaTeX 文档生成系统 — 上传文档，智能排版，一键生成专业 PDF。

## Features / 功能特性

- **Smart Document Conversion** — Upload Word/PDF/Markdown, AI analyzes content and generates professional LaTeX documents
- **Built-in Templates** — Academic papers, theses (UCAS), research reports, bid proposals, and more
- **Online Editor** — CodeMirror 6 with LaTeX syntax highlighting, real-time PDF preview
- **One-click PDF Compilation** — Integrated XeLaTeX + latexmk, with AI auto-fix for compilation errors
- **Word Export** — Direct LaTeX-to-DOCX conversion with high-fidelity formatting (Pandoc fallback available)
- **Custom Templates** — Upload a .docx reference, AI extracts styles and generates a .tex.j2 template

## How It Works / 工作原理

```
Upload Documents ──► AI Analysis (parallel) ──► Outline Planning ──► Chapter Generation (parallel)
                         batch=10                                         batch=8
                                                                            │
                                                              XeLaTeX validation per chapter
                                                              AI auto-fix on error
                                                                            ▼
                                                                     Final PDF / Word
```

## Requirements / 系统要求

| Dependency | Version | Required | Notes |
|------------|---------|----------|-------|
| Python | 3.10+ | Yes | Backend runtime |
| Node.js | 18+ | Yes | Frontend build |
| XeTeX + latexmk | Any | Yes | PDF compilation with CJK support |
| Pandoc | Any | No | Fallback for Word export |

### LLM API

Smart-LaTeX uses the **OpenAI-compatible API** protocol. You can use any provider:

| Provider | BASE_URL | Notes |
|----------|----------|-------|
| Volcengine (火山引擎/豆包) | `https://ark.cn-beijing.volces.com/api/v3` | Default |
| OpenAI | `https://api.openai.com/v1` | GPT-4o, etc. |
| DeepSeek | `https://api.deepseek.com/v1` | DeepSeek-V3, etc. |
| Local (Ollama) | `http://localhost:11434/v1` | Self-hosted models |
| Any OpenAI-compatible | `https://your-proxy/v1` | Custom proxy/gateway |

## Quick Start / 快速开始

### 1. Install / 安装

**macOS / Linux:**

```bash
git clone https://github.com/your-username/smart-latex.git
cd smart-latex
./install.sh
```

**Windows (PowerShell):**

```powershell
git clone https://github.com/your-username/smart-latex.git
cd smart-latex
.\install.ps1
```

The install script will:
- Check system dependencies (Python, Node.js, LaTeX)
- Create Python venv and install pip packages
- Install npm packages and build the frontend
- Auto-install common LaTeX packages via `tlmgr`
- Create `backend/.env` from the example template

### 2. Configure / 配置

Edit `backend/.env` with your API credentials:

```bash
# Required — your LLM API key
DOUBAO_API_KEY=sk-xxxxxxxxxxxxxxxx

# Required — model name or endpoint ID
DOUBAO_MODEL=gpt-4o

# Optional — change if not using Volcengine (default)
DOUBAO_BASE_URL=https://api.openai.com/v1
```

<details>
<summary>Full configuration reference / 完整配置说明</summary>

| Variable | Description | Default |
|----------|-------------|---------|
| `DOUBAO_API_KEY` | LLM API key | *(required)* |
| `DOUBAO_BASE_URL` | OpenAI-compatible API base URL | `https://ark.cn-beijing.volces.com/api/v3` |
| `DOUBAO_MODEL` | Model name or endpoint ID | *(required)* |
| `DATABASE_URL` | SQLite connection string | `sqlite+aiosqlite:///./storage/smart_latex.db` |
| `STORAGE_DIR` | Runtime file storage directory | `./storage` |
| `LATEX_CMD` | Path to `latexmk` | `latexmk` |
| `CORS_ORIGINS` | Allowed CORS origins (JSON array) | `["http://localhost:5173","http://localhost:8000"]` |

</details>

### 3. Start / 启动

**Production mode** (serves frontend build via backend):

```bash
./start.sh          # macOS / Linux
.\start.ps1         # Windows
```

Open http://localhost:8000 in your browser.

**Development mode** (hot reload for both frontend and backend):

```bash
./scripts/dev.sh    # macOS / Linux
.\scripts\dev.ps1   # Windows
```

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API docs: http://localhost:8000/docs

## LaTeX Installation / LaTeX 安装

<details>
<summary>macOS</summary>

```bash
brew install --cask basictex
```

After installation, run `./install.sh` — it will auto-install required LaTeX packages via `tlmgr`.

Alternatively, install the full TeX Live distribution (larger but complete):
```bash
brew install --cask mactex
```

</details>

<details>
<summary>Linux (Ubuntu/Debian)</summary>

```bash
sudo apt install texlive-xetex texlive-lang-chinese texlive-latex-extra latexmk
```

</details>

<details>
<summary>Windows</summary>

Install [MiKTeX](https://miktex.org/) (recommended, auto-installs packages) or [TeX Live](https://tug.org/texlive/).

</details>

## Project Structure / 项目结构

```
smart-latex/
├── backend/                  # FastAPI backend
│   ├── app/
│   │   ├── api/v1/           # REST API routes
│   │   ├── core/
│   │   │   ├── compiler/     # LaTeX compilation & LaTeX→DOCX converter
│   │   │   ├── llm/          # LLM client, prompt templates, tool calling
│   │   │   ├── parsers/      # Document parsers (DOCX, PDF, MD, TXT)
│   │   │   └── templates/    # Jinja2 LaTeX templates (builtin + custom)
│   │   ├── models/           # SQLAlchemy async models
│   │   └── services/         # Business logic layer
│   ├── tests/
│   └── requirements.txt
├── frontend/                 # React + TypeScript frontend
│   └── src/
│       ├── components/       # Editor (CodeMirror 6), ChatPanel, DocumentPanel
│       ├── pages/            # HomePage, Workspace, TemplateGallery, Settings
│       ├── stores/           # Zustand state management
│       └── api/              # Axios API client with SSE streaming
├── scripts/                  # Dev/build scripts
├── install.sh / install.ps1  # One-click install
└── start.sh / start.ps1      # One-click start
```

## Tech Stack / 技术栈

| Layer | Technologies |
|-------|-------------|
| Frontend | React 19, TypeScript, Vite, Ant Design, CodeMirror 6, Zustand |
| Backend | FastAPI, SQLAlchemy (async), Jinja2, python-docx, PyMuPDF |
| AI | OpenAI-compatible API (GPT, DeepSeek, Doubao, Ollama, etc.) |
| Compilation | XeLaTeX + latexmk |
| Export | Direct LaTeX→DOCX converter (python-docx), Pandoc fallback |
| Database | SQLite (via aiosqlite) |
| Streaming | SSE (Server-Sent Events) for generation & compilation progress |

## Built-in Templates / 内置模板

| Template | Description |
|----------|-------------|
| `academic_paper` | General academic paper (ctexart) |
| `ucas_thesis` | UCAS dissertation — Chinese Academy of Sciences (ucasthesis) |
| `comm_research_report` | Telecom research report with cover page & approval table |
| `bid_proposal` | Bidding proposal / technical document |
| `work_report` | General work report |

## Contributing / 贡献

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feat/my-feature`)
3. Commit your changes
4. Push to your fork and submit a Pull Request

## License / 许可证

[MIT](LICENSE)
