from flask import Flask, request, render_template, send_file
import os
import uuid
import subprocess

app = Flask(__name__)
UPLOAD_FOLDER = "uploads"
RESULTS_FOLDER = "results"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(RESULTS_FOLDER, exist_ok=True)

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        survey_url = request.form["survey_url"]
        file = request.files["word_file"]

        run_id = str(uuid.uuid4())
        word_path = os.path.join(UPLOAD_FOLDER, f"{run_id}.docx")
        result_path = os.path.join(RESULTS_FOLDER, run_id)

        file.save(word_path)

        os.makedirs(result_path, exist_ok=True)

        # Executa o robô
        subprocess.run([
            "python", "runner.py",
            survey_url,
            result_path
        ])

        return send_file(
            f"{result_path}/report.pdf",
            as_attachment=True
        )

    return render_template("index.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
