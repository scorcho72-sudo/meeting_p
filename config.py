# ============================================================
# 영업관리 시스템 - 데이터베이스 및 앱 설정
# 환경에 맞게 아래 정보를 수정하세요.
# ============================================================

DB_URI  = 'postgresql://postgres.qmqrjenbuggphtwcblle:pwRYSSsSwRF3BfDB@aws-1-ap-northeast-2.pooler.supabase.com:5432/postgres'

# URI에서 개별 파싱 (pg8000용)
import urllib.parse as _up
_u = _up.urlparse(DB_URI)
DB_HOST = _u.hostname
DB_PORT = _u.port or 5432
DB_NAME = _u.path.lstrip('/')
DB_USER = _u.username
DB_PASS = _u.password

# ============================================================
# 서브디렉토리 설정
# 루트(/)에 설치 시 → ''
# /meet 폴더에 설치 시 → '/meet'
# ============================================================
BASE_PATH = ''

SECRET_KEY = 'sales_mgmt_secret_2026_security_change_me'
