# services.py
import math
import io
import csv
import config
from math import radians, cos, sin, asin, sqrt
from typing import Optional, List, Dict

import smtplib
from email.message import EmailMessage
from datetime import datetime, date, timedelta

from config import (
    OFFICE_LAT, OFFICE_LON, OFFICE_RADIUS_METERS,
    CHECKIN_MORNING_START, CHECKIN_MORNING_END, CHECKIN_AFTERNOON_EXACT,
    CHECKOUT_MIN_TIME,
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, HR_EMAIL, MD_EMAIL,
    ATTENDANCE_PERIOD_START_DAY, ATTENDANCE_PERIOD_END_DAY
)
from mydb import (
    fetch_attendance_for_period, fetch_all_employees,
    update_employee_leave, fetch_monthly_attendance_all, get_connection  # For monthly report (calendar month)
)

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


def is_checkin_allowed(current_time: datetime.time) -> bool:
    """Checks if the current time is within allowed check-in windows."""
    # Check for morning window
    morning_allowed = (CHECKIN_MORNING_START <= current_time <= CHECKIN_MORNING_END)
    # Check for afternoon exact time
    afternoon_allowed = (current_time == CHECKIN_AFTERNOON_EXACT)
    return morning_allowed or afternoon_allowed

def is_checkout_allowed(current_time: datetime.time) -> bool:
    """Checks if the current time is after the minimum allowed check-out time."""
    return current_time >= CHECKOUT_MIN_TIME

def get_attendance_period_dates(ref_date: date) -> tuple[date, date]:
    """
    Calculates the start and end dates for the attendance period
    (20th of previous month to 20th of current month or similar).
    """
    if ref_date.day > ATTENDANCE_PERIOD_END_DAY:
        # Example: if today is Oct 25, period is Oct 21 to Nov 20
        start_month = ref_date.month
        start_year = ref_date.year
        end_month = (ref_date.month % 12) + 1
        end_year = ref_date.year if end_month != 1 else ref_date.year + 1
    else:
        # Example: if today is Oct 15, period is Sep 21 to Oct 20
        end_month = ref_date.month
        end_year = ref_date.year
        start_month = (ref_date.month - 2 + 12) % 12 + 1 # month-1, then adjust for Jan
        start_year = ref_date.year if start_month != 12 else ref_date.year - 1

    start_date = date(start_year, start_month, ATTENDANCE_PERIOD_START_DAY)
    end_date = date(end_year, end_month, ATTENDANCE_PERIOD_END_DAY)

    # Adjust start_date if it falls in the current month but should be previous
    if ref_date.day <= ATTENDANCE_PERIOD_END_DAY:
        if start_date.month == ref_date.month:
             # This means start_date was calculated for current year/month but should be previous year/month
            start_date = date(start_date.year, start_date.month - 1, ATTENDANCE_PERIOD_START_DAY)
            if start_date.month == 0: # Handle December case
                start_date = date(start_date.year - 1, 12, ATTENDANCE_PERIOD_START_DAY)

    return start_date, end_date


def calculate_working_days_and_leaves_for_employee(user_email: str, ref_date: date = None):
    """
    Calculates working days and leaves for a user based on the attendance period (20th to 20th).
    If ref_date is not provided, uses today's date to determine the current period.
    """
    if ref_date is None:
        ref_date = date.today()

    start_period, end_period = get_attendance_period_dates(ref_date)
    
    attendance_records = fetch_attendance_for_period(user_email, start_period, end_period)

    # Calculate actual working days based on unique check-ins within the period
    checked_in_dates = set()
    for record in attendance_records:
        if record["action"] == "check-in":
            checked_in_dates.add(record["event_time"].date())
    
    total_working_days = len(checked_in_dates)

    # Note: total_leave from DB should be updated by the scheduled task
    # This function primarily *calculates* total_working for display.
    # The actual 'total_leave' in DB is managed by the daily leave marking job.

    return total_working_days, start_period, end_period


def mark_leaves_for_absent_employees():
    """
    Marks 1 leave for employees who have not checked in today.
    Runs daily.
    """
    today = date.today()
    employees = fetch_all_employees()
    
    for employee in employees:
        user_email = employee["email"]
        if user_email == HR_EMAIL: # Skip HR account
            continue

        # Check for check-in today
        todays_attendance = fetch_attendance_for_period(user_email, today, today)
        checked_in_today = any(r["action"] == "check-in" for r in todays_attendance)

        if not checked_in_today:
            current_leave = employee.get("total_leave", 0)
            update_employee_leave(user_email, current_leave + 1)
            print(f"Marked 1 leave for {user_email} on {today.strftime('%Y-%m-%d')}")
        else:
            print(f"{user_email} checked in today. No leave marked.")


def send_monthly_report_email_task() -> None:
    """
    Generate a CSV for the PREVIOUS calendar month's attendance and email it to HR and MD.
    This is a scheduled task that runs on a specific day (e.g., 20th) of the CURRENT month.
    """
    # 1. Calculate the year and month for the PREVIOUS calendar month
    today = date.today()
    first_of_current_month = today.replace(day=1)
    last_day_of_previous_month = first_of_current_month - timedelta(days=1)
    year = last_day_of_previous_month.year
    month = last_day_of_previous_month.month

    print(f"Generating report for: {year}-{month:02d}")

    # 2. Fetch data using the calculated previous month
    rows = fetch_monthly_attendance_all(year, month)
    if not rows:
        print(f"No attendance data for {year}-{month:02d}. Skipping report.")
        return

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["user_email", "action", "event_time", "latitude", "longitude", "location_text"])
    for r in rows:
        writer.writerow([
            r.get("user_email"),
            r.get("action"),
            r.get("event_time").strftime("%Y-%m-%d %H:%M:%S") if r.get("event_time") else "",
            r.get("latitude"),
            r.get("longitude"),
            r.get("location_text"),
        ])
    csv_data = output.getvalue().encode("utf-8")

    msg = EmailMessage()
    msg["Subject"] = f"Monthly Attendance Report {year}-{month:02d}"
    from_email = SMTP_USER
    msg["From"] = from_email
    msg["To"] = HR_EMAIL
    msg["Cc"] = MD_EMAIL
    msg.set_content(f"Attached is the attendance report for {year}-{month:02d}.")
    msg.add_attachment(
        csv_data,
        maintype="text",
        subtype="csv",
        filename=f"attendance_{year}_{month:02d}.csv",
    )

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        print(f"Monthly report for {year}-{month:02d} emailed successfully.")
    except Exception as e:
        print(f"Failed to send monthly report email: {e}")

def reset_monthly_totals():
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE employee_details SET total_working = 0, total_leave = 0")
        conn.commit()
    finally:
        cursor.close()
        conn.close()