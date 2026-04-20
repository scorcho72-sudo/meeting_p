#!/usr/bin/env python3
"""Supabase 연결 가능한 주소 자동 탐색"""
import ssl
import socket
import pg8000.dbapi

PASS = 'pwRYSSsSwRF3BfDB'
DB   = 'postgres'
PROJ = 'qmqrjenbuggphtwcblle'

# 시도할 연결 목록 (host, port, user)
candidates = [
    # 직접 연결
    (f'db.{PROJ}.supabase.co',                        5432, 'postgres'),
    # Transaction Pooler - 주요 리전
    (f'aws-0-ap-northeast-2.pooler.supabase.com',     6543, f'postgres.{PROJ}'),
    (f'aws-0-ap-northeast-1.pooler.supabase.com',     6543, f'postgres.{PROJ}'),
    (f'aws-0-ap-southeast-1.pooler.supabase.com',     6543, f'postgres.{PROJ}'),
    (f'aws-0-us-east-1.pooler.supabase.com',          6543, f'postgres.{PROJ}'),
    (f'aws-0-us-west-1.pooler.supabase.com',          6543, f'postgres.{PROJ}'),
    # Session Pooler (port 5432)
    (f'aws-0-ap-northeast-2.pooler.supabase.com',     5432, f'postgres.{PROJ}'),
    (f'aws-0-ap-northeast-1.pooler.supabase.com',     5432, f'postgres.{PROJ}'),
]

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

print("=" * 60)
print("Supabase 연결 테스트")
print("=" * 60)

success = None
for host, port, user in candidates:
    print(f"\n시도: {user}@{host}:{port}")
    # 소켓 연결 테스트
    try:
        s = socket.create_connection((host, port), timeout=5)
        s.close()
        print(f"  ✔ 소켓 연결 OK")
    except Exception as e:
        print(f"  ✘ 소켓 실패: {e}")
        continue

    # pg8000 연결 테스트
    try:
        conn = pg8000.dbapi.connect(
            host=host, port=port, database=DB,
            user=user, password=PASS, ssl_context=ssl_ctx
        )
        cur = conn.cursor()
        cur.execute("SELECT 1")
        conn.close()
        print(f"  ✔ DB 연결 성공!")
        success = (host, port, user)
        break
    except Exception as e:
        print(f"  ✘ DB 연결 실패: {e}")

print("\n" + "=" * 60)
if success:
    host, port, user = success
    uri = f"postgresql://{user}:{PASS}@{host}:{port}/{DB}"
    print(f"✅ 연결 성공한 URI:")
    print(f"   {uri}")
    print("\nconfig.py의 DB_URI를 위 값으로 교체하세요.")
else:
    print("❌ 모든 연결 실패")
    print("Supabase 대시보드 → Connect → Connection pooling URI를 확인하세요.")
print("=" * 60)
