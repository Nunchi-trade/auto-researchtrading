"""데이터 다운로드 진입점. Usage: uv run upbit_prepare_run.py"""
import argparse
from upbit_prepare import download_upbit_data, DATA_DIR

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upbit 데이터 다운로드")
    parser.add_argument("--symbols", nargs="+", default=None,
                        help="다운로드할 심볼 (기본: 전체)")
    args = parser.parse_args()

    print(f"캐시 디렉토리: {DATA_DIR}")
    print("Upbit 데이터 다운로드 중...")
    download_upbit_data(args.symbols)
    print("완료! 백테스트 준비됨.")
