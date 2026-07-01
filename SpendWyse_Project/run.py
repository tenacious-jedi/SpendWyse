import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("FLASK_RUN_PORT", "5001"))
    app.run(debug=True, port=port)
