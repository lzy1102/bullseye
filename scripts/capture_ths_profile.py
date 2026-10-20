#!/usr/bin/env python3
"""
capture_ths_profile - 一键抓取同花顺柜台登录参数 (ths-trade-client / ths_rea).

Windows 双击 scripts\\capture_ths_profile.bat 即可；也可以直接运行本脚本。

流程:
    1. 确认 ths-trade-client 已安装（缺失则 pip install "ths-trade-client[capture]"）
    2. 确认同花顺下单程序 xiadan.exe 在运行（没有就等待并提示）
    3. 调用 ths_client.capture_profile 抓取参数到 user_data/local_profile.json
    4. 校验必填字段并打印下一步

抓取期间必须在客户端里完成一次登录（关掉交易窗口重开最快）。
生成的文件含资金账号与股东号，仓库已 .gitignore 忽略，切勿提交。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / "user_data" / "local_profile.json"
REQUIRED_FIELDS = ("zjzh", "gdzh_sh", "gdzh_sz")
XIADAN = "xiadan.exe"
BANNER = "=" * 62


def setup_console() -> None:
    """Make Chinese output readable regardless of how the script was launched.

    The .bat launcher sets chcp 65001, but a direct `python capture_...py`
    (PowerShell / IDE / other) can still run under cp936, which garbles every
    Chinese line. Fix the console code page ourselves and force UTF-8 streams.
    """
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # py3.7+
        except Exception:
            pass


def log(msg: str = "") -> None:
    print(msg, flush=True)


def have_package() -> bool:
    return (
        subprocess.run(
            [sys.executable, "-c", "import ths_client"],
            capture_output=True,
        ).returncode
        == 0
    )


def install_package() -> bool:
    log("[2/4] 安装 ths-trade-client (含抓包依赖) ...")
    r = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade",
         "ths-trade-client[capture]"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if r.returncode != 0:
        log("[x] 安装失败。请检查网络，或手动执行:")
        log('    pip install "ths-trade-client[capture]"')
        log((r.stderr or "")[-500:])
        return False
    return True


def xiadan_running() -> bool:
    if sys.platform != "win32":
        return True  # 非 Windows 无法检测，也不该拦
    r = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {XIADAN}"],
                       capture_output=True, text=True, errors="replace")
    return XIADAN.lower() in (r.stdout or "").lower()


def wait_for_xiadan(timeout: int = 120) -> bool:
    if xiadan_running():
        return True
    log("[3/4] 没检测到同花顺下单程序 (xiadan.exe):")
    log("      1) 打开同花顺 -> 进入「交易 / 下单」")
    log(f"      2) 下面会等待 {timeout} 秒，期间在客户端里完成登录")
    log()
    import time

    waited = 0
    while waited < timeout:
        time.sleep(3)
        waited += 3
        if xiadan_running():
            log(f"[3/4] 检测到 xiadan.exe（等待 {waited} 秒）")
            return True
    return False


def run_capture(out: Path, extra: list[str]) -> int:
    log("[4/4] 开始抓取（默认最长 180 秒，请在客户端里完成一次登录）...")
    log()
    cmd = [sys.executable, "-m", "ths_client.capture_profile", "--out", str(out)]
    cmd += extra
    return subprocess.run(cmd).returncode


def validate(path: Path) -> tuple[bool, list[str]]:
    """Return (ok, missing_fields). Missing/corrupt file -> (False, [...])."""
    if not path.exists():
        return False, list(REQUIRED_FIELDS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False, ["<文件不是合法 JSON>"]
    missing = [f for f in REQUIRED_FIELDS if not data.get(f)]
    return (not missing), missing


def next_steps(out: Path) -> None:
    rel = out.relative_to(REPO_ROOT) if out.is_relative_to(REPO_ROOT) else out
    log(BANNER)
    log("  抓取成功")
    log(BANNER)
    log(f"  文件: {rel}")
    log()
    log("  下一步:")
    log("    1) 在 config.yaml 里启用 THS 网关（参考 config.yaml.example）:")
    log("         market_type: custom")
    log("         custom:")
    log('           gateway: "bullseye.gateway.stock.ths_gateway.ThsGateway"')
    log(f'           profile: "{rel.as_posix()}"')
    log("           datafeed: baostock")
    log()
    log("    2) 只读自检（不会下单），把账户/持仓与券商客户端核对一致:")
    log("         bullseye trade --strategy MacdCandle --config config.yaml --dry")
    log()
    log("    3) 该文件含资金账号与股东号，已被 .gitignore 忽略，切勿提交。")
    log()


def main(argv: Optional[list[str]] = None) -> int:
    setup_console()
    parser = argparse.ArgumentParser(
        description="一键抓取同花顺柜台登录参数 (ths-trade-client)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help=f"输出文件（默认 {DEFAULT_OUT.name}）")
    parser.add_argument("--timeout", type=int, default=None,
                        help="抓取最长等待秒数（透传给 ths-capture-profile）")
    parser.add_argument("--pid", default=None,
                        help="指定 xiadan.exe 进程 ID（多开时用）")
    parser.add_argument("--wait", type=int, default=120,
                        help="等待 xiadan.exe 启动的秒数")
    args, extra = parser.parse_known_args(argv)

    log()
    log(BANNER)
    log("  同花顺柜台参数一键抓取")
    log(BANNER)
    log(f"  Python : {sys.version.split()[0]}  ({sys.executable})")
    log(f"  输出   : {args.out}")
    log()

    if not have_package() and not install_package():
        return 1
    log("[1/4] ths-trade-client 已就绪")

    if not wait_for_xiadan(args.wait):
        log("[x] 等待超时，仍未检测到 xiadan.exe。")
        log("    如果客户端确实开着，可能是以管理员身份运行导致进程名不同，")
        log("    可手动指定进程: capture_ths_profile.bat --pid <PID>")
        return 1
    log("[3/4] 同花顺客户端状态 OK")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    passthrough = extra + (["--timeout", str(args.timeout)] if args.timeout else [])
    if args.pid:
        passthrough += ["--pid", str(args.pid)]
    rc = run_capture(args.out, passthrough)
    log()
    if rc != 0:
        log(f"[x] 抓取失败（退出码 {rc}）。常见原因:")
        log("    - 抓取期间没有在客户端里登录（关掉交易窗口重开最快）")
        log("    - 客户端没有进到「下单」页，站点文件未缓存")
        log("    - 权限不足（试试以管理员身份运行）")
        return rc

    ok, missing = validate(args.out)
    if not ok:
        log(f"[!] 文件已写出但校验失败，缺少/异常字段: {', '.join(missing)}")
        log(f"    请检查: {args.out}")
        return 1

    next_steps(args.out)
    return 0


if __name__ == "__main__":
    setup_console()
    raise SystemExit(main())