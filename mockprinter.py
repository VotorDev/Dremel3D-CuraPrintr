import json
import os
from flask import Flask, flash, request, redirect, url_for
from werkzeug.utils import secure_filename

app = Flask(__name__)


@app.route("/")
def index():
    return "hi"


ALLOWED_EXTENSIONS = {"gcode"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# Shape of a real 3D40 answer to GETPRINTERSTATUS, including its "elaspedtime"
# typo and the trailing space in "filament_type ".
IDLE = {
    "buildPlate_target_temperature": 0,
    "chamber_temperature": 0,
    "door_open": 0,
    "elaspedtime": 0,
    "error_code": 200,
    "extruder_target_temperature": 0,
    "fanSpeed": 0,
    "filament_type ": "PLA",
    "firmware_version": "v1.0_R03.06.06",
    "jobname": "",
    "jobstatus": "ready",
    "layer": 0,
    "message": "success",
    "networkBuild": 1,
    "platform_temperature": 25,
    "progress": 0,
    "remaining": 0,
    "status": "idle",
    "temperature": 25,
    "totalTime": 0,
}

PRINTING = {
    **IDLE,
    "elaspedtime": 249,
    "extruder_target_temperature": 220,
    "jobstatus": "building",
    "layer": 7,
    "platform_temperature": 60,
    "progress": 14,
    "remaining": 1501,
    "status": "busy",
    "temperature": 219,
    "totalTime": 1750,
}

state = {"status": dict(IDLE)}


@app.route("/print_file_uploads", methods=["POST"])
def file():
    if "print_file" not in request.files:
        print("err file not found in post")
        return "err"
    file = request.files["print_file"]
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file.save(os.path.join("./tmp", filename))
        state["status"]["jobname"] = filename
        return "ok saved"


@app.route("/command", methods=["POST"])
def command():
    print(request.form)
    if "GETPRINTERSTATUS" in request.form:
        return json.dumps(state["status"])
    if "PRINT" in request.form:
        # The printer reports the job it was told to print.
        state["status"] = dict(PRINTING, jobname=request.form["PRINT"])
    elif "CANCEL" in request.form:
        state["status"] = dict(IDLE, jobname=request.form["CANCEL"])
    return "ok"


app.run(port=int(os.environ.get("PORT", 5000)))
