"""run the app via the built-in web server"""

import os

from t5gweb import create_app

app = create_app.create_app()
if __name__ == "__main__":
    SVC_PORT = int(os.environ.get("SVC_PORT", 8080))
    app.run(debug=True, host="0.0.0.0", port=SVC_PORT)
