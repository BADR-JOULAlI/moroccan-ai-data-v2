"""Experimental training entrypoint for a future supervised classifier.

Planned approach:
- manually validated samples only;
- TF-IDF over character n-grams;
- logistic regression;
- labels: darija_arabe, darija_latine, darija_arabizi, arabe_standard, autre.

No data is downloaded and no model is trained by this placeholder.
"""

from __future__ import annotations


def main() -> None:
    print("Experimental only: no supervised model is trained by default.")


if __name__ == "__main__":
    main()
