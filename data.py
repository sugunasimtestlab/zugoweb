
from datetime import date
import mysql.connector
from typing import Optional, List, Dict
# --- Local Imports ---
import config
from employees import users as static_users 
from fastapi import HTTPException



# ===========================================================================
# DATABASE SETUP & DEPENDENCY
# ===========================================================================

def get_db_connection():
    """Dependency to get a database connection."""
    try:
        conn = mysql.connector.connect(
            host=config.DB_HOST,
            port=config.DB_PORT,
            user=config.DB_USER,
            password=config.DB_PASSWORD,
            database=config.DB_NAME
        )
        yield conn
    except mysql.connector.Error as err:
        raise HTTPException(status_code=500, detail=f"Database connection failed: {err}")
    finally:
        if 'conn' in locals() and conn.is_connected():
            conn.close()




# ===========================================================================
# DATABASE UTILITY FUNCTIONS
# ===========================================================================

def fetch_employee_by_email(db: mysql.connector.MySQLConnection, email: str) -> Optional[Dict]:
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM employee_details WHERE email = %s", (email,))
    employee = cursor.fetchone()
    cursor.close()
    
    # If employee exists but has missing fields, fill them from static_users
    if employee:
        static_user = static_users.get(email)
        if static_user:
            # Fill in any missing/null fields from static data
            if not employee.get("phone"):
                employee["phone"] = static_user.get("phone")
            if not employee.get("parent_phone"):
                employee["parent_phone"] = static_user.get("parent_phone")
            if not employee.get("dob"):
                employee["dob"] = static_user.get("dob")
            if not employee.get("gender"):
                employee["gender"] = static_user.get("gender")
            if not employee.get("employee_number"):
                employee["employee_number"] = static_user.get("employee_number")
            if not employee.get("aadhar"):
                employee["aadhar"] = static_user.get("aadhar")
            if not employee.get("joining_date"):
                employee["joining_date"] = static_user.get("joining_date")
            if not employee.get("native"):
                employee["native"] = static_user.get("native")
            if not employee.get("address"):
                employee["address"] = static_user.get("address")
            if not employee.get("photo") or employee.get("photo") == "profile.jpg":
                employee["photo"] = static_user.get("photo", "profile.jpg")
            if not employee.get("job_role"):
                employee["job_role"] = static_user.get("job_role", "Employee")
    
    return employee


def fetch_attendance_for_today(db: mysql.connector.MySQLConnection, user_email: str) -> List[Dict]:
    cursor = db.cursor(dictionary=True)
    today = date.today()
    cursor.execute(
        "SELECT * FROM attendance WHERE user_email = %s AND DATE(event_time) = %s",
        (user_email, today)
    )
    records = cursor.fetchall()
    cursor.close()
    return records
    

def fetch_all_employees(db: mysql.connector.MySQLConnection) -> List[Dict]:
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM employee_details WHERE email != %s", (config.HR_EMAIL,))
    employees = cursor.fetchall()
    cursor.close()

    # If DB has no rows yet, fall back to the static `employees` data (employees.py)
    if not employees:
        try:
            # `static_users` is imported from `employees` as `static_users` at the top
            employees = [
                {
                    "name": u.get("name"),
                    "email": k,
                    "photo": u.get("photo", "profile.jpg"),
                    "phone": u.get("phone"),
                    "employee_number": u.get("employee_number"),
                    "job_role": u.get("job_role", "Employee")
                }
                for k, u in static_users.items()
                if k and k != config.HR_EMAIL
            ]
        except Exception:
            employees = []
    else:
        # If employees exist in DB, merge with static data to fill null fields
        for emp in employees:
            email = emp.get("email")
            if email and email in static_users:
                static_user = static_users[email]
                # Fill in any missing/null fields from static data
                if not emp.get("phone"):
                    emp["phone"] = static_user.get("phone")
                if not emp.get("parent_phone"):
                    emp["parent_phone"] = static_user.get("parent_phone")
                if not emp.get("dob"):
                    emp["dob"] = static_user.get("dob")
                if not emp.get("gender"):
                    emp["gender"] = static_user.get("gender")
                if not emp.get("employee_number"):
                    emp["employee_number"] = static_user.get("employee_number")
                if not emp.get("aadhar"):
                    emp["aadhar"] = static_user.get("aadhar")
                if not emp.get("joining_date"):
                    emp["joining_date"] = static_user.get("joining_date")
                if not emp.get("native"):
                    emp["native"] = static_user.get("native")
                if not emp.get("address"):
                    emp["address"] = static_user.get("address")
                if not emp.get("photo") or emp.get("photo") == "profile.jpg":
                    emp["photo"] = static_user.get("photo", "profile.jpg")
                if not emp.get("job_role"):
                    emp["job_role"] = static_user.get("job_role", "Employee")

    return employees


def fetch_notifications_for_user(db: mysql.connector.MySQLConnection, user_email: str) -> List[Dict]:
    """Fetch unread notifications for a user."""
    cursor = db.cursor(dictionary=True)
    cursor.execute(
        """SELECT id, recipient_email, message, task_id, type, is_read, created_at 
           FROM notifications 
           WHERE recipient_email = %s AND is_read = FALSE 
           ORDER BY created_at DESC LIMIT 10""",
        (user_email,)
    )
    notifications = cursor.fetchall()
    cursor.close()
    return notifications


def mark_notification_as_read(db: mysql.connector.MySQLConnection, notification_id: int):
    """Mark a notification as read."""
    cursor = db.cursor()
    cursor.execute(
        "UPDATE notifications SET is_read = TRUE WHERE id = %s",
        (notification_id,)
    )
    db.commit()
    cursor.close()