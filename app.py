import uvicorn
import csv
import io
import mysql.connector
import os
from contextlib import asynccontextmanager
from datetime import datetime, date, time, timedelta
from math import radians, cos, sin, asin, sqrt
from typing import Optional, List, Dict

from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

# --- Local Imports ---
import config
from employees import users as static_users # For initial data reference
from services import calculate_working_days_and_leaves_for_employee, is_at_office

# ===========================================================================
# LIFESPAN MANAGER (Handles Startup/Shutdown)
# ===========================================================================

def initialize_database_schema():
    """Initializes the database schema."""
    try:
        conn = mysql.connector.connect(
            host=config.DB_HOST, user=config.DB_USER, password=config.DB_PASSWORD, port=config.DB_PORT
        )
        cursor = conn.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{config.DB_NAME}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        cursor.execute(f"USE `{config.DB_NAME}`")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                id BIGINT PRIMARY KEY AUTO_INCREMENT, user_email VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
                action ENUM('check-in','check-out') NOT NULL, event_time DATETIME NOT NULL,
                latitude DECIMAL(10,7) NULL, longitude DECIMAL(10,7) NULL,
                location_text VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL, INDEX idx_user_time (user_email, event_time)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """)
        # Create employee_details table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS employee_details (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
                email VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci UNIQUE NOT NULL,
                password VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL, 
                photo VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT 'profile.jpg',
                job_role VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT 'Employee',
                phone VARCHAR(20),
                parent_phone VARCHAR(20),
                dob VARCHAR(50),
                gender VARCHAR(50),
                employee_number VARCHAR(50) UNIQUE,
                aadhar VARCHAR(50),
                joining_date VARCHAR(50),
                native VARCHAR(255),
                address TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
                pan_card VARCHAR(50),
                bank_details TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
                salary VARCHAR(50),
                total_leave INT DEFAULT 0,
                total_working INT DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """)

        # Create tasks table separately (avoid multi-statement execution)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INT AUTO_INCREMENT PRIMARY KEY,
                title VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
                description TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
                assigned_to VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
                assigned_by VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
                status ENUM('todo', 'in_progress', 'completed') DEFAULT 'todo',
                due_date DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (assigned_to) REFERENCES employee_details(email),
                FOREIGN KEY (assigned_by) REFERENCES employee_details(email)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """)

        # Create notifications table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INT AUTO_INCREMENT PRIMARY KEY,
                recipient_email VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
                message TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
                task_id INT,
                type ENUM('task_assigned', 'task_updated', 'task_completed') DEFAULT 'task_assigned',
                is_read BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_recipient (recipient_email),
                INDEX idx_read_status (recipient_email, is_read),
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """)

        # Commit schema changes before performing further queries
        conn.commit()

        # Use a fresh cursor for subsequent SELECT/INSERTs to ensure no pending results
        try:
            cursor2 = conn.cursor()
            cursor2.execute("SELECT 1 FROM employee_details WHERE email = %s LIMIT 1", (config.HR_EMAIL,))
            hr_row = cursor2.fetchone()
            if not hr_row:
                default_hr_password = os.getenv("HR_PASSWORD", "zugo@123")
                # Insert a minimal HR user record
                cursor2.execute(
                    "INSERT INTO employee_details (name, email, password, job_role) VALUES (%s, %s, %s, %s)",
                    ("HR", config.HR_EMAIL, default_hr_password, "HR Manager")
                )
                conn.commit()
                print(f"Inserted default HR account: {config.HR_EMAIL}")
            cursor2.close()
        except Exception as _e:
            print(f"Warning: could not ensure HR account exists: {_e}")

        # Seed employee data from employees.py
        try:
            cursor3 = conn.cursor()
            for email, user_data in static_users.items():
                # Skip HR account
                if email == config.HR_EMAIL:
                    continue
                    
                # Check if employee already exists
                cursor3.execute("SELECT email FROM employee_details WHERE email = %s", (email,))
                if cursor3.fetchone():
                    continue  # Employee already exists, skip
                
                # Extract all available data
                name = user_data.get("name", "")
                password = user_data.get("password", "zugo@123")
                photo = user_data.get("photo", "profile.jpg")
                phone = user_data.get("phone")
                parent_phone = user_data.get("parent_phone")
                dob = user_data.get("dob")
                gender = user_data.get("gender")
                employee_number = user_data.get("employee_number")
                aadhar = user_data.get("aadhar")
                joining_date = user_data.get("joining_date")
                native = user_data.get("native")
                address = user_data.get("address")
                job_role = user_data.get("job_role", "Employee")
                pan_card = user_data.get("pan_card")
                bank_details = user_data.get("bank_details")
                salary = user_data.get("salary")
                
                cursor3.execute(
                    """INSERT INTO employee_details 
                       (name, email, password, photo, phone, parent_phone, dob, gender, 
                        employee_number, aadhar, joining_date, native, address, job_role, pan_card, bank_details, salary)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (name, email, password, photo, phone, parent_phone, dob, gender,
                     employee_number, aadhar, joining_date, native, address, job_role, pan_card, bank_details, salary)
                )
            conn.commit()
            cursor3.close()
            print("Employee data seeding complete.")
        except Exception as _e:
            print(f"Warning: could not seed employee data: {_e}")

        cursor.close()
        conn.close()
        print("Database schema initialization complete.")
    except mysql.connector.Error as err:
        print(f"Error during DB initialization: {err}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Application startup...")
    initialize_database_schema()
    yield
    print("Application shutdown...")


# ===========================================================================
# FastAPI APP INITIALIZATION
# ===========================================================================

app = FastAPI(title="Zugo Attendance Management System", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key="a_very_secret_key_change_me")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


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


# Database initialization is now handled by the lifespan manager


# ===========================================================================
# SERVICE FUNCTIONS (Business Logic)
# ===========================================================================

def is_at_office(lat: float, lon: float) -> bool:
    """Check if a location is within the office radius."""
    def haversine(lat1, lon1, lat2, lon2):
        R = 6371000  # Earth radius in meters
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = sin(dlat / 2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2)**2
        c = 2 * asin(sqrt(a))
        return R * c
    return haversine(lat, lon, config.OFFICE_LAT, config.OFFICE_LON) <= config.OFFICE_RADIUS_METERS


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


# ===========================================================================
# API ROUTTES (ENDPOINTS)
# ===========================================================================

@app.get("/", response_class=HTMLResponse, summary="Display login page")
async def login_page(request: Request):
    """Serves the login page."""
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/", response_class=RedirectResponse)
async def handle_login(request: Request, email: str = Form(...), password: str = Form(...), db: mysql.connector.MySQLConnection = Depends(get_db_connection)):
    """Processes login form submission, authenticates user, and sets session."""
    employee = fetch_employee_by_email(db, email)
    if employee and employee["password"] == password:
        request.session["user_email"] = email
        if email == config.HR_EMAIL:
            return RedirectResponse(url="/hr-dashboard", status_code=status.HTTP_303_SEE_OTHER)
        # First login: redirect to attendance page
        return RedirectResponse(url="/report", status_code=status.HTTP_303_SEE_OTHER)
    
    # To show an error, we redirect back to the login page with a query parameter
    return RedirectResponse(url="/?error=Invalid+Credentials", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/signup", response_class=HTMLResponse, summary="Handle new user registration")
async def signup(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: mysql.connector.MySQLConnection = Depends(get_db_connection)
):
    """Registers a new employee."""
    if fetch_employee_by_email(db, email):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Email already registered"})
    
    # Get all details from employees.py if available
    user_data = static_users.get(email)
    if user_data:
        name = user_data.get("name", name)
        photo = user_data.get("photo", "profile.jpg")
        phone = user_data.get("phone")
        parent_phone = user_data.get("parent_phone")
        dob = user_data.get("dob")
        gender = user_data.get("gender")
        employee_number = user_data.get("employee_number")
        aadhar = user_data.get("aadhar")
        joining_date = user_data.get("joining_date")
        native = user_data.get("native")
        address = user_data.get("address")
        job_role = user_data.get("job_role", "Employee")
        pan_card = user_data.get("pan_card")
        bank_details = user_data.get("bank_details")
        salary = user_data.get("salary")
    
    cursor = db.cursor()
    cursor.execute(
        """INSERT INTO employee_details 
           (name, email, password, photo, phone, parent_phone, dob, gender, 
            employee_number, aadhar, joining_date, native, address, job_role)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (name, email, password, photo, phone, parent_phone, dob, gender,
         employee_number, aadhar, joining_date, native, address, job_role)
    )
    db.commit()
    cursor.close()
    
    request.session["user_email"] = email
    return RedirectResponse(url="/report", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/report", response_class=HTMLResponse, summary="Display employee attendance")
async def report(request: Request, db: mysql.connector.MySQLConnection = Depends(get_db_connection)):
    """Shows the main dashboard for a logged-in employee."""
    user_email = request.session.get("user_email")
    if not user_email:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    # Redirect HR to HR Management page instead of employee report
    if user_email == config.HR_EMAIL:
        return RedirectResponse(url="/hr-management", status_code=status.HTTP_303_SEE_OTHER)

    user_data = fetch_employee_by_email(db, user_email) or _build_user_from_static(user_email)
    if not user_data:
        request.session.clear()
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    # Get today's records for the attendance log
    records = fetch_attendance_for_today(db, user_email)
    sorted_records = sorted(records, key=lambda x: x["event_time"], reverse=True)

    # Build monthly report data
    report_data, total_seconds = _build_report_for_user(db, user_email, days=30)
    total_hours = total_seconds / 3600 if total_seconds else 0

    is_hr = user_email == config.HR_EMAIL

    return templates.TemplateResponse("report.html", {
        "request": request,
        "user": user_data,
        "records": sorted_records,
        "report_data": report_data,
        "total_working_hours": f"{total_hours:.2f}",
        "error": request.query_params.get("error"),
        "success": request.query_params.get("success"),
        "is_hr": is_hr
    })


@app.get("/download_report", summary="Download attendance report as CSV")
async def download_report(request: Request, db: mysql.connector.MySQLConnection = Depends(get_db_connection)):
    """Return a CSV file of the user's attendance report (last 30 days)."""
    user_email = request.session.get("user_email")
    if not user_email:
        # Not logged in -> redirect to login
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    # Build report
    report_data, _ = _build_report_for_user(db, user_email, days=30)

    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Day", "Check In", "Check Out", "Total Hours"])
    for row in report_data:
        writer.writerow([row.get("day"), row.get("check_in"), row.get("check_out"), row.get("total_hours")])

    csv_content = output.getvalue()
    output.close()

    filename = f"attendance_{user_email.replace('@', '_at_')}.csv"
    return Response(content=csv_content, media_type="text/csv", headers={
        "Content-Disposition": f"attachment; filename={filename}"
    })

@app.get("/dashboard", response_class=HTMLResponse, summary="Display employee dashboard (profile view)")
async def dashboard_view(request: Request, db: mysql.connector.MySQLConnection = Depends(get_db_connection)):
    """Render `dashboard.html` showing the employee's full profile (attendance log removed).

    This route is used when the user clicks the profile circle in the header.
    """
    user_email = request.session.get("user_email")
    if not user_email:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    # Redirect HR to HR Management page instead of employee dashboard
    if user_email == config.HR_EMAIL:
        return RedirectResponse(url="/hr-management", status_code=status.HTTP_303_SEE_OTHER)

    user = fetch_employee_by_email(db, user_email) or _build_user_from_static(user_email)
    if not user:
        request.session.clear()
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    # Dashboard no longer includes attendance log (it's on /report)
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "error": request.query_params.get("error"),
        "success": request.query_params.get("success")
    })
@app.post("/attendance", summary="Handle check-in/check-out actions")
async def handle_attendance(
    request: Request,
    action: str = Form(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
    db: mysql.connector.MySQLConnection = Depends(get_db_connection)
):
    """Processes check-in and check-out requests."""
    # Get user from session
    user_email = request.session.get("user_email")
    if not user_email:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    # Location validation with detailed error
    try:
        if not is_at_office(float(latitude), float(longitude)):
            return RedirectResponse(
                url=f"/report?error=Location+outside+office+bounds:+{latitude:.6f},+{longitude:.6f}",
                status_code=status.HTTP_303_SEE_OTHER
            )
    except ValueError:
        return RedirectResponse(
            url="/report?error=Invalid+location+data.+Please+enable+location+services",
            status_code=status.HTTP_303_SEE_OTHER
        )

    now = datetime.now()
    current_time = now.time()
    today = now.date()
    
    # Fetch today's attendance records
    cursor = db.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT * FROM attendance 
        WHERE user_email = %s AND DATE(event_time) = %s
        ORDER BY event_time DESC
        """,
        (user_email, today)
    )
    todays_records = cursor.fetchall()
    cursor.close()

    # Check-in Logic
    if action == "check-in":
        is_morning = config.CHECKIN_MORNING_START <= current_time <= config.CHECKIN_MORNING_END
        is_afternoon = current_time == config.CHECKIN_AFTERNOON_EXACT

        if not (is_morning or is_afternoon):
            return RedirectResponse(
                url=f"/report?error=Check-in+only+allowed+between+{config.CHECKIN_MORNING_START}+and+{config.CHECKIN_MORNING_END}+or+at+{config.CHECKIN_AFTERNOON_EXACT}",
                status_code=status.HTTP_303_SEE_OTHER
            )

        if any(r['action'] == 'check-in' for r in todays_records):
            return RedirectResponse(
                url="/report?error=Already+checked+in+today",
                status_code=status.HTTP_303_SEE_OTHER
            )

    # Check-out Logic
    elif action == "check-out":
        if current_time < config.CHECKOUT_MIN_TIME:
            return RedirectResponse(
                url=f"/report?error=Check-out+only+allowed+after+{config.CHECKOUT_MIN_TIME}",
                status_code=status.HTTP_303_SEE_OTHER
            )

        if not any(r['action'] == 'check-in' for r in todays_records):
            return RedirectResponse(
                url="/report?error=Must+check-in+before+checking+out",
                status_code=status.HTTP_303_SEE_OTHER
            )

        if any(r['action'] == 'check-out' for r in todays_records):
            return RedirectResponse(
                url="/report?error=Already+checked+out+today",
                status_code=status.HTTP_303_SEE_OTHER
            )

    # Insert attendance record
    try:
        cursor = db.cursor()
        cursor.execute(
            """
            INSERT INTO attendance 
            (user_email, action, event_time, latitude, longitude, location_text)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (user_email, action, now, latitude, longitude, f"{latitude:.6f}, {longitude:.6f}")
        )
        db.commit()
        cursor.close()

        # Update total working days for check-ins
        if action == "check-in":
            working_days, _, _ = calculate_working_days_and_leaves_for_employee(user_email, today)
            cursor = db.cursor()
            cursor.execute(
                "UPDATE employee_details SET total_working = %s WHERE email = %s",
                (working_days, user_email)
            )
            db.commit()
            cursor.close()

        success_msg = f"Successfully+{action.replace('-', '+')}+at+{now.strftime('%I:%M+%p')}"
        return RedirectResponse(
            url=f"/report?success={success_msg}",
            status_code=status.HTTP_303_SEE_OTHER
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/report?error=Database+error:+{str(e)}",
            status_code=status.HTTP_303_SEE_OTHER
        )


@app.get("/hr-dashboard", response_class=HTMLResponse, summary="Display HR dashboard")
async def hr_dashboard(request: Request, db: mysql.connector.MySQLConnection = Depends(get_db_connection)):
    """Shows the main dashboard for the HR manager."""
    user_email = request.session.get("user_email")
    if not user_email or user_email != config.HR_EMAIL:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    hr_user = fetch_employee_by_email(db, user_email)
    if not hr_user:
        # If the HR user record is missing for some reason, clear session and redirect to login
        request.session.clear()
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    employees = fetch_all_employees(db)
    
    # You might want to calculate total working days for the current month here
    # For simplicity, we are showing the stored total.
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": hr_user,
        "employees": employees
    })

@app.post("/assign-task", response_class=RedirectResponse)
async def assign_task(
    request: Request,
    title: str = Form(...),
    description: str = Form(...),
    assigned_to: str = Form(...),
    due_date: str = Form(...),
    db: mysql.connector.MySQLConnection = Depends(get_db_connection)
):
    """Assign a new task to an employee and create notification."""
    user_email = request.session.get("user_email")
    if not user_email or user_email != config.HR_EMAIL:
        raise HTTPException(status_code=403, detail="Only HR can assign tasks")
    
    # Prevent HR from assigning task to themselves
    if assigned_to == config.HR_EMAIL:
        return RedirectResponse(url="/workspace?error=Cannot+assign+task+to+HR", status_code=303)
    
    cursor = db.cursor()
    try:
         # Insert task
        cursor.execute(
            """
            INSERT INTO tasks (title, description, assigned_to, assigned_by, due_date)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (title, description, assigned_to, user_email, due_date)
        )
        db.commit()
        
        # Get the inserted task ID
        task_id = cursor.lastrowid
        
        # Create notification for the assigned employee
        assigned_emp = fetch_employee_by_email(db, assigned_to)
        assigned_name = assigned_emp.get("name", assigned_to) if assigned_emp else assigned_to
        
        notification_message = f"New task assigned: '{title}' - Due: {due_date}"
        
        cursor.execute(
            """
            INSERT INTO notifications (recipient_email, message, task_id, type)
            VALUES (%s, %s, %s, %s)
            """,
            (assigned_to, notification_message, task_id, 'task_assigned')
        )
        db.commit()
        
        return RedirectResponse(url="/workspace?success=Task+assigned+successfully", status_code=303)
    except mysql.connector.Error as e:
        return RedirectResponse(url=f"/workspace?error={str(e)}", status_code=303)
    finally:
        cursor.close()

@app.get("/workspace", response_class=HTMLResponse)
async def workspace(request: Request, db: mysql.connector.MySQLConnection = Depends(get_db_connection)):
    user_email = request.session.get("user_email")
    if not user_email:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    
    is_hr = user_email == config.HR_EMAIL
    
    # Fetch tasks
    cursor = db.cursor(dictionary=True)
    if is_hr:
        # HR sees all tasks
        cursor.execute("""
            SELECT t.*, e.name as assigned_to_name 
            FROM tasks t 
            JOIN employee_details e ON t.assigned_to = e.email
            ORDER BY t.created_at DESC
        """)
    else:
        # Employees see only their tasks
        cursor.execute("""
            SELECT t.*, e.name as assigned_by_name 
            FROM tasks t 
            JOIN employee_details e ON t.assigned_by = e.email
            WHERE t.assigned_to = %s
            ORDER BY t.created_at DESC
        """, (user_email,))
        
    tasks = cursor.fetchall()
    
    # Get employee list for HR task assignment
    employees = []
    if is_hr:
        cursor.execute(
            "SELECT email, name FROM employee_details WHERE email != %s",
            (config.HR_EMAIL,)
        )
        employees = cursor.fetchall()
    
    cursor.close()
    
    return templates.TemplateResponse("task_manager.html", {
        "request": request,
        "assigned_tasks": tasks, # Renamed for clarity in the template
        "employees": employees,
        "is_hr": is_hr,
        "user_email": user_email,
        "error": request.query_params.get("error"),
        "success": request.query_params.get("success")
    })


def _build_user_from_static(email: str):
    """Return a dict user object from the static `static_users` if available."""
    u = static_users.get(email)
    if not u:
        return None
    # Normalize keys to match DB shape
    return {
        "name": u.get("name"),
        "email": u.get("email", email),
        "photo": u.get("photo", "profile.jpg"),
        "phone": u.get("phone"),
        "employee_number": u.get("employee_number"),
        "aadhar": u.get("aadhar") or u.get("AADHAR"),
        "dob": u.get("dob"),
        "gender": u.get("gender"),
        "job_role": u.get("job_role", "Employee"),
        "native": u.get("native"),
        "address": u.get("address"),
        "joining_date": u.get("joining_date"),
        "parent_phone": u.get("parent_phone"),
        "total_working": u.get("total_working", 0),
        "total_leave": u.get("total_leave", 0),
    }


def _build_report_for_user(db, user_email, days: int = 30):
    """Build report rows for the last `days` days for the given user.

    Returns list of dicts: {day, check_in, check_out, total_hours}
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    cursor = db.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT event_time, action FROM attendance
        WHERE user_email = %s AND event_time BETWEEN %s AND %s
        ORDER BY event_time ASC
        """,
        (user_email, start_date, end_date)
    )
    rows = cursor.fetchall()
    cursor.close()

    # Group by date
    by_date = {}
    for r in rows:
        d = r["event_time"].date().isoformat()
        by_date.setdefault(d, []).append(r)

    report = []
    total_working_seconds = 0
    for day, events in sorted(by_date.items()):
        # Find earliest check-in and latest check-out
        check_ins = [e["event_time"] for e in events if e["action"] == "check-in"]
        check_outs = [e["event_time"] for e in events if e["action"] == "check-out"]

        check_in = min(check_ins).strftime("%I:%M %p") if check_ins else "-"
        check_out = max(check_outs).strftime("%I:%M %p") if check_outs else "-"

        seconds = 0
        if check_ins and check_outs:
            seconds = int((max(check_outs) - min(check_ins)).total_seconds())
            total_working_seconds += seconds

        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        total_str = f"{hours}h {minutes}m" if seconds else "-"

        report.append({
            "day": day,
            "check_in": check_in,
            "check_out": check_out,
            "total_hours": total_str
        })

    return report, total_working_seconds


@app.get("/employees", response_class=HTMLResponse)
async def employees_page(request: Request, db: mysql.connector.MySQLConnection = Depends(get_db_connection)):
    user_email = request.session.get("user_email")
    if not user_email:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
        
    # Get current user's role
    is_hr = user_email == config.HR_EMAIL
    
    # Get employees list
    all_employees = fetch_all_employees(db)
    
    # Add presence information
    try:
        cursor = db.cursor()
        today = date.today()
        for emp in all_employees:
            email = emp.get("email")
            if email:
                # Check attendance
                cursor.execute(
                    "SELECT 1 FROM attendance WHERE user_email = %s AND DATE(event_time) = %s LIMIT 1",
                    (email, today)
                )
                emp["present_today"] = bool(cursor.fetchone())
                
                # Add salary info for HR only
                if is_hr:
                    cursor.execute(
                        "SELECT salary FROM employee_details WHERE email = %s",
                        (email,)
                    )
                    salary_row = cursor.fetchone()
                    emp["salary"] = salary_row[0] if salary_row else None
                    
        cursor.close()
    except Exception:
        # Handle error gracefully
        for emp in all_employees:
            emp["present_today"] = False
            if is_hr:
                emp["salary"] = None
                
    # Use different templates for HR vs employee view
    template_name = "employee_list.html"
    
    return templates.TemplateResponse(template_name, {
        "request": request,
        "employees": all_employees,
        "is_hr": is_hr
    })


# Dashboard (per-user profile view)
@app.get("/dashboard", response_class=HTMLResponse, summary="Display employee dashboard (profile view)")
async def dashboard_view(request: Request, db: mysql.connector.MySQLConnection = Depends(get_db_connection)):
    user_email = request.session.get("user_email")
    if not user_email:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    user = fetch_employee_by_email(db, user_email) or _build_user_from_static(user_email)
    if not user:
        request.session.clear()
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "error": request.query_params.get("error"),
        "success": request.query_params.get("success")
    })
    
    
@app.get("/logout", summary="Log user out")
async def logout(request: Request):
    """Clears the user session."""
    request.session.clear()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/update-task-status")
async def update_task_status(
    request: Request,
    db: mysql.connector.MySQLConnection = Depends(get_db_connection)
):
    """Update task status (employee can only update status of tasks assigned to them)"""
    user_email = request.session.get("user_email")
    if not user_email:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        body = await request.json()
        task_id = body.get("taskId")
        new_status = body.get("status")
        
        if not task_id or not new_status:
            raise HTTPException(status_code=400, detail="Missing taskId or status")
            
        # Verify task belongs to user
        cursor = db.cursor()
        cursor.execute(
            "SELECT 1 FROM tasks WHERE id = %s AND assigned_to = %s",
            (task_id, user_email)
        )
        if not cursor.fetchone():
            cursor.close()
            raise HTTPException(status_code=403, detail="Not authorized to update this task")
        
        # Update status
        cursor.execute(
            "UPDATE tasks SET status = %s WHERE id = %s",
            (new_status, task_id)
        )
        db.commit()
        cursor.close()
        
        return {"success": True}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/hr-management", response_class=HTMLResponse, summary="HR Management Dashboard")
async def hr_management(request: Request, db: mysql.connector.MySQLConnection = Depends(get_db_connection)):
    """HR-only page showing all employees with salary and privacy details."""
    user_email = request.session.get("user_email")
    if not user_email:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    
    # Check if user is HR
    if user_email != config.HR_EMAIL:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    
    # Fetch all employees EXCEPT HR email
    cursor = db.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM employee_details WHERE email != %s ORDER BY name ASC",
        (config.HR_EMAIL,)
    )
    employees = cursor.fetchall()
    cursor.close()
    
    # Merge with static data to get salary info
    for emp in employees:
        static_data = static_users.get(emp['email'], {})
        if 'salary' in static_data:
            emp['salary'] = static_data['salary']
        else:
            emp['salary'] = 'Not Set'
    
    return templates.TemplateResponse("hr_management.html", {
        "request": request,
        "employees": employees,
        "is_hr": True,
        "user_email": user_email
    })


# =================================================================
# MAIN EXECUTION
# ==============================================================================

if __name__ == "__main__":
    
    # This runs the ASGI server. Use --reload for development.
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
