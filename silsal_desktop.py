# -*- coding: utf-8 -*-
"""
════════════════════════════════════════════════════════════════════
 سلسل 7 — مشغّل نسخة الديسك توب (نافذة مستقلة عن المتصفح)
════════════════════════════════════════════════════════════════════
• يفتح النظام في نافذة برامج مستقلة شكلها شكل أي برنامج ديسك توب
  (بدون شريط عنوان المتصفح وبدون التبويبات) عبر WebView2،
  وبحجم تلقائي 85% من شاشة الجهاز — يناسب كل المقاسات تلقائياً
  حتى مع تكبير خطوط ويندوز (DPI Scaling).
• بدون شاشة DOS سوداء: شغّله من أيقونة «تشغيل-سلسل-7.vbs»
  (تعمل بـ pythonw = لا تظهر أي نافذة أوامر إطلاقاً).
• لا يفشل بصمت: أي خطأ غير متوقع يظهر في رسالة واضحة على الشاشة
  (مربع رسالة ويندوز يعمل حتى بدون أي مكتبات واجهة)، مع تسجيل
  التفاصيل الكاملة في instance/desktop.log.
• محمية: أدوات المطور (Inspect / F12) والقائمة اليمنى مُعطّلة داخل
  نافذة البرنامج، ووضع التصحيح مُغلق تماماً.
• عند إغلاق النافذة (X) يقرأ «سلوك الإغلاق» من إعدادات النظام:
    - exit       : إغلاق نهائي — يُوقف السيرفر وكل العمليات بالكامل.
    - background : السيرفر يستمر بالخلفية لخدمة باقي الأجهزة
                   (كاشير / موبايل / متصفحات)، ويُوقف نهائياً من
                   ملف «إيقاف-سيرفر-سلسل» أو بإغلاق النافذة وهو
                   على وضع «إغلاق نهائي».
• لو السيرفر شغّال بالفعل (من تشغيلة سابقة بالخلفية) لا يُشغَّل
  ثانية — تُفتح نافذة جديدة تتصل بنفس السيرفر مباشرة.
• لو كان السيرفر في طور الاقلاع من تشغيلة أخرى ينتظر حتى يجهز
  بدل فشل فوري (حل مشكلة النقر المزدوج على الأيقونة).
• فحوصات الاتصال المحلية تتجاهل البروكسي تماماً (مهم للأجهزة التي
  تستخدم برامج VPN/Proxy) حتى لا تُفشل فحوصات 127.0.0.1.
• لو كانت مكتبات النظام ناقصة يحاول تثبيتها تلقائياً بمريء قبل
  إظهار أي رسالة خطأ.
• للتشخيص بشاشة ظاهرة: شغّل «فحص-وتشخيص-سلسل.vbs» أو اضبط
  متغير البيئة SILSAL_VERBOSE=1.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

APP_TITLE = 'Silsal 7 — نظام سلسل لإدارة الأعمال والمحاسبة'
PORT = int(os.environ.get('PORT', '7500'))
BASE = f'http://127.0.0.1:{PORT}'
URL = BASE + '/'
UA = 'SilsalDesktop/7'
ROOT = os.path.dirname(os.path.abspath(__file__))
CREATE_NO_WINDOW = 0x08000000 if os.name == 'nt' else 0
VERBOSE = os.environ.get('SILSAL_VERBOSE', '') in ('1', 'true', 'yes', 'on')

# لا تستخدم أي بروكسي أبداً في فحوصات 127.0.0.1
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

_server_error: list[Exception] = []


def _log(msg: str) -> None:
    """سجل بسيط في instance/desktop.log للمتابعة عند الحاجة."""
    try:
        log_dir = os.path.join(ROOT, 'instance')
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, 'desktop.log'), 'a', encoding='utf-8') as f:
            f.write(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] {msg}\n')
    except Exception:
        pass
    if VERBOSE:
        try:
            print(msg, flush=True)
        except Exception:
            pass


def _fatal(title: str, msg: str) -> None:
    """رسالة خطأ ظاهرة على الشاشة — تعمل تحت pythonw بدون أي مكتبات."""
    try:
        import traceback
        _log(f'FATAL | {title} | {msg}')
    except Exception:
        pass
    full = (
        f'{msg}\n'
        '──────────────────────────\n'
        'لمعرفة التفاصيل: شغّل ملف «فحص-وتشخيص-سلسل.vbs»\n'
        'أو راجع ملف السجل: instance\\desktop.log'
    )
    try:
        if os.name == 'nt':
            import ctypes
            # MB_ICONERROR (0x10) | MB_SYSTEMMODAL (0x1000) | MB_TOPMOST (0x40000)
            ctypes.windll.user32.MessageBoxW(0, full, title, 0x10 | 0x1000 | 0x40000)
    except Exception as e:  # حتى لا نفشل بصمت أبداً
        _log(f'messagebox failed: {e!r}')


def _request(path: str, timeout: float = 1.5, method: str = 'GET'):
    req = urllib.request.Request(BASE + path, method=method, headers={'User-Agent': UA})
    with _OPENER.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def server_alive(timeout: float = 1.0) -> bool:
    """هل يوجد سيرفر سلسل يعمل حالياً على هذا الجهاز؟"""
    try:
        return bool(_request('/api/desktop/ping', timeout=timeout).get('ok'))
    except Exception:
        return False


def _import_app():
    from app import app, init_db  # noqa: E402
    return app, init_db


def _import_app_with_recovery():
    """استيراد النظام — ولو كانت المكتبات ناقصة يثبّتها تلقائياً ثم يعيد المحاولة."""
    try:
        return _import_app()
    except Exception as e:
        _log(f'app import failed: {e!r} — attempting automatic requirements install')
        try:
            req = os.path.join(ROOT, 'requirements.txt')
            if os.path.isfile(req):
                subprocess.run(
                    [sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check',
                     '--quiet', '-r', req],
                    check=False, timeout=900,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=CREATE_NO_WINDOW,
                )
        except Exception as pe:
            _log(f'pip recovery failed: {pe!r}')
    # المحاولة الثانية: لو فشلت يُرفع الاستثناء → رسالة ظاهرة
    return _import_app()


def start_server() -> str:
    """تشغيل سيرفر النظام داخل خيط من نفس العملية (بدون نافذة أوامر).

    يرجع: 'up' نجاح | 'up-wait' سيرفر آخر في طور الاقلاع وجاهز الآن | 'dead' فشل ظاهر.
    """
    os.chdir(ROOT)
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)

    try:
        app, init_db = _import_app_with_recovery()
    except Exception as e:
        import traceback
        tb = traceback.format_exc(limit=3)
        _log(f'app import failed twice: {tb}')
        _fatal(
            'سلسل 7 — مكتبات النظام ناقصة',
            'تعذّر تحميل ملفات النظام (غالباً مكتبة بايثون ناقصة).\n'
            f'تفاصيل مختصرة: {str(e)[:200]}\n\n'
            'الحل: شغّل ملف «فحص-وتشخيص-سلسل.vbs» ثم اقرأ السطر الأخير\n'
            'في النافذة — سيوضح المكتبة الناقصة بالتحديد.',
        )
        return 'dead'

    try:
        init_db()
    except Exception as e:
        import traceback
        tb = traceback.format_exc(limit=3)
        _log(f'init_db failed: {tb}')
        _fatal(
            'سلسل 7 — خطأ في تهيئة قاعدة البيانات',
            f'تفاصيل مختصرة: {str(e)[:200]}',
        )
        return 'dead'

    _server_error.clear()

    def _serve() -> None:
        try:
            # host=0.0.0.0 حتى تبقى الأجهزة الأخرى قادرة على الاتصال عبر الشبكة
            app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)
        except SystemExit:
            # Werkzeug يستدعي sys.exit(1) عند فشل ربط المنفذ (المنفذ مستخدم)
            # — SystemExit لا يُلتقط بـ except Exception فيبقى الخيط ميتاً بصمت!
            _server_error.append(OSError(98, 'address already in use (werkzeug sys.exit)'))
            _log('server thread: werkzeug exited on port-bind failure (port busy)')
        except Exception as e:  # noqa: BLE001
            _server_error.append(e)
            _log(f'server thread error: {e!r}')

    threading.Thread(target=_serve, daemon=False, name='silsal-server').start()

    # انتظار جاهزية السيرفر (حتى 40 ثانية) — فحص خطأ الخيط أولاً لتوفير الوقت
    for _ in range(160):
        if _server_error:
            break
        if server_alive():
            _log(f'server started on port {PORT}')
            return 'up'
        time.sleep(0.25)

    if not _server_error and server_alive():
        _log(f'server started on port {PORT} (late)')
        return 'up'

    if _server_error:
        e = _server_error[0]
        win = getattr(e, 'winerror', None)
        err = getattr(e, 'errno', None)
        text = str(e).lower()
        if 10048 in (win, err) or err == 98 or 'address already in use' in text or 'only one usage' in text:
            # المنفذ محجوز: قد يكون سلسل آخر في طور الاقلاع من تشغيلة سابقة — ننتظره
            # (ping بقصير 0.5 ثانية حتى لا تُعلّق البروكسيات/البرامج الصامتة الإقلاع)
            _log('port busy — waiting for an already-starting silsal server')
            for _ in range(40):
                if server_alive(timeout=0.5):
                    _log('another silsal instance became ready — reusing it')
                    return 'up-wait'
                time.sleep(0.25)
            _fatal(
                f'سلسل 7 — المنفذ {PORT} مستخدم ببرنامج آخر',
                f'لا يستطيع سيرفر سلسل فتح المنفذ {PORT} لأنه محجوز.\n\n'
                f'الحل: أغلق البرنامج الذي يستخدم المنفذ {PORT} ثم أعد المحاولة،\n'
                f'أو شغّل النظام على منفذ آخر عبر متغير البيئة PORT.',
            )
        else:
            _fatal(
                'سلسل 7 — فشل تشغيل السيرفر',
                f'تفاصيل مختصرة: {str(e)[:300]}',
            )
    else:
        _fatal(
            'سلسل 7 — السيرفر لم يستجب',
            'لم يستجب سيرفر النظام خلال المهلة المحددة.\n'
            'شغّل «فحص-وتشخيص-سلسل.vbs» لمشاهدة السبب.',
        )
    return 'dead'


def _user_data_root() -> str:
    r"""مجلد بيانات النافذة في ملف تعريف المستخدم بويندوز (لا يُكبّر مجلد النظام).
    على ويندوز: %LOCALAPPDATA%\Silsal7 — وعلى الأنظمة الأخرى: مجلد instance للتوافق.
    """
    if os.name == 'nt':
        base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
        path = os.path.join(base, 'Silsal7')
    else:
        path = os.path.join(ROOT, 'instance')
    os.makedirs(path, exist_ok=True)
    return path


def _cleanup_old_profiles() -> None:
    """إزالة ملفات تعريف النافذة القديمة من مجلد النظام (نُقلت لملف تعريف المستخدم)."""
    for name in ('desktop_profile', 'desktop_profile_browser'):
        old = os.path.join(ROOT, 'instance', name)
        if os.path.isdir(old):
            import shutil
            try:
                shutil.rmtree(old, ignore_errors=True)
                _log(f'old profile removed from system folder: instance/{name}')
            except Exception as e:
                _log(f'old profile cleanup failed ({name}): {e!r}')


def close_behavior() -> str:
    try:
        b = (_request('/api/desktop/ping', timeout=2.0).get('close_behavior') or 'exit').lower()
        return b if b in ('exit', 'background') else 'exit'
    except Exception:
        return 'exit'


def ensure_pywebview() -> bool:
    """التأكد من توفر مكتبة النافذة المستقلة — تُثبَّت تلقائياً عند أول تشغيل."""
    try:
        import webview  # noqa: F401
        return True
    except ImportError:
        pass
    _log('pywebview not installed — installing (first run only)')
    try:
        cmd = [sys.executable, '-m', 'pip', 'install', '--quiet', '--disable-pip-version-check', 'pywebview>=5.1']
        subprocess.run(
            cmd, check=False, timeout=900,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
        import webview  # noqa: F401
        _log('pywebview installed automatically')
        return True
    except Exception as e:
        _log(f'pywebview unavailable: {e!r}')
        return False


def _screen_size():
    r"""أبعاد الشاشة الفعلية بالبكسل الفيزيائي (بغضّ النظر عن وعي DPI).
    1) EnumDisplaySettingsW — يعطي دقة الشاشة الحقيقية دائماً حتى مع
       تكبير خطوط ويندوز 125%/150% (أدق طريقة بدون مكتبات خارجية).
    2) احتياط: GetSystemMetrics مع تصحيح معامل التكبير.
    """
    if os.name != 'nt':
        return 0, 0
    try:
        import ctypes
        user32 = ctypes.windll.user32
        # (1) الأبعاد الفيزيائية الحقيقية من إعدادات العرض
        try:
            class _DEVMODE(ctypes.Structure):
                _fields_ = [
                    ('dmDeviceName', ctypes.c_wchar * 32),
                    ('dmSpecVersion', ctypes.c_ushort),
                    ('dmDriverVersion', ctypes.c_ushort),
                    ('dmSize', ctypes.c_ushort),
                    ('dmDriverExtra', ctypes.c_ushort),
                    ('dmFields', ctypes.c_ulong),
                    ('dmPositionX', ctypes.c_long),
                    ('dmPositionY', ctypes.c_long),
                    ('dmDisplayOrientation', ctypes.c_ulong),
                    ('dmDisplayFixedOutput', ctypes.c_ulong),
                    ('dmColor', ctypes.c_short),
                    ('dmDitherType', ctypes.c_short),
                    ('dmDisplayFlags', ctypes.c_short),
                    ('dmNup', ctypes.c_short),
                    ('dmPanningWidth', ctypes.c_ulong),
                    ('dmPanningHeight', ctypes.c_ulong),
                    ('dmPelsWidth', ctypes.c_ulong),
                    ('dmPelsHeight', ctypes.c_ulong),
                    ('dmBitsPerPel', ctypes.c_ulong),
                    ('dmPelsFrequency', ctypes.c_ulong),
                    ('_tail', ctypes.c_ubyte * 32),  # إكمال طول DEVMODE القياسي (156 بايت)
                ]
            dm = _DEVMODE()
            dm.dmSize = ctypes.sizeof(_DEVMODE)  # 156
            # ENUM_CURRENT_SETTINGS = -1
            if user32.EnumDisplaySettingsW(None, -1, ctypes.byref(dm)):
                w, h = int(dm.dmPelsWidth), int(dm.dmPelsHeight)
                if w >= 640 and h >= 480:
                    return w, h
        except Exception:
            pass
        # (2) احتياط: GetSystemMetrics + تصحيح الـ DPI إن كانت العملية غير مدركة
        try:
            w, h = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
            dpi = 96
            try:
                dpi = user32.GetDpiForSystem()
            except Exception:
                pass
            scale = 100
            try:
                scale = ctypes.windll.shcore.GetScaleFactorForDevice(0)
            except Exception:
                pass
            if scale > 100 and dpi == 96:
                w, h = int(w * scale / 100), int(h * scale / 100)
            if w >= 640 and h >= 480:
                return w, h
        except Exception:
            pass
    except Exception:
        pass
    return 0, 0


def _window_size_85():
    """حجم نافذة النظام = 85% من الشاشة — يعطي مساحة عمل واسعة
    ويبقي أجزاء من سطح المكتب وشريط المهام ظاهرة حول النافذة."""
    w, h = _screen_size()
    if w and h:
        return max(800, round(w * 0.85)), max(560, round(h * 0.85))
    return 1360, 768  # قيمة احتياطية معقولة إن تعذّر قياس الشاشة


def run_webview_window() -> None:
    """فتح النافذة المستقلة الاحترافية (WebView2 على Windows)."""
    import webview

    # ملف التعريف داخل ملف تعريف المستخدم بويندوز حتى لا يكبر حجم مجلد النظام
    profile = os.path.join(_user_data_root(), 'desktop_profile')
    os.makedirs(profile, exist_ok=True)
    sw, sh_ = _screen_size()
    w, h = _window_size_85()  # 85% من الشاشة تلقائياً عند كل فتح
    _log(f'window size: {w}x{h} (85% of screen {sw}x{sh_})')
    webview.create_window(
        APP_TITLE,
        URL,
        width=w,
        height=h,
        min_size=(820, 560),
        background_color='#161322',
        user_agent=UA,           # يستخدمه النظام لتعطيل Inspect والقائمة اليمنى
    )
    # debug=False → أدوات المطور مغلقة تماماً | private_mode=False → تذكرني يعمل بين الجلسات
    try:
        icon = os.path.join(ROOT, 'static', 'img', 'silsal.ico')
        if os.path.isfile(icon):
            webview.start(debug=False, private_mode=False, storage_path=profile, icon=icon)
        else:
            webview.start(debug=False, private_mode=False, storage_path=profile)
    except TypeError:
        # إصدارات pywebview الأقدم لا تدعم icon
        webview.start(debug=False, private_mode=False, storage_path=profile)


def run_browser_app_window():
    """خطة بديلة إذا تعذر تثبيت pywebview: نافذة تطبيق من Edge/Chrome (--app).

    تنتظر حتى يغلق المستخدم النافذة (p.wait) حتى يُطبَّق سلوك الإغلاق في الوقت الصحيح.
    """
    candidates = [
        os.path.expandvars(r'%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe'),
        os.path.expandvars(r'%ProgramFiles%\Microsoft\Edge\Application\msedge.exe'),
        os.path.expandvars(r'%ProgramFiles%\Google\Chrome\Application\chrome.exe'),
        os.path.expandvars(r'%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe'),
        os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe'),
    ]
    # ملف التعريف داخل ملف تعريف المستخدم بويندوز حتى لا يكبر حجم مجلد النظام
    profile = os.path.join(_user_data_root(), 'desktop_profile_browser')
    bw, bh = _window_size_85()  # 85% من الشاشة تلقائياً عند كل فتح
    for exe in candidates:
        if os.path.isfile(exe):
            p = subprocess.Popen([
                exe,
                f'--app={URL}',
                f'--user-agent={UA}',
                f'--window-size={bw},{bh}',
                f'--user-data-dir={profile}',
                '--no-first-run',
                '--no-default-browser-check',
            ], creationflags=CREATE_NO_WINDOW)
            _log(f'app window via {os.path.basename(exe)} — waiting for it to close')
            try:
                p.wait()  # ينتظر إغلاق المستخدم للنافذة
            except Exception:
                pass
            return 'app-window'
    # آخر الحلول: المتصفح الافتراضي (لا يمكن انتظار التبويب — نترك السيرفر يعمل)
    import webbrowser
    webbrowser.open(URL)
    _log('fallback: default browser (cannot track close — server stays)')
    return 'browser-tab'


def main() -> int:
    try:
        # ── تطبيق أي تحديث مُنزّل قبل تشغيل السيرفر ──
        # بمجرد إعادة تشغيل البرنامج تُستبدل ملفات النظام بالإصدار الجديد تلقائياً
        # (مجلد instance ببيانات العميل محمي تماماً) — ثم يقلع النظام بالإصدار الجديد.
        try:
            import silsal_updater  # noqa: E402
            _applied = silsal_updater.apply_pending_at_boot()
            if _applied:
                _log(f'pending update applied at boot → version {_applied}')
        except Exception as _boot_upd_err:
            _log(f'boot update apply skipped: {_boot_upd_err!r}')

        _log(f'launcher started | python={os.path.basename(sys.executable)} '
             f'| version={sys.version.split()[0]} | port={PORT}')
        _cleanup_old_profiles()
        if not server_alive():
            state = start_server()
            if state == 'dead':
                return 1
            # 'up-wait': سيرفر آخر جهز للتو — نكمل طبيعي على نفس السيرفر
        else:
            _log('existing silsal server detected — reusing it')

        opened = False
        window_kind = None
        if ensure_pywebview():
            try:
                run_webview_window()   # يرجع بعد إغلاق المستخدم للنافذة
                opened = True
                window_kind = 'webview'
            except Exception as e:
                _log(f'webview failed: {e!r} — trying browser app mode')
        if not opened:
            try:
                window_kind = run_browser_app_window()
                opened = True
            except Exception as e:
                _log(f'browser fallback failed: {e!r}')

        if not opened:
            _fatal(
                'سلسل 7 — تعذّر فتح النافذة',
                'تعذّر فتح نافذة النظام بالطريقتين (WebView2 والمتصفح).\n'
                'الحل: تأكد أن Windows 10/11 محدّث (WebView2 مدمج به)،\n'
                'أو شغّل «فحص-وتشخيص-سلسل.vbs» لمشاهدة التفاصيل.',
            )
            return 1

        # ── بعد إغلاق النافذة: تطبيق «سلوك الإغلاق» المختار من الإعدادات ──
        behavior = close_behavior()
        _log(f'window closed ({window_kind}) — close_behavior={behavior}')
        if behavior == 'exit':
            try:
                _request('/api/desktop/shutdown', method='POST', timeout=2.0)
            except Exception:
                pass
            time.sleep(0.5)
            os._exit(0)  # إغلاق نهائي لأي عملية متبقية (بما فيها السيرفر المحلي)
            return 0
        # background: الخروج من عملية النافذة فقط — خيط السيرفر (غير Daemon)
        # يُبقي العملية حية في الخلفية بدون أي نافذة، ويُوقف من «إيقاف-سيرفر-سلسل».
        return 0
    except SystemExit:
        raise
    except Exception:
        import traceback
        tb = traceback.format_exc(limit=3)
        _fatal('سلسل 7 — خطأ غير متوقع', f'تفاصيل الخطأ:\n{tb[-700:]}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
