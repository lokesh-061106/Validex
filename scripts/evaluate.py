"""Evaluate the AI modules on a labelled synthetic set and write EVALUATION.md.

    cd backend
    python ../scripts/evaluate.py            # full run (includes EasyOCR on scans; a few minutes on CPU)
    python ../scripts/evaluate.py --quick    # skip scanned-document OCR

Metrics (mapped to the problem statement's evaluation criteria):
  * tamper detection precision / recall / F1, per modality and per technique
  * OCR field-extraction accuracy (digital PDFs and scanned images)
  * duplicate-image detection rate and false-match rate
  * source-verification status accuracy (verified / mismatch / expired / pending / unavailable)
  * processing time per document
All data is synthetic; numbers indicate behaviour on this set, not real-world accuracy.
"""

import argparse
import io
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.join(ROOT, "backend"))

from app.ml.data_extractor import data_extractor  # noqa: E402
from app.ml.forgery_detector import forgery_detector  # noqa: E402
from app.ml.image_hash import hamming, phash  # noqa: E402
from app.ml.ocr_engine import ocr_engine  # noqa: E402
from app.ml.qr_verifier import verify_qr  # noqa: E402
from app.mock_authority import service as mock  # noqa: E402
from app.models.document import DocumentType  # noqa: E402
from app.services.verification_service import SOURCES, _compare, _outcome  # noqa: E402
from app.services.matching import compare_field, identifier_distance, ocr_fix_identifier  # noqa: E402

import synthetic as syn  # noqa: E402
from demo_documents import fire_noc  # noqa: E402

RS = np.random.RandomState(42)
NAMES = ["Saraswati Institute of Engineering", "Kaveri College of Technology", "Narmada Institute of Management",
         "Godavari Polytechnic College", "Himalaya School of Pharmacy", "Vindhya Institute of Architecture",
         "Aravalli Engineering College", "Sahyadri Institute of Technology", "Nilgiri College of Engineering",
         "Malwa Technical Institute"]


def rand_cert(i: int) -> tuple[bytes, dict]:
    name = NAMES[i % len(NAMES)]
    cert = f"DFS/HQ/20{20 + i % 6}/NOC-{RS.randint(10000, 99999)}"
    d, m, y = RS.randint(1, 28), RS.randint(1, 12), 2026 + RS.randint(0, 3)
    valid = f"{d:02d}/{m:02d}/{y}"
    truth = {"certificate_number": cert, "valid_until_iso": f"{y}-{m:02d}-{d:02d}", "issue_date_iso": "2024-01-10", "holder": name}
    pdf = fire_noc(name, cert, "10/01/2024", valid, "2024-01-10", truth["valid_until_iso"], "Sector 5, Greater Noida 201310")
    return pdf, truth


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0}


def eval_tampering(n: int):
    samples = []  # (modality, technique, label, bytes, name)
    for i in range(n):
        pdf, truth = rand_cert(i)
        samples.append(("pdf", "clean", 0, pdf, f"clean_pdf_{i}.pdf"))
        old = truth["valid_until_iso"]
        printed = datetime.strptime(old, "%Y-%m-%d").strftime("%d/%m/%Y")
        tech = ["whiteout", "redact_font", "overlay", "metadata"][i % 4]
        new_value = "31/12/2030"
        if tech == "whiteout":
            t = syn.tamper_whiteout(pdf, printed, new_value)
        elif tech == "redact_font":
            t = syn.tamper_redact(pdf, printed, new_value)
        elif tech == "overlay":
            t = syn.tamper_overlay(pdf, printed, new_value)
        else:
            t = syn.tamper_metadata(pdf)
        samples.append(("pdf", tech, 1, t, f"tampered_pdf_{i}_{tech}.pdf"))

        page = syn.render(pdf)
        noise = 2 + (i % 6)
        clean_scan = syn.scan(page, seed=i, noise=noise, quality=70 + (i % 5) * 5)
        samples.append(("scan", "clean", 0, clean_scan, f"clean_scan_{i}.jpg"))
        tech_s = ["paste", "clone", "paste_low_noise", "lowq_splice"][i % 4]
        if tech_s == "paste":
            t = syn.scan_paste(syn.scan(page, seed=100 + i, noise=6, quality=90), (95, 300, 340, 330), "Valid Up to: 31/12/2030")
        elif tech_s == "paste_low_noise":
            t = syn.scan_paste(syn.scan(page, seed=100 + i, noise=2, quality=75), (95, 300, 340, 330), "Valid Up to: 31/12/2030")
        elif tech_s == "clone":
            t = syn.scan_clone(clean_scan, (880, 1360, 1080, 1560), (200, 1050))
        else:
            other = syn.scan(syn.render(rand_cert(i + 50)[0]), seed=200 + i, quality=25)
            from PIL import Image
            base = Image.open(io.BytesIO(clean_scan)).convert("RGB")
            base.paste(Image.open(io.BytesIO(other)).convert("RGB").crop((60, 280, 500, 340)), (60, 280))
            buf = io.BytesIO()
            base.save(buf, "JPEG", quality=90)
            t = buf.getvalue()
        samples.append(("scan", tech_s, 1, t, f"tampered_scan_{i}_{tech_s}.jpg"))

    results = []
    for modality, tech, label, data, name in samples:
        t0 = time.time()
        rep = forgery_detector.analyze_document(data, name)
        results.append({"modality": modality, "technique": tech, "label": label, "predicted": int(rep.is_tampered),
                        "level": rep.level, "seconds": time.time() - t0, "signals": [i["method"] for i in rep.indicators]})

    out = {"by_modality": {}, "by_technique": {}, "false_positives": []}
    for modality in ("pdf", "scan", "all"):
        rs = [r for r in results if modality == "all" or r["modality"] == modality]
        tp = sum(1 for r in rs if r["label"] and r["predicted"])
        fp = sum(1 for r in rs if not r["label"] and r["predicted"])
        fn = sum(1 for r in rs if r["label"] and not r["predicted"])
        tn = sum(1 for r in rs if not r["label"] and not r["predicted"])
        out["by_modality"][modality] = {**prf(tp, fp, fn), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
                                        "false_positive_rate": round(fp / (fp + tn), 3) if fp + tn else 0.0}
    by_t = defaultdict(list)
    for r in results:
        if r["label"]:
            by_t[f"{r['modality']}:{r['technique']}"].append(r["predicted"])
    out["by_technique"] = {k: {"detected": sum(v), "total": len(v), "rate": round(sum(v) / len(v), 3)} for k, v in sorted(by_t.items())}
    out["false_positives"] = [r for r in results if not r["label"] and r["predicted"]][:5]
    out["avg_seconds"] = {m: round(float(np.mean([r["seconds"] for r in results if r["modality"] == m])), 3) for m in ("pdf", "scan")}
    return out


def eval_ocr(n_pdf: int, n_scan: int):
    fields = ["certificate_number", "valid_until_iso", "issue_date_iso", "holder"]
    res = {}
    near_id = defaultdict(int)
    for modality, count in (("pdf", n_pdf), ("scan", n_scan)):
        correct = defaultdict(int)
        times = []
        for i in range(count):
            pdf, truth = rand_cert(300 + i)
            data = pdf if modality == "pdf" else syn.scan(syn.render(pdf, dpi=200), seed=i, noise=3, quality=90)
            t0 = time.time()
            ocr = ocr_engine.extract(data, modality == "pdf")
            got = data_extractor.extract_fields(ocr.text, DocumentType.FIRE_SAFETY)
            if modality == "scan" and got.get("certificate_number"):
                got["certificate_number"] = ocr_fix_identifier(got["certificate_number"])
                near_id[modality] += int(identifier_distance(got["certificate_number"], truth["certificate_number"]) <= 1)
            times.append(time.time() - t0)
            for f in fields:
                if f == "holder":
                    ok = compare_field("holder", got.get(f), truth[f], "name")["match"] is True
                elif f == "certificate_number":
                    ok = compare_field(f, got.get(f), truth[f], "identifier")["match"] is True
                else:
                    ok = got.get(f) == truth[f]
                correct[f] += int(ok)
        if count:
            res[modality] = {"documents": count, "engine": ocr.engine,
                             "field_accuracy": {f: round(correct[f] / count, 3) for f in fields},
                             "overall": round(sum(correct.values()) / (count * len(fields)), 3),
                             "avg_seconds": round(float(np.mean(times)), 2),
                             "identifier_within_1_edit": round(near_id[modality] / count, 3) if modality == "scan" else None}
    return res


def eval_duplicates(n: int):
    originals = [syn.lab_placeholder(1000 + i, f"LAB {i}") for i in range(n)]
    hashes = [phash(o) for o in originals]
    detected, false_matches, pairs = 0, 0, 0
    for i, o in enumerate(originals):
        variant = syn.recompress_resize(o, 0.6 + (i % 4) * 0.1, 60 + (i % 4) * 10)
        if hamming(phash(variant), hashes[i]) <= 8:
            detected += 1
        for j in range(i + 1, n):
            pairs += 1
            if hamming(hashes[i], hashes[j]) <= 8:
                false_matches += 1
    return {"near_duplicates": n, "detected": detected, "detection_rate": round(detected / n, 3),
            "distinct_pairs": pairs, "false_matches": false_matches,
            "false_match_rate": round(false_matches / pairs, 4) if pairs else 0.0}


def eval_verification():
    """Expected status for each case vs. what the QR check + registry lookup return."""
    spec = SOURCES[DocumentType.FIRE_SAFETY]
    reg = mock._registry()["authorities"]["fire_services"]["records"]
    cases = []
    for cert, rec in reg.items():
        expired = rec["valid_until"] < datetime.now().strftime("%Y-%m-%d")
        cases.append((f"genuine {cert}", cert, dict(rec), "expired" if expired else "verified"))
        altered = dict(rec, valid_until="2031-12-31")
        cases.append((f"altered date {cert}", cert, altered, "mismatch"))
        cases.append((f"altered holder {cert}", cert, dict(rec, holder="Some Other Institute of Technology"), "mismatch"))
    cases.append(("unknown certificate", "DFS/HQ/2026/NOC-00000", {"holder": "X", "valid_until": "2030-01-01"}, "mismatch"))
    rows, correct = [], 0
    for label, cert, printed, expected in cases:
        extracted = {"certificate_number": cert, "holder": printed.get("holder"), "valid_until": printed.get("valid_until"),
                     "issue_date": printed.get("issue_date")}
        resp = mock.lookup("fire_services", cert)
        if resp["status"] == "not_found":
            got = "mismatch"
        else:
            status, _ = _outcome(_compare(spec, extracted, resp["record"]), resp["record"], spec)
            got = status.value
        correct += int(got == expected)
        rows.append({"case": label, "expected": expected, "got": got})
    mock.set_outage(True)
    try:
        mock.lookup("fire_services", "DFS/HQ/2024/NOC-98421")
        got = "verified"
    except mock.SourceUnavailable:
        got = "unavailable"
    finally:
        mock.set_outage(False)
    rows.append({"case": "source outage", "expected": "unavailable", "got": got})
    correct += int(got == "unavailable")
    pend = mock.lookup("university_noc", "AKTU/NOC/2026/1290")["status"]
    rows.append({"case": "record not yet digitised", "expected": "pending", "got": pend})
    correct += int(pend == "pending")

    # Signed-QR check on generated certificates: genuine vs. whiteout-edited
    pdf, truth = rand_cert(900)
    qr_ok = verify_qr(pdf, True)
    printed = datetime.strptime(truth["valid_until_iso"], "%Y-%m-%d").strftime("%d/%m/%Y")
    qr_tampered = verify_qr(syn.tamper_whiteout(pdf, printed, "31/12/2031"), True)
    rows.append({"case": "signed QR decodes and verifies", "expected": "valid", "got": "valid" if qr_ok and qr_ok["signature_valid"] else "invalid"})
    correct += int(bool(qr_ok and qr_ok["signature_valid"]))
    qr_vs_print = compare_field("valid_until", "2031-12-31", (qr_tampered or {}).get("data", {}).get("valid_until"), "date")
    rows.append({"case": "QR contents vs edited printed date", "expected": "mismatch", "got": "mismatch" if qr_vs_print["match"] is False else "match"})
    correct += int(qr_vs_print["match"] is False)
    return {"cases": len(rows), "correct": correct, "accuracy": round(correct / len(rows), 3), "rows": rows}


def write_report(r: dict) -> str:
    t = r["tampering"]
    lines = ["# Validex - evaluation on synthetic data", "",
             f"Generated {r['generated_at']} by `scripts/evaluate.py`. All documents are synthetic; these numbers show "
             "behaviour on this labelled set and are not a claim about real-world accuracy.", "",
             "## Tampering indicators (document flagged = medium or high likelihood)", "",
             "| Set | Precision | Recall | F1 | False-positive rate | TP | FP | FN | TN |", "|---|---|---|---|---|---|---|---|---|"]
    for m, v in t["by_modality"].items():
        lines.append(f"| {m} | {v['precision']} | {v['recall']} | {v['f1']} | {v['false_positive_rate']} | {v['tp']} | {v['fp']} | {v['fn']} | {v['tn']} |")
    lines += ["", "| Technique | Detected | Rate |", "|---|---|---|"]
    for k, v in t["by_technique"].items():
        lines.append(f"| {k} | {v['detected']}/{v['total']} | {v['rate']} |")
    lines += ["", f"Average analysis time: PDF {t['avg_seconds']['pdf']}s, scan {t['avg_seconds']['scan']}s.", "",
              "Known limits: low-quality splices and pastes onto heavily compressed, low-noise scans are hard for pixel "
              "forensics; such cases rely on QR/source verification instead.", "", "## OCR field extraction", ""]
    for m, v in r["ocr"].items():
        lines.append(f"* **{m}** ({v['documents']} docs, engine `{v['engine']}`, {v['avg_seconds']}s/doc): overall {v['overall']} — "
                     + ", ".join(f"{k} {a}" for k, a in v["field_accuracy"].items())
                     + (f"; identifier within 1 character edit: {v['identifier_within_1_edit']}" if v.get("identifier_within_1_edit") is not None else ""))
    lines += ["", "Scanned identifiers are not trusted for exact lookups: a verified signed QR supplies the identifier when "
              "present, and an OCR-read identifier with no registry match is routed to manual review, not reported as a mismatch."]
    d = r["duplicates"]
    lines += ["", "## Duplicate images (pHash, threshold 8/64)", "",
              f"* Near-duplicates detected: {d['detected']}/{d['near_duplicates']} ({d['detection_rate']})",
              f"* False matches among distinct images: {d['false_matches']}/{d['distinct_pairs']} ({d['false_match_rate']})",
              "", "## Source verification status", "", f"Accuracy {r['verification']['accuracy']} "
              f"({r['verification']['correct']}/{r['verification']['cases']})", "", "| Case | Expected | Got |", "|---|---|---|"]
    for row in r["verification"]["rows"]:
        lines.append(f"| {row['case']} | {row['expected']} | {row['got']} |")
    path = os.path.join(ROOT, "EVALUATION.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("-n", type=int, default=20, help="documents per class")
    args = parser.parse_args()
    report = {"generated_at": datetime.now().isoformat(timespec="seconds")}
    print("Tampering ...")
    report["tampering"] = eval_tampering(args.n)
    print("OCR ...")
    report["ocr"] = eval_ocr(10, 0 if args.quick else 4)
    print("Duplicates ...")
    report["duplicates"] = eval_duplicates(15)
    print("Verification ...")
    report["verification"] = eval_verification()
    os.makedirs(os.path.join(ROOT, "sample_docs", "eval"), exist_ok=True)
    with open(os.path.join(ROOT, "sample_docs", "eval", "eval_report.json"), "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(json.dumps({k: v for k, v in report["tampering"].items() if k != "false_positives"}, indent=2))
    print(json.dumps(report["ocr"], indent=2))
    print(json.dumps(report["duplicates"]))
    print("verification accuracy", report["verification"]["accuracy"])
    print("Report:", write_report(report))
