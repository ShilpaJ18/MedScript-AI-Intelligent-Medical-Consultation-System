import bcrypt
import mysql.connector
import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config
from database.db import get_db_connection

def seed_db():
    print("Seeding database with default test accounts using bcrypt...")
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # 1. Check if patient@hospital.com is already created
        cursor.execute("SELECT id FROM users WHERE email = 'patient@hospital.com'")
        if cursor.fetchone():
            print("Database already contains test accounts. Skipping seeding.")
            cursor.close()
            conn.close()
            return
            
        # 2. Add Test Patient: John Doe / patient@hospital.com / patient123
        hashed_pat = bcrypt.hashpw("patient123".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cursor.execute(
            "INSERT INTO users (name, age, gender, email, phone, password, user_type) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            ("John Doe", 34, "Male", "patient@hospital.com", "+1234567890", hashed_pat, "patient")
        )
        patient_user_id = cursor.lastrowid
        cursor.execute("INSERT INTO patients (user_id, blood_group) VALUES (%s, %s)", (patient_user_id, "O+"))
        print("✓ Created test patient account (patient@hospital.com / patient123)")

        # 3. Add Main Doctor: doctor@hospital.com / doctor123
        hashed_doc = bcrypt.hashpw("doctor123".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cursor.execute(
            "INSERT INTO users (name, age, gender, email, phone, password, user_type) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            ("Dr. Priya Verma", 45, "Female", "doctor@hospital.com", "+919800000001", hashed_doc, "doctor")
        )
        doc_user_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO doctors (user_id, specialization, license_number, experience_years, bio, rating, is_verified) "
            "VALUES (%s, %s, %s, %s, %s, %s, TRUE)",
            (doc_user_id, "Cardiology", "MD-1001", 12, "Experienced cardiologist focused on patient-centered heart care.", 4.8)
        )
        print("✓ Created primary doctor account (doctor@hospital.com / doctor123)")

        # 4. Add Additional Doctors
        additional_docs = [
            {
                'name': 'Dr. Arun Patel',
                'email': 'arun.patel@example.com',
                'phone': '+919800000002',
                'specialization': 'Orthopedics',
                'license_number': 'MD-1002',
                'experience_years': 10,
                'bio': 'Orthopedic specialist for bone and joint health.',
                'rating': 4.7
            },
            {
                'name': 'Dr. Meera Iyer',
                'email': 'meera.iyer@example.com',
                'phone': '+919800000003',
                'specialization': 'Dermatology',
                'license_number': 'MD-1003',
                'experience_years': 8,
                'bio': 'Skilled dermatologist offering advanced skin treatments.',
                'rating': 4.9
            },
            {
                'name': 'Dr. Rajesh Nair',
                'email': 'rajesh.nair@example.com',
                'phone': '+919800000004',
                'specialization': 'General Medicine',
                'license_number': 'MD-1004',
                'experience_years': 15,
                'bio': 'General physician with a strong focus on preventive care.',
                'rating': 4.6
            },
            {
                'name': 'Dr. Anjali Sharma',
                'email': 'anjali.sharma@example.com',
                'phone': '+919800000005',
                'specialization': 'Pediatrics',
                'license_number': 'MD-1005',
                'experience_years': 9,
                'bio': 'Compassionate pediatrician for child and adolescent health.',
                'rating': 4.8
            }
        ]
        
        for d in additional_docs:
            cursor.execute(
                "INSERT INTO users (name, age, gender, email, phone, password, user_type) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (d['name'], 40, "Other", d['email'], d['phone'], hashed_doc, "doctor")
            )
            du_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO doctors (user_id, specialization, license_number, experience_years, bio, rating, is_verified) "
                "VALUES (%s, %s, %s, %s, %s, %s, TRUE)",
                (du_id, d['specialization'], d['license_number'], d['experience_years'], d['bio'], d['rating'])
            )
            print(f"✓ Created doctor account for {d['name']}")

        conn.commit()
        cursor.close()
        conn.close()
        print("Seeding completed successfully!")
    except Exception as e:
        print(f"Error during seeding: {e}")

if __name__ == '__main__':
    seed_db()
