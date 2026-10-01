import logging
from pathlib import Path

import cv2
import numpy as np

from app.services.ocr_service import OCRService

logger = logging.getLogger(__name__)


class PaddleOCRService(OCRService):
    """PaddleOCR PP-OCRv6 (onnxruntime) con el mismo contrato que OCRService.

    Motor alternativo para pruebas A/B desde la UI (ver VALIDACION_PADDLEOCR.md).
    El modelo se carga perezosamente en el primer uso.
    """

    def __init__(self, lang: str = "es", dpi: int = 300, min_conf: int = 60):
        super().__init__(lang=lang, dpi=dpi, min_conf=min_conf)
        self._engine = None

    def _get_engine(self):
        if self._engine is None:
            from paddleocr import PaddleOCR

            logger.info("paddle_inicializando_modelo")
            self._engine = PaddleOCR(
                lang=self.lang,
                engine="onnxruntime",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        return self._engine

    @staticmethod
    def _unir(result) -> tuple[str, float]:
        textos: list = []
        scores: list = []
        for page in result:
            textos.extend(page.get("rec_texts") or [])
            scores.extend(page.get("rec_scores") or [])
        conf = 100.0 * sum(scores) / len(scores) if scores else 0.0
        return "\n".join(textos).strip(), float(conf)

    def extract_text_from_image(self, file_path: str | Path) -> tuple[str, float]:
        result = self._get_engine().predict(str(file_path))
        return self._unir(result)

    def _ocr_image(self, image: np.ndarray) -> tuple[str, float]:
        rgb = image
        if image.ndim == 3 and image.shape[2] == 3:
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        result = self._get_engine().predict(rgb)
        return self._unir(result)
