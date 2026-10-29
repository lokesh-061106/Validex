# Validex - evaluation on synthetic data

Generated 2026-10-28T23:33:29 by `scripts/evaluate.py`. All documents are synthetic; these numbers show behaviour on this labelled set and are not a claim about real-world accuracy.

## Tampering indicators (document flagged = medium or high likelihood)

| Set | Precision | Recall | F1 | False-positive rate | TP | FP | FN | TN |
|---|---|---|---|---|---|---|---|---|
| pdf | 1.0 | 1.0 | 1.0 | 0.0 | 20 | 0 | 0 | 20 |
| scan | 1.0 | 0.5 | 0.667 | 0.0 | 10 | 0 | 10 | 20 |
| all | 1.0 | 0.75 | 0.857 | 0.0 | 30 | 0 | 10 | 40 |

| Technique | Detected | Rate |
|---|---|---|
| pdf:metadata | 5/5 | 1.0 |
| pdf:overlay | 5/5 | 1.0 |
| pdf:redact_font | 5/5 | 1.0 |
| pdf:whiteout | 5/5 | 1.0 |
| scan:clone | 5/5 | 1.0 |
| scan:lowq_splice | 0/5 | 0.0 |
| scan:paste | 5/5 | 1.0 |
| scan:paste_low_noise | 0/5 | 0.0 |

Average analysis time: PDF 0.015s, scan 0.828s.

Known limits: low-quality splices and pastes onto heavily compressed, low-noise scans are hard for pixel forensics; such cases rely on QR/source verification instead.

## OCR field extraction

* **pdf** (10 docs, engine `pdf-native`, 0.0s/doc): overall 1.0 — certificate_number 1.0, valid_until_iso 1.0, issue_date_iso 1.0, holder 1.0
* **scan** (4 docs, engine `easyocr`, 15.25s/doc): overall 0.688 — certificate_number 0.0, valid_until_iso 1.0, issue_date_iso 1.0, holder 0.75; identifier within 1 character edit: 1.0

Scanned identifiers are not trusted for exact lookups: a verified signed QR supplies the identifier when present, and an OCR-read identifier with no registry match is routed to manual review, not reported as a mismatch.

## Duplicate images (pHash, threshold 8/64)

* Near-duplicates detected: 15/15 (1.0)
* False matches among distinct images: 0/105 (0.0)

## Source verification status

Accuracy 1.0 (14/14)

| Case | Expected | Got |
|---|---|---|
| genuine DFS/HQ/2024/NOC-98421 | verified | verified |
| altered date DFS/HQ/2024/NOC-98421 | mismatch | mismatch |
| altered holder DFS/HQ/2024/NOC-98421 | mismatch | mismatch |
| genuine DFS/HQ/2022/NOC-44102 | expired | expired |
| altered date DFS/HQ/2022/NOC-44102 | mismatch | mismatch |
| altered holder DFS/HQ/2022/NOC-44102 | mismatch | mismatch |
| genuine DFS/HQ/2023/NOC-61177 | verified | verified |
| altered date DFS/HQ/2023/NOC-61177 | mismatch | mismatch |
| altered holder DFS/HQ/2023/NOC-61177 | mismatch | mismatch |
| unknown certificate | mismatch | mismatch |
| source outage | unavailable | unavailable |
| record not yet digitised | pending | pending |
| signed QR decodes and verifies | valid | valid |
| QR contents vs edited printed date | mismatch | mismatch |
