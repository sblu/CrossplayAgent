import io
import numpy as np
from PIL import Image


def capture_screenshot(driver) -> np.ndarray:
    png_bytes = driver.get_screenshot_as_png()
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    return np.array(img)
