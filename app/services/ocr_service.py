import cv2
import numpy as np
import pytesseract
from PIL import Image
import pdf2image
from pathlib import Path
from typing import Union, Tuple
import logging

logger = logging.getLogger(__name__)


class OCRService:
    def __init__(self, tesseract_cmd: str = "tesseract", lang: str = "spa", dpi: int = 300):
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        self.lang = lang
        self.dpi = dpi
        self.custom_config = r'--oem 3 --psm 6 -c preserve_interword_spaces=1'

    def preprocess_image(self, image: np.ndarray) -> np.ndarray:
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        h, w = gray.shape
        if h < 1000:
            scale = 1000 / h
            gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            h, w = gray.shape

        coords = np.column_stack(np.where(gray > 0))
        if len(coords) > 0:
            angle = cv2.minAreaRect(coords)[-1]
            if angle < -45:
                angle = -(90 + angle)
            else:
                angle = -angle
            if abs(angle) > 0.5:
                M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
                gray = cv2.warpAffine(gray, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

        gray = cv2.fastNlMeansDenoising(gray, h=10)

        binary = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )

        kernel = np.ones((1, 1), np.uint8)
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

        return binary

    def extract_text_from_image(self, file_path: Union[str, Path]) -> Tuple[str, float]:
        image = cv2.imread(str(file_path))
        if image is None:
            raise ValueError(f"No se pudo leer la imagen: {file_path}")

        processed = self.preprocess_image(image)

        data = pytesseract.image_to_data(processed, lang=self.lang, config=self.custom_config, output_type=pytesseract.Output.DICT)
        text = pytesseract.image_to_string(processed, lang=self.lang, config=self.custom_config)

        confidences = [int(c) for c in data['conf'] if int(c) > 0]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0

        return text.strip(), avg_confidence

    def extract_text_from_pdf(self, file_path: Union[str, Path]) -> Tuple[str, float, int]:
        images = pdf2image.convert_from_path(file_path, dpi=self.dpi)
        texts = []
        all_confidences = []

        for i, img in enumerate(images):
            cv_image = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            processed = self.preprocess_image(cv_image)

            data = pytesseract.image_to_data(processed, lang=self.lang, config=self.custom_config, output_type=pytesseract.Output.DICT)
            text = pytesseract.image_to_string(processed, lang=self.lang, config=self.custom_config)

            texts.append(f"--- PÁGINA {i+1} ---\n{text}")

            confidences = [int(c) for c in data['conf'] if int(c) > 0]
            all_confidences.extend(confidences)

        avg_confidence = sum(all_confidences) / len(all_confidences) if all_confidences else 0
        return "\n\n".join(texts), avg_confidence, len(images)

    def extract_text(self, file_path: Union[str, Path]) -> Tuple[str, float, int]:
        path = Path(file_path)
        if path.suffix.lower() == ".pdf":
            text, confidence, pages = self.extract_text_from_pdf(path)
            return text, confidence, pages
        else:
            text, confidence = self.extract_text_from_image(path)
            return text, confidence, 1