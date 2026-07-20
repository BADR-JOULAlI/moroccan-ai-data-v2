from transformers import AutoTokenizer
from pathlib import Path

model_cache_path=Path(__file__).parent.parent.parent.parent / "models_cache"

# Download GPT-2 tokenizer to local path
tokenizer_path = model_cache_path / "aragpt2_base_tokenizer"
tokenizer_path.mkdir(parents=True, exist_ok=True)

tokenizer = AutoTokenizer.from_pretrained("aubmindlab/aragpt2-base")
tokenizer.save_pretrained(str(tokenizer_path))