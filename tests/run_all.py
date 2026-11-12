"""运行全部测试：test_*.py 按顺序跑，live_*.py 并行跑（各自启动模拟服务器和机器人进程，端口、数据库、心跳文件都是自己的）。
每个文件的输出先收起来，全部跑完后按文件名顺序打印；最后列出失败的文件，有失败时退出码为 1。
本地和 CI 用同一个脚本。

用法（项目根目录下）：
  python tests/run_all.py          # live 测试的并行数默认是 CPU 核数
  python tests/run_all.py -j 4     # 指定并行数（CI 用 6，见 .github/workflows/test.yml）
  python tests/run_all.py live_media_test.py test_db.py   # 只跑这几个
"""
import argparse
import asyncio
import os
import sys
import time

TESTS = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(TESTS)
TIMEOUT = 600  # 秒：单个文件卡住时不要拖住整次运行
GITHUB = os.getenv("GITHUB_ACTIONS") == "true"


async def run(name: str, sem: asyncio.Semaphore) -> tuple[str, int, str, float]:
    async with sem:
        start = time.time()
        proc = await asyncio.create_subprocess_exec(
            sys.executable, os.path.join(TESTS, name), cwd=PROJECT,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), TIMEOUT)
            code = proc.returncode
        except TimeoutError:
            proc.kill()
            out, _ = await proc.communicate()
            out += f"\n超时：{TIMEOUT} 秒还没跑完，已结束\n".encode()
            code = -1
        return name, code, out.decode(errors="replace"), time.time() - start


def show(name: str, code: int, out: str, secs: float) -> None:
    status = "ok" if code == 0 else f"FAILED (exit {code})"
    title = f"{name}  {status}  {secs:.0f}s"
    print(f"::group::{title}" if GITHUB else f"===== {title}")
    print(out.rstrip())
    if GITHUB:
        print("::endgroup::")
    sys.stdout.flush()


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 4, help="live 测试的并行数")
    ap.add_argument("files", nargs="*", help="只跑这些文件（默认全部）")
    args = ap.parse_args()

    names = args.files or sorted(f for f in os.listdir(TESTS)
                                 if f.endswith(".py") and f.startswith(("test_", "live_")))
    names = [os.path.basename(f) for f in names]
    unit = [n for n in names if n.startswith("test_")]
    live = [n for n in names if not n.startswith("test_")]
    start = time.time()

    results = []
    one = asyncio.Semaphore(1)
    for n in unit:  # 很快，按顺序跑
        results.append(r := await run(n, one))
        show(*r)
    many = asyncio.Semaphore(max(1, args.jobs))
    live_results = await asyncio.gather(*(run(n, many) for n in live))
    for r in live_results:  # 按文件名顺序打印，不按完成先后
        show(*r)
    results += live_results

    failed = [name for name, code, _, _ in results if code != 0]
    slowest = sorted(live_results, key=lambda r: -r[3])[:3]
    print(f"\n{len(results) - len(failed)}/{len(results)} files passed in {time.time() - start:.0f}s "
          f"(live tests {args.jobs} at a time; slowest: "
          + ", ".join(f"{n} {s:.0f}s" for n, _, _, s in slowest) + ")")
    if failed:
        print(("::error::Failed: " if GITHUB else "Failed: ") + " ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
