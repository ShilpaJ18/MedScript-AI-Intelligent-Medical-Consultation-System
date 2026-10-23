# AI-Powered Medical Audio Prescription & Appointment Management System

✙ **CareVoice AI** is a state-of-the-art Web Application designed for clinical environments. It allows patients to schedule private 25-minute consultation slots with verified medical practitioners, captures live audio dialogue during visits, automatically transcribes the conversation using Speech-to-Text models, and utilizes Gemini Pro API to extract clinical entities for generating structured, downloadable PDF prescriptions.

---

## ✙ Features Overview
1. **Security & RBAC**:
   - Role-Based Access Control: Patients, Doctors, and Administrators have customized views.
   - Encrypted Password Hashing using `bcrypt`.
   - Flask session security boundaries preventing unauthorized data viewing.
2. **Double Booking Prevention**:
   - Doctors configure available working hours for weekly days.
   - Doctor-facing generator splits time ranges into exact 25-minute consultation slots.
   - Database level `UNIQUE` constraint preventing double booking.
   - Concurrent reserve safeguard validation inside backend controllers.
3. **Clinical Transcription**:
   - Integrates `SpeechRecognition` libraries for translating voice to text.
   - Robust offline backup clinical transcript generator simulating medical dialogues if speech libraries or audio feeds fail.
4. **AI structured Prescription Compilation**:
   - Feeds consultation text to Gemini Pro API to gather Symptoms, Diagnoses, Medications (strength, intake frequencies, durations), Lab Tests, Advice, and Follow-up times.
   - Local backup parsers if API credentials are not set.
   - Interactive review page where practitioners refine or append prescriptions before finalizing.
5. **Branded Hospital PDFs**:
   - Compiles professional medical scripts using ReportLab.
   - Features signature blocks, hospital branding, patient metadata.

---

## ✙ Tech Stack
- **Frontend**: HTML5, CSS3, Vanilla JS, Bootstrap 5, FontAwesome Icons
- **Backend Controller**: Python Flask
- **Relational Store**: MySQL (localhost:3306)
- **AI Processing**: Gemini Pro API, SpeechRecognition Library
- **PDF Generation**: ReportLab

---

## ✙ Getting Started

### 1. Prerequisites
- Python 3.8 or higher installed on Windows.
- MySQL Server running on `localhost:3306`.

### 2. Configure Environment Parameters
Create a `.env` file in the root directory:
```env
SECRET_KEY=medical_audio_prescription_super_secret_key_12345
MYSQL_HOST=localhost
MYSQL_USER=root
MYSQL_PASSWORD=root
MYSQL_DB=medical_audio_prescription_db
MYSQL_PORT=3306
GEMINI_API_KEY=your_gemini_api_key_here
```

### 3. Install Dependencies
Initialize and activate your python environment, then run:
```bash
pip install -r requirements.txt
```

### 4. Create and Seed Database
The application automatically creates the database and executes `database/schema.sql` upon import.
Once the database schema initializes, seed default test accounts by running:
```bash
python database/seed.py
```

### 5. Launch the Application
Start the Flask local development server:
```bash
python app.py
```
Open **http://localhost:5000** in your browser.

---

## ✙ Test Credentials

| Portal User Role | Email Address | Password | Credentials / Permissions |
| :--- | :--- | :--- | :--- |
| **System Administrator** | `admin@hospital.com` | `admin123` | Master control system logs, doctor verifications. |
| **Medical Specialist** | `doctor@hospital.com` | `doctor123` | Dr. Priya Verma (Cardiologist). consultation recorder, slot generation. |
| **Patient Profile** | `patient@hospital.com` | `patient123` | John Doe. booking slots, feedbacks, PDF outputs. |

*Alternative doctor accounts:*
- `arun.patel@example.com` / `doctor123` (Dr. Arun Patel - Orthopedics)
- `meera.iyer@example.com` / `doctor123` (Dr. Meera Iyer - Dermatology)
- `rajesh.nair@example.com` / `doctor123` (Dr. Rajesh Nair - General Medicine)
- `anjali.sharma@example.com` / `doctor123` (Dr. Anjali Sharma - Pediatrics)
