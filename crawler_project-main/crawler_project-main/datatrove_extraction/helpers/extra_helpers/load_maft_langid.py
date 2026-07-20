# NumPy 2.0 compatibility patch for FastText
import numpy as np
_original_array = np.array
def _patched_array(obj, copy=False, **kwargs):
    if copy is False:
        return np.asarray(obj, **kwargs)
    return _original_array(obj, copy=copy, **kwargs)
np.array = _patched_array

from huggingface_hub import hf_hub_download
from pathlib import Path
import fasttext

def load_maft_langid_model():
    """
    Download (if needed) and load the MAFT LangID FastText model.
    Path is resolved relative to project root.
    """

    # helpers/ -> crawling/ -> project root
    PROJECT_ROOT = Path(__file__).resolve().parents[2]

    MODEL_DIR = PROJECT_ROOT / "models_cache" / "maft_langid"
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    model_file = MODEL_DIR / "model.bin"

    if not model_file.exists():
        hf_hub_download(
            repo_id="Morocco-MTNRA-Labs/MAFT_LangID",
            filename="model.bin",
            local_dir=MODEL_DIR,
        )

    return fasttext.load_model(str(model_file))
