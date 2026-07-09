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

# 或發布 npm wrapper 後使用 npm / npx
npm install -g project-memory-mcp
npx project-memory-mcp
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

## Agent / MCP 快速啟用

各 agent 工具的 MCP 設定片段請看 `project-memory-mcp/AGENT_SETUP.md`。
最短路徑是讓 client 執行已安裝的 stdio server：

```json
{
  "mcpServers": {
    "project-memory": {
      "command": "project-memory-mcp",
      "args": []
    }
  }
}
```

## LLM 描述分析預設策略

- 預設先使用本機 OpenAI-compatible LLM：`http://localhost:4000/v1`，模型：`patcher-main`。
- 如果 local endpoint 不通，MCP 不會默默要求呼叫端 agent 消耗自己的 token；會回傳 fallback，要求 agent 先詢問使用者是否允許 agent-driven analysis。
- 如果使用者未允許，系統仍會保留基本靜態知識圖：files、symbols、imports、calls、hashes、static graph edges；LLM summary/description 會維持 pending。

## 併行分析與索引優化 (Parallel Analysis & Indexing)

本專案支援對專案檔案進行**相依性分析與併行化索引**，以大幅縮短大型專案初始化與索引的等待時間。

### 1. 運作邏輯
- **相依性圖譜構建 (Dependency Graph)**：系統會先透過靜態分析（`StaticLocator`）解析所有原始碼檔案的 `imports`、`calls` 以及 `symbols` 定義，並找出檔案之間的直接與間接引用關係。
- **拓撲排序分群 (Topological Sort Grouping)**：利用 Kahn 演算法（Kahn's Algorithm）對檔案的相依性進行拓撲排序，將無相依關係（或其相依檔案已分析完成）的檔案分歸到同一個層級（Level）。
- **併行靜態解析 (Parallel Static Analysis)**：利用 `ThreadPoolExecutor` 搭配配置的 worker 執行緒，同時對獨立檔案進行 tree-sitter 語法樹分析。
- **併行 LLM 描述產生 (Parallel LLM Analysis)**：利用 `asyncio.Semaphore` 限制最大併發 LLM 請求數，依據拓撲層級（Level-by-Level）由上而下併行呼叫 LLM 進行語義分析與摘要生成，確保被依賴的父檔案優先完成分析，以利子檔案分析時能有更佳的上下文參考。

### 2. 設定參數 (config.yaml)
您可以在 `config.yaml` 中調整併行設定：
```yaml
parallel:
  max_workers: 4         # 靜態解析 ThreadPool 的最大工作執行緒數
  max_llm_concurrent: 2  # 同一時間對 LLM Endpoint 發起請求的最大併發限制
  batch_size: 10         # 靜態分析時的分批批次大小
  enable_static: true    # 是否啟用併行靜態解析
  enable_llm: true       # 是否啟用併行 LLM 摘要生成
```

## 前置需求

- Python >= 3.10
- 本機 LLM 伺服器（預設：`http://localhost:4000/v1`，模型：`patcher-main`）
- 或設定其他 LLM 提供商（Anthropic / OpenAI / Google）

## 詳細說明

更多細節請參閱 `project-memory-mcp/README.md`。
