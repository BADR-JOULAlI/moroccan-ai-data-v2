import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

LLM_ENDPOINT = os.getenv("LLM_ENDPOINT", "http://localhost:8000/v1/chat/completions")
MODEL_NAME = os.getenv("MODEL_NAME", "")
MAX_CONTEXT = int(os.getenv("MAX_CONTEXT", "8192"))
PROMPT_OVERHEAD_TOKENS = int(os.getenv("PROMPT_OVERHEAD_TOKENS", "300"))
SAFETY_MARGIN = int(os.getenv("SAFETY_MARGIN", "100"))

# Max characters per chunk — ensures input ≤ half context window
MAX_CHUNK_TOKENS = (MAX_CONTEXT // 2) - PROMPT_OVERHEAD_TOKENS - SAFETY_MARGIN
MAX_CHUNK_CHARS = MAX_CHUNK_TOKENS * 2


def correct_chunk(text: str) -> str:
    prompt = f"""أنت نظام متخصص في تصحيح أخطاء التعرف الضوئي على الحروف (OCR) في النصوص العربية الفصحى.
هذه النصوص تتعلق بمحتوى عربي متنوع، وقد تشمل خطابات رسمية، ونصوصاً إدارية، ومقالات، ووثائق قانونية.

قواعد صارمة:
1. صحح فقط الكلمات المشوهة بسبب OCR، بالاستناد إلى السياق والمعنى.
2. إذا ظهر تكرار غير منطقي لنفس العبارة، احذف التكرارات وأبقِ على نسخة واحدة فقط.
3. لا تضف جملاً جديدة ولا تلخص النص.
4. حافظ على نفس عدد الفقرات تقريباً.
5. أخرج النص المصحح فقط بدون أي تعليق.

النص:
{text}

النص المصحح:"""

    # Output budget = whatever is left after input
    estimated_input_tokens = len(prompt) // 3
    max_output_tokens = MAX_CONTEXT - estimated_input_tokens - SAFETY_MARGIN
    max_output_tokens = max(256, min(max_output_tokens, MAX_CONTEXT // 2))

    response = requests.post(
        LLM_ENDPOINT,
        json={
            "model": MODEL_NAME,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": max_output_tokens,
        },
        timeout=300,
    )
    response.raise_for_status()
    result = response.json()
    return result["choices"][0]["message"]["content"].strip()


def split_into_chunks(text: str, chunk_size: int) -> list[str]:
    """Split text on paragraph boundaries to avoid cutting mid-sentence."""
    chunks = []
    current_chunk = []
    current_size = 0

    for paragraph in text.split("\n"):
        para_size = len(paragraph) + 1  # +1 for the newline
        if current_size + para_size > chunk_size and current_chunk:
            chunks.append("\n".join(current_chunk))
            current_chunk = [paragraph]
            current_size = para_size
        else:
            current_chunk.append(paragraph)
            current_size += para_size

    if current_chunk:
        chunks.append("\n".join(current_chunk))

    return chunks


def correct_ocr_with_gemma(doc):
    text = doc.text or ""

    if len(text.strip()) < 20:
        return True

    try:
        if len(text) <= MAX_CHUNK_CHARS:
            # Short doc — fits in one call
            doc.text = correct_chunk(text)
        else:
            # Long doc — split into chunks, correct each, rejoin
            chunks = split_into_chunks(text, MAX_CHUNK_CHARS)
            corrected_chunks = [correct_chunk(chunk) for chunk in chunks]
            doc.text = "\n\n".join(corrected_chunks)
    except Exception as e:
        print(f"[ocr_correction] Failed for doc {doc.id}: {e}")

    return True