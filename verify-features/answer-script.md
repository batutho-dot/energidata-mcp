# Independent answer script

- **What it does:** computes the right answers to the 10 questions from raw API rows with the standard library only.
- **How to reach it:** `python eval/answers.py` (downloads once into `eval/data/`, writes `eval/expected.json`).
- **How verify drives it:** step `answers` imports it and recomputes in memory from the cache, writing nothing.
- **End state that proves it worked:** all 10 answers equal the committed `eval/expected.json`.
- **Gotchas:** first run needs the network and waits out 429 answers (about 60 s each).
