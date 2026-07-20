from helpers.docling_code.docling.models.easyocr_model import EasyOcrModel
from helpers.docling_code.docling.models.ocr_mac_model import OcrMacModel
from helpers.docling_code.docling.models.picture_description_api_model import PictureDescriptionApiModel
from helpers.docling_code.docling.models.picture_description_vlm_model import PictureDescriptionVlmModel
from helpers.docling_code.docling.models.rapid_ocr_model import RapidOcrModel
from helpers.docling_code.docling.models.tesseract_ocr_cli_model import TesseractOcrCliModel
from helpers.docling_code.docling.models.tesseract_ocr_model import TesseractOcrModel


def ocr_engines():
    return {
        "ocr_engines": [
            EasyOcrModel,
            OcrMacModel,
            RapidOcrModel,
            TesseractOcrModel,
            TesseractOcrCliModel,
        ]
    }


def picture_description():
    return {
        "picture_description": [
            PictureDescriptionVlmModel,
            PictureDescriptionApiModel,
        ]
    }
