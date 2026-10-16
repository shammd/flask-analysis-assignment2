from flask import Flask
from werkzeug.exceptions import HTTPException
from werkzeug.routing import Map, Rule
from werkzeug.wrappers import Request, Response

BODY = "Hello World!"
CONTENT_TYPE = "text/html; charset=utf-8"
BODY_BYTES = BODY.encode("utf-8") # encoede for to carry through network
HEADERS = [("Content-Type", CONTENT_TYPE), ("Content-Length", str(len(BODY_BYTES)))]

# Bare WSGI app (used as the baseline in measurements)
def baseline_application(environ, start_response):
    if environ["PATH_INFO"] == "/hello":
        start_response("200 OK", HEADERS)
        return [BODY_BYTES]
    start_response("404 Not Found", [("Content-Type", "text/plain")])
    return [b"Not Found"]

# Werkzeug only app (using the werkzeug tools, no flask yet)
URLmap = Map([Rule("/hello", endpoint="hello")])
@Request.application
def werkzeug_application(request):
    try:
        URLmap.bind_to_environ(request.environ).match()
    except HTTPException as error:
        return error
    return Response(BODY, mimetype="text/html")

# Flask 3.1.3 (Flask used, internal werkzeug usage)
flask_application = Flask(__name__)
@flask_application.route("/hello")
def hello():
    return BODY

APPS = {
    "bare_wsgi": baseline_application,
    "werkzeug": werkzeug_application,
    "flask": flask_application
}

# main (For equivalency check)
def main():
    from werkzeug.test import Client # only used inside the apps.py main
    print("Check if all apps are equivalent")
    print()
    for path in ("/hello", "/missing"):
        for label, app in APPS.items():
            response = Client(app).get(path)
            print(f"{path:10} {label:12} {response.status:16} "
                  f"{response.headers.get('Content-Type')!s:28} "
                  f"len={response.headers.get('Content-Length')!s:4} "
                  f"{response.get_data(as_text=True)[:20]!r} ")
        print()

if __name__ == "__main__":
    main()