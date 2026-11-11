# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════
 سلسل 7 — محرك التحديث التلقائي (Update Engine)
═══════════════════════════════════════════════════════════════════════
الفكرة:
• يفحص ملف version.json على الإنترنت (رابط ثابت لا يتغير — GitHub) دورياً
  كل عدة دقائق، وأيضاً أثناء استخدام البرنامج — فأول ما يجهاز العميل
  يوصل بالإنترنت يظهر داخل البرنامج شريط إشعار بوجود تحديث جديد.
• البرنامج يعمل أوفلاين 100% كالعادة: أي فشل شبكة يُتجاهل بصمت تماماً،
  ولا يخرج أي بيانات من جهاز العميل إلى الإنترنت (الفحص قراءة فقط
  لملف نصي صغير).
• التنزيل يجري داخل البرنامج مع شريط تقدّم، ثم يُتحقق من سلامة الحزمة
  (SHA-256 اختياري + فحص سلامة ZIP).
• التثبيت: بمجرد إعادة تشغيل البرنامج تُستبدل ملفات النظام تلقائياً
  بالإصدار الجديد ثم يقلع النظام — مع حماية مطلقة لمجلد instance
  (قاعدة البيانات، الإعدادات، الترخيص، النسخ الاحتياطية: لا تُمس أبداً)،
  ويُحفظ باك أب كامل للنسخة السابقة للتراجع عند أي خطأ.

الملفات:
• الإعدادات: instance/update_config.json  (رابط version.json + مدة الفحص)
• الحالة:    instance/update_state.json   (نتيجة آخر فحص / التنزيل / التثبيت)
• السجل:     instance/update_log.txt
"""
import hashlib
import json
import os
import shutil
import threading
import time
import urllib.error
import urllib.request
import zipfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, 'instance')
UPDATES_DIR = os.path.join(INSTANCE_DIR, 'updates')
CONFIG_FILE = os.path.join(INSTANCE_DIR, 'update_config.json')
STATE_FILE = os.path.join(INSTANCE_DIR, 'update_state.json')
LOG_FILE = os.path.join(INSTANCE_DIR, 'update_log.txt')

APP_VERSION = '7.1.4'          # ← يتحدّث مع كل إصدار جديد للنظام
CHECK_TIMEOUT = 8              # ثواني — فحص سريع لا يعطّل شيئاً
DOWNLOAD_TIMEOUT = 40          # ثواني مهلة كل قطعة أثناء التنزيل
MAX_ZIP_BYTES = 800 * 1024 * 1024

CONFIG_DEFAULTS = {
    'manifest_url': 'https://raw.githubusercontent.com/mohamednasserohi700-commits/Silsal-Updates/main/version.json',  # رابط version.json الثابت لهذه النسخة (قابل للتغيير من صفحة التحديثات أو instance/update_config.json)
    'interval_min': 15,        # كل كم دقيقة يعيد الفحص تلقائياً
    'demo': False,             # وضع التجربة: إشعار وهمي لمعاينة الشكل بدون إنترنت
    'demo_version': '7.5.0',
}

STATE_DEFAULTS = {
    'last_check': 0,           # وقت آخر فحص (epoch)
    'last_error': '',          # آخر خطأ فحص (إن وجد)
    'latest': None,            # آخر مانيفست صحيح {'version','url','notes','date','sha256','demo'}
    'dismissed_version': '',   # الإصدار الذي ضغط المستخدم «لاحقاً» له
    'download': {'phase': 'idle', 'percent': 0, 'error': '', 'version': '', 'file': ''},
    'pending_install': None,   # {'zip': المسار, 'version': الرقم} — يُطبَّق عند إعادة التشغيل
    'installed_version': '',   # آخر إصدار تم تثبيته بنجاح
    'installed_at': 0,
    'installed_seen': True,    # هل شوهد إشعار «تم التحديث» بالفعل؟
}

# مجلدات/ملفات لا تُمس نهائياً عند استبدال ملفات النظام (بيانات العميل)
PROTECTED_DIR_NAMES = {'instance', '__pycache__', 'venv', '.git', '.vscode',
                       'desktop_profile', 'desktop_profile_browser'}
PROTECTED_EXT = {'.db', '.db-wal', '.db-shm', '.log', '.pyc', '.tmp'}

LOCK = threading.RLock()


# ─────────────────────────── السجل ───────────────────────────
def _log(msg):
    """سجل نصي بسيط في instance/update_log.txt — لا يرفع استثناءات أبداً."""
    try:
        os.makedirs(INSTANCE_DIR, exist_ok=True)
        try:
            if os.path.getsize(LOG_FILE) > 512 * 1024:
                os.replace(LOG_FILE, LOG_FILE + '.old')
        except OSError:
            pass
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] {msg}\n')
    except Exception:
        pass


# ─────────────────────── الإعدادات والحالة ───────────────────────
def load_config():
    cfg = dict(CONFIG_DEFAULTS)
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            d = json.loads(f.read() or '{}')
        if isinstance(d, dict):
            for k in CONFIG_DEFAULTS:
                if k in d:
                    cfg[k] = d[k]
    except Exception:
        pass
    return cfg


def save_config(cfg):
    try:
        os.makedirs(INSTANCE_DIR, exist_ok=True)
        tmp = CONFIG_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=1)
        os.replace(tmp, CONFIG_FILE)
        return True
    except Exception as e:
        _log(f'config save failed: {e!r}')
        return False


def load_state():
    st = json.loads(json.dumps(STATE_DEFAULTS))  # نسخة عميقة بسيطة
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            d = json.loads(f.read() or '{}')
        if isinstance(d, dict):
            for k in STATE_DEFAULTS:
                if k in d:
                    st[k] = d[k]
            if not isinstance(st.get('download'), dict):
                st['download'] = dict(STATE_DEFAULTS['download'])
    except Exception:
        pass
    return st


def save_state(st):
    try:
        os.makedirs(INSTANCE_DIR, exist_ok=True)
        tmp = STATE_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        _log(f'state save failed: {e!r}')


# ─────────────────────── مقارنة الإصدارات ───────────────────────
def version_tuple(v):
    out = []
    for part in str(v or '').strip().split('.'):
        num = ''
        for ch in part:
            if ch.isdigit():
                num += ch
            else:
                break
        out.append(int(num) if num else 0)
    return tuple(out) if out else (0,)


def is_newer(remote, local):
    """هل الإصدار البعيد أحدث من المحلي؟"""
    try:
        return version_tuple(remote) > version_tuple(local)
    except Exception:
        return False


def is_different(remote, local):
    """هل الإصدار البعيد مختلف عن المحلي؟ — قاعدة التحديث في سلسل:
    أي رقم مختلف في version.json على GitHub (أكبر أو أصغر) يعني وجود
    تحديث جاهز للتنزيل، ومطابقة الرقم لنسختك تعني أن النسخة محدثة.
    لا يشترط النظام أي تسلسل أو ترتيب للأرقام."""
    try:
        return version_tuple(remote) != version_tuple(local)
    except Exception:
        return False


# ─────────────────────── الفحص (version.json) ───────────────────────
def _friendly_net_error(e):
    if isinstance(e, urllib.error.HTTPError):
        if e.code == 404:
            return 'ملف version.json غير موجود على الرابط (404) — تأكد من صحة الرابط وأن المستودع Public'
        return f'خطأ من الخادم ({e.code})'
    if isinstance(e, urllib.error.URLError):
        return 'لا يوجد اتصال بالإنترنت الآن — سيُعاد الفحص تلقائياً بدون أي تأثير على البرنامج'
    if isinstance(e, json.JSONDecodeError):
        return 'الرابط لا يعيد ملف version.json صحيح — راجع خطوات الدليل'
    return f'تعذّر الفحص: {e}'


def fetch_manifest(force=False):
    """قراءة version.json من الإنترنت (أو وضع التجربة) وتخزين النتيجة.
    يعيد (manifest أو None, رسالة خطأ أو '')."""
    cfg = load_config()
    if not force:
        with LOCK:
            st = load_state()
            if (time.time() - (st.get('last_check') or 0)) < 45:
                return (st.get('latest'), st.get('last_error') or '')
    m, err = None, ''
    try:
        if cfg.get('demo'):
            m = {'version': str(cfg.get('demo_version') or '7.5.0'),
                 'url': '',
                 'notes': 'وضع تجربة لمعاينة شكل الإشعار وصفحة التحديث — أوقفه بعد المعاينة من الزر بالأسفل',
                 'date': time.strftime('%Y-%m-%d'), 'sha256': '', 'demo': True}
        else:
            url = (cfg.get('manifest_url') or '').strip()
            if not url:
                err = 'لم يتم ضبط رابط التحديث بعد — الصق رابط version.json في خانة الإعدادات بالأسفل'
            else:
                req = urllib.request.Request(url, headers={
                    'User-Agent': 'Silsal7-Updater/1.0',
                    'Cache-Control': 'no-cache',
                })
                with urllib.request.urlopen(req, timeout=CHECK_TIMEOUT) as r:
                    raw = r.read().decode('utf-8', 'replace')
                d = json.loads(raw)
                ver = str(d.get('version') or '').strip()
                if not ver:
                    raise ValueError('version.json لا يحتوي رقم إصدار')
                m = {'version': ver,
                     'url': str(d.get('url') or d.get('download') or '').strip(),  # يقبل الحقلين url و download
                     'notes': str(d.get('notes') or ''),
                     'date': str(d.get('date') or ''),
                     'sha256': str(d.get('sha256') or ''),
                     'demo': False}
    except Exception as e:  # noqa: BLE001 — أي فشل شبكة يُتجاهل بهدوء تام
        m, err = None, _friendly_net_error(e)
    with LOCK:
        st = load_state()
        st['last_check'] = time.time()
        if m:
            st['latest'] = m
            st['last_error'] = ''
        elif err:
            st['last_error'] = err
        save_state(st)
    if m:
        _log(f'check: latest={m["version"]} current={APP_VERSION} different={is_different(m["version"], APP_VERSION)}')
    return (m, err)


_loop_started = False
_loop_lock = threading.Lock()
_check_inflight = {'t': 0.0}


def _interval_seconds():
    try:
        return max(5, int(load_config().get('interval_min') or 15)) * 60
    except Exception:
        return 15 * 60


def check_due(st=None):
    """هل حان وقت فحص جديد؟"""
    st = st or load_state()
    return (time.time() - (st.get('last_check') or 0)) >= _interval_seconds()


def check_enabled(cfg=None):
    cfg = cfg or load_config()
    return bool(cfg.get('demo') or (cfg.get('manifest_url') or '').strip())


def start_background_loop():
    """خيط خلفي: فحص دوري صامت (طلب واحد صغير كل عدة دقائق — لا يؤثر على الأداء)."""
    global _loop_started
    with _loop_lock:
        if _loop_started:
            return
        _loop_started = True

    def _loop():
        time.sleep(25)  # مهلة حتى يجهز إقلاع النظام تماماً
        while True:
            try:
                if check_enabled() and check_due():
                    fetch_manifest(force=True)
            except Exception:
                pass
            time.sleep(60)

    threading.Thread(target=_loop, daemon=True, name='silsal-update-check').start()
    _log('background check loop started')


def maybe_check_async():
    """يُستدعى عند تصفح المدير للبرنامج: لو حان موعد الفحص يشغّله في خيط منفصل
    (بدون أي انتظار) — فيظهر الإشعار سريعاً أول ما الجهاز يوصل بالإنترنت."""
    try:
        if not check_enabled():
            return
        if not check_due():
            return
        if time.time() - _check_inflight['t'] < 120:
            return
        _check_inflight['t'] = time.time()
        threading.Thread(target=lambda: fetch_manifest(force=True), daemon=True).start()
    except Exception:
        pass


# ─────────────────────── التنزيل ───────────────────────
def start_download():
    """بدء تنزيل حزمة التحديث في خيط منفصل مع تتبع التقدم."""
    st = load_state()
    d = st.get('download') or {}
    if d.get('phase') == 'downloading':
        return (False, 'التنزيل جارٍ بالفعل — تابع التقدم من هذه الصفحة')
    if d.get('phase') == 'ready' and st.get('pending_install'):
        return (False, 'التحديث مُنزّل وجاهز بالفعل — أعد تشغيل البرنامج لتثبيته')
    m = st.get('latest')
    if not m:
        return (False, 'لا يوجد تحديث للتنزيل — اضغط «فحص الآن» أولاً')
    cfg = load_config()
    if cfg.get('demo'):
        return (False, 'وضع التجربة مفعّل — التنزيل يعمل بعد ربط رابط GitHub الحقيقي وإيقاف وضع التجربة')
    url = m.get('url') or ''
    if not url.lower().startswith(('http://', 'https://')):
        return (False, 'حقل url في ملف version.json فارغ أو غير صحيح — راجع الدليل')
    if not (url.lower().startswith('https://') or '://localhost' in url.lower() or '://127.0.0.1' in url.lower()):
        return (False, 'للأمان يُسمح فقط بروابط HTTPS الآمنة (http للمحلي فقط)')
    threading.Thread(target=_download_worker, args=(dict(m),), daemon=True, name='silsal-update-dl').start()
    return (True, 'بدأ تنزيل التحديث… تابع التقدم من هذه الصفحة')


def _download_worker(m):
    with LOCK:
        st = load_state()
        if (st.get('download') or {}).get('phase') == 'downloading':
            return
        st['download'] = {'phase': 'downloading', 'percent': 0, 'error': '',
                          'version': m.get('version', ''), 'file': ''}
        save_state(st)
    tmp = os.path.join(UPDATES_DIR, 'download_tmp.zip')
    try:
        os.makedirs(UPDATES_DIR, exist_ok=True)
        req = urllib.request.Request(m['url'], headers={'User-Agent': 'Silsal7-Updater/1.0'})
        done, total = 0, 0
        h = hashlib.sha256()
        with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as r, open(tmp, 'wb') as f:
            try:
                total = int(r.headers.get('Content-Length') or 0)
            except (TypeError, ValueError):
                total = 0
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if done > MAX_ZIP_BYTES:
                    raise RuntimeError('حجم ملف التحديث أكبر من المسموح')
                if total:
                    pct = min(99, int(done * 100 / total))
                    with LOCK:
                        s2 = load_state()
                        if (s2.get('download') or {}).get('phase') == 'downloading':
                            s2['download']['percent'] = pct
                            save_state(s2)
        sha = (m.get('sha256') or '').strip().lower()
        if sha and len(sha) == 64 and h.hexdigest() != sha:
            raise RuntimeError('فشل التحقق من سلامة الملف (SHA-256) — الملف لا يطابق بصمة version.json')
        if not zipfile.is_zipfile(tmp):
            raise RuntimeError('الملف المُنزّل ليس حزمة ZIP صالحة — راجع رابط url في version.json')
        with zipfile.ZipFile(tmp) as z:
            if z.testzip() is not None:
                raise RuntimeError('الحزمة تحتوي ملفاً تالفاً — أعد رفع الحزمة على GitHub')
        final = os.path.join(UPDATES_DIR, f'update_v{m.get("version", "new")}.zip')
        try:
            for fn in os.listdir(UPDATES_DIR):
                if fn.startswith('update_v') and fn.endswith('.zip') and fn != os.path.basename(final):
                    os.remove(os.path.join(UPDATES_DIR, fn))
        except OSError:
            pass
        os.replace(tmp, final)
        with LOCK:
            st = load_state()
            st['download'] = {'phase': 'ready', 'percent': 100, 'error': '',
                              'version': m.get('version', ''), 'file': final}
            # بمجرد اكتمال التنزيل: التحديث يُطبَّق تلقائياً عند إعادة تشغيل البرنامج
            st['pending_install'] = {'zip': final, 'version': m.get('version', '')}
            save_state(st)
        _log(f'download: ready v{m.get("version")} ({done:,} bytes)')
    except Exception as e:  # noqa: BLE001
        try:
            os.remove(tmp)
        except OSError:
            pass
        with LOCK:
            st = load_state()
            st['download'] = {'phase': 'error', 'percent': 0, 'error': str(e)[:300],
                              'version': m.get('version', ''), 'file': ''}
            save_state(st)
        _log(f'download: failed {e!r}')


# ─────────────────────── التثبيت (استبدال الملفات) ───────────────────────
def _iter_app_files(src):
    """ملفات النظام فقط — مع استبعاد بيانات العميل والمجلدات المحمية نهائياً."""
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in PROTECTED_DIR_NAMES]
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            if ext in PROTECTED_EXT:
                continue
            yield os.path.join(root, fn)


def _copy_tree(src, dst):
    """نسخ شجرة ملفات (للباك أب أو للاستبدال) بنفس قواعد الحماية."""
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in PROTECTED_DIR_NAMES]
        rel_root = os.path.relpath(root, src)
        target_root = dst if rel_root == '.' else os.path.join(dst, rel_root)
        os.makedirs(target_root, exist_ok=True)
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            if ext in PROTECTED_EXT:
                continue
            shutil.copy2(os.path.join(root, fn), os.path.join(target_root, fn))


def _rmtree_force(path):
    """حذف شجرة مجلدات بشكل قوي: يتجاوز خاصية القراءة فقط (chmod ثم إعادة
    محاولة) — مهم على ويندوز حيث تفشل النظافة الصامتة تاركة بقايا تعطّل
    كل محاولات التحديث التالية. وإن تعذر الحذف فعلاً (ملف مقفول من برنامج
    خارجي) يُرفع خطأ عربي واضح بدل رموز ويندوز الغامضة."""
    if not os.path.exists(path):
        return

    def _retry(func, p, _exc):
        # إعادة المحاولة بعد رفع الصلاحيات: على الملف نفسه وعلى المجلد الأب
        # (الحذف يحتاج صلاحية كتابة على الأب وليس على الملف فقط)
        for t in (p, os.path.dirname(p)):
            try:
                os.chmod(t, 0o666 if os.path.isfile(t) else 0o777)
            except OSError:
                pass
        try:
            func(p)
        except OSError:
            pass

    shutil.rmtree(path, onerror=_retry)
    if os.path.exists(path):
        raise RuntimeError(
            'تعذر تنظيف مجلد التحديث المؤقت "' + path + '" — غالباً ملف داخله '
            'مقفول من مضاد الفيروسات أو برنامج آخر. أغلق البرنامج وامسح المجلد '
            'يدوياً ثم اضغط «تنزيل التحديث» من جديد.')


def _extract_zip(zip_path, dest):
    """فك الحزمة: يدعم وجود مجلد جذر واحد داخل الـ ZIP، مع حماية من مسارات مشبوهة،
    وتجاوز أي ملفات/مجلدات محمية (instance وقواعد البيانات لا تُمس)."""
    with zipfile.ZipFile(zip_path) as z:
        names = [n.replace('\\', '/').strip('/') for n in z.namelist()]
        tops = {n.split('/')[0] for n in names if n}
        prefix = ''
        if len(tops) == 1:
            only = next(iter(tops))
            if not os.path.splitext(only)[1]:
                prefix = only + '/'

        def _strip(n):
            if prefix and n.startswith(prefix):
                return n[len(prefix):]
            return n

        # بادئات المجلدات لكل المدخلات — بعض أدوات الضغط تحفظ المجلدات
        # كملفات صفرية بلا شرطة مائلة (static بدل static/) فتُكتب كملف
        # ويفشل إنشاء الملفات الداخلية بعدها (WinError 183 على ويندوز)
        dir_prefixes = set()
        for n in (_strip(x) for x in names):
            if not n:
                continue
            p = n.split('/')
            for i in range(1, len(p)):
                dir_prefixes.add('/'.join(p[:i]))
        for info in z.infolist():
            n = _strip(info.filename.replace('\\', '/').strip('/'))
            if not n or n.endswith('/'):
                continue
            if n in dir_prefixes and info.file_size == 0:
                continue  # مدخل «مجلد» حُفظ كملف صفري بلا "/" — يُتجاهل
            parts = [p for p in n.split('/') if p not in ('', '.')]
            if not parts or any(p == '..' for p in parts):
                continue  # حماية zip-slip
            if parts[0] in PROTECTED_DIR_NAMES:
                continue
            if any(p == '__pycache__' for p in parts):
                continue
            if os.path.splitext(n)[1].lower() in PROTECTED_EXT:
                continue
            target = os.path.join(dest, os.path.join(*parts))
            d = os.path.dirname(target)
            # بقايا محاولة سابقة أو مدخل شاذ: ملف مكان مجلد → يُحذف،
            # ومجلد مكان ملف → يُزال — الفك يصبح ذاتي الإشفار دائماً
            if os.path.isfile(d):
                try:
                    os.remove(d)
                except OSError:
                    pass
            os.makedirs(d, exist_ok=True)
            if os.path.isdir(target):
                shutil.rmtree(target, ignore_errors=True)
            with z.open(info) as fsrc, open(target, 'wb') as fdst:
                shutil.copyfileobj(fsrc, fdst, 256 * 1024)


def apply_pending_sync():
    """تطبيق التحديث المعلّق: باك أب ← فك ← استبدال (مع حماية instance) ← تحديث الحالة.
    يعيد (True, version) عند النجاح و(False, رسالة) عند الفشل — مع تراجع تلقائي للباك أب."""
    st = load_state()
    p = st.get('pending_install')
    if not p:
        return (False, 'لا يوجد تحديث معلّق للتثبيت')
    zip_path = p.get('zip') or ''
    ver = str(p.get('version') or '?')
    if not zip_path or not os.path.isfile(zip_path):
        with LOCK:
            st = load_state()
            st['pending_install'] = None
            save_state(st)
        return (False, 'ملف التحديث غير موجود — أعد تنزيله من صفحة التحديثات')
    extract_dir = os.path.join(UPDATES_DIR, 'extract_tmp')
    backup_dir = os.path.join(UPDATES_DIR, 'backup_prev')
    try:
        _log(f'apply: start v{ver}')
        _rmtree_force(extract_dir)
        os.makedirs(extract_dir, exist_ok=True)
        _extract_zip(zip_path, extract_dir)
        if not os.path.isfile(os.path.join(extract_dir, 'app.py')):
            raise RuntimeError('الحزمة لا تحتوي ملفات النظام الصحيحة (app.py مفقود)')
        # باك أب للنسخة الحالية (للتراجع عند أي خطأ) — يُحتفظ بآخر باك أب فقط
        _rmtree_force(backup_dir)
        os.makedirs(backup_dir, exist_ok=True)
        _copy_tree(BASE_DIR, backup_dir)
        # الاستبدال
        _copy_tree(extract_dir, BASE_DIR)
        if not os.path.isfile(os.path.join(BASE_DIR, 'app.py')):
            raise RuntimeError('تعذر نسخ ملفات النظام')
        with LOCK:
            st = load_state()
            st['pending_install'] = None
            st['installed_version'] = ver
            st['installed_at'] = time.time()
            st['installed_seen'] = False
            st['download'] = dict(STATE_DEFAULTS['download'])
            st['latest'] = None
            st['last_error'] = ''
            save_state(st)
        shutil.rmtree(extract_dir, ignore_errors=True)
        _log(f'apply: success → v{ver}')
        return (True, ver)
    except Exception as e:  # noqa: BLE001
        _log(f'apply: FAILED {e!r} — restoring backup')
        try:
            if os.path.isdir(backup_dir):
                _copy_tree(backup_dir, BASE_DIR)
                _log('apply: restore from backup done')
        except Exception as re_:  # noqa: BLE001
            _log(f'apply: restore failed {re_!r}')
        with LOCK:
            try:
                st = load_state()
                st['pending_install'] = None
                st['last_error'] = f'فشل تثبيت التحديث: {e}'
                save_state(st)
            except Exception:
                pass
        return (False, str(e))


def apply_pending_at_boot():
    """يُستدعى من مشغّل الديسك توب (silsal_desktop.py) قبل تشغيل السيرفر:
    لو يوجد تحديث مُنزّل يُستبدل الكود الآن فيقلع النظام مباشرة بالإصدار الجديد.
    لا يرفع استثناءات أبداً — أي خطأ يعني استكمال التشغيل الطبيعي."""
    try:
        st = load_state()
        if not st.get('pending_install'):
            return None
        ok, ver = apply_pending_sync()
        return ver if ok else None
    except Exception as e:  # noqa: BLE001
        _log(f'boot apply error: {e!r}')
        return None


# ─────────────────────── التثبيت الآن (إعادة تشغيل تلقائية) ───────────────────────
def arm_install():
    st = load_state()
    d = st.get('download') or {}
    if d.get('phase') != 'ready' or not d.get('file') or not os.path.isfile(d['file']):
        return (False, 'لا يوجد تحديث مُنزّل وجاهز — نزّل التحديث أولاً')
    with LOCK:
        st = load_state()
        st['pending_install'] = {'zip': d['file'], 'version': d.get('version') or ''}
        save_state(st)
    _log(f'install armed → v{d.get("version")}')
    return (True, d.get('version') or '')


def spawn_detached_installer(port, vbs_path=''):
    """ويندوز: يشغّل apply_update.py بعملية مستقلة تنتظر إغلاق السيرفر ثم تطبّق
    التحديث وتعيد فتح البرنامج تلقائياً. (على أنظمة أخرى: التثبيت عند إعادة التشغيل اليدوي)."""
    if os.name != 'nt':
        return (False, 'not-windows')
    try:
        import subprocess
        import sys
        flags = 0x00000008 | 0x08000000  # DETACHED_PROCESS | CREATE_NO_WINDOW
        py = sys.executable
        pw = os.path.join(os.path.dirname(py), 'pythonw.exe')
        if os.path.isfile(pw):
            py = pw
        args = [py, os.path.join(BASE_DIR, 'apply_update.py'), '--port', str(port)]
        if vbs_path and os.path.isfile(vbs_path):
            args += ['--vbs', vbs_path]
        else:
            # النسخ بدون مشغّل VBS: المثبّت يعيد فتح البرنامج عبر pythonw app.py مباشرة
            args += ['--py', py]
        subprocess.Popen(args, cwd=BASE_DIR, creationflags=flags, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        _log('detached installer spawned')
        return (True, '')
    except Exception as e:  # noqa: BLE001
        _log(f'detached installer spawn failed: {e!r}')
        return (False, str(e))


# ─────────────────────── واجهات العرض ───────────────────────
def dismiss_now():
    """«لاحقاً»: إخفاء إشعار التحديث الحالي + اعتماد إشعار «تم التحديث»."""
    with LOCK:
        st = load_state()
        if st.get('installed_at') and not st.get('installed_seen'):
            st['installed_seen'] = True
        m = st.get('latest')
        if m and m.get('version'):
            st['dismissed_version'] = m['version']
        save_state(st)


def mark_installed_seen():
    with LOCK:
        st = load_state()
        st['installed_seen'] = True
        save_state(st)


def banner_info():
    """معلومات شريط الإشعار: installed / ready / available — أو None."""
    st = load_state()
    now = time.time()
    if st.get('installed_at') and not st.get('installed_seen') and (now - st['installed_at'] < 3 * 86400):
        return {'kind': 'installed', 'version': st.get('installed_version') or ''}
    p = st.get('pending_install')
    if p and p.get('zip') and os.path.isfile(p['zip']):
        return {'kind': 'ready', 'version': p.get('version') or ''}
    m = st.get('latest')
    if m and m.get('version') and is_different(m['version'], APP_VERSION) \
            and st.get('dismissed_version') != m['version']:
        return {'kind': 'available', 'version': m['version'],
                'notes': m.get('notes') or '', 'date': m.get('date') or '',
                'demo': bool(m.get('demo'))}
    return None


def _time_ago_str(ts):
    if not ts:
        return 'لم يتم الفحص بعد'
    diff = int(time.time() - ts)
    if diff < 0:
        diff = 0
    if diff < 60:
        return 'قبل لحظات'
    if diff < 3600:
        return f'منذ {diff // 60} دقيقة'
    if diff < 86400:
        return f'منذ {diff // 3600} ساعة'
    return f'منذ {diff // 86400} يوم'


def _size_str(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return ''
    if n <= 0:
        return ''
    for unit in ('بايت', 'ك.ب', 'م.ب', 'ج.ب'):
        if n < 1024:
            return f'{n:.0f} {unit}' if unit == 'بايت' else f'{n:.1f} {unit}'
        n /= 1024
    return f'{n:.1f} ت.ب'


def snapshot():
    """لقطة كاملة للحالة — تُستخدم في صفحة التحديثات وفي التحديث الحي (polling)."""
    st = load_state()
    cfg = load_config()
    d = st.get('download') or {}
    m = st.get('latest')
    zip_path = d.get('file') or ''
    pending = st.get('pending_install')
    return {
        'app_version': APP_VERSION,
        'manifest_url': cfg.get('manifest_url') or '',
        'configured': bool((cfg.get('manifest_url') or '').strip() or cfg.get('demo')),
        'demo': bool(cfg.get('demo')),
        'interval_min': cfg.get('interval_min') or 15,
        'last_check': st.get('last_check') or 0,
        'last_check_str': _time_ago_str(st.get('last_check') or 0),
        'last_error': st.get('last_error') or '',
        'latest': m,
        'update_available': bool(m and is_different(m.get('version', ''), APP_VERSION)),
        'download': {'phase': d.get('phase') or 'idle', 'percent': d.get('percent') or 0,
                     'error': d.get('error') or '', 'version': d.get('version') or ''},
        'pending_install': pending,
        'ready_version': (pending or {}).get('version', '') if pending else '',
        'installed_version': st.get('installed_version') or '',
        'installed_at': st.get('installed_at') or 0,
        'installed_recently': bool(st.get('installed_at') and time.time() - st['installed_at'] < 86400),
        'dismissed_version': st.get('dismissed_version') or '',
        'can_auto_relaunch': (os.name == 'nt'),
        'zip_size_str': _size_str(os.path.getsize(zip_path) if zip_path and os.path.isfile(zip_path) else 0),
    }


def save_user_config(manifest_url=None, interval_min=None, demo=None):
    """حفظ الإعدادات من صفحة التحديثات — مع تحقق أمان من الرابط."""
    cfg = load_config()
    if manifest_url is not None:
        u = str(manifest_url).strip()
        if u:
            low = u.lower()
            if not low.startswith(('http://', 'https://')):
                return (False, 'الرابط يجب أن يبدأ بـ https:// (رابط version.json من GitHub)')
            if low.startswith('http://'):
                from urllib.parse import urlparse
                host = (urlparse(u).hostname or '').lower()
                if host not in ('localhost', '127.0.0.1'):
                    return (False, 'للأمان يُسمح بروابط HTTPS فقط — رابط GitHub يكون https:// تلقائياً')
            cfg['manifest_url'] = u
            cfg['demo'] = False  # ضبط رابط حقيقي يوقف وضع التجربة تلقائياً
        else:
            cfg['manifest_url'] = ''
    if interval_min is not None:
        try:
            cfg['interval_min'] = max(5, min(720, int(interval_min)))
        except (TypeError, ValueError):
            pass
    if demo is not None:
        cfg['demo'] = bool(demo)
    if save_config(cfg):
        _log(f'config saved: url={"set" if cfg.get("manifest_url") else "empty"} '
             f'interval={cfg.get("interval_min")} demo={cfg.get("demo")}')
        return (True, '')
    return (False, 'تعذر حفظ ملف الإعدادات — تأكد من صلاحيات مجلد instance')
