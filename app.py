#!/usr/bin/env python3
# ============================================================
# 영업관리 시스템 - Flask + PostgreSQL 메인 앱
# 실행: python app.py
# WSGI: gunicorn app:app
# ============================================================

import io
import csv
import re
from datetime import datetime, timedelta
from functools import wraps

import psycopg2
import psycopg2.extras
import openpyxl

try:
    import chardet
    HAS_CHARDET = True
except ImportError:
    HAS_CHARDET = False

from flask import (
    Flask, session, request, redirect,
    jsonify, render_template, Response, g
)
from werkzeug.security import generate_password_hash, check_password_hash

from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS, BASE_PATH, SECRET_KEY

# ============================================================
# Flask 앱 설정
# ============================================================

app = Flask(__name__)
app.secret_key = SECRET_KEY

_BASE = BASE_PATH.rstrip('/') if BASE_PATH else ''


# ============================================================
# DB 연결 (요청별 커넥션)
# ============================================================

def get_db():
    if 'db' not in g:
        g.db = psycopg2.connect(
            host=DB_HOST, port=DB_PORT,
            dbname=DB_NAME, user=DB_USER, password=DB_PASS,
            cursor_factory=psycopg2.extras.RealDictCursor
        )
        g.db.autocommit = False
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop('db', None)
    if db is not None:
        if exc:
            try:
                db.rollback()
            except Exception:
                pass
        else:
            try:
                db.commit()
            except Exception:
                pass
        try:
            db.close()
        except Exception:
            pass


# ============================================================
# 공통 헬퍼
# ============================================================

def null_or_str(v):
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def null_or_int(v):
    if v is None or v == '':
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def require_login(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            return jsonify({'error': '로그인이 필요합니다.'}), 401
        return f(*args, **kwargs)
    return decorated


def seven_days_ago():
    return datetime.now() - timedelta(days=7)


def generate_company_code(cur):
    today = datetime.now().strftime('%Y%m%d')
    cur.execute(
        "SELECT COUNT(*) AS cnt FROM sm_companies WHERE company_code LIKE %s",
        (today + '-%',)
    )
    row = cur.fetchone()
    seq = (row['cnt'] if row else 0) + 1
    return f"{today}-{seq:03d}"


def serialize_row(row):
    if row is None:
        return None
    result = {}
    for k, v in dict(row).items():
        if hasattr(v, 'isoformat'):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


def serialize_rows(rows):
    return [serialize_row(r) for r in (rows or [])]


# ============================================================
# 파일 파싱 (XLSX / CSV)
# ============================================================

def read_xlsx(file_obj):
    try:
        wb = openpyxl.load_workbook(file_obj, read_only=True, data_only=True)
        ws = wb.active
        rows = []
        for row in ws.iter_rows(values_only=True):
            cells = [str(c).strip() if c is not None else '' for c in row]
            if any(c != '' for c in cells):
                rows.append(cells)
        wb.close()
        return rows
    except Exception:
        return []


def read_csv_bytes(raw_bytes):
    # UTF-8 BOM 처리
    if raw_bytes.startswith(b'\xef\xbb\xbf'):
        raw_bytes = raw_bytes[3:]
        encoding = 'utf-8'
    else:
        if HAS_CHARDET:
            detected = chardet.detect(raw_bytes[:4096])
            encoding = detected.get('encoding') or 'utf-8'
        else:
            encoding = 'utf-8'
        if encoding and encoding.lower() in ('euc-kr', 'cp949', 'ms949', 'uhc'):
            encoding = 'cp949'

    try:
        text = raw_bytes.decode(encoding, errors='replace')
    except (LookupError, TypeError):
        text = raw_bytes.decode('utf-8', errors='replace')

    first_line = text.split('\n')[0] if text else ''
    counts = {',': first_line.count(','), '\t': first_line.count('\t'), ';': first_line.count(';')}
    delimiter = max(counts, key=counts.get)

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = []
    for row in reader:
        cells = [c.strip() for c in row]
        if any(c != '' for c in cells):
            rows.append(cells)
    return rows


def read_upload_file(file_storage):
    filename = file_storage.filename or ''
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext in ('xlsx', 'xls'):
        return read_xlsx(file_storage.stream)
    elif ext == 'csv':
        raw = file_storage.read()
        return read_csv_bytes(raw)
    return []


def download_csv(display_filename, headers, sample_rows=None):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    for row in (sample_rows or []):
        writer.writerow(row)
    csv_bytes = b'\xef\xbb\xbf' + buf.getvalue().encode('utf-8')

    from urllib.parse import quote
    encoded_name = quote(display_filename, safe='')
    return Response(
        csv_bytes,
        mimetype='text/csv; charset=utf-8',
        headers={
            'Content-Disposition': f"attachment; filename*=UTF-8''{encoded_name}",
            'Cache-Control': 'no-cache, no-store, must-revalidate',
        }
    )


# ============================================================
# 페이지 라우트
# ============================================================

@app.route('/')
def index():
    if not session.get('user_id'):
        return redirect(('' if not _BASE else _BASE) + '/login')
    return render_template('app.html', base_path=_BASE)


@app.route('/login')
def login_page():
    if session.get('user_id'):
        return redirect(('' if not _BASE else _BASE) + '/')
    return render_template('login.html', base_path=_BASE)


# ============================================================
# 인증 API
# ============================================================

@app.route('/api/login', methods=['POST'])
def api_login():
    b = request.get_json(silent=True) or {}
    username = (b.get('username') or '').strip()
    password = b.get('password') or ''
    if not username or not password:
        return jsonify({'success': False, 'message': '아이디와 비밀번호를 입력하세요.'}), 400

    cur = get_db().cursor()
    cur.execute("SELECT * FROM sm_users WHERE username = %s LIMIT 1", (username,))
    user = cur.fetchone()
    if user and check_password_hash(user['password'], password):
        session['user_id'] = user['id']
        session['username'] = user['username']
        return jsonify({'success': True, 'username': user['username']})
    return jsonify({'success': False, 'message': '아이디 또는 비밀번호가 올바르지 않습니다.'}), 401


@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'success': True})


@app.route('/api/change-password', methods=['POST'])
@require_login
def api_change_password():
    b = request.get_json(silent=True) or {}
    current = b.get('current_password') or ''
    new_pw  = b.get('new_password') or ''
    if not current or not new_pw:
        return jsonify({'success': False, 'message': '모든 항목을 입력하세요.'}), 400

    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT password FROM sm_users WHERE id = %s LIMIT 1", (session['user_id'],))
    user = cur.fetchone()
    if not user or not check_password_hash(user['password'], current):
        return jsonify({'success': False, 'message': '현재 비밀번호가 올바르지 않습니다.'}), 400

    cur.execute(
        "UPDATE sm_users SET password = %s WHERE id = %s",
        (generate_password_hash(new_pw), session['user_id'])
    )
    db.commit()
    return jsonify({'success': True})


@app.route('/api/session', methods=['GET'])
def api_session():
    if session.get('user_id'):
        return jsonify({'logged_in': True, 'username': session.get('username')})
    return jsonify({'logged_in': False})


# ============================================================
# 대시보드 API
# ============================================================

@app.route('/api/dashboard', methods=['GET'])
@require_login
def api_dashboard():
    db  = get_db()
    ago = seven_days_ago()
    cur = db.cursor()

    cur.execute(
        "SELECT id, company_name, created_at FROM sm_companies WHERE created_at >= %s ORDER BY created_at DESC",
        (ago,)
    )
    new_companies = serialize_rows(cur.fetchall())

    cur.execute(
        """SELECT cc.id, cc.name, c.company_name, cc.department, cc.created_at
           FROM sm_company_contacts cc
           JOIN sm_companies c ON cc.company_id = c.id
           WHERE cc.created_at >= %s
           ORDER BY cc.created_at DESC""",
        (ago,)
    )
    new_contacts = serialize_rows(cur.fetchall())

    cur.execute(
        """SELECT m.id, m.meeting_type, m.meeting_datetime, m.content, m.created_at,
                  STRING_AGG(DISTINCT c.company_name, ', ') AS companies
           FROM sm_meetings m
           LEFT JOIN sm_meeting_companies mc ON m.id = mc.meeting_id
           LEFT JOIN sm_companies c ON mc.company_id = c.id
           WHERE m.created_at >= %s
           GROUP BY m.id
           ORDER BY m.created_at DESC""",
        (ago,)
    )
    new_meetings = serialize_rows(cur.fetchall())

    return jsonify({
        'new_companies': new_companies,
        'new_contacts':  new_contacts,
        'new_meetings':  new_meetings,
    })


# ============================================================
# 영업 담당자 API
# ============================================================

@app.route('/api/sales-reps', methods=['GET'])
@require_login
def api_sr_list():
    search = (request.args.get('search') or '').strip()
    cur = get_db().cursor()
    if search:
        like = f'%{search}%'
        cur.execute(
            "SELECT * FROM sm_sales_reps WHERE name LIKE %s OR emp_no LIKE %s ORDER BY created_at DESC",
            (like, like)
        )
    else:
        cur.execute("SELECT * FROM sm_sales_reps ORDER BY created_at DESC")
    return jsonify(serialize_rows(cur.fetchall()))


@app.route('/api/sales-reps/<int:rep_id>', methods=['GET'])
@require_login
def api_sr_get(rep_id):
    cur = get_db().cursor()
    cur.execute("SELECT * FROM sm_sales_reps WHERE id = %s LIMIT 1", (rep_id,))
    row = cur.fetchone()
    if not row:
        return jsonify({'error': '존재하지 않습니다.'}), 404
    return jsonify(serialize_row(row))


@app.route('/api/sales-reps', methods=['POST'])
@require_login
def api_sr_create():
    b = request.get_json(silent=True) or {}
    emp_no = (b.get('emp_no') or '').strip()
    name   = (b.get('name') or '').strip()
    if not emp_no or not name:
        return jsonify({'success': False, 'message': '사원번호와 성명은 필수입니다.'}), 400
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            "INSERT INTO sm_sales_reps (emp_no, name, rank, position, phone, email) VALUES (%s,%s,%s,%s,%s,%s)",
            (emp_no, name, null_or_str(b.get('rank')), null_or_str(b.get('position')),
             null_or_str(b.get('phone')), null_or_str(b.get('email')))
        )
        db.commit()
        return jsonify({'success': True})
    except psycopg2.errors.UniqueViolation:
        db.rollback()
        return jsonify({'success': False, 'message': '이미 존재하는 사원번호입니다.'}), 400


@app.route('/api/sales-reps/<int:rep_id>', methods=['PUT'])
@require_login
def api_sr_update(rep_id):
    b = request.get_json(silent=True) or {}
    emp_no = (b.get('emp_no') or '').strip()
    name   = (b.get('name') or '').strip()
    if not emp_no or not name:
        return jsonify({'success': False, 'message': '사원번호와 성명은 필수입니다.'}), 400
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            "UPDATE sm_sales_reps SET emp_no=%s, name=%s, rank=%s, position=%s, phone=%s, email=%s WHERE id=%s",
            (emp_no, name, null_or_str(b.get('rank')), null_or_str(b.get('position')),
             null_or_str(b.get('phone')), null_or_str(b.get('email')), rep_id)
        )
        db.commit()
        return jsonify({'success': True})
    except psycopg2.errors.UniqueViolation:
        db.rollback()
        return jsonify({'success': False, 'message': '이미 존재하는 사원번호입니다.'}), 400


@app.route('/api/sales-reps/<int:rep_id>', methods=['DELETE'])
@require_login
def api_sr_delete(rep_id):
    db = get_db()
    db.cursor().execute("DELETE FROM sm_sales_reps WHERE id = %s", (rep_id,))
    db.commit()
    return jsonify({'success': True})


# ============================================================
# 업체 API
# ============================================================

def comp_solutions(cur, company_id):
    cur.execute(
        """SELECT cd.id, cd.code_value
           FROM sm_company_solutions cs
           JOIN sm_codes cd ON cs.solution_id = cd.id
           WHERE cs.company_id = %s
           ORDER BY cd.sort_order""",
        (company_id,)
    )
    return serialize_rows(cur.fetchall())


def comp_save_solutions(db, company_id, solution_ids):
    cur = db.cursor()
    cur.execute("DELETE FROM sm_company_solutions WHERE company_id = %s", (company_id,))
    for sid in solution_ids:
        try:
            cur.execute(
                "INSERT INTO sm_company_solutions (company_id, solution_id) VALUES (%s, %s)",
                (company_id, int(sid))
            )
        except Exception:
            pass


@app.route('/api/companies', methods=['GET'])
@require_login
def api_comp_list():
    search = (request.args.get('search') or '').strip()
    cur = get_db().cursor()
    if search:
        cur.execute(
            "SELECT * FROM sm_companies WHERE company_name LIKE %s ORDER BY created_at DESC, id DESC",
            (f'%{search}%',)
        )
    else:
        cur.execute("SELECT * FROM sm_companies ORDER BY created_at DESC, id DESC")
    rows = serialize_rows(cur.fetchall())
    for r in rows:
        r['solutions'] = comp_solutions(cur, r['id'])
    return jsonify(rows)


@app.route('/api/companies/<int:comp_id>', methods=['GET'])
@require_login
def api_comp_get(comp_id):
    cur = get_db().cursor()
    cur.execute("SELECT * FROM sm_companies WHERE id = %s LIMIT 1", (comp_id,))
    row = cur.fetchone()
    if not row:
        return jsonify({'error': '존재하지 않습니다.'}), 404
    row = serialize_row(row)
    row['solutions']    = comp_solutions(cur, comp_id)
    row['solution_ids'] = [s['id'] for s in row['solutions']]
    return jsonify(row)


@app.route('/api/companies', methods=['POST'])
@require_login
def api_comp_create():
    b = request.get_json(silent=True) or {}
    company_name = (b.get('company_name') or '').strip()
    if not company_name:
        return jsonify({'success': False, 'message': '업체명은 필수입니다.'}), 400
    db = get_db()
    cur = db.cursor()
    code = generate_company_code(cur)
    cur.execute(
        """INSERT INTO sm_companies
           (company_code, company_name, ceo_name, business_reg_no, corp_reg_no, address, phone)
           VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (code, company_name,
         null_or_str(b.get('ceo_name')), null_or_str(b.get('business_reg_no')),
         null_or_str(b.get('corp_reg_no')), null_or_str(b.get('address')),
         null_or_str(b.get('phone')))
    )
    new_id = cur.fetchone()['id']
    comp_save_solutions(db, new_id, b.get('solution_ids') or [])
    db.commit()
    return jsonify({'success': True, 'id': new_id, 'company_code': code})


@app.route('/api/companies/<int:comp_id>', methods=['PUT'])
@require_login
def api_comp_update(comp_id):
    b = request.get_json(silent=True) or {}
    company_name = (b.get('company_name') or '').strip()
    if not company_name:
        return jsonify({'success': False, 'message': '업체명은 필수입니다.'}), 400
    db = get_db()
    cur = db.cursor()
    cur.execute(
        """UPDATE sm_companies
           SET company_name=%s, ceo_name=%s, business_reg_no=%s,
               corp_reg_no=%s, address=%s, phone=%s
           WHERE id=%s""",
        (company_name,
         null_or_str(b.get('ceo_name')), null_or_str(b.get('business_reg_no')),
         null_or_str(b.get('corp_reg_no')), null_or_str(b.get('address')),
         null_or_str(b.get('phone')), comp_id)
    )
    comp_save_solutions(db, comp_id, b.get('solution_ids') or [])
    db.commit()
    return jsonify({'success': True})


@app.route('/api/companies/<int:comp_id>', methods=['DELETE'])
@require_login
def api_comp_delete(comp_id):
    db = get_db()
    db.cursor().execute("DELETE FROM sm_companies WHERE id = %s", (comp_id,))
    db.commit()
    return jsonify({'success': True})


@app.route('/api/companies/template', methods=['GET'])
@require_login
def api_comp_template():
    return download_csv(
        '업체_등록양식.csv',
        ['업체명(필수)', '대표자명', '사업자등록번호', '법인등록번호', '주소', '연락처'],
        [['(주)예시업체', '홍길동', '000-00-00000', '000000-0000000', '서울시 강남구', '02-0000-0000']]
    )


@app.route('/api/companies/import', methods=['POST'])
@require_login
def api_comp_import():
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': '파일이 없습니다.'}), 400
    f = request.files['file']
    ext = (f.filename or '').rsplit('.', 1)[-1].lower()
    if ext not in ('xlsx', 'xls', 'csv'):
        return jsonify({'success': False, 'message': 'Excel(.xlsx) 또는 CSV(.csv) 파일만 가능합니다.'}), 400

    rows = read_upload_file(f)
    if not rows:
        return jsonify({'success': False, 'message': '파일을 읽을 수 없거나 데이터가 없습니다.'}), 400

    db = get_db()
    cur = db.cursor()
    ok = 0
    errs = []
    for i, row in enumerate(rows[1:], start=2):
        company_name = (row[0] if len(row) > 0 else '').strip()
        if not company_name:
            errs.append(f'행 {i}: 업체명 없음')
            continue
        try:
            code = generate_company_code(cur)
            cur.execute(
                """INSERT INTO sm_companies
                   (company_code, company_name, ceo_name, business_reg_no, corp_reg_no, address, phone)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (code, company_name,
                 row[1] if len(row) > 1 and row[1].strip() else None,
                 row[2] if len(row) > 2 and row[2].strip() else None,
                 row[3] if len(row) > 3 and row[3].strip() else None,
                 row[4] if len(row) > 4 and row[4].strip() else None,
                 row[5] if len(row) > 5 and row[5].strip() else None)
            )
            ok += 1
        except Exception as e:
            db.rollback()
            errs.append(f'행 {i}: {e}')
            cur = db.cursor()
    db.commit()
    return jsonify({'success': True, 'imported': ok, 'errors': errs})


# ============================================================
# 업체 담당자 API
# ============================================================

@app.route('/api/contacts', methods=['GET'])
@require_login
def api_ct_list():
    search     = (request.args.get('search') or '').strip()
    company_id = null_or_int(request.args.get('company_id'))
    cur = get_db().cursor()
    sql = """SELECT cc.*, c.company_name
             FROM sm_company_contacts cc
             JOIN sm_companies c ON cc.company_id = c.id"""
    params = []
    conds  = []
    if search:
        like = f'%{search}%'
        conds.append("(cc.name LIKE %s OR c.company_name LIKE %s)")
        params += [like, like]
    if company_id:
        conds.append("cc.company_id = %s")
        params.append(company_id)
    if conds:
        sql += ' WHERE ' + ' AND '.join(conds)
    sql += ' ORDER BY cc.created_at DESC'
    cur.execute(sql, params)
    return jsonify(serialize_rows(cur.fetchall()))


@app.route('/api/contacts/<int:ct_id>', methods=['GET'])
@require_login
def api_ct_get(ct_id):
    db = get_db()
    cur = db.cursor()
    cur.execute(
        """SELECT cc.*, c.company_name
           FROM sm_company_contacts cc
           JOIN sm_companies c ON cc.company_id = c.id
           WHERE cc.id = %s LIMIT 1""",
        (ct_id,)
    )
    row = cur.fetchone()
    if not row:
        return jsonify({'error': '존재하지 않습니다.'}), 404
    row = serialize_row(row)

    cur.execute(
        """SELECT m.id, m.meeting_type, m.meeting_datetime, m.scheduled_datetime,
                  m.content, m.conclusion, m.follow_up,
                  STRING_AGG(DISTINCT co.company_name, ', ') AS companies,
                  STRING_AGG(DISTINCT sr.name, ', ')         AS sales_reps
           FROM sm_meetings m
           JOIN sm_meeting_contacts mc   ON m.id = mc.meeting_id
           LEFT JOIN sm_meeting_companies mco ON m.id = mco.meeting_id
           LEFT JOIN sm_companies co    ON mco.company_id = co.id
           LEFT JOIN sm_meeting_sales_reps msr ON m.id = msr.meeting_id
           LEFT JOIN sm_sales_reps sr   ON msr.sales_rep_id = sr.id
           WHERE mc.contact_id = %s
           GROUP BY m.id
           ORDER BY m.meeting_datetime DESC NULLS LAST""",
        (ct_id,)
    )
    row['meeting_history'] = serialize_rows(cur.fetchall())

    cur.execute(
        """SELECT id, company_id, company_name, end_date, created_at
           FROM sm_contact_company_history
           WHERE contact_id = %s
           ORDER BY created_at ASC""",
        (ct_id,)
    )
    row['company_history'] = serialize_rows(cur.fetchall())
    return jsonify(row)


@app.route('/api/contacts', methods=['POST'])
@require_login
def api_ct_create():
    b = request.get_json(silent=True) or {}
    name       = (b.get('name') or '').strip()
    company_id = null_or_int(b.get('company_id'))
    if not name or not company_id:
        return jsonify({'success': False, 'message': '성명과 업체명은 필수입니다.'}), 400
    db = get_db()
    cur = db.cursor()
    cur.execute(
        """INSERT INTO sm_company_contacts
           (name, company_id, department, rank, position, job_type, office_phone, mobile_phone, email)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (name, company_id,
         null_or_str(b.get('department')), null_or_str(b.get('rank')),
         null_or_str(b.get('position')),   null_or_str(b.get('job_type')),
         null_or_str(b.get('office_phone')), null_or_str(b.get('mobile_phone')),
         null_or_str(b.get('email')))
    )
    new_id = cur.fetchone()['id']
    db.commit()
    return jsonify({'success': True, 'id': new_id})


@app.route('/api/contacts/<int:ct_id>', methods=['PUT'])
@require_login
def api_ct_update(ct_id):
    b = request.get_json(silent=True) or {}
    name        = (b.get('name') or '').strip()
    new_comp_id = null_or_int(b.get('company_id'))
    is_transfer = bool(b.get('is_transfer', False))
    if not name or not new_comp_id:
        return jsonify({'success': False, 'message': '성명과 업체명은 필수입니다.'}), 400

    db = get_db()
    cur = db.cursor()

    if is_transfer:
        cur.execute("SELECT company_id FROM sm_company_contacts WHERE id = %s LIMIT 1", (ct_id,))
        old = cur.fetchone()
        if old and old['company_id'] != new_comp_id:
            cur.execute(
                "SELECT company_name FROM sm_companies WHERE id = %s LIMIT 1",
                (old['company_id'],)
            )
            old_comp = cur.fetchone()
            if old_comp:
                cur.execute(
                    """INSERT INTO sm_contact_company_history
                       (contact_id, company_id, company_name, end_date)
                       VALUES (%s, %s, %s, CURRENT_DATE)""",
                    (ct_id, old['company_id'], old_comp['company_name'])
                )

    cur.execute(
        """UPDATE sm_company_contacts
           SET name=%s, company_id=%s, department=%s, rank=%s, position=%s,
               job_type=%s, office_phone=%s, mobile_phone=%s, email=%s
           WHERE id=%s""",
        (name, new_comp_id,
         null_or_str(b.get('department')), null_or_str(b.get('rank')),
         null_or_str(b.get('position')),   null_or_str(b.get('job_type')),
         null_or_str(b.get('office_phone')), null_or_str(b.get('mobile_phone')),
         null_or_str(b.get('email')), ct_id)
    )
    db.commit()
    return jsonify({'success': True})


@app.route('/api/contacts/<int:ct_id>', methods=['DELETE'])
@require_login
def api_ct_delete(ct_id):
    db = get_db()
    db.cursor().execute("DELETE FROM sm_company_contacts WHERE id = %s", (ct_id,))
    db.commit()
    return jsonify({'success': True})


@app.route('/api/contacts/template', methods=['GET'])
@require_login
def api_ct_template():
    return download_csv(
        '업체담당자_등록양식.csv',
        ['성명(필수)', '업체명(필수)', '업체코드', '부서명', '직급', '직책', '직군', '일반전화', '휴대폰번호', '이메일'],
        [['홍길동', '(주)예시업체', '20260417-001', '영업팀', '과장', '팀장', '영업',
          '02-0000-0000', '010-0000-0000', 'hong@example.com']]
    )


@app.route('/api/contacts/import', methods=['POST'])
@require_login
def api_ct_import():
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': '파일이 없습니다.'}), 400
    f = request.files['file']
    ext = (f.filename or '').rsplit('.', 1)[-1].lower()
    if ext not in ('xlsx', 'xls', 'csv'):
        return jsonify({'success': False, 'message': 'Excel(.xlsx) 또는 CSV(.csv) 파일만 가능합니다.'}), 400

    rows = read_upload_file(f)
    if not rows:
        return jsonify({'success': False, 'message': '파일을 읽을 수 없거나 데이터가 없습니다.'}), 400

    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT id, company_name, company_code FROM sm_companies")
    name_map = {}
    code_map = {}
    for c in cur.fetchall():
        name_map[c['company_name'].strip().lower()] = c['id']
        if c['company_code']:
            code_map[c['company_code'].strip()] = c['id']

    ok = 0
    errs = []
    # 컬럼: 성명(0) 업체명(1) 업체코드(2) 부서(3) 직급(4) 직책(5) 직군(6) 일반전화(7) 휴대폰(8) 이메일(9)
    for i, row in enumerate(rows[1:], start=2):
        row = [(c.strip() if c else '') for c in row]
        name      = row[0] if len(row) > 0 else ''
        comp_name = row[1] if len(row) > 1 else ''
        comp_code = row[2] if len(row) > 2 else ''
        if not name:
            errs.append(f'행 {i}: 성명 없음')
            continue
        if not comp_name and not comp_code:
            errs.append(f"행 {i}: 업체명 또는 업체코드가 없습니다 (읽은 성명: '{name}')")
            continue
        comp_id = None
        if comp_code:
            comp_id = code_map.get(comp_code.strip())
        if comp_id is None and comp_name:
            comp_id = name_map.get(comp_name.strip().lower())
        if comp_id is None:
            ref = comp_code if comp_code else comp_name
            errs.append(f"행 {i}: 업체 '{ref}' 를 찾을 수 없습니다 (업체명:'{comp_name}' 업체코드:'{comp_code}')")
            continue
        try:
            cur.execute(
                """INSERT INTO sm_company_contacts
                   (name, company_id, department, rank, position, job_type, office_phone, mobile_phone, email)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (name, comp_id,
                 row[3] if len(row) > 3 and row[3] else None,
                 row[4] if len(row) > 4 and row[4] else None,
                 row[5] if len(row) > 5 and row[5] else None,
                 row[6] if len(row) > 6 and row[6] else None,
                 row[7] if len(row) > 7 and row[7] else None,
                 row[8] if len(row) > 8 and row[8] else None,
                 row[9] if len(row) > 9 and row[9] else None)
            )
            ok += 1
        except Exception as e:
            db.rollback()
            errs.append(f'행 {i}: {e}')
            cur = db.cursor()

    db.commit()
    return jsonify({'success': True, 'imported': ok, 'errors': errs})


# ============================================================
# 미팅 API
# ============================================================

def mt_save_relations(db, meeting_id, company_ids, contact_ids, sales_rep_ids):
    cur = db.cursor()
    cur.execute("DELETE FROM sm_meeting_companies  WHERE meeting_id = %s", (meeting_id,))
    cur.execute("DELETE FROM sm_meeting_contacts   WHERE meeting_id = %s", (meeting_id,))
    cur.execute("DELETE FROM sm_meeting_sales_reps WHERE meeting_id = %s", (meeting_id,))
    seen_c, seen_n, seen_r = set(), set(), set()
    for cid in company_ids:
        cid = int(cid)
        if cid not in seen_c:
            cur.execute(
                "INSERT INTO sm_meeting_companies (meeting_id, company_id) VALUES (%s,%s)",
                (meeting_id, cid)
            )
            seen_c.add(cid)
    for nid in contact_ids:
        nid = int(nid)
        if nid not in seen_n:
            cur.execute(
                "INSERT INTO sm_meeting_contacts (meeting_id, contact_id) VALUES (%s,%s)",
                (meeting_id, nid)
            )
            seen_n.add(nid)
    for rid in sales_rep_ids:
        rid = int(rid)
        if rid not in seen_r:
            cur.execute(
                "INSERT INTO sm_meeting_sales_reps (meeting_id, sales_rep_id) VALUES (%s,%s)",
                (meeting_id, rid)
            )
            seen_r.add(rid)


def mt_get_relations(cur, meeting_id):
    cur.execute(
        """SELECT c.id, c.company_name
           FROM sm_meeting_companies mc
           JOIN sm_companies c ON mc.company_id = c.id
           WHERE mc.meeting_id = %s""",
        (meeting_id,)
    )
    companies = serialize_rows(cur.fetchall())

    cur.execute(
        """SELECT cc.id, cc.name, co.company_name, co.id AS company_id
           FROM sm_meeting_contacts mc
           JOIN sm_company_contacts cc ON mc.contact_id = cc.id
           JOIN sm_companies co ON cc.company_id = co.id
           WHERE mc.meeting_id = %s""",
        (meeting_id,)
    )
    contacts = serialize_rows(cur.fetchall())

    cur.execute(
        """SELECT sr.id, sr.name
           FROM sm_meeting_sales_reps msr
           JOIN sm_sales_reps sr ON msr.sales_rep_id = sr.id
           WHERE msr.meeting_id = %s""",
        (meeting_id,)
    )
    reps = serialize_rows(cur.fetchall())
    return companies, contacts, reps


@app.route('/api/meetings', methods=['GET'])
@require_login
def api_mt_list():
    sc = (request.args.get('search_company') or '').strip()
    ss = (request.args.get('search_content') or '').strip()
    cur = get_db().cursor()
    sql = """SELECT DISTINCT m.*, sr.name AS registered_by_name,
                    STRING_AGG(DISTINCT c.company_name, ', ') AS companies
             FROM sm_meetings m
             LEFT JOIN sm_sales_reps sr ON m.registered_by = sr.id
             LEFT JOIN sm_meeting_companies mc ON m.id = mc.meeting_id
             LEFT JOIN sm_companies c ON mc.company_id = c.id"""
    params = []
    conds  = []
    if sc:
        conds.append("c.company_name LIKE %s")
        params.append(f'%{sc}%')
    if ss:
        conds.append("m.content LIKE %s")
        params.append(f'%{ss}%')
    if conds:
        sql += ' WHERE ' + ' AND '.join(conds)
    sql += ' GROUP BY m.id, sr.name ORDER BY m.created_at DESC'
    cur.execute(sql, params)
    rows = serialize_rows(cur.fetchall())
    for row in rows:
        _, contacts, reps = mt_get_relations(cur, row['id'])
        row['contacts']   = contacts
        row['sales_reps'] = reps
    return jsonify(rows)


@app.route('/api/meetings/<int:mt_id>', methods=['GET'])
@require_login
def api_mt_get(mt_id):
    cur = get_db().cursor()
    cur.execute(
        """SELECT m.*, sr.name AS registered_by_name
           FROM sm_meetings m
           LEFT JOIN sm_sales_reps sr ON m.registered_by = sr.id
           WHERE m.id = %s LIMIT 1""",
        (mt_id,)
    )
    row = cur.fetchone()
    if not row:
        return jsonify({'error': '존재하지 않습니다.'}), 404
    row = serialize_row(row)
    companies, contacts, reps = mt_get_relations(cur, mt_id)
    row['companies']     = companies
    row['company_ids']   = [c['id'] for c in companies]
    row['contacts']      = contacts
    row['contact_ids']   = [c['id'] for c in contacts]
    row['sales_reps']    = reps
    row['sales_rep_ids'] = [r['id'] for r in reps]
    return jsonify(row)


@app.route('/api/meetings', methods=['POST'])
@require_login
def api_mt_create():
    b = request.get_json(silent=True) or {}
    db = get_db()
    cur = db.cursor()
    cur.execute(
        """INSERT INTO sm_meetings
           (meeting_type, scheduled_datetime, meeting_datetime,
            content, conclusion, follow_up, registered_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (null_or_str(b.get('meeting_type')),
         null_or_str(b.get('scheduled_datetime')),
         null_or_str(b.get('meeting_datetime')),
         null_or_str(b.get('content')),
         null_or_str(b.get('conclusion')),
         null_or_str(b.get('follow_up')),
         null_or_int(b.get('registered_by')))
    )
    new_id = cur.fetchone()['id']
    mt_save_relations(
        db, new_id,
        b.get('company_ids') or [],
        b.get('contact_ids') or [],
        b.get('sales_rep_ids') or []
    )
    db.commit()
    return jsonify({'success': True, 'id': new_id})


@app.route('/api/meetings/<int:mt_id>', methods=['PUT'])
@require_login
def api_mt_update(mt_id):
    b = request.get_json(silent=True) or {}
    db = get_db()
    cur = db.cursor()
    cur.execute(
        """UPDATE sm_meetings
           SET meeting_type=%s, scheduled_datetime=%s, meeting_datetime=%s,
               content=%s, conclusion=%s, follow_up=%s, registered_by=%s
           WHERE id=%s""",
        (null_or_str(b.get('meeting_type')),
         null_or_str(b.get('scheduled_datetime')),
         null_or_str(b.get('meeting_datetime')),
         null_or_str(b.get('content')),
         null_or_str(b.get('conclusion')),
         null_or_str(b.get('follow_up')),
         null_or_int(b.get('registered_by')),
         mt_id)
    )
    mt_save_relations(
        db, mt_id,
        b.get('company_ids') or [],
        b.get('contact_ids') or [],
        b.get('sales_rep_ids') or []
    )
    db.commit()
    return jsonify({'success': True})


@app.route('/api/meetings/<int:mt_id>', methods=['DELETE'])
@require_login
def api_mt_delete(mt_id):
    db = get_db()
    db.cursor().execute("DELETE FROM sm_meetings WHERE id = %s", (mt_id,))
    db.commit()
    return jsonify({'success': True})


# ============================================================
# 코드 관리 API
# ============================================================

@app.route('/api/codes', methods=['GET'])
@require_login
def api_code_list():
    cat = (request.args.get('category') or '').strip()
    cur = get_db().cursor()
    if cat:
        cur.execute(
            "SELECT * FROM sm_codes WHERE category = %s ORDER BY sort_order, id",
            (cat,)
        )
    else:
        cur.execute("SELECT * FROM sm_codes ORDER BY category, sort_order, id")
    return jsonify(serialize_rows(cur.fetchall()))


@app.route('/api/codes', methods=['POST'])
@require_login
def api_code_create():
    b   = request.get_json(silent=True) or {}
    cat = (b.get('category') or '').strip()
    val = (b.get('code_value') or '').strip()
    if not cat or not val:
        return jsonify({'success': False, 'message': '카테고리와 코드값은 필수입니다.'}), 400
    db = get_db()
    cur = db.cursor()
    cur.execute(
        "SELECT COALESCE(MAX(sort_order), -1) AS mx FROM sm_codes WHERE category = %s",
        (cat,)
    )
    max_order = cur.fetchone()['mx']
    cur.execute(
        "INSERT INTO sm_codes (category, code_value, sort_order) VALUES (%s,%s,%s) RETURNING id",
        (cat, val, max_order + 1)
    )
    new_id = cur.fetchone()['id']
    db.commit()
    return jsonify({'success': True, 'id': new_id})


@app.route('/api/codes/<int:code_id>', methods=['PUT'])
@require_login
def api_code_update(code_id):
    b = request.get_json(silent=True) or {}
    val = (b.get('code_value') or '').strip()
    if not val:
        return jsonify({'success': False, 'message': '코드값은 필수입니다.'}), 400
    db = get_db()
    db.cursor().execute("UPDATE sm_codes SET code_value = %s WHERE id = %s", (val, code_id))
    db.commit()
    return jsonify({'success': True})


@app.route('/api/codes/<int:code_id>', methods=['DELETE'])
@require_login
def api_code_delete(code_id):
    db = get_db()
    db.cursor().execute("DELETE FROM sm_codes WHERE id = %s", (code_id,))
    db.commit()
    return jsonify({'success': True})


# ============================================================
# BASE_PATH 접두어 API 라우트 추가
# ============================================================

if _BASE:
    _api_rules = [
        ('/api/login',                  'POST',              api_login),
        ('/api/logout',                 'POST',              api_logout),
        ('/api/change-password',        'POST',              api_change_password),
        ('/api/session',                'GET',               api_session),
        ('/api/dashboard',              'GET',               api_dashboard),
        ('/api/sales-reps',             'GET',               api_sr_list),
        ('/api/sales-reps',             'POST',              api_sr_create),
        ('/api/sales-reps/<int:rep_id>','GET',               api_sr_get),
        ('/api/sales-reps/<int:rep_id>','PUT',               api_sr_update),
        ('/api/sales-reps/<int:rep_id>','DELETE',            api_sr_delete),
        ('/api/companies/template',     'GET',               api_comp_template),
        ('/api/companies/import',       'POST',              api_comp_import),
        ('/api/companies',              'GET',               api_comp_list),
        ('/api/companies',              'POST',              api_comp_create),
        ('/api/companies/<int:comp_id>','GET',               api_comp_get),
        ('/api/companies/<int:comp_id>','PUT',               api_comp_update),
        ('/api/companies/<int:comp_id>','DELETE',            api_comp_delete),
        ('/api/contacts/template',      'GET',               api_ct_template),
        ('/api/contacts/import',        'POST',              api_ct_import),
        ('/api/contacts',               'GET',               api_ct_list),
        ('/api/contacts',               'POST',              api_ct_create),
        ('/api/contacts/<int:ct_id>',   'GET',               api_ct_get),
        ('/api/contacts/<int:ct_id>',   'PUT',               api_ct_update),
        ('/api/contacts/<int:ct_id>',   'DELETE',            api_ct_delete),
        ('/api/meetings',               'GET',               api_mt_list),
        ('/api/meetings',               'POST',              api_mt_create),
        ('/api/meetings/<int:mt_id>',   'GET',               api_mt_get),
        ('/api/meetings/<int:mt_id>',   'PUT',               api_mt_update),
        ('/api/meetings/<int:mt_id>',   'DELETE',            api_mt_delete),
        ('/api/codes',                  'GET',               api_code_list),
        ('/api/codes',                  'POST',              api_code_create),
        ('/api/codes/<int:code_id>',    'PUT',               api_code_update),
        ('/api/codes/<int:code_id>',    'DELETE',            api_code_delete),
    ]

    # 같은 (full_path, method) 조합만 한 번씩 등록
    _registered_bp = set()
    for _path, _method, _view in _api_rules:
        _full_path = _BASE + _path
        _key = (_full_path, _method)
        if _key in _registered_bp:
            continue
        _registered_bp.add(_key)
        # endpoint 이름: 'bp_' + 뷰이름 + '_' + 메서드 (중복 없음)
        _ep_name = f'bp_{_view.__name__}_{_method.lower()}'
        app.add_url_rule(
            _full_path,
            endpoint=_ep_name,
            view_func=_view,
            methods=[_method]
        )


# ============================================================
# 에러 핸들러
# ============================================================

@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Not Found'}), 404
    return '<h1>404 Not Found</h1>', 404


@app.errorhandler(500)
def internal_error(e):
    return jsonify({'success': False, 'message': f'서버 오류: {e}'}), 500


# ============================================================
# 개발 서버 실행
# ============================================================

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
