from app import app
from database import initialize_database

# Ensure database is initialized before serving
initialize_database()

if __name__ == "__main__":
    app.run()
