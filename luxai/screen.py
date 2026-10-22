from pathlib import Path
from datetime import datetime
import mss
from PIL import Image
import pytesseract

def capture_screen():
    out = Path.home() / "Pictures" / "LuxAI"
    out.mkdir(parents=True, exist_ok=True)
    path = out / ("screen_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".png")
    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[1])
        Image.frombytes("RGB", shot.size, shot.rgb).save(path)
    return str(path)

def read_screen_text(image_path, tesseract_path=""):
    if tesseract_path:
        pytesseract.pytesseract.tesseract_cmd = tesseract_path
    return pytesseract.image_to_string(Image.open(image_path), lang="eng+rus")
