from t5gweb.db import SessionLocal  # Import SessionLocal
# dependencies.py - Dependency injection

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()