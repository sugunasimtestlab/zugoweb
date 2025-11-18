#!/usr/bin/env python3
"""
Reset Database Script - Drops and recreates the database with fresh schema
"""
import mysql.connector
from config import DB_HOST, DB_USER, DB_PASSWORD, DB_PORT, DB_NAME

def reset_database():
    """Drop the existing database and recreate it with fresh schema."""
    try:
        # Connect without database to drop it
        conn = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            port=DB_PORT
        )
        cursor = conn.cursor()
        
        # Drop database if exists
        print(f"⏳ Dropping database '{DB_NAME}'...")
        cursor.execute(f"DROP DATABASE IF EXISTS `{DB_NAME}`")
        print(f"✅ Database '{DB_NAME}' dropped successfully!")
        
        # Create new database
        print(f"⏳ Creating fresh database '{DB_NAME}'...")
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        print(f"✅ Database '{DB_NAME}' created successfully!")
        
        cursor.close()
        conn.close()
        
        print("\n✅ Database reset complete!")
        print("📝 Next step: Start the app server")
        print("   The app will automatically recreate the schema on startup")
        print("\n💡 Command to start server:")
        print("   cd c:\\Users\\Hey! Zugo\\project\\zugoweb")
        print("   .\\env\\Scripts\\python.exe -m uvicorn app:app --reload")
        
    except mysql.connector.Error as err:
        print(f"❌ Error: {err}")
        return False
    
    return True

if __name__ == "__main__":
    print("=" * 60)
    print("DATABASE RESET SCRIPT")
    print("=" * 60)
    print(f"\nThis will delete all data from database: {DB_NAME}")
    
    confirm = input("\nAre you sure? Type 'YES' to continue: ").strip().upper()
    
    if confirm == "YES":
        reset_database()
    else:
        print("❌ Reset cancelled!")
