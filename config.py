import os
from datetime import time

#Database Configuration (ensure these are set in your environment or .env file)
DB_NAME = os.getenv("DB_NAME", "zugo_attendance")
DB_USER = os.getenv("DB_USER", "zugoweb")
DB_PASSWORD = os.getenv("DB_PASSWORD", "Zugo@123")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "3306"))


# Office Location for Attendance
OFFICE_LAT = 11.1205615
OFFICE_LON = 77.3396206
OFFICE_RADIUS_METERS = 100

# Attendance Time Constraints (HH:MM format)
CHECKIN_MORNING_START = time(9, 10)    # 09:10 AM
CHECKIN_MORNING_END = time(19, 45)     # 06:45 PM
CHECKIN_AFTERNOON_EXACT = time(13, 30) # 01:30 PM
CHECKOUT_MIN_TIME = time(19, 15)       # 07:15 PM

# Email Configuration
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "zugopvtnetwork@gmail.com")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
HR_EMAIL = os.getenv("HR_EMAIL", "zugopvtnetwork@gmail.com")
MD_EMAIL = os.getenv("MD_EMAIL", "zugoprivitelimited.com")


# --- LOCATION CONFIGURATION ---
OFFICE_LAT = 11.120529  # your office's latitude
OFFICE_LON = 77.3398681 # your office's longitude
OFFICE_RADIUS_METERS = 100  # 100 meters radius for location validation

# Scheduler Settings
LEAVE_MARKING_HOUR = 20  # 8 PM UTC
MONTHLY_REPORT_DAY = 20  # Day of the month to send report

# Attendance Calculation Period (21st to 20th)
ATTENDANCE_PERIOD_START_DAY = 21  # Start calculation from the 21st
ATTENDANCE_PERIOD_END_DAY = 20    # End calculation on the 20th