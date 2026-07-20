#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chạy TẤT CẢ tests/test_*.py — mỗi file 1 tiến trình con (chúng tự set DB/env riêng
qua HOMESTAY_DB_PATH nên không đụng nhau). Exit 1 nếu bất kỳ file nào fail → dùng
cho CI (GitHub Actions) lẫn chạy tay TỪ GỐC:

    python tests/run_all.py
"""

import glob
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")

    files = sorted(glob.glob(os.path.join(ROOT, "tests", "test_*.py")))
    if not files:
        print("Không tìm thấy file test nào.")
        return 1

    failed = []
    for f in files:
        rel = os.path.relpath(f, ROOT)
        print(f"\n{'=' * 60}\n▶ {rel}\n{'=' * 60}", flush=True)
        r = subprocess.run([sys.executable, f], cwd=ROOT, env=env)
        if r.returncode != 0:
            failed.append(rel)

    print("\n" + "=" * 60)
    print(f"Tổng: {len(files)} file test")
    if failed:
        print(f"❌ FAIL {len(failed)} file:")
        for f in failed:
            print(f"   - {f}")
        return 1
    print("✅ TẤT CẢ FILE TEST PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
