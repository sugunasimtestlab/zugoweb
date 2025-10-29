import os
import mysql.connector
from datetime import datetime
from config import DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT
import json


def _build_connection_config(include_database: bool = True) -> dict:
    """Build connection config from config.py values with safe defaults."""
    host = DB_HOST or os.getenv("DB_HOST", "localhost") or "localhost"
    port_raw = DB_PORT or os.getenv("DB_PORT", "3306") or "3306"
    try:
        port = int(port_raw)
    except Exception:
        port = 3306
    user = DB_USER or os.getenv("DB_USER", "root") or "root"
    password = DB_PASSWORD or os.getenv("DB_PASSWORD", "") or ""
    cfg = {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
    }
    if include_database:
        database = DB_NAME or os.getenv("DB_NAME", "zugo_attendance") or "zugo_attendance"
        cfg["database"] = database
    return cfg


def get_connection():
    """Create and return a MySQL connection using environment variables/config."""
    return mysql.connector.connect(**_build_connection_config(include_database=True))


def _ensure_database_exists() -> None:
    """Create the database if it doesn't exist yet."""
    db_name = DB_NAME or os.getenv("DB_NAME", "zugo_attendance") or "zugo_attendance"
    conn = mysql.connector.connect(**_build_connection_config(include_database=False))
    try:
        cursor = conn.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def initialize_schema() -> None:
    """Ensure the database schema required for attendance exists."""
    _ensure_database_exists()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS attendance (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                user_email VARCHAR(255) NOT NULL,
                action ENUM('check-in','check-out') NOT NULL,
                event_time DATETIME NOT NULL,
                latitude DECIMAL(10,7) NULL,
                longitude DECIMAL(10,7) NULL,
                location_text VARCHAR(255) NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_user_month (user_email, event_time)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INT AUTO_INCREMENT PRIMARY KEY,
                assigned_to VARCHAR(255) NOT NULL,
                assigned_by VARCHAR(255) NOT NULL,
                title VARCHAR(255) NOT NULL,
                description TEXT DEFAULT NULL,
                due_date DATE DEFAULT NULL,
                status ENUM('pending', 'completed') DEFAULT 'pending',
                work_file VARCHAR(255) DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def insert_attendance(
    user_email: str,
    action: str,
    event_time: datetime,
    latitude: float | None,
    longitude: float | None,
    location_text: str | None,
    
    
) -> None:
    """Insert a check-in/out row into the attendance table."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO attendance (user_email, action, event_time, latitude, longitude, location_text)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (user_email, action, event_time, latitude, longitude, location_text),
        )
        conn.commit()
        
        
    finally:
        cursor.close()
        conn.close()


def fetch_monthly_attendance_for_user(user_email: str, year: int, month: int):
    """Return list of dict rows for a user's attendance in a given month."""
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, user_email, action, event_time, latitude, longitude, location_text
            FROM attendance
            WHERE user_email = %s
              AND YEAR(event_time) = %s
              AND MONTH(event_time) = %s
            ORDER BY event_time ASC
            """,
            (user_email, year, month),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def fetch_monthly_attendance_all(year: int, month: int):
    """Return list of dict rows for all users' attendance for a month."""
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, user_email, action, event_time, latitude, longitude, location_text
            FROM attendance
            WHERE YEAR(event_time) = %s
              AND MONTH(event_time) = %s
            ORDER BY user_email ASC, event_time ASC
            """,
            (year, month),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()



def insert_employee(name: str, email: str, password: str):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO employee_details (name, email, password) VALUES (%s, %s, %s)",
            (name, email, password)
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def fetch_employee_by_email(email: str):
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM employee_details WHERE email = %s",
            (email,)
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

def insert_hr_dashboard_snapshot(data: dict):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO hr_dashboard_snapshots (snapshot_time, data) VALUES (NOW(), %s)",
            (json.dumps(data),)
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def update_employee_leave(email: str, total_leave: int):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE employee_details SET total_leave = %s WHERE email = %s",
            (total_leave, email)
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def update_employee_working_days(email: str, total_working: int):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE employee_details SET total_working = %s WHERE email = %s",
            (total_working, email)
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def fetch_all_employees():
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM employee_details")
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

def fetch_attendance_for_period(user_email, start_date, end_date):
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM attendance WHERE user_email = %s AND event_time BETWEEN %s AND %s ORDER BY event_time ASC",
            (user_email, start_date, end_date)
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()
