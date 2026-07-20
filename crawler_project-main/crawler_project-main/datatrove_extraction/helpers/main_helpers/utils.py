from datatrove.data import MediaType
import base64

MIME_TYPES = {
    "pdf": [
        "application/pdf",
        "application/x-pdf",
        "application/acrobat",
        "applications/vnd.pdf",
        "text/pdf",
    ]
}

def filter_non_pdf(data):
    """We changed the logic here to keep the documents that are not pdf and not ending with .pdf
    -> the goal is storing the pdfs for later processing
    -> this is done to avoid the loss of data that is not pdf and not ending with .pdf
    """
    from loguru import logger
    from urllib.parse import urlparse
    import re

    #### used for filtering urls containing /bo/ or bo_ ####
    #url = data.media[0]["url"]

    # Reject URLs containing /bo/ or bo_ (case-insensitive)
    #if re.search(r'/bo/|bo_', url, re.IGNORECASE):
    #    logger.info(f"Filtering {url} because it contains /bo/ or bo_")
    #    return True  # filter it out

    pdf_mime_types = MIME_TYPES["pdf"]
    def is_mime_pdf(data):
        if data.media[0]["metadata"]["content_mime_detected"] in pdf_mime_types or data.media[0]["metadata"]["content_mime_type"] in pdf_mime_types:
            return True
        return False

    if is_mime_pdf(data):
        return False

    # check url too
    parsed_url = urlparse(data.media[0]["url"])
    path = parsed_url.path.lower()
    if path.endswith(".pdf"):
        logger.info(f"Keeping {data.media[0]['url']} because it ends with .pdf, it has mime-type {data.media[0]['metadata']['content_mime_detected']}")
        return False
    return True

def filter_non_html(data):
    """We changed the logic here to keep the documents that are not html and not ending with .html
    -> the goal is storing the htmls for later processing
    -> this is done to avoid the loss of data that is not html and not ending with .html
    """
    from loguru import logger
    from urllib.parse import urlparse

    def is_mime_html(data):
        mime_type = data.media[0]["metadata"]["content_mime_detected"]
        record_type = data.media[0]["record_type"]

        if mime_type is None:
            mime_type = data.media[0]["metadata"]["content_mime_type"]
        if mime_type is not None and (
            mime_type != "text/html"
            and mime_type != "application/xhtml+xml"
            and (record_type != "conversion" or mime_type != "text/plain")
        ):
            return False
        return True

    def decode_html(data):
        import cchardet
        import base64
        charset = "UTF-8"
        content_bytes = data.media[0]["metadata"]["content_bytes"]
        content_bytes = base64.b64decode(content_bytes)
        try:
            html = content_bytes.decode(charset)
            return html
        except UnicodeDecodeError:
            encoding_det = cchardet.detect(content_bytes)["encoding"]
            if not encoding_det or encoding_det == charset:
                return None
            charset = encoding_det

            try:
                html = content_bytes.decode(charset)
                return html
            except (UnicodeDecodeError, LookupError):
                return None
    
    # if is_mime_html(data):
    #     decoded = decode_html(data)
    #     if decoded is None:
    #         logger.warning(f"Cou")
    #     data.text = decode_html(data)
    #     data.media[0]["metadata"]["content_bytes"] = "<content decoded and stored in text field>"
    #     return False
    # return True

    if is_mime_html(data):
        decoded = decode_html(data)
        if decoded is None:
            logger.warning(f"Could not decode HTML for {data.media[0]['url']} — skipping")
            return True  # treat as non-html → skip
        data.text = decoded
        data.media[0]["metadata"]["content_bytes"] = "<content decoded and stored in text field>"
        return False
    return True

def get_content_bytes(data):
    """Get the content bytes from the data"""
    content_bytes_b64 = data.media[0]["metadata"]["content_bytes"]
    content = base64.b64decode(content_bytes_b64) if content_bytes_b64 else b""

    return content if content else b""

def filter_non_pdf_ending_with_pdf(data):
    def is_mime_pdf(data):
        pdf_mime_types = MIME_TYPES["pdf"]
        if data.media[0]["metadata"]["content_mime_detected"] in pdf_mime_types or data.media[0]["metadata"]["content_mime_type"] in pdf_mime_types:
            return True
        return False
    
    return is_mime_pdf(data)

def filter_ocr(data):
    meta = data.media[0]["metadata"] or {}
    return not (
        meta.get("ocr_prob", 0) >= 0.2 or meta.get("garbled_text_ratio", 0) > 0.0
    )

from datatrove.data import Document


def iter_pages(document: Document):
    start = 0
    for media in document.media:
        for offset in media["metadata"].get("page_offsets", []):
            yield document.text[start:offset]
            start = offset

