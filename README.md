# Smart-LaTeX

AI 驱动的 LaTeX 文档生成系统 — 上传文档，智能排版，一键生成专业 PDF。

## 功能特性

- **智能文档转换**：上传 Word/PDF/Markdown，AI 自动分析内容并生成专业 LaTeX 文档
- **内置模板**：学术论文、工作报告、招标方案、通信研究报告等多种模板
- **在线编辑器**：LaTeX 语法高亮、自动补全，实时预览
- **一键编译 PDF**：集成 XeLaTeX 编译，编译错误 AI 自动修复
- **Word 导出**：通过 Pandoc 将 LaTeX 转为 Word 格式
- **自定义模板**：上传 .docx 样式文件，AI 自动提取格式生成 .tex.j2 模板

## 系统要求

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | 3.10+ | 后端运行时 |
| Node.js | 18+ | 前端构建 |
| LaTeX | XeTeX + latexmk | PDF 编译 |
| Pandoc | 可选 | Word 导出 |

### LaTeX 安装

- **macOS**: `brew install --cask basictex`（安装后运行 install.sh 自动补全宏包）
- **Windows**: [MiKTeX](https://miktex.org/)（推荐，自动安装宏包）或 [TeX Live](https://tug.org/texlive/)
- **Linux**: `sudo apt install texlive-xetex texlive-lang-chinese latexmk`

### API 密钥

需要豆包大模型 API Key（[火山引擎控制台](https://console.volcengine.com/ark)）。

## 快速安装

### macOS / Linux

```bash
git clone <repo-url> smart-latex
cd smart-latex
./install.sh
```

### Windows (PowerShell)

```powershell
git clone <repo-url> smart-latex
cd smart-latex
.\install.ps1
```

安装完成后，编辑 `backend/.env` 填入 API 密钥。

## 启动服务

### macOS / Linux

```bash
./start.sh
```

### Windows

```powershell
.\start.ps1
```

启动后访问 http://localhost:8000。

## 开发模式

前后端热更新，适合开发调试。

### macOS / Linux

```bash
./scripts/dev.sh
```

### Windows

```powershell
.\scripts\dev.ps1
```

- 前端: http://localhost:5173
- 后端: http://localhost:8000
- API 文档: http://localhost:8000/docs

## 配置说明

配置文件位于 `backend/.env`，基于 `backend/.env.example` 模板：

| 配置项 | 说明 | 示例 |
|--------|------|------|
| `DOUBAO_API_KEY` | 豆包 API 密钥 | `your-api-key` |
| `DOUBAO_BASE_URL` | API 地址 | `https://ark.cn-beijing.volces.com/api/v3` |
| `DOUBAO_MODEL` | 模型端点 ID | `ep-xxxx` |
| `DATABASE_URL` | 数据库连接 | `sqlite+aiosqlite:///./storage/smart_latex.db` |
| `STORAGE_DIR` | 文件存储目录 | `./storage` |
| `LATEX_CMD` | latexmk 路径 | `latexmk` 或 `/Library/TeX/texbin/latexmk` |
| `CORS_ORIGINS` | CORS 允许来源 | `["http://localhost:5173","http://localhost:8000"]` |

## 项目结构

```
smart-latex/
├── backend/                # FastAPI 后端
│   ├── app/
│   │   ├── api/            # API 路由
│   │   ├── core/           # 核心逻辑
│   │   │   ├── compiler/   # LaTeX 编译器
│   │   │   ├── llm/        # LLM 集成 & prompts
│   │   │   ├── parsers/    # 文档解析器
│   │   │   └── templates/  # Jinja2 LaTeX 模板
│   │   ├── models/         # 数据库模型
│   │   └── services/       # 业务逻辑
│   ├── tests/              # 后端测试
│   ├── storage/            # 运行时文件存储
│   └── requirements.txt
├── frontend/               # React 前端
│   ├── src/
│   │   ├── api/            # API 客户端
│   │   ├── components/     # React 组件
│   │   ├── pages/          # 页面
│   │   ├── stores/         # 状态管理
│   │   └── utils/          # 工具函数
│   └── package.json
├── scripts/                # 开发脚本
│   ├── dev.sh              # Mac/Linux 开发模式
│   └── dev.ps1             # Windows 开发模式
├── test_doc/               # 测试文档
├── install.sh              # Mac/Linux 安装脚本
├── install.ps1             # Windows 安装脚本
├── start.sh                # Mac/Linux 启动脚本
└── start.ps1               # Windows 启动脚本
```

## 技术栈

- **前端**: React 19 + TypeScript + Vite + Ant Design
- **后端**: FastAPI + SQLAlchemy + Jinja2
- **AI**: 豆包大模型（火山引擎 API）
- **编译**: XeLaTeX + latexmk
- **导出**: Pandoc (LaTeX → Word)
