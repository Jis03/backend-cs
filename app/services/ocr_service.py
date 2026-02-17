from paddleocr import PaddleOCR
import os

os.environ["DISABLE_MODEL_SOURCE_CHECK"] = "True"

ocr = PaddleOCR(lang="th", use_textline_orientation=True)

def run_ocr(image_path: str):
    result = ocr.ocr(image_path)

    texts = []
    scores = []

    for page in result:
        for i, t in enumerate(page["rec_texts"]):
            texts.append(t)
            scores.append(page["rec_scores"][i])

    return texts, scores
