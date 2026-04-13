from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse
import io

# ... (其餘 import 與設定保持不變)

@app.post("/export")
async def export_excel(sql_query: str = Form(...)):
    try:
        conn = get_db_connection()
        df = pd.read_sql(sql_query, conn)
        conn.close()
        
        # 建立 Excel 檔案在記憶體中
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

app = FastAPI(title="Gemio ERP Smart Query")

# 設定模板目錄
templates = Jinja2Templates(directory="templates")

# 定義資料表 Schema (用於 Prompt)
# 注意: 因為 View 已經將欄位定義為中文，請告訴 Gemini 直接使用中文欄位名
TABLE_SCHEMAS = """
1. 資料表名稱: 科目餘額表
   欄位名稱: 
   - 會計科目
   - 科目名稱
   - 科目餘額

2. 資料表名稱: 採購明細表
   欄位名稱: 
   - 採購編號
   - 項次
   - 採購日期
   - 預定交期
   - 產品編號
   - 產品名稱
   - 採購量
   - 進貨量
   - 結案量
   - 未交量
"""

def get_db_connection():
    server = f"{os.getenv('DB_HOST')},{os.getenv('DB_PORT')}"
    database = os.getenv('DB_NAME')
    username = os.getenv('DB_USER')
    password = os.getenv('DB_PASSWORD')
    
    conn_str = (
        f"DRIVER={{SQL Server}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password};"
        "Connect Timeout=30;"
    )
    return pyodbc.connect(conn_str)

def init_db_views():
    """在啟動時自動建立必要的 View"""
    print("正在檢查並建立資料庫 View...")
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 建立 科目餘額表
        sql_acci = """
        IF OBJECT_ID('科目餘額表', 'V') IS NOT NULL DROP VIEW 科目餘額表;
        EXEC('CREATE VIEW 科目餘額表 AS 
              SELECT accino AS 會計科目, accinm AS 科目名稱, amt AS 科目餘額 
              FROM casper.dbo.acci')
        """
        cursor.execute(sql_acci)
        
        # 建立 採購明細表
        sql_pod = """
        IF OBJECT_ID('採購明細表', 'V') IS NOT NULL DROP VIEW 採購明細表;
        EXEC('CREATE VIEW 採購明細表 AS 
              SELECT pono AS 採購編號, poseq AS 項次, podate AS 採購日期, podatew AS 預定交期, 
                     itemno AS 產品編號, itemnm AS 產品名稱, 
                     ISNULL(poqty,0) 採購量, ISNULL(poqty_pu,0) 進貨量, ISNULL(poqty_pox,0) 結案量, 
                     ISNULL(poqty,0)-ISNULL(poqty_pu,0)-ISNULL(poqty_pox,0) 未交量 
              FROM casper.dbo.pod')
        """
        cursor.execute(sql_pod)
        
        conn.commit()
        conn.close()
        print("View 建立成功！")
    except Exception as e:
        print(f"建立 View 失敗 (這可能是因為權限不足或原始資料表不存在): {e}")

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
        # 1. 準備 Prompt (略)
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
        
        # 4. 處理數據 (自動加總)
        numeric_cols = df.select_dtypes(include=['number']).columns
        if not df.empty and len(numeric_cols) > 0:
            sums = df[numeric_cols].sum().to_frame().T
            sums.index = ["合計"]
            # 確保非數字欄位顯示為空字串而非 NaN
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
        if "Login failed" in error_msg:
            return HTMLResponse(content="<div class='alert alert-danger'>❌ 資料庫連線失敗：請檢查 .env 中的帳號密碼。</div>")
        return HTMLResponse(content=f"<div class='alert alert-danger'>❌ 系統錯誤: {error_msg}</div>")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("APP_PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
