import os, uuid
from datetime import datetime

UPLOAD_ROOT = "uploads"

def save_upload_file(file):
    today = datetime.now().strftime("%Y-%m-%d")
    folder = os.path.join(UPLOAD_ROOT, today)
    os.makedirs(folder, exist_ok=True)

    ext = os.path.splitext(file.filename)[1]
    filename = f"{uuid.uuid4()}{ext}"
    path = os.path.join(folder, filename)

    with open(path, "wb") as f:
        f.write(file.file.read())

    return path
