from dotenv import load_dotenv
import os
from datetime import time

load_dotenv()


DB_NAME = "zugo_attendance"      # Your MySQL database name
DB_USER = "zugoweb"                 # Your MySQL username
DB_PASSWORD = "Zugo@123"     # Your MySQL password
DB_HOST = "localhost"            # Usually 'localhost'
DB_PORT = 3306                   # Default MySQL port

SECRET_KEY = "your_secret_key_here"

# config.py

#Database Configuration (ensure these are set in your environment or .env file)
DB_NAME = os.getenv("DB_NAME", "zugo_attendance")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")

# Flask Secret Key
#SECRET_KEY = os.getenv("SECRET_KEY", "super_secret_key_change_me")

# Office Location for Attendance
OFFICE_LAT = 11.1205615
OFFICE_LON = 77.3396206
OFFICE_RADIUS_METERS = 100 # meters

# Attendance Time Constraints (HH:MM format)
CHECKIN_MORNING_START = time(9, 30) # 09:30 AM
CHECKIN_MORNING_END = time(19, 45)   # 09:45 AM
CHECKIN_AFTERNOON_EXACT = time(13, 30) # 01:30 PM
CHECKOUT_MIN_TIME = time(19, 15)    # 07:15 PM

# Email Configuration (ensure these are set in your environment or .env file)
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "zugopvtnetwork@gmail.com") # e.g., zugopvtnetwork@gmail.com
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", " ")
HR_EMAIL = os.getenv("HR_EMAIL", "zugopvtnetwork@gmail.com")  
MD_EMAIL = os.getenv("MD_EMAIL", "zugoprivitelimited.com")

# Scheduler Settings
LEAVE_MARKING_HOUR = 20 # 8 PM UTC
MONTHLY_REPORT_DAY = 20 # Day of the month to send report

# Attendance Calculation Period (20th to 20th)
ATTENDANCE_PERIOD_START_DAY = 21 # Start calculation from the 21st of the previous month
ATTENDANCE_PERIOD_END_DAY = 20   # End calculation on the 20th of the current month