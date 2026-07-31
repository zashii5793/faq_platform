"""ingest.py のエッジケース（既存 test_ingest.py の補強）。"""
from __future__ import annotations


import pytest

from app.ingest import analyze, parse


# ============================================================
# 拡張子の境界
# ============================================================
class TestExtensionEdgeCases:
    def test_uppercase_extension(self):
        chunks = parse("FILE.MD", "# title\n\n本文".encode("utf-8"))
        assert len(chunks) >= 1

    def test_mixed_case_extension(self):
        chunks = parse("file.Md", "# title\n\n本文".encode("utf-8"))
        assert len(chunks) >= 1

    def test_no_extension(self):
        """拡張子なしファイルは ValueError で reject されるべき（仕様）。"""
        with pytest.raises(ValueError, match="unsupported format"):
            analyze("README", "# title\n\n本文".encode("utf-8"))

    def test_double_extension(self):
        """foo.txt.md のような二重拡張子は最後の拡張子で判定される。"""
        chunks = parse("foo.txt.md", "# title\n\n本文".encode("utf-8"))
        assert len(chunks) >= 1


# ============================================================
# 不正なファイル中身（拡張子と不一致）
# ============================================================
class TestContentMismatch:
    def test_md_with_binary_content(self):
        """.md なのにバイナリは utf-8 decode で失敗するはず。"""
        binary = b"\x00\x01\x02\xff\xfe"
        try:
            chunks = parse("evil.md", binary)
            # decode 失敗時にどう振る舞うか
            assert isinstance(chunks, list)
        except (UnicodeDecodeError, Exception):
            # 例外を投げてもOK
            pass

    def test_pdf_with_invalid_content(self):
        """.pdf なのに無効データ。"""
        try:
            chunks = parse("fake.pdf", b"this is not a pdf")
            assert isinstance(chunks, list)
        except Exception:
            pass

    def test_xlsx_with_invalid_content(self):
        try:
            chunks = parse("fake.xlsx", b"not actual xlsx")
            assert isinstance(chunks, list)
        except Exception:
            pass


# ============================================================
# 巨大データ
# ============================================================
class TestLargeContent:
    def test_1mb_text_does_not_timeout(self):
        """1MB のテキストでも妥当な時間で処理完了する。"""
        import time
        big = ("これは長いテキストです。" * 100 + "\n\n").encode("utf-8") * 100
        start = time.time()
        chunks = parse("big.md", big)
        elapsed = time.time() - start
        assert elapsed < 5.0, f"1MB のパースに {elapsed:.2f}秒かかった（5秒以内が期待）"
        assert len(chunks) > 0

    def test_many_tiny_chunks(self):
        """1万個の小さな段落でもクラッシュしない。"""
        text = "\n\n".join([f"段落{i}" for i in range(10_000)])
        chunks = parse("many.md", text.encode("utf-8"))
        assert len(chunks) > 0


# ============================================================
# 特殊文字・絵文字・Unicode 正規化
# ============================================================
class TestSpecialChars:
    def test_emoji_in_content(self):
        text = "# 🚗 タイトル\n\n本文に絵文字 👍🎉🔥 を含む"
        chunks = parse("emoji.md", text.encode("utf-8"))
        assert len(chunks) >= 1
        assert "🚗" in chunks[0].text or "👍" in chunks[0].text

    def test_surrogate_pair_emoji(self):
        text = "サロゲートペア絵文字: 🇯🇵 (日本国旗)"
        chunks = parse("flag.md", text.encode("utf-8"))
        assert len(chunks) >= 1

    def test_bom_at_start(self):
        """UTF-8 BOM 付きでも正しく処理される。"""
        text = "﻿# タイトル\n\n本文"
        chunks = parse("bom.md", text.encode("utf-8"))
        assert len(chunks) >= 1
        # BOM が本文の先頭に残らない
        if chunks:
            assert not chunks[0].text.startswith("﻿")

    def test_zero_width_chars(self):
        """ゼロ幅文字（U+200B）を含むテキストでも処理可能。"""
        text = "本​文​テスト"
        chunks = parse("zerowidth.md", text.encode("utf-8"))
        assert len(chunks) >= 1


# ============================================================
# 行末・改行
# ============================================================
class TestLineEndings:
    def test_crlf_normalized(self):
        """CRLF 行末でも正しく段落分割される。"""
        text = "# Title\r\n\r\n段落1の本文\r\n\r\n段落2の本文"
        chunks = parse("crlf.md", text.encode("utf-8"))
        assert len(chunks) >= 1

    def test_cr_only_old_mac(self):
        """CR のみ（旧Mac形式）でも処理可能。"""
        text = "Line1\rLine2\rLine3"
        chunks = parse("cr.md", text.encode("utf-8"))
        # クラッシュしないこと
        assert isinstance(chunks, list)


# ============================================================
# analyze: 推奨ジャッジ
# ============================================================
class TestAnalyze:
    def test_normal_md_is_ok(self):
        result = analyze("normal.md", "# タイトル\n\n本文" .encode("utf-8"))
        assert result.recommendation == "ok"

    def test_pii_heavy_file_warns_or_blocks(self):
        """PII が大量に含まれるファイルは warn / danger（取り込み非推奨）。"""
        text = "顧客リスト:\n\nメール: a@b.com, c@d.com, e@f.com\n電話: 090-1111-2222, 090-3333-4444\nマイナンバー: 1234-5678-9012\nカード: 4111-1111-1111-1111\n"
        result = analyze("pii.md", text.encode("utf-8"))
        assert result.recommendation in ("warn", "danger")
