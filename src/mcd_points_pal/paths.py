"""仓库内数据目录（`fixtures/` 与 `web/`）的定位。

**为什么需要专门做这件事**：这套代码有三种运行方式，数据目录在磁盘上的
相对位置各不相同。写死一种，另外两种就会报出让人看不懂的 FileNotFoundError。

  1. 源码直跑 —— `PYTHONPATH=src python3 -m mcd_points_pal ...`（clone 即用）
  2. 可编辑安装 —— `pip install -e .`
     以上两种，数据目录都在**本文件的上级**（仓库根 / 包内）
  3. 安装后运行 —— `pip install .` 之后敲 `mcd-points-pal ...`
     此时本文件已被复制进 site-packages，磁盘上离数据目录很远，
     只能从**当前工作目录**往上回溯

策略：从「本文件所在位置」和「当前工作目录」两处分别向上回溯，
取第一个「目录存在**且**带有标志文件」的结果。标志文件是必要的 ——
否则 `/` 或用户主目录下任意一个同名空目录都会被误认成数据目录。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parents[1]  # src/mcd_points_pal/ -> 仓库根


def locate(name: str, marker: str) -> Path:
    """找出带 `marker` 标志文件的 `name` 目录。

    找不到时返回『按仓库结构推断』的路径 —— 不抛异常，让调用方在真正
    读取时给出更有上下文的提示（比如告诉用户可以用 --fixtures 指定）。
    """
    for start in (PACKAGE_DIR, Path.cwd().resolve()):
        for parent in (start, *start.parents):
            candidate = parent / name
            if (candidate / marker).is_file():
                return candidate
    return REPO_ROOT / name


FIXTURES = locate("fixtures", "points_products.json")
WEB_DIR = locate("web", "index.html")

_HOWTO = (
    "请任选一种方式：\n"
    "  1. 在 git clone 出来的仓库目录里运行（推荐）\n"
    "  2. 显式指定目录：--fixtures /路径/to/fixtures\n"
    "  3. 改用实时模式：加 --live 并设置环境变量 MCD_MCP_TOKEN\n"
)


def missing_hint(path: Optional[Path] = None, what: str = "离线快照目录") -> str:
    """数据目录缺失时给用户看的话 —— 要说清「怎么办」，而不只是「没找到」。

    自动定位失败时不报路径：那时推断出来的路径（site-packages 深处）
    对用户没有任何指导意义，反而会让人以为是自己路径写错了。
    """
    if path is None:
        return "没找到%s（已从包安装位置与当前目录分别向上查找）。\n\n%s" % (what, _HOWTO)
    return "%s不存在：%s\n\n%s" % (what, path, _HOWTO)
