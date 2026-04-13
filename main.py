from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import os
from dotenv import load_dotenv
import pyodbc
import google.generativeai as genai

# 加載環境變數
load_dotenv()

app = FastAPI(title="Gemio ERP Smart Query")

# 設定模板目錄
templates = Jinja2Templates(directory="templates")

# 資料庫連線字串 (待填寫)
def get_db_connection():
    conn_str = (
        f"DRIVER={{SQL Server}};"
        f"SERVER={os.getenv('DB_HOST')},{os.getenv('DB_PORT')};"
        f"DATABASE={os.getenv('DB_NAME')};"
        f"UID={os.getenv('DB_USER')};"
        f"PWD={os.getenv('DB_PASSWORD')};"
    )
    return pyodbc.connect(conn_str)

# Gemini API 設定
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-1.5-flash')

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/query")
async def handle_query(request: Request, user_input: str = Form(...)):
    # 這裡將實作 NL -> SQL -> DB -> View 的邏輯
    # 目前僅為預留位置
    return {"status": "success", "message": f"您輸入的是: {user_input}"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("APP_PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
