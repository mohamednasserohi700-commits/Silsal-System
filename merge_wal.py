#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
دمج ملفات erp.db-wal داخل erp.db والرجوع لوضع الحفظ العادي (بدون -wal / -shm).

الاستخدام (والتطبيق مقفول تماماً):
    python merge_wal.py                     # يبحث عن erp.db في المجلد الحالي أو instance/
    python merge_wal.py "C:\\path\\to\\instance"

بيعمل:
  1) نسخة أمان من كل الملفات (db + wal + shm) في مجلد wal_safety_copy_<الوقت>
  2) دمج كل التغييرات اللي في -wal جوه ملف .db  (wal_checkpoint TRUNCATE)
  3) الرجوع لوضع journal_mode=DELETE  → ملفات -wal و -shm بتتمسح لوحدها
  4) فحص سلامة القاعدة (integrity_check) وعدّ الجداول
"""
import os
import sys
import shutil
import sqlite3
from datetime import datetime

DB_NAMES = ("erp.db", "license_pool.db", "license_used.db")


def find_folder():
    if len(sys.argv) > 1:
        return os.path.abspath(sys.argv[1])
    here = os.getcwd()
    for cand in (here, os.path.join(here, "instance"),
                 os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance"),
                 os.path.dirname(os.path.abspath(__file__))):
        if os.path.isfile(os.path.join(cand, "erp.db")):
            return cand
    return None


def main():
    folder = find_folder()
    if not folder or not os.path.isfile(os.path.join(folder, "erp.db")):
        print("لم أجد erp.db — مرّر مسار المجلد كمعامل: python merge_wal.py \"المسار\"")
        sys.exit(1)

    print("المجلد:", folder)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safety = os.path.join(folder, "wal_safety_copy_" + stamp)
    os.makedirs(safety, exist_ok=True)

    # 1) نسخة أمان لكل الملفات كما هي
    for name in DB_NAMES:
        for ext in ("", "-wal", "-shm"):
            p = os.path.join(folder, name + ext)
            if os.path.isfile(p):
                shutil.copy2(p, os.path.join(safety, name + ext))
    print("تم عمل نسخة أمان في:", safety)

    ok_all = True
    for name in DB_NAMES:
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        wal = path + "-wal"
        wal_size = os.path.getsize(wal) if os.path.isfile(wal) else 0
        print("\n== %s  (حجم -wal قبل الدمج: %.1f KB)" % (name, wal_size / 1024))
        try:
            con = sqlite3.connect(path, timeout=30)
            # 2) دمج كل ما في WAL داخل الملف الرئيسي
            busy, log_frames, ckpt = con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            print("   دمج الـ WAL:", "تم" if not busy else "لم يكتمل")
            if busy:
                print("   !! فيه برنامج تاني فاتح القاعدة — اقفل السيستم تماماً وشغّل السكريبت تاني")
                ok_all = False
            # 3) الرجوع لوضع DELETE
            mode = con.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
            print("   journal_mode الآن:", mode)
            # 4) فحص السلامة
            integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
            tables = con.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
            print("   integrity_check:", integrity, "| عدد الجداول:", tables)
            if name == "erp.db":
                for t in ("sale", "purchase", "product", "customer", "supplier"):
                    try:
                        n = con.execute("SELECT count(*) FROM %s" % t).fetchone()[0]
                        print("   %-10s %s صف" % (t, n))
                    except sqlite3.Error:
                        pass
            con.close()
            if integrity != "ok" or mode.lower() != "delete":
                ok_all = False
        except Exception as e:
            print("   !! خطأ:", e)
            ok_all = False

    print("\nالملفات المتبقية:")
    for f in sorted(os.listdir(folder)):
        p = os.path.join(folder, f)
        if os.path.isfile(p):
            print("   %-24s %8.1f KB" % (f, os.path.getsize(p) / 1024))

    print("\n" + ("تم بنجاح ✔ — شغّل السيستم." if ok_all else "فيه ملاحظات فوق ⚠ — راجعها قبل تشغيل السيستم."))


if __name__ == "__main__":
    main()
