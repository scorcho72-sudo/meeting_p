#!/usr/bin/env python3
# ============================================================
# 영업관리 시스템 - DB 테이블 생성 + 초기 데이터
# 실행: python install.py
# ============================================================

import sys
import ssl
import pg8000.dbapi
from werkzeug.security import generate_password_hash

try:
    from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS
except ImportError:
    print("config.py 파일을 찾을 수 없습니다.")
    sys.exit(1)


DDL = """
CREATE TABLE IF NOT EXISTS sm_users (
    id         BIGSERIAL PRIMARY KEY,
    username   VARCHAR(60)  NOT NULL UNIQUE,
    password   VARCHAR(255) NOT NULL,
    created_at TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sm_sales_reps (
    id         BIGSERIAL PRIMARY KEY,
    emp_no     VARCHAR(30)  NOT NULL UNIQUE,
    name       VARCHAR(50)  NOT NULL,
    rank       VARCHAR(30),
    position   VARCHAR(30),
    phone      VARCHAR(30),
    email      VARCHAR(100),
    created_at TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sm_companies (
    id               BIGSERIAL PRIMARY KEY,
    company_code     VARCHAR(20)  UNIQUE,
    company_name     VARCHAR(200) NOT NULL,
    ceo_name         VARCHAR(50),
    business_reg_no  VARCHAR(30),
    corp_reg_no      VARCHAR(30),
    address          TEXT,
    phone            VARCHAR(30),
    created_at       TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sm_codes (
    id         BIGSERIAL PRIMARY KEY,
    category   VARCHAR(30)  NOT NULL,
    code_value VARCHAR(100) NOT NULL,
    sort_order INT          NOT NULL DEFAULT 0,
    created_at TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sm_company_solutions (
    company_id  BIGINT NOT NULL REFERENCES sm_companies(id) ON DELETE CASCADE,
    solution_id BIGINT NOT NULL REFERENCES sm_codes(id)     ON DELETE CASCADE,
    PRIMARY KEY (company_id, solution_id)
);

CREATE TABLE IF NOT EXISTS sm_company_contacts (
    id           BIGSERIAL PRIMARY KEY,
    name         VARCHAR(50)  NOT NULL,
    company_id   BIGINT       NOT NULL REFERENCES sm_companies(id) ON DELETE CASCADE,
    department   VARCHAR(80),
    rank         VARCHAR(30),
    position     VARCHAR(30),
    job_type     VARCHAR(30),
    office_phone VARCHAR(30),
    mobile_phone VARCHAR(30),
    email        VARCHAR(100),
    created_at   TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sm_contact_company_history (
    id           BIGSERIAL PRIMARY KEY,
    contact_id   BIGINT       NOT NULL REFERENCES sm_company_contacts(id) ON DELETE CASCADE,
    company_id   BIGINT,
    company_name VARCHAR(200) NOT NULL,
    end_date     DATE,
    created_at   TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sm_meetings (
    id                 BIGSERIAL PRIMARY KEY,
    meeting_type       VARCHAR(20),
    scheduled_datetime TIMESTAMP,
    meeting_datetime   TIMESTAMP,
    content            TEXT,
    conclusion         TEXT,
    follow_up          TEXT,
    registered_by      BIGINT REFERENCES sm_sales_reps(id) ON DELETE SET NULL,
    created_at         TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sm_meeting_companies (
    meeting_id BIGINT NOT NULL REFERENCES sm_meetings(id)  ON DELETE CASCADE,
    company_id BIGINT NOT NULL REFERENCES sm_companies(id) ON DELETE CASCADE,
    PRIMARY KEY (meeting_id, company_id)
);

CREATE TABLE IF NOT EXISTS sm_meeting_contacts (
    meeting_id BIGINT NOT NULL REFERENCES sm_meetings(id)         ON DELETE CASCADE,
    contact_id BIGINT NOT NULL REFERENCES sm_company_contacts(id) ON DELETE CASCADE,
    PRIMARY KEY (meeting_id, contact_id)
);

CREATE TABLE IF NOT EXISTS sm_meeting_sales_reps (
    meeting_id   BIGINT NOT NULL REFERENCES sm_meetings(id)   ON DELETE CASCADE,
    sales_rep_id BIGINT NOT NULL REFERENCES sm_sales_reps(id) ON DELETE CASCADE,
    PRIMARY KEY (meeting_id, sales_rep_id)
);
"""


def connect():
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    return pg8000.dbapi.connect(
        host=DB_HOST, port=DB_PORT,
        database=DB_NAME, user=DB_USER, password=DB_PASS,
        ssl_context=ssl_ctx
    )


def run_ddl(conn):
    cur = conn.cursor()
    # pg8000은 한 번에 여러 DDL 실행이 안 되므로 구문별로 분리
    statements = [s.strip() for s in DDL.split(';') if s.strip()]
    for stmt in statements:
        cur.execute(stmt)
    conn.commit()
    cur.close()
    print("[OK] 테이블 생성 완료")


def fetchone(cur):
    row = cur.fetchone()
    if row is None:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def insert_initial_data(conn):
    cur = conn.cursor()

    # 관리자 계정 (admin / admin1234)
    cur.execute("SELECT id FROM sm_users WHERE username = %s", ('admin',))
    if not cur.fetchone():
        hashed = generate_password_hash('admin1234')
        cur.execute(
            "INSERT INTO sm_users (username, password) VALUES (%s, %s)",
            ('admin', hashed)
        )
        print("[OK] 관리자 계정 생성: admin / admin1234")
    else:
        print("[OK] 관리자 계정 이미 존재")

    # 기본 코드 데이터
    default_codes = [
        ('직급', ['사원', '주임', '대리', '과장', '차장', '부장', '이사', '상무', '전무', '부사장', '사장', '대표이사']),
        ('직책', ['팀원', '팀장', '파트장', '실장', '본부장', '센터장', '대표']),
        ('직군', ['영업', '기술', '개발', '마케팅', '기획', '관리', '경영']),
        ('솔루션', [
            '방화벽', 'IPS', 'IDS', 'VPN', 'WAF', 'DDoS 방어', '취약점진단', '보안관제',
            'EDR', 'NAC', 'DLP', 'SIEM', 'ESM', 'PAM', 'IAM', 'SSO',
            '망분리', '암호화', '백신/Anti-Malware', '이메일 보안',
        ]),
    ]
    for cat, values in default_codes:
        cur.execute("SELECT COUNT(*) AS cnt FROM sm_codes WHERE category = %s", (cat,))
        row = cur.fetchone()
        cnt = row[0] if row else 0
        if cnt == 0:
            for i, val in enumerate(values):
                cur.execute(
                    "INSERT INTO sm_codes (category, code_value, sort_order) VALUES (%s, %s, %s)",
                    (cat, val, i)
                )
            print(f"[OK] 코드 삽입: {cat} ({len(values)}건)")
        else:
            print(f"[OK] 코드 이미 존재: {cat}")

    conn.commit()
    cur.close()


def main():
    print("=" * 50)
    print("영업관리 시스템 - 설치 스크립트 (Supabase)")
    print("=" * 50)
    print(f"DB: {DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}")
    print()

    try:
        conn = connect()
        print("[OK] Supabase DB 연결 성공")
    except Exception as e:
        print(f"[ERROR] DB 연결 실패: {e}")
        print("config.py의 DB_PASS(비밀번호)를 확인하세요.")
        sys.exit(1)

    try:
        run_ddl(conn)
        insert_initial_data(conn)
    except Exception as e:
        print(f"[ERROR] 설치 중 오류: {e}")
        conn.rollback()
    finally:
        conn.close()

    print()
    print("=" * 50)
    print("설치 완료!")
    print("python app.py 로 서버를 시작하세요.")
    print("접속: http://localhost:5000")
    print("기본 계정: admin / admin1234")
    print("=" * 50)


if __name__ == '__main__':
    main()
