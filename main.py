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

3. 資料表名稱: 庫存現行表
   欄位名稱: 產品編號, 產品名稱, 規格, 目前庫存量

4. 資料表名稱: 銷貨明細表
   欄位名稱: 銷貨單號, 銷貨日期, 客戶名稱, 產品編號, 產品名稱, 銷貨數量, 銷貨單價, 銷貨小計

5. 資料表名稱: 客商資料表
   欄位名稱: 對象編號, 名稱, 類型(客戶/廠商), 電話, 地址

6. 資料表名稱: 應收明細表
   欄位名稱: 收款編號, 立帳日期, 出貨編號, 帳款月份, 客戶代碼, 客戶名稱, 應收金額, 預收款日, 收款金額, 應收餘額
"""

# 定義要建立的 View SQL (使用字典方便擴充)
VIEWS_SQL = {
    "科目餘額表": """
        SELECT accino AS 會計科目, accinm AS 科目名稱, amt AS 科目餘額 
        FROM casper.dbo.acci
    """,
    "採購明細表": """
        SELECT pono AS 採購編號, poseq AS 項次, podate AS 採購日期, podatew AS 預定交期, 
               itemno AS 產品編號, itemnm AS 產品名稱, 
               ISNULL(poqty,0) 採購量, ISNULL(poqty_pu,0) 進貨量, ISNULL(poqty_pox,0) 結案量, 
               ISNULL(poqty,0)-ISNULL(poqty_pu,0)-ISNULL(poqty_pox,0) 未交量 
        FROM casper.dbo.pod
    """,
    "庫存現行表": """
        SELECT itemno AS 產品編號, itemnm AS 產品名稱, itemspec AS 規格, stkq AS 目前庫存量
        FROM casper.dbo.itm
    """,
    "銷貨明細表": """
        SELECT sono AS 銷貨單號, sodate AS 銷貨日期, cusnm AS 客戶名稱, 
               itemno AS 產品編號, itemnm AS 產品名稱, qty AS 銷貨數量, 
               price AS 銷貨單價, (qty * price) AS 銷貨小計
        FROM casper.dbo.sol
    """,
    "客商資料表": """
        SELECT cusno AS 對象編號, cusnm AS 名稱, '客戶' AS 類型, tel AS 電話, addr AS 地址 FROM casper.dbo.cus
        UNION ALL
        SELECT purno AS 對象編號, purnm AS 名稱, '廠商' AS 類型, tel AS 電話, addr AS 地址 FROM casper.dbo.pur
    """,
    "應收明細表": """
        SELECT rzno AS 收款編號, rzdate AS 立帳日期, sdno AS 出貨編號, yyyymm AS 帳款月份, 
               custno AS 客戶代碼, custnm AS 客戶名稱, 
               ISNULL(db_amt,0) + ISNULL(chjer.dbo.uf_rzh_rzexpamounta(rzno),0) AS 應收金額, 
               date1 AS 預收款日, raamounta AS 收款金額, 
               ISNULL(db_amt,0) + ISNULL(chjer.dbo.uf_rzh_rzexpamounta(rzno),0) - raamounta AS 應收餘額
        FROM casper.dbo.RZH 
        WHERE ISNULL(code_z,'N')<>'V'
    """
}

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
    """在啟動時檢查必要的 View，確保系統數據源正確"""
    print("\n--- [資料庫初始化與診斷中] ---")
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        for view_name, select_sql in VIEWS_SQL.items():
            try:
                print(f"🔍 正在檢查並建立視圖: {view_name}...")
                # 使用參考程式碼的 robust 建立方式
                check_sql = f"""
                IF OBJECT_ID('{view_name}', 'V') IS NULL 
                BEGIN 
                    EXEC('CREATE VIEW [{view_name}] AS {select_sql}');
                    PRINT '   ✅ {view_name} 建立成功';
                END
                ELSE
                BEGIN
                    PRINT '   ℹ️ {view_name} 已存在，跳過建立';
                END
                """
                cursor.execute(check_sql)
                conn.commit()
            except Exception as view_err:
                print(f"   ⚠️ {view_name} 初始化失敗: {view_err}")
                conn.rollback()
        
        conn.close()
        print("--- [診斷完備：View 初始化程序結束] ---\n")
    except Exception as e:
        print(f"❌ 資料庫連線初始化失敗: {e}")
        print("💡 請確認 .env 中的資料庫權限是否允許 CREATE VIEW，以及 casper.dbo 下原始表是否存在。")

# Gemini API 設定
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-2.5-flash')

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

@app.post("/query")
async def handle_query(request: Request, user_input: str = Form(...)):
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
        
        # 2. 呼叫 Gemini
        try:
            response = model.generate_content(prompt)
            generated_sql = clean_sql(response.text)
        except Exception as ai_err:
            if "429" in str(ai_err):
                return HTMLResponse(content="<div class='alert alert-warning'>⚠️ API 請求過於頻繁（免費版限制），請稍候 60 秒再試一次。</div>")
            raise ai_err
        
        # 3. 執行 SQL
        conn = get_db_connection()
        df = pd.read_sql(generated_sql, conn)
        conn.close()
        
        # 4. 處理數據 (自動加總 - 整合自參考程式碼)
        numeric_cols = df.select_dtypes(include=['number']).columns
        if not df.empty and len(numeric_cols) > 0:
            sums = df[numeric_cols].sum().to_frame().T
            sums.index = ["合計"]
            # 確保非數字欄位顯示為空字串而非 NaN
            for col in df.columns:
                if col not in numeric_cols:
                    sums[col] = ""
            display_df = pd.concat([df, sums])
            summary_html = display_df.to_html(classes="table table-striped table-hover", index=False, border=0, na_rep="")
        else:
            summary_html = df.to_html(classes="table table-striped table-hover", index=False, border=0, na_rep="")

        return HTMLResponse(content=f"""
            <div id="sql-code-update" hx-swap-oob="innerHTML:#sql-display"><code>{generated_sql}</code></div>
            <div class="table-responsive">
                {summary_html}
            </div>
        """)

    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg:
             return HTMLResponse(content="<div class='alert alert-warning'>⚠️ API 請求過於頻繁（免費版限制），請稍候 60 秒再試一次。</div>")
        if "Login failed" in error_msg:
            return HTMLResponse(content="<div class='alert alert-danger'>❌ 資料庫連線失敗：請檢查 .env 中的帳號密碼。</div>")
        return HTMLResponse(content=f"<div class='alert alert-danger'>❌ 系統錯誤: {error_msg}</div>")

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
