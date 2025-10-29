import uvicorn
import mysql.connector
from contextlib import asynccontextmanager
from datetime import datetime, date, time, timedelta
from math import radians, cos, sin, asin, sqrt
from typing import Optional, List, Dict

from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

# --- Local Imports ---
import config
from employees import users as static_users # For initial data reference
from services import calculate_working_days_and_leaves_for_employee, is_at_office

# ==============================================================================
# LIFESPAN MANAGER (Handles Startup/Shutdown)
# ==============================================================================

def initialize_database_schema():
    """Initializes the database schema."""
    try:
        conn = mysql.connector.connect(
            host=config.DB_HOST, user=config.DB_USER, password=config.DB_PASSWORD, port=config.DB_PORT
        )
        cursor = conn.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{config.DB_NAME}`")
        cursor.execute(f"USE `{config.DB_NAME}`")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                id BIGINT PRIMARY KEY AUTO_INCREMENT, user_email VARCHAR(255) NOT NULL,
                action ENUM('check-in','check-out') NOT NULL, event_time DATETIME NOT NULL,
                latitude DECIMAL(10,7) NULL, longitude DECIMAL(10,7) NULL,
                location_text VARCHAR(255) NULL, INDEX idx_user_time (user_email, event_time)
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS employee_details (
                id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(255) NOT NULL,
                email VARCHAR(255) UNIQUE NOT NULL, password VARCHAR(255) NOT NULL,
                photo VARCHAR(255) DEFAULT 'profile.jpg', job_role VARCHAR(255) DEFAULT 'Employee',
                total_leave INT DEFAULT 0, total_working INT DEFAULT 0
            );
        """)
        conn.commit()
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

# ==============================================================================
# FastAPI APP INITIALIZATION
# ==============================================================================

app = FastAPI(title="Zugo Attendance Management System", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key="a_very_secret_key_change_me")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ==============================================================================
# DATABASE SETUP & DEPENDENCY
# ==============================================================================

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


# ==============================================================================
# SERVICE FUNCTIONS (Business Logic)
# ==============================================================================

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

# ==============================================================================
# DATABASE UTILITY FUNCTIONS
# ==============================================================================

def fetch_employee_by_email(db: mysql.connector.MySQLConnection, email: str) -> Optional[Dict]:
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM employee_details WHERE email = %s", (email,))
    employee = cursor.fetchone()
    cursor.close()
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
    return employees

# ==============================================================================
# API ROUTES (ENDPOINTS)
# ==============================================================================

@app.get("/", response_class=HTMLResponse, summary="Display login page")
async def login_page(request: Request):
    """Serves the login page."""
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/", response_class=RedirectResponse, summary="Handle user login")
async def handle_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: mysql.connector.MySQLConnection = Depends(get_db_connection)
):
    """Processes login form submission, authenticates user, and sets session."""
    employee = fetch_employee_by_email(db, email)
    if employee and employee["password"] == password:
        request.session["user_email"] = email
        if email == config.HR_EMAIL:
            return RedirectResponse(url="/hr-dashboard", status_code=status.HTTP_303_SEE_OTHER)
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    
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
    
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO employee_details (name, email, password) VALUES (%s, %s, %s)",
        (name, email, password)
    )
    db.commit()
    cursor.close()
    
    request.session["user_email"] = email
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/dashboard", response_class=HTMLResponse, summary="Display employee dashboard")
async def dashboard(request: Request, db: mysql.connector.MySQLConnection = Depends(get_db_connection)):
    """Shows the main dashboard for a logged-in employee."""
    user_email = request.session.get("user_email")
    if not user_email:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    user_data = fetch_employee_by_email(db, user_email)
    if not user_data: # If user was deleted but session exists
        request.session.clear()
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
        
    records = fetch_attendance_for_today(db, user_email)
    sorted_records = sorted(records, key=lambda x: x["event_time"], reverse=True)

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user_data,
        "records": sorted_records,
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
                url=f"/dashboard?error=Location+outside+office+bounds:+{latitude:.6f},+{longitude:.6f}",
                status_code=status.HTTP_303_SEE_OTHER
            )
    except ValueError:
        return RedirectResponse(
            url="/dashboard?error=Invalid+location+data.+Please+enable+location+services",
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
                url=f"/dashboard?error=Check-in+only+allowed+between+{config.CHECKIN_MORNING_START}+and+{config.CHECKIN_MORNING_END}+or+at+{config.CHECKIN_AFTERNOON_EXACT}",
                status_code=status.HTTP_303_SEE_OTHER
            )

        if any(r['action'] == 'check-in' for r in todays_records):
            return RedirectResponse(
                url="/dashboard?error=Already+checked+in+today",
                status_code=status.HTTP_303_SEE_OTHER
            )

    # Check-out Logic
    elif action == "check-out":
        if current_time < config.CHECKOUT_MIN_TIME:
            return RedirectResponse(
                url=f"/dashboard?error=Check-out+only+allowed+after+{config.CHECKOUT_MIN_TIME}",
                status_code=status.HTTP_303_SEE_OTHER
            )

        if not any(r['action'] == 'check-in' for r in todays_records):
            return RedirectResponse(
                url="/dashboard?error=Must+check-in+before+checking+out",
                status_code=status.HTTP_303_SEE_OTHER
            )

        if any(r['action'] == 'check-out' for r in todays_records):
            return RedirectResponse(
                url="/dashboard?error=Already+checked+out+today",
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
            url=f"/dashboard?success={success_msg}",
            status_code=status.HTTP_303_SEE_OTHER
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/dashboard?error=Database+error:+{str(e)}",
            status_code=status.HTTP_303_SEE_OTHER
        )


@app.get("/hr-dashboard", response_class=HTMLResponse, summary="Display HR dashboard")
async def hr_dashboard(request: Request, db: mysql.connector.MySQLConnection = Depends(get_db_connection)):
    """Shows the main dashboard for the HR manager."""
    user_email = request.session.get("user_email")
    if not user_email or user_email != config.HR_EMAIL:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    hr_user = fetch_employee_by_email(db, user_email)
    employees = fetch_all_employees(db)
    
    # You might want to calculate total working days for the current month here
    # For simplicity, we are showing the stored total.
    
    return templates.TemplateResponse("hr_dashboard.html", {
        "request": request,
        "user": hr_user,
        "employees": employees
    })

@app.get("/workspace", response_class=HTMLResponse, summary="Display Task Manager")
async def workspace(request: Request, db: mysql.connector.MySQLConnection = Depends(get_db_connection)):
    """Serves the task manager page."""
    user_email = request.session.get("user_email")
    if not user_email:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    
    # Fetch tasks assigned to the user
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT t.*, e.name as assigned_by_name 
        FROM tasks t 
        JOIN employee_details e ON t.assigned_by = e.email
        WHERE t.assigned_to = %s
        ORDER BY t.created_at DESC
    """, (user_email,))
    assigned_tasks = cursor.fetchall()
    
    # If user is HR, also fetch all employee emails for task assignment
    is_hr = user_email == config.HR_EMAIL
    employees = []
    if is_hr:
        cursor.execute("SELECT email, name FROM employee_details WHERE email != %s", (config.HR_EMAIL,))
        employees = cursor.fetchall()
    
    cursor.close()
    
    return templates.TemplateResponse("task_manager.html", {
        "request": request,
        "user_email": user_email,
        "tasks": assigned_tasks,
        "employees": employees,
        "is_hr": is_hr
    })

@app.get("/logout", summary="Log user out")
async def logout(request: Request):
    """Clears the user session."""
    request.session.clear()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


# =================================================================
# MAIN EXECUTION
# ==============================================================================

if __name__ == "__main__":
    # This runs the ASGI server. Use --reload for development.
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)