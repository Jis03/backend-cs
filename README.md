# 🏦 OCR-BANK

OCR-BANK is a backend service for extracting and managing bank transaction data using **OCR (Optical Character Recognition)**.

The system is powered by **PaddleOCR** for text detection and recognition, and built with **FastAPI** for high-performance API services. Extracted data is stored in a **PostgreSQL** database for further processing and analysis.

---

## ✨ Features

- OCR processing powered by **PaddleOCR**
- RESTful API built with **FastAPI**
- Interactive API documentation and testing via **Swagger UI** (`/docs`)
- **PostgreSQL** database for structured data storage, including:
  - uploaded files
  - transaction records
  - user accounts
  - monthly financial goals
  - user profiles

---

## 🛠 Tech Stack

- 🐍 Python 3.10.6
- ⚡ FastAPI
- 🔍 PaddleOCR
- 🐘 PostgreSQL

---

## 🚀 Getting Started

### 🔧 Prerequisites

Make sure you have the following installed:

- Python **3.10.6**
- PostgreSQL
- pip

---

## 📦 Installation

Clone the repository:

```bash
git clone https://github.com/Jis03/backend-cs.git
cd backend-cs
```
Create a virtual environment:

```bash
python -m venv venv
```

Activate the virtual environment:

Windows
```bash
venv\Scripts\activate
```
macOS / Linux
```bash
source venv/bin/activate
```

Install dependencies:
```bash
pip install -r requirements.txt
```
⚠️ If you encounter missing dependencies, install them based on the error messages shown in the terminal.

▶️ Running the Application

Start the FastAPI server:
```bash
python -m uvicorn app.main:app --reload --port 8000
```

📖 API Documentation

Once the server is running, open:

http://localhost:8000/docs

## 🗄 Database Configuration

This project uses PostgreSQL.

Default connection settings:

- Host: localhost  
- Port: 5433  
- Database: your_database_name  
- Username: your_username  
- Password: your_password  

> ⚠️ Note: The default PostgreSQL port is 5432, but this project uses port 5433.

## 🔐 Environment Variables

Create a `.env` file and configure:

```env
DATABASE_URL=postgresql://username:password@localhost:5433/dbname
```

🗄 Database Setup

This project uses PostgreSQL.

Enable Extension
```bash
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
🧱 Database Schema
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    email TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users (username);

CREATE TABLE IF NOT EXISTS uploads (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    original_filename TEXT,
    file_path TEXT NOT NULL,
    file_hash TEXT,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_uploads_uploaded_at ON uploads (uploaded_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS ux_uploads_file_hash ON uploads (file_hash);

DO $$
BEGIN
    CREATE TYPE expense_category AS ENUM (
        'ค่าอาหาร/เครื่องดื่ม',
        'ค่าเดินทาง',
        'ค่าของใช้/จิปาถะ',
        'ค่าที่พัก/สาธารณูปโภค',
        'อื่นๆ'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END
$$;

-- transactions
CREATE TABLE IF NOT EXISTS transactions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    upload_id UUID NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
    bank TEXT,
    transferred_at TIMESTAMPTZ,
    amount NUMERIC(12,2),
    category TEXT,
    category_enum expense_category,
    category_source TEXT,
    memo TEXT,
    raw_ocr JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tx_transferred_at ON transactions (transferred_at DESC);
CREATE INDEX IF NOT EXISTS idx_tx_bank ON transactions (bank);
CREATE INDEX IF NOT EXISTS idx_tx_created_at ON transactions (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tx_raw_ocr_gin ON transactions USING GIN (raw_ocr);

-- goals
CREATE TABLE IF NOT EXISTS goals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL,
    month VARCHAR(7) NOT NULL,
    amount NUMERIC(12,2) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT fk_goals_user
        FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE CASCADE,

    CONSTRAINT uniq_user_month_goal
        UNIQUE (user_id, month)
);

CREATE INDEX IF NOT EXISTS idx_goals_user_id ON goals (user_id);

-- user_profiles
CREATE TABLE IF NOT EXISTS user_profiles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    display_name VARCHAR(150),
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    phone VARCHAR(30),
    profile_image_url TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
```

