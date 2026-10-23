import mysql.connector
from mysql.connector import pooling
import os
import sys

# Add parent directory to path so config can be imported when running db.py directly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config

db_pool = None

def get_db_connection(with_db=True):
    """
    Get a direct connection to the database.
    If with_db is True, it connects to the target database.
    If with_db is False, it connects to the MySQL server (used for database creation).
    """
    try:
        connection_config = {
            "host": Config.MYSQL_HOST,
            "user": Config.MYSQL_USER,
            "password": Config.MYSQL_PASSWORD,
            "port": Config.MYSQL_PORT,
        }
        if with_db:
            connection_config["database"] = Config.MYSQL_DB
            
        try:
            return mysql.connector.connect(**connection_config)
        except mysql.connector.Error:
            # Fallback with auth_plugin if default pure-python driver fails
            connection_config["auth_plugin"] = "mysql_native_password"
            return mysql.connector.connect(**connection_config)
    except mysql.connector.Error as err:
        print(f"Database connection error: {err}")
        raise err

def initialize_database():
    """
    Runs the schema.sql file to set up the database and its tables.
    """
    try:
        # First connect without database selection to create database if not exists
        conn = get_db_connection(with_db=False)
        cursor = conn.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {Config.MYSQL_DB}")
        cursor.close()
        conn.close()

        # Connect to newly created/existing database
        conn = get_db_connection(with_db=True)
        cursor = conn.cursor()
        
        schema_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'schema.sql')
        if not os.path.exists(schema_path):
            print(f"Warning: Schema file not found at {schema_path}")
            return
            
        with open(schema_path, 'r', encoding='utf-8') as f:
            schema_sql = f.read()
            
        # Split sql file into individual queries and run them
        statements = schema_sql.split(';')
        for statement in statements:
            if statement.strip():
                cursor.execute(statement)
                
        conn.commit()
        print("Database schema initialized successfully.")
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error during database initialization: {e}")


def _column_exists(cursor, table, column):
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s AND column_name = %s",
        (Config.MYSQL_DB, table, column)
    )
    return cursor.fetchone()[0] > 0


def run_migrations():
    """
    Idempotent, additive migrations for databases that were created before
    doctor-availability break times and appointment_time existed.
    Safe to run on every app start; never drops or renames existing data.
    """
    try:
        conn = get_db_connection(with_db=True)
        cursor = conn.cursor()

        # 1. doctor_availability.break_start / break_end (optional lunch/break window)
        if not _column_exists(cursor, 'doctor_availability', 'break_start'):
            cursor.execute("ALTER TABLE doctor_availability ADD COLUMN break_start TIME NULL AFTER end_time")
            print("Migration: added doctor_availability.break_start")
        if not _column_exists(cursor, 'doctor_availability', 'break_end'):
            cursor.execute("ALTER TABLE doctor_availability ADD COLUMN break_end TIME NULL AFTER break_start")
            print("Migration: added doctor_availability.break_end")

        # 2. appointments.appointment_time (exact booked start time)
        if not _column_exists(cursor, 'appointments', 'appointment_time'):
            cursor.execute("ALTER TABLE appointments ADD COLUMN appointment_time TIME NULL AFTER appointment_date")
            print("Migration: added appointments.appointment_time")
            # Backfill from linked appointment_slots so existing bookings keep working
            cursor.execute(
                "UPDATE appointments a JOIN appointment_slots s ON a.slot_id = s.id "
                "SET a.appointment_time = s.slot_start_time WHERE a.appointment_time IS NULL"
            )
            print("Migration: backfilled appointments.appointment_time from appointment_slots")

        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error during database migration: {e}")

# Try to initialize the database upon import
try:
    initialize_database()
    run_migrations()
except Exception as e:
    print(f"Failed to auto-initialize DB: {e}")
