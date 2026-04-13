FROM python:3.11-slim

WORKDIR /app

# 安裝編譯依賴與 Microsoft ODBC Driver 18 for SQL Server
RUN apt-get update && apt-get install -y \
    curl apt-transport-https gnupg2 unixodbc-dev gcc g++ \
    && curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - \
    && curl https://packages.microsoft.com/config/debian/11/prod.list > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y msodbcsql18 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 複製依賴檔並安裝
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製原始碼
COPY . .

# 開放 FastAPI 預設通訊埠
EXPOSE 8000

# 啟動應用程式
CMD ["python", "main.py"]
