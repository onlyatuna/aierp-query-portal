# AIERP Query Portal (Gemio ERP 智慧查詢系統)

這是一個基於 **FastAPI** 與 **Gemini API** 的自然語言轉 SQL 查詢入口網站，專為 Gemio ERP 系統設計。

## 🚀 技術棧
- **Backend:** FastAPI (Python)
- **AI Model:** Google Gemini API
- **Database:** Microsoft SQL Server
- **Frontend:** HTML + HTMX + Bootstrap (輕量互動)

## 🛠️ 本地開發設定

1. **安裝依賴套件:**
   ```bash
   pip install -r requirements.txt
   ```

2. **設定環境變數:**
   複製 `.env.example` 並更名為 `.env`，填入您的資料庫資訊與 Gemini API Key。
   ```bash
   cp .env.example .env
   ```

3. **啟動服務:**
   ```bash
   python main.py
   ```

## 🌐 部署
本專案設計為可獨立部署於 GCP 或其他雲端平台。
預設 Port 為 `8000` (可於 .env 修改)。
