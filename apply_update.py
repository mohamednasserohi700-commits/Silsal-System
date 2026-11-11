# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════
 سلسل 7 — المثبّت المنفصل للتحديث (Detached Installer)
═══════════════════════════════════════════════════════════════════════
يعمل بعملية مستقلة تماماً عن السيرفر (عند الضغط على «تثبيت الآن وإعادة
التشغيل» من صفحة التحديثات):

   1) ينتظر توقف سيرفر النظام تماماً (يفحص ping محلي حتى 60 ثانية).
   2) يطبّق التحديث: باك أب للنسخة السابقة ← استبدال الملفات بالحزمة
      المُنزّلة — بدون لمس مجلد instance (بيانات العميل) نهائياً.
   3) يعيد فتح البرنامج تلقائياً عبر «تشغيل-سلسل-7.vbs» فيقلع النظام
      بالإصدار الجديد.

كذلك نفس العملية تحدث تلقائياً (بدون هذا الملف) عند إعادة تشغيل عادية:
silsal_desktop.py يستدعي silsal_updater.apply_pending_at_boot() قبل
تشغيل السيرفر — فأي تحديث مُنزّل يُطبَّق بمجرد إعادة فتح البرنامج.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import silsal_updater as up  # noqa: E402


def _server_alive(port, timeout=1.0):
    """هل ما زال سيرفر سلسل يعمل على هذا الجهاز؟ (بدون بروكسي — فحص محلي)"""
    import urllib.request
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(
            f'http://127.0.0.1:{port}/api/desktop/ping',
            headers={'User-Agent': 'SilsalDesktop/7'})
        with opener.open(req, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser(description='سلسل 7 — تطبيق التحديث المعلّق وإعادة التشغيل')
    ap.add_argument('--port', default='7500', help='منفذ سيرفر النظام لانتظار إغلاقه')
    ap.add_argument('--vbs', default='', help='مسار ملف التشغيل لإعادة فتح البرنامج تلقائياً')
    ap.add_argument('--py', default='', help='مسار python لإعادة فتح البرنامج عبر app.py (للنسخ بدون VBS)')
    a = ap.parse_args()

    up._log(f'installer: started (port={a.port})')

    # 1) انتظار توقف السيرفر تماماً
    deadline = time.time() + 60
    while time.time() < deadline:
        if not _server_alive(int(a.port)):
            break
        time.sleep(0.5)
    time.sleep(1.0)  # هامش إغلاق كامل للعملية وتحرير أي مقابض ملفات

    # 2) تطبيق التحديث (باك أب ← استبدال ← حماية instance)
    ok, ver = up.apply_pending_sync()
    up._log(f'installer: apply ok={ok} version={ver}')
    if not ok:
        up._log('installer: التحديث لم يُطبَّق — النسخة الحالية سليمة ويمكن تشغيل البرنامج كالمعتاد')
        return 1

    # 3) إعادة فتح البرنامج تلقائياً
    if a.vbs and os.path.isfile(a.vbs):
        try:
            if os.name == 'nt':
                os.startfile(a.vbs)  # noqa: S606 — ملف تشغيل النظام نفسه
                up._log(f'installer: relaunched via {os.path.basename(a.vbs)}')
            else:
                up._log('installer: relaunch skipped (not windows)')
        except Exception as e:  # noqa: BLE001
            up._log(f'installer: relaunch failed: {e!r}')
    elif a.py and os.name == 'nt' and os.path.isfile(a.py):
        try:
            import subprocess
            flags = 0x00000008 | 0x08000000  # DETACHED_PROCESS | CREATE_NO_WINDOW
            subprocess.Popen([a.py, os.path.join(up.BASE_DIR, 'app.py')], cwd=up.BASE_DIR,
                             creationflags=flags, close_fds=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            up._log('installer: relaunched via python app.py')
        except Exception as e:  # noqa: BLE001
            up._log(f'installer: relaunch via python failed: {e!r}')
    else:
        up._log('installer: ملف التشغيل غير موجود — افتح البرنامج يدوياً')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        import traceback
        try:
            up._log('installer: crash\n' + traceback.format_exc(limit=3))
        except Exception:
            pass
        sys.exit(1)
