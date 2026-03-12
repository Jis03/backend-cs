import os
import uuid
import hashlib
from datetime import datetime


UPLOAD_ROOT = "uploads"


def prepare_upload_file(file):
    content = file.file.read()

    if not content:
        raise ValueError("empty file")

    file_hash = hashlib.sha256(content).hexdigest()

    ext = os.path.splitext(file.filename or "")[1]
    return content, file_hash, ext


def save_file_content(content: bytes, ext: str = ""):
    today = datetime.now().strftime("%Y-%m-%d")
    folder = os.path.join(UPLOAD_ROOT, today)
    os.makedirs(folder, exist_ok=True)

    filename = f"{uuid.uuid4()}{ext}"
    path = os.path.join(folder, filename)

    with open(path, "wb") as f:
        f.write(content)

    return path