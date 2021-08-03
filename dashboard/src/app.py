"""run the app via the built-in web server"""
import os
from t5gweb import create_app
app = create_app()
if __name__ == "__main__":
    if os.environ.get('SVC_PORT') is None:
        SVC_PORT = 8080
    else:
        SVC_PORT = int(os.environ.get('SVC_PORT'))
    #DB_VARIABLES = ['DB_USER','DB_PASSWORD','DB_DATABASE','DB_HOST','MAGIC_WORD']
    #for key in DB_VARIABLES:
    #    if os.environ.get(key) is None:
    #      print("%s is not defined. bailing..." % (key))
    #      quit()
    app.run(debug=True, host="0.0.0.0", port=SVC_PORT)
