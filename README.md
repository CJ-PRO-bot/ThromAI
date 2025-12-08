# **ThromAI – Smart Waste & Drain Management System**

*A Smart AI-Powered Waste Reporting, Verification & Monitoring System for Bhutan’s Thromdes*

---

## 🚀 **Project Overview**

**ThromAI** is a youth-led smart waste management platform designed to help Bhutanese Thromdes modernize waste monitoring, reduce drain blockages, and improve sanitation through:

* AI-based verification
* Real-time hotspot mapping
* School SUPW cleanup reporting
* Mobile-first citizen reporting
* Evidence-based monitoring
* Future push notifications and follow-ups

This system is proposed for the **Thimphu Thromde 9-month pilot initiative**
(3 months development + 6 months field deployment).

---

## 🛠️ **Core Features**

### **1. AI-Based Waste Verification**

* Identifies waste categories: Organic, Plastic, Paper, Metal, Hazardous, Drain Waste, etc.
* Confirms whether waste is actually cleaned (before/after comparison)
* Flags low-quality or fraudulent submissions

### **2. Smart Reporting System**

Supports submissions from:

* Schools (SUPW)
* Citizens
* Municipal workers

Each report includes:

* Photo
* Location
* Description

### **3. Real-Time Dashboard for Thromde Admin**

* Hotspot detection
* Submission analytics
* Filter by zones/streets/schools
* Completion rate tracking
* Follow-up management

### **4. Drain Blockage Monitoring**

* Detects blocked drains
* Trash accumulation indicators
* Overflow/waterlogging risk analysis

### **5. Google Maps / GIS Integration**

* Mark frequent waste sites
* Visualize high-risk zones
* Monitor progress over weeks/months

---

## 📁 **Project Structure**

```
PhotoVerifierApp/
│── app.py                     # Flask application entry point
│── models.py                  # ORM models & DB schema
│── templates/                 # All Jinja2 templates (UI pages)
│
│── static/
│    ├── style.css             # Global stylesheet
│    └── uploads/              # User-uploaded files (gitignored)
│
│── tools/                     # Database + maintenance scripts
│    ├── create_tables.py
│    ├── migrate_sqlite_to_postgres.py
│    ├── db_upgrade.py
│    ├── inspect_db.py
│    ├── make_admin.py
│    ├── purge_submissions.py
│    └── ...many others
│
│── ai/                        # Optional AI/ML supporting code
│
│── waste_v1/                  # ONNX model + class map
│    ├── validity_classifier.onnx
│    └── class_map.json
│
│── verifier.py                # Wrapper functions for ONNX inference
│── requirements.txt           # Python dependencies
│── Procfile                   # Deployment config
│── .env                       # Environment variables (gitignored)
└── README.md
```

---

## 🔧 **Prerequisites**

* Python **3.10+**
* pip
* SQLite (default) or PostgreSQL
* Optional: GPU libraries (ONNX runs on CPU by default)

---

## 🔮 **Future Enhancements (Phase 2)**

These can be added after MVP validation:

* Android/iOS mobile app
* Facebook/social sharing
* Push notifications
* Citizen reward system
* Municipal API integration (Thromde, MoICE, MoH, NEC)
* Advanced AI detection models (YOLOv9 / SAM / custom ONNX)

---

## ⚙️ **Setting Up (Local Development)**

### **1. Clone the Repository**

```bash
git clone <repo-url>
cd PhotoVerifierApp
```

Your working directory should be:

```
c:/PhotoVerifierApp_2(0) - pilot_testing
```

---

### **2. Create & Activate Virtual Environment (Windows)**

```bash
python -m venv .venv
.venv\Scripts\activate
```

---

### **3. Install Dependencies**

```bash
pip install -r requirements.txt
```

---

### **4. Configure Environment Variables**

Create or edit **.env**:

```
FLASK_ENV=development
SECRET_KEY=change-this
DATABASE_URL=sqlite:///instance/app.db
UPLOAD_FOLDER=static/uploads
ONNX_MODEL_PATH=waste_v1/validity_classifier.onnx
CLASS_MAP_PATH=waste_v1/class_map.json
MAPBOX_TOKEN=your-mapbox-token
```

Check `app.py` and `models.py` for any additional variables.

---

### **5. Initialize Database**

**SQLite (default):**

```bash
python tools/create_tables.py
```

**Optional upgrades:**

```bash
python tools/db_upgrade.py
python tools/db_upgrade_review.py
python tools/db_upgrade_points.py
python tools/backfill_phash.py
```

---

### **6. Create an Admin User**

```bash
python tools/make_admin.py --email you@example.com
```

---

### **7. Run the Application**

**Development server:**

```bash
python app.py
```

**Or via Flask CLI:**

```bash
set FLASK_APP=app.py
flask run --host=0.0.0.0 --port=5000
```

Open the app:
👉 [http://localhost:5000](http://localhost:5000)

---

## 🧭 **Usage Guide**

### **For Users**

* Sign up / log in
* Upload photos
* Participate in verification
* View results + chat/history
* Check leaderboard ranking
* Explore verified hotspot map

### **For Admins**

Admin routes:

```
/admin_dashboard
/admin_review
/admin_users
/admin_user_detail
/admin_heatmap
```

Admins can:

* Approve / reject submissions
* Moderate review activity
* Manage users
* Inspect hotspot patterns

---

## 💾 **Data Storage**

### **SQLite (default)**

* File path: `instance/app.db`
* Ensure the `instance/` directory exists

### **PostgreSQL (optional)**

Set:

```
DATABASE_URL=postgres://user:pass@host:5432/dbname
```

Migration tools located in `tools/`.

### **Uploads**

* Stored in `static/uploads`
* This folder is gitignored

---

## 🧠 **Model Inference (AI)**

### **Model Files**

* `waste_v1/validity_classifier.onnx`
* `waste_v1/class_map.json`

### **Execution Pipeline**

`verifier.py` handles:

* Preprocessing
* Running ONNX inference
* Returning class + confidence score

Make sure `.env` paths are correct.

---

## 📄 **License**

Add a LICENSE file (MIT recommended).
