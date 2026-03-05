# Smart-LaTeX 使用说明

## 环境要求

| 依赖 | 版本要求 | 说明 |
|------|---------|------|
| Python | 3.10+ | 后端运行环境 |
| Node.js | 18+ | 前端构建 |
| npm | - | 随 Node.js 安装 |
| XeLaTeX + latexmk | - | LaTeX 编译（可选，不装则无法生成 PDF） |
| Pandoc | - | Word 导出（可选） |

**LaTeX 安装参考：**
- macOS: `brew install --cask basictex && sudo tlmgr install latexmk`
- Ubuntu: `sudo apt install texlive-xetex texlive-lang-chinese latexmk`

## 安装步骤

```bash
# 1. 解压
unzip smart-latex.zip
cd smart-latex

# 2. 一键安装（创建虚拟环境、安装依赖、构建前端、检测 LaTeX）
./install.sh

# 3. 配置 API 密钥（首次安装必须）
#    编辑 backend/.env，填入以下内容：
vi backend/.env
```

**`backend/.env` 配置项：**

```env
# LLM API 配置（必填，支持任何 OpenAI 兼容接口）
DOUBAO_API_KEY=你的API密钥
DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
DOUBAO_MODEL=你的模型端点ID

# 以下通常无需修改
DATABASE_URL=sqlite+aiosqlite:///./storage/smart_latex.db
STORAGE_DIR=./storage
LATEX_CMD=latexmk
CORS_ORIGINS=["http://localhost:5173","http://localhost:8000"]
```

## 启动服务

```bash
# 生产模式（前端静态文件由后端托管，单端口）
./start.sh
# 访问 http://localhost:8000

# 开发模式（前后端热更新，双端口）
./scripts/dev.sh
# 前端 http://localhost:5173 | 后端 http://localhost:8000
```

## 功能说明

1. **上传文档** — 支持 Word (.docx)、PDF、Markdown、TXT 格式
2. **AI 分析与生成** — 自动分析文档内容，规划大纲，逐章生成 LaTeX 代码
3. **在线编辑** — 内置 LaTeX 代码编辑器，支持语法高亮
4. **编译 PDF** — 一键编译生成 PDF，编译错误自动修复
5. **AI 对话** — 通过对话微调 LaTeX 内容
6. **模板系统** — 支持多种 LaTeX 模板，可自定义

## 目录结构

```
smart-latex/
├── install.sh          # 一键安装脚本
├── start.sh            # 生产模式启动
├── scripts/dev.sh      # 开发模式启动
├── backend/            # FastAPI 后端
│   ├── .env.example    # 环境变量模板
│   ├── requirements.txt
│   └── app/            # 应用代码
├── frontend/           # React 前端
│   ├── package.json
│   └── src/
└── docs/               # 项目文档
```