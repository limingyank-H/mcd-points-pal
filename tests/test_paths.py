"""数据目录定位的回归测试。

背景：`pip install .` 之后从无关目录运行，曾经会抛出一条只有路径的
`FileNotFoundError: .../site-packages/../fixtures/points_products.json`，
用户完全不知道该怎么办。这里把「三种运行方式都能找到数据目录」
和「找不到时说人话」两件事钉住。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from mcd_points_pal import paths  # noqa: E402
from mcd_points_pal.datasource import FixtureSource  # noqa: E402


def test_repo_data_directories_are_discoverable():
    """clone 下来直接跑时，两个数据目录都要能被找到。"""
    assert (paths.FIXTURES / "points_products.json").is_file()
    assert (paths.WEB_DIR / "index.html").is_file()


def test_locate_falls_back_to_working_directory(tmp_path, monkeypatch):
    """`pip install .` 后在克隆目录里运行 —— 只能靠当前工作目录回溯。

    构造一个「包内没有、工作目录里有」的场景来验证这条回退路径。
    """
    fake = tmp_path / "fixtures"
    fake.mkdir()
    (fake / "marker.json").write_text("{}", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    assert paths.locate("fixtures", "marker.json") == fake


def test_locate_requires_the_marker_file(tmp_path, monkeypatch):
    """同名空目录不算数 —— 否则用户主目录下一个叫 fixtures 的文件夹就会骗过定位。"""
    (tmp_path / "fixtures").mkdir()  # 有目录，但没有标志文件
    monkeypatch.chdir(tmp_path)
    assert paths.locate("fixtures", "marker.json") != tmp_path / "fixtures"


def test_explicit_missing_directory_tells_you_what_to_do(tmp_path):
    """显式指定的目录不存在时，要带上路径和三条出路。"""
    with pytest.raises(FileNotFoundError) as excinfo:
        FixtureSource(tmp_path / "nope")

    message = str(excinfo.value)
    assert "--fixtures" in message
    assert "--live" in message
    assert str(tmp_path / "nope") in message


def test_auto_detected_failure_does_not_leak_a_useless_path(monkeypatch):
    """自动定位失败时不要报一个 site-packages 深处的路径 —— 那是误导。"""
    from mcd_points_pal import datasource

    monkeypatch.setattr(datasource, "FIXTURES", Path("/definitely/not/here"))
    with pytest.raises(FileNotFoundError) as excinfo:
        FixtureSource()

    message = str(excinfo.value)
    assert "/definitely/not/here" not in message
    assert "--fixtures" in message
