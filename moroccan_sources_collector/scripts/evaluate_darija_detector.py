from __future__ import annotations

import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.analysis.darija_detector import detect_darija  # noqa: E402

SAMPLES = ROOT / "data" / "validation" / "darija_detection_samples.csv"


def _compatible(expected: str, predicted: str) -> bool:
    if expected == predicted:
        return True
    if expected == "indeterminee" and predicted in {"indeterminee", "arabe_standard_probable"}:
        return True
    return False


def main() -> None:
    rows = list(csv.DictReader(SAMPLES.open(encoding="utf-8")))
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    by_class: dict[str, list[bool]] = defaultdict(list)
    scores: dict[str, list[int]] = defaultdict(list)
    false_positive = []
    false_negative = []
    for row in rows:
        expected = row["expected_label"]
        result = detect_darija(row["text"])
        predicted = result["Langue_principale"]
        ok = _compatible(expected, predicted)
        confusion[expected][predicted] += 1
        by_class[expected].append(ok)
        scores[expected].append(int(result["Score_darija"]))
        if not ok and expected == "indeterminee":
            false_positive.append((row["text"], predicted, result["Score_darija"]))
        if not ok and expected != "indeterminee":
            false_negative.append((row["text"], expected, predicted, result["Score_darija"]))
    total = len(rows)
    correct = sum(sum(v for pred, v in preds.items() if _compatible(exp, pred)) for exp, preds in confusion.items())
    print(f"Evaluation indicative sur {total} exemples artificiels")
    print(f"Accuracy indicative: {correct / total:.2%}")
    print("\nPrecision indicative par classe attendue:")
    for label, values in sorted(by_class.items()):
        avg = sum(scores[label]) / len(scores[label])
        print(f"- {label}: {sum(values)}/{len(values)} corrects, score moyen {avg:.1f}")
    print("\nMatrice de confusion:")
    for expected, preds in sorted(confusion.items()):
        print(f"- {expected}: {dict(preds)}")
    print("\nFaux positifs:")
    for item in false_positive[:10]:
        print(f"- {item}")
    print("\nFaux negatifs:")
    for item in false_negative[:10]:
        print(f"- {item}")


if __name__ == "__main__":
    main()
