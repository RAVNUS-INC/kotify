"""공통 Jinja2Templates 인스턴스 + 글로벌 헬퍼.

모든 route는 여기서 templates를 import한다.
각 route가 자체 인스턴스를 만들면 csrf_token 같은 글로벌이
한 인스턴스에만 등록되어 다른 route에서 500 에러가 발생한다.
"""
from __future__ import annotations

from fastapi.templating import Jinja2Templates

from app.security.csrf import get_csrf_token

templates = Jinja2Templates(directory="app/templates")

# 모든 템플릿에서 {{ csrf_token(request) }} 사용 가능
templates.env.globals["csrf_token"] = get_csrf_token
