import base64
import logging
import mimetypes
from typing import Dict, Any
from openai import OpenAI
from ..config import Config

logger = logging.getLogger(__name__)

class MultimodalOCRProcessor:
    """Handles layout-aware structural document parsing using unified multimodal VLMs."""
    def __init__(self):
        Config.validate()
        self.client = OpenAI(base_url=Config.API_BASE_URL, api_key=Config.API_KEY)

    def encode_image_to_base64(self, image_path: str) -> str:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")

    def execute_raw_ocr_analysis(self, image_path: str) -> Dict[str, Any]:
        """Provides spatial text extraction heuristics before parsing structured fields."""
        base64_image = self.encode_image_to_base64(image_path)
        mime_type = mimetypes.guess_type(image_path)[0]
        if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValueError(f"Unsupported image type for OCR: {image_path}")
        prompt = (
            "Analyze this document image layout. Extract all visible text strings natively. "
            "Group spatial text fields by proximity and note checkbox choices."
        )
        try:
            response = self.client.chat.completions.create(
                model="gemini-2.5-flash",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}
                    ]
                }]
            )
            return {"raw_text": response.choices[0].message.content, "status": "SUCCESS"}
        except Exception as e:
            logger.error(f"VLM OCR compilation failed: {str(e)}")
            return {"raw_text": "", "status": f"FAILED: {str(e)}"}
