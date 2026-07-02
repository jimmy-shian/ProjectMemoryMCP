# PMCPS - Project Memory MCP Server

本專案為 **Project Memory MCP** 的開發與研究版本，提供一個 LLM 驅動的知識圖譜 MCP 伺服器，可用於程式碼理解、方程式追蹤、影響分析及代理輔助編輯。

## 目錄結構

```
PMCPS/
├── project-memory-mcp/   # 核心套件
│   ├── src/              # 原始碼
│   ├── tests/            # 測試
│   ├── pyproject.toml    # 套件設定
│   └── README.md         # 套件說明
├── references/           # 參考實作與資源
└── RESEARCH_REPORT.md    # 研究報告
```

## 安裝方式

```bash
# 進入核心套件目錄
cd project-memory-mcp

# 使用 uv 安裝（推薦）
uv sync

# 或使用 pip
pip install -e .
```

## 在其他專案使用

安裝一次後，`project-memory` CLI 指令即可在全域使用：

```bash
# 進入你想分析的專案
cd 你的專案路徑

# 初始化
project-memory init .

# 建立索引
project-memory index .

# 查詢
project-memory query file src/main.py
project-memory query symbol MyClass

# 啟動 MCP 伺服器
project-memory serve
```

## 前置需求

- Python >= 3.10
- 本機 LLM 伺服器（預設：`http://localhost:4000/v1`，模型：`patcher-main`）
- 或設定其他 LLM 提供商（Anthropic / OpenAI / Google）

## 詳細說明

更多細節請參閱 `project-memory-mcp/README.md`。