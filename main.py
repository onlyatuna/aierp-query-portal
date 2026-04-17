from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse
import os
from dotenv import load_dotenv
import pyodbc
import google.generativeai as genai
import pandas as pd
import re
import io

# 加載環境變數
load_dotenv()

app = FastAPI(title="Gemio ERP Smart Query")

# 設定模板目錄
templates = Jinja2Templates(directory="templates")

# 定義資料表 Schema (用於 Prompt)
TABLE_SCHEMAS = """
1. 資料表名稱: 科目餘額表
   欄位名稱: 會計科目, 科目名稱, 科目餘額

2. 資料表名稱: 採購明細表
   欄位名稱: 採購編號, 項次, 採購日期, 預定交期, 產品編號, 產品名稱, 採購量, 進貨量, 結案量, 未交量

3. 資料表名稱: 進貨明細表 (欄位必須精確)
   欄位名稱: 採購編號, 項次, 進貨日期, 廠商編號, 廠商名稱, 產品編號, 產品名稱, 數量, 單價, 金額

4. 資料表名稱: 應收明細表
   欄位名稱: 收款編號, 立帳日期, 出貨編號, 帳款月份, 客戶代碼, 客戶名稱, 應收金額, 預收款日, 收款金額, 應收餘額
"""

# 註：gemio 已經有內建的視圖 (科目餘額表, 採購明細表, 進貨明細表, 應收明細表)，無需手動建立。

def get_db_connection():
    server = f"{os.getenv('DB_HOST')},{os.getenv('DB_PORT')}"
    database = os.getenv('DB_NAME')
    username = os.getenv('DB_USER')
    password = os.getenv('DB_PASSWORD')
    
    conn_str = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password};"
        "Encrypt=yes;"
        "TrustServerCertificate=yes;"
        "Connect Timeout=30;"
    )
    return pyodbc.connect(conn_str)

def init_db_views():
    """在啟動時檢查資料庫連線狀況"""
    print("\n--- [資料庫連線診斷中] ---")
    try:
        conn = get_db_connection()
        print("✅ 資料庫連線成功")
        
        # 簡單測試讀取一個預期存在的 View
        cursor = conn.cursor()
        cursor.execute("SELECT TOP 1 * FROM 科目餘額表")
        print("✅ 內建視圖存取測試成功 (科目餘額表)")
        
        conn.close()
        print("--- [診斷完備] ---\n")
    except Exception as e:
        print(f"❌ 資料庫連線初始化失敗: {e}")
        print("💡 請確認 .env 中的資料庫屬性是否正確，以及 gemio 內建視圖是否存在。")

# Gemini API 設定 (改為由使用者在前端手動填入 API Key)

@app.on_event("startup")
async def startup_event():
    init_db_views()

def clean_sql(sql_text):
    # 移除 Markdown 語法 (如 ```sql ... ```)
    sql_text = re.sub(r'```sql', '', sql_text)
    sql_text = re.sub(r'```', '', sql_text)
    return sql_text.strip()

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request=request, name="index.html", context={}
    )

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/query")
async def handle_query(request: Request, user_input: str = Form(...), api_key: str = Form(...)):
    try:
        # 1. 準備 Prompt
        prompt = f"""
        你是一個 SQL 專家。請根據以下資料表結構，將使用者的自然語言問題轉換為 T-SQL 查詢語句。
        資料庫類型: Microsoft SQL Server
        
        {TABLE_SCHEMAS}
        
        使用者問題: "{user_input}"
        
        注意事項:
        - 僅回傳 SQL 語句，不要有任何解釋文字。
        - 欄位名稱請儘量使用中文別名。
        - SQL 語法必須符合 T-SQL 規範。
        
        SQL:
        """
        
        # 2. 呼叫 Gemini (使用前端傳入的 API Key 動態建立模型)
        try:
            genai.configure(api_key=api_key)
            user_model = genai.GenerativeModel('gemini-2.5-flash')
            response = user_model.generate_content(prompt)
            generated_sql = clean_sql(response.text)
        except Exception as ai_err:
            if "429" in str(ai_err):
                return HTMLResponse(content="<div class='alert alert-warning'>⚠️ API 請求過於頻繁（免費版限制），請稍候 60 秒再試一次。</div>")
            raise ai_err
        
        # 3. 執行 SQL
        conn = get_db_connection()
        df = pd.read_sql(generated_sql, conn)
        conn.close()
        
        # 4. 處理數據與生成 HTML
        if df.empty:
            summary_html = """
            <div class="flex flex-col items-center justify-center py-16 text-on-surface-variant">
                <span class="material-symbols-outlined text-5xl mb-4 opacity-30 text-primary">search_off</span>
                <p class="font-medium">查無符合條件的資料</p>
                <p class="text-xs opacity-50 mt-1">請試著換個問法，或確認資料庫是否有相關記錄。</p>
            </div>
            """
        else:
            # 自動加總邏輯
            numeric_cols = df.select_dtypes(include=['number']).columns
            if len(numeric_cols) > 0:
                sums = df[numeric_cols].sum().to_frame().T
                sums.index = ["合計"]
                for col in df.columns:
                    if col not in numeric_cols:
                        sums[col] = ""
                display_df = pd.concat([df, sums])
                summary_html = display_df.to_html(classes="table table-striped table-hover", index=False, border=0, na_rep="")
            else:
                summary_html = df.to_html(classes="table table-striped table-hover", index=False, border=0, na_rep="")

        return HTMLResponse(content=f"""
            <div id="sql-code-update" hx-swap-oob="innerHTML:#sql-display"><code>{generated_sql}</code></div>
            <div class="w-full h-full">
                {summary_html}
            </div>
        """)

    except Exception as e:
        error_msg = str(e)
        alert_cls = "bg-red-50 text-red-700 border-red-200"
        icon = "error"
        
        # 嘗試從 locals 取得已生成的 SQL，若還沒生成則顯示空白
        failed_sql = locals().get('generated_sql', '-- 尚未生成 SQL --')

        if "429" in error_msg:
            icon = "timer"
            msg = "API 請求過於頻繁（免費版限制），請稍候 60 秒再試一次。"
            alert_cls = "bg-amber-50 text-amber-700 border-amber-200"
        elif "Login failed" in error_msg:
            msg = "資料庫連線失敗：請檢查伺服器端的資料庫設定。"
        else:
            msg = f"系統錯誤: {error_msg}"

        return HTMLResponse(content=f"""
            <div id="sql-code-update" hx-swap-oob="innerHTML:#sql-display"><code>{failed_sql}</code></div>
            <div class="p-6 rounded-xl border {alert_cls} flex items-start gap-4">
                <span class="material-symbols-outlined">{icon}</span>
                <div>
                    <p class="font-bold">查詢失敗</p>
                    <p class="text-sm mt-1">{msg}</p>
                </div>
            </div>
        """)

@app.post("/export")
async def export_excel(sql_query: str = Form(...)):
    try:
        conn = get_db_connection()
        df = pd.read_sql(sql_query, conn)
        conn.close()
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='查詢結果')
        
        output.seek(0)
        
        headers = {
            'Content-Disposition': 'attachment; filename="query_result.xlsx"'
        }
        return StreamingResponse(output, headers=headers, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except Exception as e:
        return HTMLResponse(content=f"<script>alert('匯出失敗: {str(e)}');</script>")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("APP_PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
