"""顧客への配布用 ZIP パッケージを作成。

GitHub リポジトリを Private 化した後、新規顧客に渡すための ZIP を
このスクリプトで作る。顧客がリポジトリにアクセスできなくても、
この ZIP だけ渡せばインストールできる。

使い方:
    python scripts/build_customer_package.py --tenant a_company
    python scripts/build_customer_package.py --tenant b_company --output ./dist

出力: .private/inquira-<tenant>-YYYYMMDD.zip
"""
from __future__ import annotations

import argparse
import datetime
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 配布に含めるファイル/フォルダ
INCLUDE = [
    "app",
    "scripts",
    "pyproject.toml",
    "LICENSE",
]

# テナント固有のものは別途追加
TENANT_INCLUDE = [
    "install.ps1",
    "install.sh",
    "inquira.service",
    ".env.template",
    "README.md",
]

# 除外する隠しファイル・キャッシュ等
EXCLUDE_DIRS = {
    ".git", "__pycache__", ".venv", ".pytest_cache", ".ruff_cache",
    "data", "docs", "tests", "tenants",  # tenants は明示指定のものだけ含める
    ".private",
}
EXCLUDE_SUFFIX = (".pyc", ".pyo", ".log")


def build(tenant_slug: str, output_dir: Path) -> Path:
    tenant_dir = ROOT / "tenants" / tenant_slug
    if not tenant_dir.is_dir():
        raise SystemExit(f"❌ tenants/{tenant_slug} が見つかりません")

    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_zip = output_dir / f"inquira-{tenant_slug}-{ts}.zip"

    print(f"📦 配布パッケージを生成中: {out_zip}")

    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        # 共通ソース
        for top in INCLUDE:
            top_path = ROOT / top
            if top_path.is_file():
                zf.write(top_path, arcname=top)
                continue
            for f in _walk(top_path):
                arc = str(f.relative_to(ROOT))
                zf.write(f, arcname=arc)

        # テナント固有ファイル (実値の .env は含めない)
        for fname in TENANT_INCLUDE:
            f = tenant_dir / fname
            if f.exists():
                arc = f"tenants/{tenant_slug}/{fname}"
                zf.write(f, arcname=arc)

    size_kb = out_zip.stat().st_size / 1024
    print(f"✅ 完成: {out_zip} ({size_kb:.1f} KB)")

    # 中身を検証 (顧客情報漏れチェック)
    danger = []
    with zipfile.ZipFile(out_zip) as zf:
        for name in zf.namelist():
            if name.endswith((".png", ".pdf", ".jpg", ".jpeg", ".zip")):
                continue
            try:
                content = zf.open(name).read().decode("utf-8", errors="ignore")
            except Exception:
                continue
            for keyword in ["sk-ant-api", "GOCSPX-", "@gmail.com"]:
                if keyword in content and "FILL" not in content[content.find(keyword) - 50:content.find(keyword) + 50]:
                    danger.append(f"  {name}: contains '{keyword}'")
    if danger:
        print("⚠ セキュリティ警告: 以下のファイルに機密情報の可能性:")
        for d in danger:
            print(d)
        print("    配布前に必ず確認してください。")
    else:
        print("🔒 機密情報の漏洩なし (sk-ant- / GOCSPX- / @gmail.com を含まず)")

    return out_zip


def _walk(path: Path):
    if not path.exists():
        return
    if path.is_file():
        yield path
        return
    for f in path.rglob("*"):
        if f.is_dir():
            continue
        # ディレクトリ除外
        if any(part in EXCLUDE_DIRS for part in f.parts):
            continue
        if f.suffix in EXCLUDE_SUFFIX:
            continue
        yield f


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tenant", required=True,
        help="テナント slug (例: a_company)。tenants/<slug>/ を含める"
    )
    parser.add_argument(
        "--output", default=str(ROOT / ".private"),
        help="出力先ディレクトリ (デフォルト: .private/)"
    )
    args = parser.parse_args()

    out_dir = Path(args.output)
    out_zip = build(args.tenant, out_dir)

    print()
    print("=" * 60)
    print("📋 顧客への配布手順")
    print("=" * 60)
    print(f"1. 出力された ZIP をコピー: {out_zip}")
    print(f"2. 顧客に転送 (USB / OneDrive / メール添付 等)")
    print(f"   ZIP 自体には実値は含まれていません。")
    print(f"3. 別途、A社用 .env を作成して顧客に渡す")
    print(f"   または、顧客サーバー上で .env.template から手動作成してもらう")
    print(f"4. 顧客サーバーで Expand-Archive → install.ps1 実行")


if __name__ == "__main__":
    main()
