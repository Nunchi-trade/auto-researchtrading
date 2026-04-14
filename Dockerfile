FROM python:3.12-slim AS base

# uv 설치 (공식 이미지 사용)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# 의존성 파일 먼저 복사 (레이어 캐시 활용)
COPY pyproject.toml uv.lock ./

# 의존성 설치 및 PATH 설정
RUN uv sync --frozen --no-dev --no-install-project
ENV PATH="/app/.venv/bin:$PATH"

# 소스 코드 복사
COPY *.py ./
COPY benchmarks/ ./benchmarks/
COPY tests/ ./tests/

# 데이터 캐시 디렉토리 (볼륨 마운트 위치)
RUN mkdir -p /root/.cache/autotrader/data /root/.cache/autotrader_upbit/data

CMD ["uv", "run", "backtest.py"]
