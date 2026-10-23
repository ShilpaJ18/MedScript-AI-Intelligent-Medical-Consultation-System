from flask import Flask, render_template, request, redirect, session, flash, jsonify, send_file, url_for
import os
import sys
import logging
import traceback
import bcrypt
from datetime import datetime, timedelta, date, time
import json
from werkzeug.utils import secure_filename
import mysql.connector

# Add current folder to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import Config
from database.db import get_db_connection
from ai.speech_to_text import SpeechToTextTranscriber
from ai.gemini_processor import GeminiProcessor
from ai.prescription_pdf import MedicalPDFGenerator

# --- Medical RAG Chatbot Blueprint ---
from app_rag import rag_bp

app = Flask(__name__)
app.secret_key = Config.SECRET_KEY
app.logger.setLevel(logging.INFO)

# Configure upload directions
AUDIO_DIR = Config.UPLOAD_AUDIO_FOLDER
PDF_DIR = Config.GENERATED_PDF_FOLDER
STT_SESSIONS = {}

# Decorators for auth controls
def login_required(f):
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please sign in to access this section.", "warning")
            return redirect('/login')
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

def role_required(roles):
    def decorator(f):
        def wrapper(*args, **kwargs):
            if 'user_id' not in session or session.get('role') not in roles:
                flash("Access denied. Insufficient clinical privileges.", "danger")
                return redirect('/')
            return f(*args, **kwargs)
        wrapper.__name__ = f.__name__
        return wrapper
    return decorator


def _safe_close_connection(conn=None, cursor=None):
    if cursor is not None:
        try:
            cursor.close()
        except Exception:
            pass
    if conn is not None:
        try:
            if conn.is_connected():
                conn.close()
        except Exception:
            pass


def _format_date_value(value):
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.strftime('%Y-%m-%d')
    return str(value)


def _time_to_minutes(val):
    """Convert database time values and time-like strings to minutes-from-midnight."""
    if val is None:
        return None
    if isinstance(val, timedelta):
        return int(val.total_seconds() / 60)
    if isinstance(val, (datetime, time)):
        return val.hour * 60 + val.minute
    if isinstance(val, str):
        cleaned = val.strip()
        if not cleaned:
            return None
        try:
            if ':' in cleaned:
                hour_str, minute_str = cleaned.split(':', 1)
                return int(hour_str) * 60 + int(minute_str.split(':', 1)[0])
            return int(cleaned)
        except ValueError:
            try:
                parsed = datetime.strptime(cleaned, '%H:%M:%S').time()
                return parsed.hour * 60 + parsed.minute
            except ValueError:
                try:
                    parsed = datetime.strptime(cleaned, '%H:%M').time()
                    return parsed.hour * 60 + parsed.minute
                except ValueError:
                    return None
    return None


def _get_stt_session(appointment_id):
    if appointment_id not in STT_SESSIONS:
        STT_SESSIONS[appointment_id] = {"transcript_text": "", "audio_chunks": []}
    return STT_SESSIONS[appointment_id]


def _save_transcript_to_db(appointment_id, transcript_text, audio_file_path=None, language='en'):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        recording_id = None
        if audio_file_path:
            file_size = os.path.getsize(audio_file_path)
            cursor.execute(
                "INSERT INTO audio_recordings (appointment_id, audio_file_path, file_size_bytes) VALUES (%s, %s, %s)",
                (appointment_id, audio_file_path, file_size)
            )
            recording_id = cursor.lastrowid
        else:
            cursor.execute(
                "SELECT id FROM audio_recordings WHERE appointment_id = %s ORDER BY uploaded_at DESC LIMIT 1",
                (appointment_id,)
            )
            recording = cursor.fetchone()
            if recording:
                recording_id = recording[0]

        if recording_id is None:
            return False

        cursor.execute(
            """
            SELECT t.id
            FROM transcripts t
            JOIN audio_recordings r ON t.recording_id = r.id
            WHERE r.appointment_id = %s
            ORDER BY r.uploaded_at DESC, t.created_at DESC
            LIMIT 1
            """,
            (appointment_id,)
        )
        latest_transcript = cursor.fetchone()

        if latest_transcript:
            cursor.execute(
                "UPDATE transcripts SET transcript_text = %s, language = %s WHERE id = %s",
                (transcript_text, language, latest_transcript[0])
            )
        else:
            cursor.execute(
                "INSERT INTO transcripts (recording_id, transcript_text, language) VALUES (%s, %s, %s)",
                (recording_id, transcript_text, language)
            )

        conn.commit()
        return True
    finally:
        _safe_close_connection(conn, cursor)

# --- Home & Authentication ---

@app.route('/')
def index():
    if 'user_id' in session:
        role = session.get('role')
        if role == 'admin':
            return redirect('/admin_dashboard')
        elif role == 'doctor':
            return redirect('/doctor_dashboard')
        elif role == 'patient':
            return redirect('/patient_dashboard')
    return redirect('/login')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()

        if not email or not password:
            flash("All fields are required.", "danger")
            return render_template('login.html')

        # Check default admin login override if DB is uninitialized
        if email == "admin@hospital.com" and password == "admin123":
            session['user_id'] = 0
            session['email'] = email
            session['name'] = "System Administrator"
            session['role'] = 'admin'
            flash("Logged in successfully as Administrator.", "success")
            return redirect('/admin_dashboard')

        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users WHERE email = %s AND is_active = TRUE", (email,))
            user = cursor.fetchone()
            
            if user and bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
                session['user_id'] = user['id']
                session['email'] = user['email']
                session['name'] = user['name']
                session['role'] = user['user_type']
                
                # Fetch patient or doctor ref ID for quick dashboard retrieval
                if user['user_type'] == 'patient':
                    cursor.execute("SELECT id FROM patients WHERE user_id = %s", (user['id'],))
                    patient = cursor.fetchone()
                    if patient:
                        session['patient_id'] = patient['id']
                elif user['user_type'] == 'doctor':
                    cursor.execute("SELECT id FROM doctors WHERE user_id = %s", (user['id'],))
                    doc = cursor.fetchone()
                    if doc:
                        session['doctor_id'] = doc['id']
                
                flash(f"Welcome back, {user['name']}!", "success")
                return redirect('/')
            else:
                flash("Invalid email credentials or password.", "danger")
        except Exception as e:
            flash(f"Login database connectivity error: {e}", "danger")
        finally:
            if 'conn' in locals() and conn.is_connected():
                cursor.close()
                conn.close()

    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        age = request.form.get('age')
        gender = request.form.get('gender')
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '').strip()
        user_type = request.form.get('user_type')

        specialization = request.form.get('specialization', '').strip()
        license_number = request.form.get('license_number', '').strip()
        experience = request.form.get('experience_years') or 0
        bio = request.form.get('bio', '').strip()

        if not name or not email or not password or not user_type:
            flash("Required parameters are missing.", "danger")
            return render_template('register.html')

        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Check duplicate email
            cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
            if cursor.fetchone():
                flash("This email is already registered. Please login.", "warning")
                return render_template('register.html')
            
            # 1. Insert User
            cursor.execute(
                "INSERT INTO users (name, age, gender, email, phone, password, user_type) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (name, age, gender, email, phone, hashed_password, user_type)
            )
            user_id = cursor.lastrowid
            
            # 2. Insert Role Table
            if user_type == 'patient':
                cursor.execute("INSERT INTO patients (user_id) VALUES (%s)", (user_id,))
            elif user_type == 'doctor':
                if not license_number or not specialization:
                    flash("Licensed practitioners must fill out credentials.", "danger")
                    conn.rollback()
                    return render_template('register.html')
                cursor.execute(
                    "INSERT INTO doctors (user_id, specialization, license_number, experience_years, bio) VALUES (%s, %s, %s, %s, %s)",
                    (user_id, specialization, license_number, experience, bio)
                )
            
            conn.commit()
            flash("Registration successful. Please login to continue.", "success")
            return redirect('/login')
        except Exception as e:
            flash(f"System registration error: {e}", "danger")
        finally:
            if 'conn' in locals() and conn.is_connected():
                cursor.close()
                conn.close()

    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("Successfully signed out.", "info")
    return redirect('/login')

# --- Patient Module ---

@app.route('/patient_dashboard')
@login_required
@role_required(['patient'])
def patient_dashboard():
    patient_id = session.get('patient_id')
    appointments = []
    active_count = 0
    prescription_count = 0
    docs_count = 0
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # 1. Read Patient Bookings
        query = """
            SELECT a.id, a.appointment_date, a.status AS appointment_status, a.reason_for_visit,
                   s.slot_start_time, s.slot_end_time,
                   du.name AS doctor_name, d.specialization
            FROM appointments a
            JOIN appointment_slots s ON a.slot_id = s.id
            JOIN doctors d ON a.doctor_id = d.id
            JOIN users du ON d.user_id = du.id
            WHERE a.patient_id = %s
            ORDER BY a.appointment_date DESC, s.slot_start_time DESC
        """
        cursor.execute(query, (patient_id,))
        appointments = cursor.fetchall()
        for appt in appointments:
            appt['slot_start_time_str'] = _fmt_ampm(appt.get('slot_start_time'))
            appt['slot_end_time_str'] = _fmt_ampm(appt.get('slot_end_time'))
        
        # 2. Get dashboard stats
        cursor.execute("SELECT COUNT(id) AS c FROM appointments WHERE patient_id = %s AND status IN ('confirmed', 'booked', 'pending')", (patient_id,))
        res = cursor.fetchone()
        active_count = res['c'] if res else 0

        cursor.execute("SELECT COUNT(id) AS c FROM prescriptions WHERE patient_id = %s", (patient_id,))
        res = cursor.fetchone()
        prescription_count = res['c'] if res else 0

        cursor.execute("SELECT COUNT(id) AS c FROM doctors WHERE is_verified = TRUE")
        res = cursor.fetchone()
        docs_count = res['c'] if res else 0
        
    except Exception as e:
        flash(f"Failed to load patient records: {e}", "danger")
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

    return render_template(
        'patient_dashboard.html', 
        appointments=appointments, 
        active_count=active_count, 
        prescription_count=prescription_count, 
        docs_count=docs_count
    )

@app.route('/book_appointment', methods=['GET', 'POST'])
@login_required
@role_required(['patient'])
def book_appointment():
    doctors = []
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT d.id, u.name, d.specialization, d.experience_years FROM doctors d JOIN users u ON d.user_id = u.id WHERE d.is_verified = TRUE"
        )
        doctors = cursor.fetchall()
    except Exception as e:
        flash(f"Failed to query doctors list: {e}", "danger")
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

    if request.method == 'POST':
        doctor_id = request.form.get('doctor_id')
        appt_date_str = request.form.get('appointment_date')
        slot_id = request.form.get('selected_slot_id')
        reason = request.form.get('reason', '').strip()
        patient_id = session.get('patient_id')

        if not doctor_id or not appt_date_str or not slot_id:
            flash("All values must be filled to confirm your slot reservation.", "danger")
            return redirect('/book_appointment')

        try:
            appt_date_obj = datetime.strptime(appt_date_str, '%Y-%m-%d').date()
        except ValueError:
            flash("Invalid appointment date supplied.", "danger")
            return redirect('/book_appointment')
        day_name = appt_date_obj.strftime('%A')

        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)

            # Guard 1 — Lock the slot row and check it is still 'available'
            cursor.execute("SELECT slot_start_time, slot_end_time, status FROM appointment_slots WHERE id = %s FOR UPDATE", (slot_id,))
            current_slot = cursor.fetchone()

            if not current_slot or current_slot['status'] != 'available':
                flash("This slot is already booked or too close to another appointment. Please choose another available slot.", "danger")
                return redirect('/book_appointment')

            slot_start_minutes = _time_to_minutes(current_slot['slot_start_time'])
            slot_end_minutes = _time_to_minutes(current_slot['slot_end_time'])

            # Guard 2 — Doctor availability check: does the doctor work this day, and does
            # the requested slot actually fall inside their configured hours (not a break)?
            cursor.execute(
                "SELECT start_time, end_time, break_start, break_end FROM doctor_availability "
                "WHERE doctor_id = %s AND day_of_week = %s",
                (doctor_id, day_name)
            )
            availability = cursor.fetchone()
            if not availability:
                flash(f"This doctor is not available on {day_name}s. Please choose another date.", "danger")
                return redirect('/book_appointment')

            avail_start = _time_to_minutes(availability['start_time'])
            avail_end = _time_to_minutes(availability['end_time'])
            break_start = _time_to_minutes(availability.get('break_start'))
            break_end = _time_to_minutes(availability.get('break_end'))

            in_break = (
                break_start is not None and break_end is not None and
                slot_start_minutes < break_end and slot_end_minutes > break_start
            )
            if slot_start_minutes < avail_start or slot_end_minutes > avail_end or in_break:
                flash("This slot is already booked or too close to another appointment. Please choose another available slot.", "danger")
                return redirect('/book_appointment')

            # Guard 3 — Extra direct check against appointments table (slot-level)
            cursor.execute(
                "SELECT id FROM appointments "
                "WHERE doctor_id = %s AND appointment_date = %s AND slot_id = %s "
                "AND status IN ('pending', 'confirmed', 'booked', 'completed')",
                (doctor_id, appt_date_str, slot_id)
            )
            if cursor.fetchone():
                flash("This slot is already booked or too close to another appointment. Please choose another available slot.", "danger")
                return redirect('/book_appointment')

            # Guard 4 — Explicit minimum 20-minute gap check against every existing active
            # appointment for this doctor on this date (defense-in-depth beyond the slot grid).
            cursor.execute(
                "SELECT appointment_time FROM appointments "
                "WHERE doctor_id = %s AND appointment_date = %s AND status IN ('pending', 'confirmed', 'completed') "
                "AND appointment_time IS NOT NULL",
                (doctor_id, appt_date_str)
            )
            existing_times = [_time_to_minutes(r['appointment_time']) for r in cursor.fetchall()]
            for other_start in existing_times:
                if other_start is None:
                    continue
                if abs(other_start - slot_start_minutes) < SLOT_DURATION_MINUTES:
                    flash("This slot is already booked or too close to another appointment. Please choose another available slot.", "danger")
                    return redirect('/book_appointment')

            # Insert Booking (appointment_time mirrors the slot's start time)
            slot_start_str = current_slot['slot_start_time']
            if isinstance(slot_start_str, timedelta):
                total = int(slot_start_str.total_seconds())
                slot_start_str = f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"
            cursor.execute(
                "INSERT INTO appointments (patient_id, doctor_id, slot_id, appointment_date, appointment_time, reason_for_visit, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, 'confirmed')",
                (patient_id, doctor_id, slot_id, appt_date_str, slot_start_str, reason)
            )

            # Mark slot as booked to prevent any further selection
            cursor.execute("UPDATE appointment_slots SET status = 'booked' WHERE id = %s", (slot_id,))

            conn.commit()
            flash(f"Your {SLOT_DURATION_MINUTES}-minute consultation slot has been booked successfully!", "success")
            return redirect('/patient_dashboard')
        except Exception as e:
            if 'conn' in locals() and conn is not None:
                conn.rollback()
            app.logger.exception("Booking failed for doctor %s on %s", doctor_id, appt_date_str)
            flash(f"Failed to record booking: {e}", "danger")
        finally:
            _safe_close_connection(conn if 'conn' in locals() else None, cursor if 'cursor' in locals() else None)

    return render_template('book_appointment.html', doctors=doctors, today_date=date.today().strftime('%Y-%m-%d'))

@app.route('/appointment/cancel/<int:appointment_id>')
@login_required
@role_required(['patient'])
def cancel_appointment(appointment_id):
    patient_id = session.get('patient_id')
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Verify appt belongs to patient
        cursor.execute("SELECT slot_id FROM appointments WHERE id = %s AND patient_id = %s", (appointment_id, patient_id))
        appt = cursor.fetchone()
        if not appt:
            flash("Requested appointment record not found.", "danger")
            return redirect('/patient_dashboard')
            
        slot_id = appt['slot_id']
        
        # Cancel booking and make slot available again
        cursor.execute("UPDATE appointments SET status = 'cancelled' WHERE id = %s", (appointment_id,))
        cursor.execute("UPDATE appointment_slots SET status = 'available' WHERE id = %s", (slot_id,))
        
        conn.commit()
        flash("Consultation booking cancelled successfully.", "success")
    except Exception as e:
        flash(f"Failed to cancel reservation: {e}", "danger")
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()
            
    return redirect('/patient_dashboard')

@app.route('/patient/feedback', methods=['POST'])
@login_required
@role_required(['patient'])
def submit_feedback():
    appt_id = request.form.get('appointment_id')
    rating = request.form.get('rating')
    comments = request.form.get('comments', '').strip()
    patient_id = session.get('patient_id')

    if not appt_id or not rating:
        # Quick parse
        pass

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Pull doctor_id
        cursor.execute("SELECT doctor_id FROM appointments WHERE id = %s AND patient_id = %s", (appt_id, patient_id))
        appt = cursor.fetchone()
        if not appt:
            flash("Invalid consultation details for review submission.", "danger")
            return redirect('/patient_dashboard')
            
        doc_id = appt['doctor_id']
        
        cursor.execute(
            "INSERT INTO feedback (appointment_id, patient_id, doctor_id, rating, comments) VALUES (%s, %s, %s, %s, %s)",
            (appt_id, patient_id, doc_id, rating, comments)
        )
        
        # Update doctor's aggregate rating
        cursor.execute("SELECT AVG(rating) AS avg_r FROM feedback WHERE doctor_id = %s", (doc_id,))
        avg_rating = cursor.fetchone()['avg_r'] or 5.0
        cursor.execute("UPDATE doctors SET rating = %s WHERE id = %s", (avg_rating, doc_id))
        
        conn.commit()
        flash("Thank you for your rating! Feedback submitted productively.", "success")
    except Exception as e:
        flash(f"Failed to submit feedback: {e}", "danger")
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

    return redirect('/patient_dashboard')

# --- AJAX APIs ---

def _fmt_ampm(val):
    """Safely format a MySQL TIME value (timedelta or time object, or None) as 'h:MM AM/PM'."""
    minutes = _time_to_minutes(val)
    if minutes is None:
        return None
    h, m = divmod(minutes, 60)
    suffix = 'AM' if h < 12 else 'PM'
    h12 = h % 12
    if h12 == 0:
        h12 = 12
    return f"{h12}:{m:02d} {suffix}"


@app.route('/api/slots')
def api_slots():
    doctor_id = request.args.get('doctor_id')
    date_str = request.args.get('date')
    if not doctor_id or not date_str:
        return jsonify({'success': False, 'slots': []})

    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        day_name = target_date.strftime('%A')

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # 1. Look up THIS doctor's configured availability for this day of week.
        cursor.execute(
            "SELECT start_time, end_time, break_start, break_end FROM doctor_availability "
            "WHERE doctor_id = %s AND day_of_week = %s",
            (doctor_id, day_name)
        )
        availability = cursor.fetchone()

        if not availability:
            # Doctor has not configured hours for this day at all — no slots to show.
            return jsonify({
                'success': True,
                'slots': [],
                'day': day_name,
                'shift_label': '',
                'unavailable_day': True
            })

        start_minutes = _time_to_minutes(availability['start_time'])
        end_minutes = _time_to_minutes(availability['end_time'])
        break_start_minutes = _time_to_minutes(availability.get('break_start'))
        break_end_minutes = _time_to_minutes(availability.get('break_end'))

        slot_duration = SLOT_DURATION_MINUTES  # 20-minute slots, doctor-configured window

        def fmt_h12(total_minutes):
            h = total_minutes // 60
            m = total_minutes % 60
            suffix = 'AM' if h < 12 else 'PM'
            h12 = h % 12
            if h12 == 0:
                h12 = 12
            return f"{h12}:{m:02d} {suffix}"

        shift_label = f"{fmt_h12(start_minutes)} – {fmt_h12(end_minutes)}"
        if break_start_minutes is not None and break_end_minutes is not None:
            shift_label += f" (Break {fmt_h12(break_start_minutes)} – {fmt_h12(break_end_minutes)})"

        # 2. Auto-generate and INSERT IGNORE for any missing slots in the valid range,
        #    skipping any slot that overlaps the doctor's break/lunch window.
        #    The UNIQUE KEY (doctor_id, appointment_date, slot_start_time) prevents duplicates.
        current = start_minutes
        while current + slot_duration <= end_minutes:
            slot_end = current + slot_duration
            is_break = (
                break_start_minutes is not None and break_end_minutes is not None and
                current < break_end_minutes and slot_end > break_start_minutes
            )
            if not is_break:
                s_h, s_m = current // 60, current % 60
                e_h, e_m = slot_end // 60, slot_end % 60
                start_val = f"{s_h:02d}:{s_m:02d}:00"
                end_val = f"{e_h:02d}:{e_m:02d}:00"
                cursor.execute(
                    "INSERT IGNORE INTO appointment_slots "
                    "(doctor_id, appointment_date, slot_start_time, slot_end_time, status) "
                    "VALUES (%s, %s, %s, %s, 'available')",
                    (doctor_id, date_str, start_val, end_val)
                )
            current += slot_duration
        conn.commit()

        # 3. Fetch only the slots within this doctor's configured working range for this date.
        start_bound = f"{start_minutes // 60:02d}:{start_minutes % 60:02d}:00"
        end_bound = f"{end_minutes // 60:02d}:{end_minutes % 60:02d}:00"

        cursor.execute(
            "SELECT id, appointment_date, slot_start_time, slot_end_time, status "
            "FROM appointment_slots "
            "WHERE doctor_id = %s AND appointment_date = %s "
            "  AND slot_start_time >= %s AND slot_start_time < %s "
            "ORDER BY slot_start_time",
            (doctor_id, date_str, start_bound, end_bound)
        )
        rows = cursor.fetchall()

        # Helper: convert timedelta or time → "HH:MM:SS" string
        def td_to_str(val):
            if isinstance(val, timedelta):
                total = int(val.total_seconds())
                h = total // 3600
                m = (total % 3600) // 60
                s = total % 60
                return f"{h:02d}:{m:02d}:{s:02d}"
            return val.strftime('%H:%M:%S')

        # Return only AVAILABLE slots (already-booked slots are hidden from patient)
        free_slots = []
        for row in rows:
            if row['status'] == 'available':
                free_slots.append({
                    'id':               row['id'],
                    'start_time':       td_to_str(row['slot_start_time']),
                    'end_time':         td_to_str(row['slot_end_time']),
                    'status':           row['status'],
                    'appointment_date': date_str,
                    'shift_label':      shift_label,
                    'day':              day_name
                })

        return jsonify({'success': True, 'slots': free_slots, 'day': day_name, 'shift_label': shift_label})
    except Exception as e:
        app.logger.exception("Failed to load doctor slots for %s on %s", doctor_id, date_str)
        return jsonify({'success': False, 'error': str(e), 'slots': []})
    finally:
        _safe_close_connection(conn if 'conn' in locals() else None, cursor if 'cursor' in locals() else None)

# --- Doctor Module ---

@app.route('/doctor_dashboard')
@login_required
@role_required(['doctor'])
def doctor_dashboard():
    doctor_id = session.get('doctor_id')
    appointments = []
    today = date.today().strftime('%Y-%m-%d')
    today_count = 0
    pending_count = 0
    completed_count = 0
    average_rating = 5.0
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # 1. Fetch appointments
        query = """
            SELECT a.id, a.appointment_date, a.status AS appointment_status, a.reason_for_visit,
                   s.slot_start_time, s.slot_end_time,
                   pu.name AS patient_name, pu.age, pu.gender
            FROM appointments a
            JOIN appointment_slots s ON a.slot_id = s.id
            JOIN patients p ON a.patient_id = p.id
            JOIN users pu ON p.user_id = pu.id
            WHERE a.doctor_id = %s
            ORDER BY a.appointment_date DESC, s.slot_start_time DESC
        """
        cursor.execute(query, (doctor_id,))
        appointments = cursor.fetchall()
        for appt in appointments:
            appt['slot_start_time_str'] = _fmt_ampm(appt.get('slot_start_time'))
            appt['slot_end_time_str'] = _fmt_ampm(appt.get('slot_end_time'))
        
        # 2. Statistics
        cursor.execute("SELECT COUNT(id) AS c FROM appointments WHERE doctor_id = %s AND appointment_date = %s", (doctor_id, today))
        today_count = cursor.fetchone()['c']
        
        cursor.execute("SELECT COUNT(id) AS c FROM appointments WHERE doctor_id = %s AND status IN ('confirmed', 'booked', 'pending')", (doctor_id,))
        pending_count = cursor.fetchone()['c']

        cursor.execute("SELECT COUNT(id) AS c FROM appointments WHERE doctor_id = %s AND status = 'completed'", (doctor_id,))
        completed_count = cursor.fetchone()['c']

        cursor.execute("SELECT rating FROM doctors WHERE id = %s", (doctor_id,))
        doc = cursor.fetchone()
        average_rating = float(doc['rating']) if doc and doc['rating'] else 5.0
        
    except Exception as e:
        flash(f"Failed to retrieve clinical files: {e}", "danger")
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

    return render_template(
        'doctor_dashboard.html', 
        appointments=appointments,
        today_count=today_count,
        pending_count=pending_count,
        completed_count=completed_count,
        average_rating=average_rating
    )

@app.route('/doctor_slots', methods=['GET', 'POST'])
@login_required
@role_required(['doctor'])
def doctor_slots():
    doctor_id = session.get('doctor_id')
    availabilities = []
    slots = []
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Fetch existing Availabilities
        cursor.execute("SELECT * FROM doctor_availability WHERE doctor_id = %s ORDER BY FIELD(day_of_week, 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')", (doctor_id,))
        availabilities = cursor.fetchall()
        for av in availabilities:
            # mysql-connector returns TIME columns as timedelta, not datetime.time,
            # so format safely in Python rather than calling strftime() in the template.
            av['start_time_str'] = _fmt_ampm(av['start_time'])
            av['end_time_str'] = _fmt_ampm(av['end_time'])
            av['break_start_str'] = _fmt_ampm(av.get('break_start'))
            av['break_end_str'] = _fmt_ampm(av.get('break_end'))
        
        # Fetch current generated slots
        cursor.execute("SELECT * FROM appointment_slots WHERE doctor_id = %s ORDER BY appointment_date DESC, slot_start_time DESC LIMIT 40", (doctor_id,))
        slots = cursor.fetchall()
        for sl in slots:
            sl['slot_start_time_str'] = _fmt_ampm(sl['slot_start_time'])
            sl['slot_end_time_str'] = _fmt_ampm(sl['slot_end_time'])
            sl['appointment_date'] = _format_date_value(sl.get('appointment_date'))
            
    except Exception as e:
        app.logger.exception("Failed to load doctor availability page")
        flash(f"Failed to query availability matrices: {e}", "danger")
    finally:
        _safe_close_connection(conn if 'conn' in locals() else None, cursor if 'cursor' in locals() else None)

    return render_template(
        'doctor_slots.html', 
        availabilities=availabilities, 
        slots=slots, 
        today_date=date.today().strftime('%Y-%m-%d')
    )

SLOT_DURATION_MINUTES = 20  # standard consultation slot length across the whole system


@app.route('/doctor_slots/add_hours', methods=['POST'])
@login_required
@role_required(['doctor'])
def add_hours():
    doctor_id = session.get('doctor_id')
    # Support selecting several days at once (checkboxes share the name "day_of_week")
    days = request.form.getlist('day_of_week')
    start_time = request.form.get('start_time')
    end_time = request.form.get('end_time')
    break_start = request.form.get('break_start', '').strip() or None
    break_end = request.form.get('break_end', '').strip() or None

    if not days or not start_time or not end_time:
        flash("Please select at least one day and provide start/end time.", "danger")
        return redirect('/doctor_slots')

    try:
        start_dt = datetime.strptime(start_time, '%H:%M')
        end_dt = datetime.strptime(end_time, '%H:%M')
    except ValueError:
        flash("Invalid time format supplied.", "danger")
        return redirect('/doctor_slots')

    if end_dt <= start_dt:
        flash("End time must be after start time.", "danger")
        return redirect('/doctor_slots')

    if (end_dt - start_dt).total_seconds() / 60 < SLOT_DURATION_MINUTES:
        flash(f"Working window must be at least {SLOT_DURATION_MINUTES} minutes long.", "danger")
        return redirect('/doctor_slots')

    # Optional break/lunch time validation — both fields must be provided together
    if bool(break_start) != bool(break_end):
        flash("Please provide both break start and break end times, or leave both empty.", "danger")
        return redirect('/doctor_slots')

    if break_start and break_end:
        try:
            break_start_dt = datetime.strptime(break_start, '%H:%M')
            break_end_dt = datetime.strptime(break_end, '%H:%M')
        except ValueError:
            flash("Invalid break time format supplied.", "danger")
            return redirect('/doctor_slots')

        if break_end_dt <= break_start_dt:
            flash("Break end time must be after break start time.", "danger")
            return redirect('/doctor_slots')

        if break_start_dt < start_dt or break_end_dt > end_dt:
            flash("Break time must fall within your working hours.", "danger")
            return redirect('/doctor_slots')

    valid_days = {'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'}
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        saved_days = []
        for day_of_week in days:
            if day_of_week not in valid_days:
                continue
            cursor.execute(
                "INSERT INTO doctor_availability (doctor_id, day_of_week, start_time, end_time, break_start, break_end) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON DUPLICATE KEY UPDATE start_time = VALUES(start_time), end_time = VALUES(end_time), "
                "break_start = VALUES(break_start), break_end = VALUES(break_end)",
                (doctor_id, day_of_week, start_time, end_time, break_start, break_end)
            )
            saved_days.append(day_of_week)
        conn.commit()
        if saved_days:
            flash(f"Configured working hours for {', '.join(saved_days)}.", "success")
        else:
            flash("No valid days were selected.", "warning")
    except Exception as e:
        app.logger.exception("Failed to store weekly hours")
        flash(f"Failed to store weekly hours: {e}", "danger")
    finally:
        _safe_close_connection(conn if 'conn' in locals() else None, cursor if 'cursor' in locals() else None)

    return redirect('/doctor_slots')

@app.route('/doctor_slots/delete_hours/<int:hours_id>')
@login_required
@role_required(['doctor'])
def delete_hours(hours_id):
    doctor_id = session.get('doctor_id')
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM doctor_availability WHERE id = %s AND doctor_id = %s", (hours_id, doctor_id))
        conn.commit()
        flash("Working hour block removed.", "success")
    except Exception as e:
        app.logger.exception("Failed to remove hours range")
        flash(f"Failed to remove hours range: {e}", "danger")
    finally:
        _safe_close_connection(conn if 'conn' in locals() else None, cursor if 'cursor' in locals() else None)
    return redirect('/doctor_slots')

@app.route('/doctor_slots/generate', methods=['POST'])
@login_required
@role_required(['doctor'])
def generate_slots():
    doctor_id = session.get('doctor_id')
    target_date_str = request.form.get('target_date')

    if not target_date_str:
        flash("Select a calendar target date to open slots.", "danger")
        return redirect('/doctor_slots')

    try:
        target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
        day_of_week = target_date.strftime('%A')
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # 1. Fetch doctor's availability range for this day of week
        cursor.execute(
            "SELECT start_time, end_time, break_start, break_end FROM doctor_availability WHERE doctor_id = %s AND day_of_week = %s",
            (doctor_id, day_of_week)
        )
        availability = cursor.fetchone()
        
        if not availability:
            flash(f"You have no working hours range configured for {day_of_week}s. Define weekly availability first.", "warning")
            return redirect('/doctor_slots')
            
        start_min = _time_to_minutes(availability['start_time'])
        end_min = _time_to_minutes(availability['end_time'])
        break_start_min = _time_to_minutes(availability.get('break_start'))
        break_end_min = _time_to_minutes(availability.get('break_end'))

        slot_duration = SLOT_DURATION_MINUTES  # 20 minutes exactly

        slots_count = 0
        current_min = start_min
        
        while current_min + slot_duration <= end_min:
            # Skip slots that overlap the doctor's break/lunch window
            slot_end_min = current_min + slot_duration
            if break_start_min is not None and break_end_min is not None and \
               current_min < break_end_min and slot_end_min > break_start_min:
                current_min += slot_duration
                continue

            # Compute start/end time representations
            s_hour = current_min // 60
            s_min = current_min % 60
            e_hour = slot_end_min // 60
            e_min = slot_end_min % 60
            
            start_time_val = f"{s_hour:02d}:{s_min:02d}:00"
            end_time_val = f"{e_hour:02d}:{e_min:02d}:00"
            
            # Try to insert slot (Unique key on doctor_id + appointment_date + slot_start_time prevents duplicates)
            try:
                cursor.execute(
                    "INSERT IGNORE INTO appointment_slots (doctor_id, appointment_date, slot_start_time, slot_end_time, status) "
                    "VALUES (%s, %s, %s, %s, 'available')",
                    (doctor_id, target_date_str, start_time_val, end_time_val)
                )
                if cursor.rowcount > 0:
                    slots_count += 1
            except mysql.connector.Error:
                pass
                
            current_min += slot_duration
            
        conn.commit()
        if slots_count > 0:
            flash(f"Auto-generated {slots_count} consultation slots (each exactly {SLOT_DURATION_MINUTES} minutes) for {target_date_str} ({day_of_week}).", "success")
        else:
            flash(f"Slots were already generated, or working hour ranges cannot fit {SLOT_DURATION_MINUTES}-minute intervals.", "info")
            
    except Exception as e:
        app.logger.exception("Failed to compile slots for doctor %s", doctor_id)
        flash(f"Failed to compile slots: {e}", "danger")
    finally:
        _safe_close_connection(conn if 'conn' in locals() else None, cursor if 'cursor' in locals() else None)
            
    return redirect('/doctor_slots')

# --- Audio to Prescription Generation pipeline ---

@app.route('/consultation/<int:appointment_id>')
@login_required
@role_required(['doctor'])
def consultation(appointment_id):
    doctor_id = session.get('doctor_id')
    appointment = None
    transcript = None
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Verify appt details
        query = """
            SELECT a.id, a.appointment_date, a.reason_for_visit,
                   pu.name AS patient_name, pu.age, pu.gender, pu.email AS patient_email
            FROM appointments a
            JOIN patients p ON a.patient_id = p.id
            JOIN users pu ON p.user_id = pu.id
            WHERE a.id = %s AND a.doctor_id = %s
        """
        cursor.execute(query, (appointment_id, doctor_id))
        appointment = cursor.fetchone()
        
        if not appointment:
            flash("Required clinical appointment file not found.", "danger")
            return redirect('/doctor_dashboard')
            
        # Get transcription if already uploaded
        cursor.execute("""
            SELECT t.transcript_text 
            FROM transcripts t
            JOIN audio_recordings r ON t.recording_id = r.id
            WHERE r.appointment_id = %s 
            ORDER BY r.uploaded_at DESC LIMIT 1
        """, (appointment_id,))
        transcript = cursor.fetchone()
        
    except Exception as e:
        flash(f"Database error during consult load: {e}", "danger")
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()
            
    return render_template('consultation.html', appointment=appointment, transcript=transcript)

@app.route('/consultation/<int:appointment_id>/upload_file', methods=['POST'])
@login_required
@role_required(['doctor'])
def upload_audio_file(appointment_id):
    doctor_id = session.get('doctor_id')

    if 'audio_file' not in request.files:
        flash("No audio attachment detected.", "warning")
        return redirect(f'/consultation/{appointment_id}')

    file = request.files['audio_file']
    if file.filename == '':
        flash("No file matching clinical audio selected.", "warning")
        return redirect(f'/consultation/{appointment_id}')

    try:
        filename = secure_filename(f"appt_{appointment_id}_{int(datetime.now().timestamp())}_{file.filename}")
        filepath = os.path.join(AUDIO_DIR, filename)
        file.save(filepath)

        stt = SpeechToTextTranscriber()
        result = stt.transcribe(filepath)
        transcript_text = result.get('text') or 'Transcript unavailable for the uploaded audio file.'
        _save_transcript_to_db(appointment_id, transcript_text, audio_file_path=filepath, language=result.get('language', 'en'))

        flash("Consultation voice file uploaded and processed via Speech-to-Text.", "success")
    except Exception as e:
        flash(f"Audio uploading/transcribing pipeline failed: {e}", "danger")

    return redirect(f'/consultation/{appointment_id}')

@app.route('/consultation/<int:appointment_id>/save_transcript', methods=['POST'])
@login_required
@role_required(['doctor'])
def save_transcript(appointment_id):
    doctor_id = session.get('doctor_id')
    payload = request.get_json(silent=True) or {}
    transcript_text = (payload.get('transcript_text') or '').strip()

    if not transcript_text:
        return jsonify({'success': False, 'error': 'Transcript text cannot be empty.'}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id FROM appointments WHERE id = %s AND doctor_id = %s",
            (appointment_id, doctor_id)
        )
        appointment = cursor.fetchone()
        if not appointment:
            return jsonify({'success': False, 'error': 'Appointment not found.'}), 404

        saved = _save_transcript_to_db(appointment_id, transcript_text)
        if not saved:
            return jsonify({'success': False, 'error': 'No recording available to save a transcript.'}), 404

        return jsonify({'success': True, 'message': 'Transcript saved successfully.'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        _safe_close_connection(conn if 'conn' in locals() else None, cursor if 'cursor' in locals() else None)

@app.route('/consultation/<int:appointment_id>/stt/start', methods=['POST'])
@login_required
@role_required(['doctor'])
def start_stt_stream(appointment_id):
    doctor_id = session.get('doctor_id')
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id FROM appointments WHERE id = %s AND doctor_id = %s", (appointment_id, doctor_id))
        if not cursor.fetchone():
            return jsonify({'success': False, 'error': 'Appointment not found.'}), 404
    finally:
        _safe_close_connection(conn, cursor)

    STT_SESSIONS[appointment_id] = {"transcript_text": "", "audio_chunks": []}
    return jsonify({'success': True, 'transcript_text': ''})

@app.route('/consultation/<int:appointment_id>/stt/chunk', methods=['POST'])
@login_required
@role_required(['doctor'])
def stream_transcript_chunk(appointment_id):
    chunk = request.get_data()
    if not chunk:
        return jsonify({'success': False, 'error': 'No audio bytes received.'}), 400

    state = _get_stt_session(appointment_id)
    state['audio_chunks'].append(chunk)

    stt = SpeechToTextTranscriber()
    result = stt.transcribe_stream_chunk(chunk, is_final=False)
    if result.get('text'):
        existing_text = (state.get('transcript_text') or '').strip()
        new_text = result['text'].strip()
        if existing_text and new_text and new_text not in existing_text:
            state['transcript_text'] = f"{existing_text}\n{new_text}".strip()
        elif not existing_text:
            state['transcript_text'] = new_text

    return jsonify({'success': True, 'transcript_text': state['transcript_text']})

@app.route('/consultation/<int:appointment_id>/stt/stop', methods=['POST'])
@login_required
@role_required(['doctor'])
def stop_stt_stream(appointment_id):
    payload = request.get_json(silent=True) or {}
    transcript_text = (payload.get('transcript_text') or '').strip()
    state = STT_SESSIONS.pop(appointment_id, None)

    if not transcript_text and state:
        transcript_text = (state.get('transcript_text') or '').strip()
    if not transcript_text:
        transcript_text = 'Consultation transcript captured live.'

    audio_path = None
    if state and state.get('audio_chunks'):
        filename = secure_filename(f"appt_{appointment_id}_live_{int(datetime.now().timestamp())}.webm")
        audio_path = os.path.join(AUDIO_DIR, filename)
        with open(audio_path, 'wb') as handle:
            for chunk in state['audio_chunks']:
                handle.write(chunk)

    _save_transcript_to_db(appointment_id, transcript_text, audio_file_path=audio_path, language='en')
    return jsonify({'success': True, 'transcript_text': transcript_text})

@app.route('/upload_audio/<int:appointment_id>', methods=['POST'])
@login_required
@role_required(['doctor'])
def upload_audio_ajax(appointment_id):
    if 'audio' not in request.files:
        return jsonify({'success': False, 'error': 'No audio file sent.'})

    file = request.files['audio']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file chosen.'})

    try:
        filename = secure_filename(f"appt_{appointment_id}_mic_{int(datetime.now().timestamp())}.webm")
        filepath = os.path.join(AUDIO_DIR, filename)
        file.save(filepath)

        stt = SpeechToTextTranscriber()
        result = stt.transcribe(filepath)
        _save_transcript_to_db(appointment_id, result['text'], audio_file_path=filepath, language=result.get('language', 'en'))
        return jsonify({'success': True, 'transcription': result['text'], 'transcript_text': result['text']})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/consultation/<int:appointment_id>/extract')
@login_required
@role_required(['doctor'])
def extract_prescription_ai(appointment_id):
    doctor_id = session.get('doctor_id')
    raw_data = None
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # 1. Fetch transcript
        cursor.execute(
            "SELECT t.transcript_text FROM transcripts t "
            "JOIN audio_recordings r ON t.recording_id = r.id "
            "WHERE r.appointment_id = %s ORDER BY r.uploaded_at DESC LIMIT 1",
            (appointment_id,)
        )
        t_row = cursor.fetchone()
        
        if not t_row:
            flash("No transcription text exists for this consultation.", "warning")
            return redirect(f'/consultation/{appointment_id}')
            
        transcript_text = t_row['transcript_text']
        
        # 2. Invoke Gemini AI processor
        processor = GeminiProcessor()
        raw_data = processor.process_consultation(transcript_text)
        
        # Re-verify and query appointment details to merge info
        query = """
            SELECT a.id, a.appointment_date,
                   pu.name AS patient_name, pu.age, pu.gender, pu.email AS patient_email
            FROM appointments a
            JOIN patients p ON a.patient_id = p.id
            JOIN users pu ON p.user_id = pu.id
            WHERE a.id = %s
        """
        cursor.execute(query, (appointment_id,))
        appt = cursor.fetchone()
        
        # Check and merge parsed JSON fields
        if not raw_data.get('patient_name') or raw_data['patient_name'] == 'Unknown':
            raw_data['patient_name'] = appt['patient_name']
        if not raw_data.get('age'):
            raw_data['age'] = appt['age']
        if not raw_data.get('gender') or raw_data['gender'] == 'Unknown':
            raw_data['gender'] = appt['gender']
            
    except Exception as e:
        flash(f"Failure running Gemini AI: {e}", "danger")
        return redirect(f'/consultation/{appointment_id}')
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

    # Pre-render doctor review worksheet
    return render_template('review_prescription.html', appointment=appt, raw_data=raw_data)

@app.route('/prescription/submit/<int:appointment_id>', methods=['POST'])
@login_required
@role_required(['doctor'])
def submit_prescription(appointment_id):
    doctor_id = session.get('doctor_id')
    
    # 1. Parse parameters from reviewed form
    symptoms = request.form.get('symptoms', '').strip()
    diagnosis = request.form.get('diagnosis', '').strip()
    recommended_tests = request.form.get('recommended_tests', '').strip()
    follow_up_date = request.form.get('follow_up_date')
    doctor_advice = request.form.get('doctor_advice', '').strip()
    treatment_plan = request.form.get('treatment_plan', '').strip()

    # If follow_up_date is empty, default to None/Null
    if not follow_up_date:
        follow_up_date = None

    # Parse dynamic list of medicines safely
    medicines = []
    med_indices = set()
    for key in request.form.keys():
        if key.startswith('medicines['):
            try:
                idx_str = key.split('[')[1].split(']')[0]
                med_indices.add(int(idx_str))
            except (IndexError, ValueError):
                pass

    for idx in sorted(med_indices):
        m_name = request.form.get(f'medicines[{idx}][name]', '').strip()
        m_dosage = request.form.get(f'medicines[{idx}][dosage]', '').strip()
        m_freq = request.form.get(f'medicines[{idx}][frequency]', '').strip()
        m_dur = request.form.get(f'medicines[{idx}][duration]', '').strip()
        if m_name:
            medicines.append({
                'name': m_name,
                'dosage': m_dosage or 'As directed',
                'frequency': m_freq or 'As directed',
                'duration': m_dur or 'As directed'
            })

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Load Patient and Doctor info for building PDF metadata
        query = """
            SELECT a.patient_id, a.appointment_date,
                   pu.name AS patient_name, pu.age, pu.gender, pu.phone AS patient_phone,
                   du.name AS doctor_name, d.specialization, d.license_number
            FROM appointments a
            JOIN patients p ON a.patient_id = p.id
            JOIN users pu ON p.user_id = pu.id
            JOIN doctors d ON a.doctor_id = d.id
            JOIN users du ON d.user_id = du.id
            WHERE a.id = %s
        """
        cursor.execute(query, (appointment_id,))
        meta_info = cursor.fetchone()
        
        # 2. Insert Prescription Record
        cursor.execute(
            "INSERT INTO prescriptions (appointment_id, patient_id, doctor_id, symptoms, diagnosis, treatment_plan, recommended_tests, doctor_advice, follow_up_date) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (appointment_id, meta_info['patient_id'], doctor_id, symptoms, diagnosis, treatment_plan, recommended_tests, doctor_advice, follow_up_date)
        )
        rx_id = cursor.lastrowid
        
        # 3. Insert Prescription Medicines records
        for med in medicines:
            cursor.execute(
                "INSERT INTO prescription_medicines (prescription_id, medicine_name, dosage, frequency, duration) "
                "VALUES (%s, %s, %s, %s, %s)",
                (rx_id, med['name'], med['dosage'], med['frequency'], med['duration'])
            )
            
        # 4. Generate PDF Reportlab
        pdf_filename = f"prescription_{rx_id}_{appointment_id}.pdf"
        pdf_path = os.path.join(PDF_DIR, pdf_filename)
        
        prescription_data = {
            'doctor_name': meta_info['doctor_name'],
            'specialization': meta_info['specialization'],
            'license_number': meta_info['license_number'],
            'patient_name': meta_info['patient_name'],
            'age': meta_info['age'],
            'gender': meta_info['gender'],
            'patient_phone': meta_info['patient_phone'],
            'appointment_date': meta_info['appointment_date'].strftime('%Y-%m-%d'),
            'symptoms': symptoms,
            'diagnosis': diagnosis,
            'medicines': medicines,
            'recommended_tests': recommended_tests,
            'doctor_advice': doctor_advice,
            'treatment_plan': treatment_plan,
            'follow_up_date': str(follow_up_date) if follow_up_date else "As needed"
        }
        
        pdf_gen = MedicalPDFGenerator()
        pdf_gen.generate(prescription_data, pdf_path)
        
        # Update PDF path in relative directory config
        cursor.execute(
            "UPDATE prescriptions SET pdf_path = %s WHERE id = %s",
            (f"generated_pdfs/{pdf_filename}", rx_id)
        )
        
        # Set appointment status to Completed
        cursor.execute("UPDATE appointments SET status = 'completed' WHERE id = %s", (appointment_id,))
        
        # Free slot status to completed
        cursor.execute("SELECT slot_id FROM appointments WHERE id = %s", (appointment_id,))
        slot_id = cursor.fetchone()['slot_id']
        cursor.execute("UPDATE appointment_slots SET status = 'completed' WHERE id = %s", (slot_id,))
        
        # Push patient notifications
        cursor.execute("SELECT user_id FROM patients WHERE id = %s", (meta_info['patient_id'],))
        p_user_id = cursor.fetchone()['user_id']
        cursor.execute(
            "INSERT INTO notifications (user_id, message) VALUES (%s, %s)",
            (p_user_id, f"Prescription for consultation on {meta_info['appointment_date']} is ready for download.")
        )
        
        conn.commit()
        flash("Prescription signed and PDF generated successfully!", "success")
        return redirect('/doctor_dashboard')
    except Exception as e:
        flash(f"Failed to commit prescription: {e}", "danger")
        return redirect(f'/consultation/{appointment_id}/extract')
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

# --- Common view & download routes ---

@app.route('/prescription/view/<int:appointment_id>')
@login_required
def view_prescription(appointment_id):
    rx = None
    doctor = None
    patient = None
    medicines = []
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Fetch Rx
        cursor.execute("SELECT * FROM prescriptions WHERE appointment_id = %s", (appointment_id,))
        rx = cursor.fetchone()
        
        if not rx:
            flash("No prescription found for the chosen consultation.", "warning")
            return redirect('/')
            
        # Secure boundaries: check user belongs to Rx
        role = session.get('role')
        if role == 'patient' and rx['patient_id'] != session.get('patient_id'):
            flash("Access denied.", "danger")
            return redirect('/')
        elif role == 'doctor' and rx['doctor_id'] != session.get('doctor_id'):
            flash("Access denied.", "danger")
            return redirect('/')

        # Fetch doctor details
        cursor.execute("SELECT d.license_number, d.specialization, u.name from doctors d join users u on d.user_id = u.id where d.id = %s", (rx['doctor_id'],))
        doctor = cursor.fetchone()

        # Fetch patient details
        cursor.execute("SELECT p.*, u.name, u.age, u.gender from patients p join users u on p.user_id = u.id where p.id = %s", (rx['patient_id'],))
        patient = cursor.fetchone()

        # Fetch meds
        cursor.execute("SELECT * FROM prescription_medicines WHERE prescription_id = %s", (rx['id'],))
        medicines = cursor.fetchall()
        
    except Exception as e:
        flash(f"Failed to load prescription info: {e}", "danger")
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()
            
    return render_template('prescription_view.html', rx=rx, doctor=doctor, patient=patient, medicines=medicines)

@app.route('/prescription/download/<int:appointment_id>')
@login_required
def download_prescription_pdf(appointment_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT pdf_path, patient_id, doctor_id FROM prescriptions WHERE appointment_id = %s", (appointment_id,))
        rx = cursor.fetchone()
        
        if not rx or not rx['pdf_path']:
            flash("The requested PDF file is not available.", "warning")
            return redirect('/')
            
        # Secure boundary checks
        role = session.get('role')
        if role == 'patient' and rx['patient_id'] != session.get('patient_id'):
            flash("Access denied.", "danger")
            return redirect('/')
        elif role == 'doctor' and rx['doctor_id'] != session.get('doctor_id'):
            flash("Access denied.", "danger")
            return redirect('/')
            
        full_filepath = os.path.join(Config.BASE_DIR, rx['pdf_path'])
        if os.path.exists(full_filepath):
            return send_file(full_filepath, as_attachment=True)
        else:
            flash("The prescription PDF file is missing on storage.", "danger")
            return redirect('/')
    except Exception as e:
        flash(f"Error downloading PDF: {e}", "danger")
        return redirect('/')
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

# --- Admin Module ---

@app.route('/admin_dashboard')
@login_required
@role_required(['admin'])
def admin_dashboard():
    stats = {}
    doctors = []
    patients = []
    appointments = []
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Statistics
        cursor.execute("SELECT COUNT(id) AS c FROM doctors")
        stats['doctors'] = cursor.fetchone()['c']

        cursor.execute("SELECT COUNT(id) AS c FROM patients")
        stats['patients'] = cursor.fetchone()['c']

        cursor.execute("SELECT COUNT(id) AS c FROM appointments")
        stats['appointments'] = cursor.fetchone()['c']

        cursor.execute("SELECT COUNT(id) AS c FROM prescriptions")
        stats['prescriptions'] = cursor.fetchone()['c']

        # Fetch Doctors with users joined
        cursor.execute(
            "SELECT d.id, d.user_id, u.name, d.specialization, d.license_number, d.is_verified "
            "FROM doctors d JOIN users u ON d.user_id = u.id ORDER BY u.name"
        )
        doctors = cursor.fetchall()

        # Fetch Patients with users joined
        cursor.execute(
            "SELECT p.id, p.user_id, u.name, u.age, u.gender, u.email, u.phone, p.blood_group "
            "FROM patients p JOIN users u ON p.user_id = u.id ORDER BY u.name"
        )
        patients = cursor.fetchall()

        # Fetch Appointments list
        query = """
            SELECT a.id, a.appointment_date, a.status AS appointment_status,
                   s.slot_start_time,
                   pu.name AS patient_name,
                   du.name AS doctor_name
            FROM appointments a
            JOIN appointment_slots s ON a.slot_id = s.id
            JOIN patients p ON a.patient_id = p.id
            JOIN users pu ON p.user_id = pu.id
            JOIN doctors d ON a.doctor_id = d.id
            JOIN users du ON d.user_id = du.id
            ORDER BY a.appointment_date DESC, s.slot_start_time DESC
        """
        cursor.execute(query)
        appointments = cursor.fetchall()
        for sl in appointments:
            sl['slot_start_time_str'] = _fmt_ampm(sl['slot_start_time'])
            
    except Exception as e:
        flash(f"Failed to fetch administrative data: {e}", "danger")
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

    return render_template(
        'admin_dashboard.html', 
        stats=stats, 
        doctors=doctors, 
        patients=patients, 
        appointments=appointments
    )

@app.route('/admin/verify_doctor/<int:doc_id>/<int:status>')
@login_required
@role_required(['admin'])
def verify_doctor(doc_id, status):
    status_bool = True if status == 1 else False
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE doctors SET is_verified = %s WHERE id = %s", (status_bool, doc_id))
        conn.commit()
        flash("Doctor verification status changed successfully.", "success")
    except Exception as e:
        flash(f"Failed to change doctor status: {e}", "danger")
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()
    return redirect('/admin_dashboard')

@app.route('/admin/delete_user/<int:user_id>')
@login_required
@role_required(['admin'])
def delete_user(user_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
        flash("User records purged successfully.", "success")
    except Exception as e:
        flash(f"Failed to remove user: {e}", "danger")
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()
    return redirect('/admin_dashboard')

@app.route('/admin/delete_appointment/<int:appt_id>')
@login_required
@role_required(['admin'])
def delete_appointment(appt_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT slot_id FROM appointments WHERE id = %s", (appt_id,))
        appt = cursor.fetchone()
        
        if appt:
            slot_id = appt['slot_id']
            cursor.execute("DELETE FROM appointments WHERE id = %s", (appt_id,))
            cursor.execute("UPDATE appointment_slots SET status = 'available' WHERE id = %s", (slot_id,))
            conn.commit()
            flash("Appointment reservation removed successfully.", "success")
        else:
            flash("Appointment record not found.", "warning")
    except Exception as e:
        flash(f"Failed to remove appointment: {e}", "danger")
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()
    return redirect('/admin_dashboard')

# Register Medical RAG Chatbot Blueprint (adds /chat, /rag-chatbot, /chat/history routes)
app.register_blueprint(rag_bp)

if __name__ == '__main__':
    # Flask main loop on port 5014
    app.run(host='0.0.0.0', port=5014, debug=False)
