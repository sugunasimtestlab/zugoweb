import uvicorn
import csv
import io
import mysql.connector
from contextlib import asynccontextmanager
from datetime import datetime, date, timedelta

from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

#  --- Local Imports ---
import config
from employees import users as static_users 
from data import get_db_connection ,fetch_attendance_for_today ,fetch_all_employees ,fetch_employee_by_email
from services import calculate_working_days_and_leaves_for_employee, is_at_office
from schema import  initialize_database_schema 

# ===========================================================================
# FastAPI APP INITIALIZATION
# ===========================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Application startup...")
    initialize_database_schema()
    yield
    print("Application shutdown...")

app = FastAPI(title="Zugo Attendance Management System", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key="a_very_secret_key_change_me")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


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
    
    # Get employees list (excludes HR)
    all_employees = fetch_all_employees(db)
    
    # Extra safety: filter out any HR employees that somehow made it through
    all_employees = [emp for emp in all_employees if emp.get("email") != config.HR_EMAIL]
    
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


# ===========================================================================
# EMPLOYEE MANAGEMENT ENDPOINTS (HR ONLY)
# ===========================================================================

@app.get("/api/employee/{email}", summary="Get employee details by email")
async def get_employee_api(email: str, request: Request, db: mysql.connector.MySQLConnection = Depends(get_db_connection)):
    """API endpoint to fetch employee details for editing."""
    user_email = request.session.get("user_email")
    if not user_email or user_email != config.HR_EMAIL:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    employee = fetch_employee_by_email(db, email)
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    return employee


@app.post("/manage-employee", response_class=RedirectResponse, summary="Add or edit employee")
async def manage_employee(
    request: Request,
    action: str = Form(...),
    name: str = Form(...),
    new_email: str = Form(...),
    password: str = Form(None),
    phone: str = Form(None),
    employee_number: str = Form(None),
    job_role: str = Form("Employee"),
    dob: str = Form(None),
    salary: str = Form(None),
    email: str = Form(None),
    db: mysql.connector.MySQLConnection = Depends(get_db_connection)
):
    """Handle adding or editing employees (HR only)."""
    user_email = request.session.get("user_email")
    if not user_email or user_email != config.HR_EMAIL:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    
    try:
        cursor = db.cursor()
        
        if action == "add":
            # Insert new employee
            cursor.execute(
                """INSERT INTO employee_details 
                   (name, email, password, phone, employee_number, job_role, dob, salary)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (name, new_email, password or "zugo@123", phone, employee_number, job_role, dob, salary)
            )
            db.commit()
            
        elif action == "edit":
            # Update existing employee
            if password:
                cursor.execute(
                    """UPDATE employee_details 
                       SET name = %s, phone = %s, employee_number = %s, job_role = %s, dob = %s, salary = %s, password = %s
                       WHERE email = %s""",
                    (name, phone, employee_number, job_role, dob, salary, password, email)
                )
            else:
                cursor.execute(
                    """UPDATE employee_details 
                       SET name = %s, phone = %s, employee_number = %s, job_role = %s, dob = %s, salary = %s
                       WHERE email = %s""",
                    (name, phone, employee_number, job_role, dob, salary, email)
                )
            db.commit()
        
        cursor.close()
        
    except mysql.connector.Error as err:
        print(f"Database error: {err}")
        return RedirectResponse(url=f"/hr-management?error=Database error", status_code=status.HTTP_303_SEE_OTHER)
    
    return RedirectResponse(url="/hr-management?success=Employee saved", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/delete-employee", response_class=RedirectResponse, summary="Delete employee")
async def delete_employee(
    request: Request,
    email: str = Form(...),
    db: mysql.connector.MySQLConnection = Depends(get_db_connection)
):
    """Delete an employee (HR only)."""
    user_email = request.session.get("user_email")
    if not user_email or user_email != config.HR_EMAIL:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    
    # Prevent deleting HR account
    if email == config.HR_EMAIL:
        return RedirectResponse(url="/hr-management?error=Cannot delete HR account", status_code=status.HTTP_303_SEE_OTHER)
    
    try:
        cursor = db.cursor()
        cursor.execute("DELETE FROM employee_details WHERE email = %s", (email,))
        db.commit()
        cursor.close()
        
    except mysql.connector.Error as err:
        print(f"Database error: {err}")
        return RedirectResponse(url=f"/hr-management?error=Database error", status_code=status.HTTP_303_SEE_OTHER)
    
    return RedirectResponse(url="/hr-management?success=Employee deleted", status_code=status.HTTP_303_SEE_OTHER)

    
# =================================================================
# MAIN EXECUTION
# ==============================================================================

if __name__ == "__main__":
    
    # This runs the ASGI server. Use --reload for development.
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
