# from datetime import datetime, date, timedelta
# from functools import wraps # for decorators

# from mydb import (
#     insert_attendance, fetch_employee_by_email, fetch_all_employees,
#     update_employee_working_days, insert_employee, fetch_attendance_for_period
# )
# from services import (
#     is_at_office, is_checkin_allowed, is_checkout_allowed,
#     calculate_working_days_and_leaves_for_employee,
#     send_monthly_report_email_task,
#     get_attendance_period_dates
# )
# from config import HR_EMAIL, ATTENDANCE_PERIOD_START_DAY, ATTENDANCE_PERIOD_END_DAY

# # This imports the app object created in main.py
# # Use a Blueprint to avoid importing the app object and circular imports;
# # register this blueprint in main.py with: app.register_blueprint(bp)
# from flask import Blueprint
# bp = Blueprint("routes", __name__)


# def login_required(f):
#     @wraps(f)
#     def decorated_function(*args, **kwargs):
#         if "user_email" not in session:
#             return redirect(url_for("login"))
#         return f(*args, **kwargs)
#     return decorated_function

# def hr_required(f):
#     @wraps(f)
#     def decorated_function(*args, **kwargs):
#         if "user_email" not in session or session["user_email"] != HR_EMAIL:
#             return redirect(url_for("login")) # Or an unauthorized page
#         return f(*args, **kwargs)
# @bp.route("/", methods=["GET", "POST"])
# def login():
#     """Handles the login page and form submission."""
#     if request.method == "POST":
#         email = request.form["email"]
#         password = request.form["password"]

#         employee = fetch_employee_by_email(email)

#         if employee and employee["password"] == password:
#             session["user_email"] = email
#             # Redirect HR to HR dashboard, others to regular dashboard
#             if email == HR_EMAIL:
#                 return redirect(url_for("hr_dashboard"))
#             return redirect(url_for("dashboard"))
#         else:
#             return render_template("login.html", error="Invalid Credentials")
# @bp.route("/signup", methods=["POST"])
# def signup():

# @bp.route("/signup", methods=["POST"])
# def signup():
#     """Handles the signup form submission."""
#     name = request.form["name"]
#     email = request.form["email"]
#     password = request.form["password"]

#     # Check if already exists in DB
#     if fetch_employee_by_email(email):
#         return render_template("login.html", error="Email already registered")

#     # Insert into DB with default values
#     insert_employee(name=name, email=email, password=password)

#     session["user_email"] = email
#     return redirect(url_for("dashboard"))
# @app.route("/dashboard", methods=["GET", "POST"])
# @login_required
# @bp.route("/dashboard", methods=["GET", "POST"])
# @login_required
# def dashboard():
#     user_email = session["user_email"]
#     employee_data = fetch_employee_by_email(user_email)
#     error = None
#     success_message = None
#     date_today = datetime.now().date()
    
#     # 1. Fetch records before the POST logic starts (used for initial render and error paths)
#     start_period, end_period = get_attendance_period_dates(date_today)
#     attendance_records = fetch_attendance_for_period(user_email, start_period, end_period)


#     if request.method == "POST":
#         action = request.form.get("action")
#         latitude = request.form.get("latitude")
#         longitude = request.form.get("longitude")
#         now = datetime.now()
#         time_now = now.time()

#         # Validate location
#         try:
#             lat = float(latitude)
#             lon = float(longitude)
#         except (TypeError, ValueError):
#             error = "Location not detected. Please enable location services."
#             # Pass the fetched records back on error
#             return render_template("dashboard.html", user=employee_data, records=attendance_records, error=error, success_message=success_message)

#         if not is_at_office(lat, lon):
#             error = "You must be at the office to check in/out."
#             # Pass the fetched records back on error
#             return render_template("dashboard.html", user=employee_data, records=attendance_records, error=error, success_message=success_message)

#         # Fetch today's attendance records for the user
#         todays_attendance_records = fetch_attendance_for_period(user_email, date_today, date_today)
        
#         # Check-in logic
#         if action == "check-in":
#             if not is_checkin_allowed(time_now):
#                 error = "Check-in allowed only between 09:30-09:45 AM and exactly at 1:30 PM."
#                 # Pass the fetched records back on error
#                 return render_template("dashboard.html", user=employee_data, records=attendance_records, error=error, success_message=success_message)
            
#             # Check if already checked in today
#             already_checked_in = any(r["action"] == "check-in" for r in todays_attendance_records)
#             if already_checked_in:
#                 error = "Already checked in today."
#                 # Pass the fetched records back on error
#                 return render_template("dashboard.html", user=employee_data, records=attendance_records, error=error, success_message=success_message)
            
#             insert_attendance(user_email, action, now, lat, lon, f"{lat:.6f}, {lon:.6f}")
#             success_message = f"Successfully checked in at {now.strftime('%I:%M %p')}."
            
#             # Recalculate and update total_working for the current period
#             total_working, _, _ = calculate_working_days_and_leaves_for_employee(user_email, date_today)
#             update_employee_working_days(user_email, total_working)
#             employee_data = fetch_employee_by_email(user_email) # Re-fetch to update display value

#         # Check-out logic
#         elif action == "check-out":
#             if not is_checkout_allowed(time_now):
#                 error = "Check-out allowed only after 7:15 PM."
#                 # Pass the fetched records back on error
#                 return render_template("dashboard.html", user=employee_data, records=attendance_records, error=error, success_message=success_message)

#             # Check if already checked out today
#             already_checked_out = any(r["action"] == "check-out" for r in todays_attendance_records)
#             if already_checked_out:
#                 error = "Already checked out today."
#                 # Pass the fetched records back on error
#                 return render_template("dashboard.html", user=employee_data, records=attendance_records, error=error, success_message=success_message)

#             insert_attendance(user_email, action, now, lat, lon, f"{lat:.6f}, {lon:.6f}")
#             success_message = f"Successfully checked out at {now.strftime('%I:%M %p')}."

#         # Re-fetch attendance records after successful action
#         attendance_records = fetch_attendance_for_period(user_email, start_period, end_period)


#     # Final render path: fetch employee data one last time to ensure all values are current
#     employee_data = fetch_employee_by_email(user_email)

#     return render_template(
#         "dashboard.html",
#         user=employee_data,
#         records=attendance_records,
#         error=error,
#         success_message=success_message
# @bp.route("/hr-dashboard")
# @hr_required
# def hr_dashboard():
# @app.route("/hr-dashboard")
# @hr_required
# def hr_dashboard():
#     """Displays attendance data for all employees for the current custom attendance period."""

# @bp.route("/hr-dashboard")
# @hr_required
# def hr_dashboard():
#     """Displays at   tendance data for all employees for the current custom attendance period."""
#     employee_list = []

#     for employee in all_employees:
#         if employee["email"] == HR_EMAIL: # Skip HR account itself
#             continue
            
#         # Recalculate working days based on the current custom period for the dashboard
#         current_working_days, _, _ = calculate_working_days_and_leaves_for_employee(employee["email"], ref_date)

#         employee_list.append({
#             "photo": employee.get("photo", "profile.jpg"),
#             "phone": employee.get("phone", "N/A"),
#             "name": employee.get("name", "N/A"),
#             "email": employee["email"],
#             "total_working": current_working_days, # Use the count for the current period
#             "total_leave": employee.get("total_leave", 0),  # Use the total accumulated leave from DB
#             "AADHAR": employee.get("aadhar", "N/A")
#         })

#     # Fetch HR user data for header display
#     hr_user = fetch_employee_by_email(user_email)
#     user_data = hr_user if hr_user else {"name": "HR"}

#     return render_template(
#         "hr_dashboard.html", 
#         employees=employee_list, 
#         user=user_data,
#         period_start=start_period.strftime("%b %d"),
#         period_end=end_period.strftime("%b %d")
# @bp.route("/logout")
# def logout():

# @app.route("/logout")
# def logout():
#     """Logs the user out by clearing the session."""
#     session.pop("user_email", None) # Clear user_email from session
#     return redirect(url_for("login"))

# # The following block referencing 'sorted_records' was removed because 'sorted_records' is not defined and the block is not used in any route or function.
# @bp.route("/logout")
# def logout():
#     """Logs the user out by clearing the session."""
#     session.pop("user_email", None) # Clear user_email from session
#     return redirect(url_for("login"))