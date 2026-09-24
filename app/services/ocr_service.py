import cv2
import numpy as np
import pytesseract
from PIL import Image
import pdf2image
from pathlib import Path
from typing import Union, Tuple, Optional, List
import logging

logger = logging.getLogger(__name__)


class OCRService:
    def __init__(
        self,
        tesseract_cmd: str = "tesseract",
        lang: str = "spa+eng",
        dpi: int = 300,
        min_conf: int = 60,
    ):
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        self.lang = lang
        self.dpi = dpi
        self.min_conf = min_conf
        self.config_psm4 = r'--oem 3 --psm 4 -c preserve_interword_spaces=1'
        self.config_psm6 = r'--oem 3 --psm 6 -c preserve_interword_spaces=1'

    def preprocess_image(self, image: np.ndarray, variant: int = 1) -> np.ndarray:
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        h, w = gray.shape
        if h < 1000:
            scale = 1000 / h
            gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            h, w = gray.shape

        # Deskew sobre contenido (no sobre fondo blanco)
        thr = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
        coords = np.column_stack(np.where(thr > 0))
        if len(coords) > 50:
            angle = cv2.minAreaRect(coords)[-1]
            if angle < -45:
                angle = -(90 + angle)
            else:
                angle = -angle
            if abs(angle) > 0.5 and abs(angle) < 15:
                M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
                gray = cv2.warpAffine(
                    gray, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
                )

        if variant == 1:
            # CLAHE + Otsu: robusto a sombra/flash de foto móvil
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            gray = clahe.apply(gray)
            binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        else:
            # Variante 2: denoise + umbral adaptativo (comprobantes claros)
            gray = cv2.fastNlMeansDenoising(gray, h=7)
            binary = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10
            )

        return binary

    @staticmethod
    def _data_to_text(data: dict) -> str:
        lines: dict = {}
        order: List[tuple] = []
        for i, word in enumerate(data.get("text", [])):
            if not str(word).strip():
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            if key not in lines:
                lines[key] = []
                order.append(key)
            lines[key].append(str(word))
        return "\n".join(" ".join(lines[k]) for k in sorted(order))

    def _run_ocr(self, processed: np.ndarray, config: str) -> Tuple[str, float]:
        data = pytesseract.image_to_data(
            processed, lang=self.lang, config=config, output_type=pytesseract.Output.DICT
        )
        text = self._data_to_text(data)
        confidences = [int(c) for c in data["conf"] if str(c).lstrip("-").isdigit() and int(c) > 0]
        avg = sum(confidences) / len(confidences) if confidences else 0.0
        return text.strip(), float(avg)

    def _ocr_image(self, image: np.ndarray) -> Tuple[str, float]:
        # Intento 1: CLAHE+Otsu + psm 4
        p1, c1 = self._run_ocr(self.preprocess_image(image, variant=1), self.config_psm4)
        if c1 >= self.min_conf:
            return p1, c1

        # Retry: adaptativo + psm 6 si la confianza es baja
        p2, c2 = self._run_ocr(self.preprocess_image(image, variant=2), self.config_psm6)
        if c2 > c1:
            return p2, c2
        return p1, c1

    def _pdf_text_layer(self, path: Path) -> Optional[Tuple[str, float, int]]:
        """PDF con capa de texto: extrae sin rasterizar (confianza 100)."""
        try:
            from pypdf import PdfReader
        except ImportError:
            return None
        try:
            reader = PdfReader(str(path))
            texts = []
            for i, page in enumerate(reader.pages):
                t = page.extract_text() or ""
                texts.append(f"--- PÁGINA {i + 1} ---\n{t}")
            body = "\n".join(t for t in (page.extract_text() or "" for page in reader.pages))
            if len(body.strip()) >= 40:
                return "\n\n".join(texts).strip(), 100.0, len(reader.pages)
        except Exception as e:
            logger.warning("pdf_text_layer_failed: %s", e)
        return None

    def extract_text_from_image(self, file_path: Union[str, Path]) -> Tuple[str, float]:
        image = cv2.imread(str(file_path))
        if image is None:
            raise ValueError(f"No se pudo leer la imagen: {file_path}")
        return self._ocr_image(image)

    def extract_text_from_pdf(self, file_path: Union[str, Path]) -> Tuple[str, float, int]:
        layer = self._pdf_text_layer(Path(file_path))
        if layer:
            logger.info("pdf_con_capa_de_texto: %s", file_path)
            return layer

        images = pdf2image.convert_from_path(str(file_path), dpi=self.dpi)
        texts = []
        all_confidences = []

        for i, img in enumerate(images):
            cv_image = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            text, conf = self._ocr_image(cv_image)
            texts.append(f"--- PÁGINA {i + 1} ---\n{text}")
            if conf > 0:
                all_confidences.append(conf)

        avg_confidence = sum(all_confidences) / len(all_confidences) if all_confidences else 0.0
        return "\n\n".join(texts), avg_confidence, len(images)

    def extract_text(self, file_path: Union[str, Path]) -> Tuple[str, float, int]:
        path = Path(file_path)
        if path.suffix.lower() == ".pdf":
            return self.extract_text_from_pdf(path)
        text, confidence = self.extract_text_from_image(path)
        return text, confidence, 1
