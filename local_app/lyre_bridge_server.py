# -*- coding: utf-8 -*-
"""Local-only web controller for Lyre Bridge."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import webbrowser
from pathlib import Path
from typing import Dict, Optional, Set

from aiohttp import WSMsgType, web

from lyre_core import LyreEngine, MapperConfig


APP_DIR = Path(__file__).resolve().parent
WEB_DIR = APP_DIR / "web"
CONFIG_PATH = APP_DIR / "lyre-bridge-config.json"


class NullKeyboard:
    def press(self, _key: str) -> None:
        pass

    def release(self, _key: str) -> None:
        pass


def load_config() -> MapperConfig:
    if not CONFIG_PATH.exists():
        return MapperConfig()
    try:
        return MapperConfig.from_dict(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"配置文件不可用，已恢复默认设置：{error}")
        return MapperConfig()


def save_config(config: MapperConfig) -> None:
    temporary = CONFIG_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(config.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(CONFIG_PATH)


class MidiPortManager:
    """The only owner of the Windows MIDI input port."""

    def __init__(self, mido_module: object, engine: LyreEngine) -> None:
        self.mido = mido_module
        self.engine = engine
        self.port: Optional[object] = None
        self.devices = []
        self.selected: Optional[str] = None
        self.connected = False
        self.error: Optional[str] = None
        self.technical_error: Optional[str] = None
        self.revision = 0

    def _changed(self) -> None:
        self.revision += 1

    def refresh(self) -> None:
        try:
            self.devices = list(self.mido.get_input_names())
            if self.selected and self.selected not in self.devices:
                self.close("MIDI 设备已断开")
            if not self.devices:
                self.error = "没有发现 MIDI 输入，请检查电钢琴 USB 连接。"
                self.technical_error = None
        except Exception as error:
            self.devices = []
            self.error = "扫描 MIDI 设备失败。"
            self.technical_error = str(error)
        self._changed()

    def friendly_error(self, error: Exception) -> str:
        text = str(error)
        lowered = text.lower()
        if "windows mm midi input port" in lowered or "openport" in lowered:
            return "Roland MIDI 端口正被其他程序占用。请关闭旧脚本、DAW，或关闭曾连接 Web MIDI 的网页，再点“重新连接”。"
        if "invalid device" in lowered or "not found" in lowered:
            return "所选 MIDI 设备已不可用，请刷新设备列表。"
        return "无法打开 MIDI 输入；请检查设备连接后重试。"

    def open(self, name: Optional[str]) -> None:
        self.close(None)
        self.refresh()
        if not self.devices:
            return
        target = name if name in self.devices else self.devices[0]
        self.selected = target
        try:
            self.port = self.mido.open_input(target)
            self.connected = True
            self.error = None
            self.technical_error = None
            print(f"MIDI 已连接：{target}")
        except Exception as error:
            self.port = None
            self.connected = False
            self.error = self.friendly_error(error)
            self.technical_error = str(error)
            print(f"MIDI 打开失败：{error}")
        self._changed()

    def close(self, notice: Optional[str]) -> None:
        if self.port is not None:
            try:
                self.port.close()
            except Exception:
                pass
        self.port = None
        self.connected = False
        self.engine.panic(notice or "MIDI 端口正在切换")
        if notice:
            self.error = notice
        self._changed()

    def poll(self) -> None:
        if self.port is None:
            return
        try:
            for _ in range(64):
                message = self.port.poll()
                if message is None:
                    break
                self.engine.process_message(message)
        except Exception as error:
            self.error = "读取 MIDI 时设备断开，请重新连接。"
            self.technical_error = str(error)
            self.close(self.error)

    def snapshot(self) -> Dict[str, object]:
        return {
            "devices": self.devices,
            "selected": self.selected,
            "connected": self.connected,
            "error": self.error,
            "technical_error": self.technical_error,
        }


async def make_snapshot(app: web.Application) -> Dict[str, object]:
    value = app["engine"].snapshot()
    value["midi"] = app["ports"].snapshot()
    value["server"] = {"local_only": True, "version": "3.0.0"}
    return value


async def broadcast(app: web.Application) -> None:
    payload = json.dumps({"type": "state", "state": await make_snapshot(app)}, ensure_ascii=False)
    stale = []
    for socket in app["sockets"]:
        try:
            await socket.send_str(payload)
        except (ConnectionError, RuntimeError):
            stale.append(socket)
    for socket in stale:
        app["sockets"].discard(socket)


async def index_handler(_request: web.Request) -> web.FileResponse:
    return web.FileResponse(WEB_DIR / "index.html")


async def health_handler(request: web.Request) -> web.Response:
    return web.json_response(await make_snapshot(request.app))


async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    socket = web.WebSocketResponse(heartbeat=20)
    await socket.prepare(request)
    request.app["sockets"].add(socket)
    await socket.send_json({"type": "state", "state": await make_snapshot(request.app)}, dumps=lambda value: json.dumps(value, ensure_ascii=False))
    try:
        async for message in socket:
            if message.type != WSMsgType.TEXT:
                continue
            try:
                command = json.loads(message.data)
                command_type = command.get("type")
                if command_type == "config":
                    config = MapperConfig.from_dict(command.get("config"))
                    request.app["engine"].update_config(config)
                    save_config(config)
                elif command_type == "device":
                    request.app["ports"].open(command.get("name"))
                elif command_type == "refresh_devices":
                    request.app["ports"].refresh()
                elif command_type == "retry":
                    request.app["ports"].open(request.app["ports"].selected)
                elif command_type == "output":
                    request.app["engine"].set_output_enabled(bool(command.get("enabled")))
                elif command_type == "panic":
                    request.app["engine"].panic("已从网页释放全部按键")
                else:
                    raise ValueError("未知控制命令")
                await broadcast(request.app)
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                await socket.send_json({"type": "error", "message": str(error)}, dumps=lambda value: json.dumps(value, ensure_ascii=False))
    finally:
        request.app["sockets"].discard(socket)
    return socket


async def device_pump(app: web.Application) -> None:
    engine: LyreEngine = app["engine"]
    ports: MidiPortManager = app["ports"]
    last_signature = (-1, -1)
    try:
        while True:
            ports.poll()
            engine.flush_pending()
            signature = (engine.revision, ports.revision)
            if signature != last_signature:
                await broadcast(app)
                last_signature = signature
            await asyncio.sleep(0.004)
    except asyncio.CancelledError:
        raise


async def runtime_context(app: web.Application):
    app["ports"].refresh()
    if app["ports"].devices:
        app["ports"].open(app["requested_device"])
    task = asyncio.create_task(device_pump(app))
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        app["ports"].close("本地服务已停止")
        app["engine"].panic("本地服务已停止")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="原琴律桥本地网页控制台")
    parser.add_argument("--port", type=int, default=17321, help="本地网页端口，默认 17321")
    parser.add_argument("--device", help="优先连接的 MIDI 设备完整名称")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    parser.add_argument("--visual-only", action="store_true", help="只可视化，不发送 Windows 游戏按键")
    return parser


def main() -> int:
    args = make_parser().parse_args()
    try:
        import mido
        mido.set_backend("mido.backends.rtmidi")
        if args.visual_only:
            keyboard = NullKeyboard()
        else:
            from pynput.keyboard import Controller
            keyboard = Controller()
    except ImportError as error:
        print(f"缺少依赖：{error.name}")
        print("请双击 run-local.bat，让它自动安装独立环境。")
        return 2

    app = web.Application()
    app["engine"] = LyreEngine(load_config(), keyboard)
    app["ports"] = MidiPortManager(mido, app["engine"])
    app["sockets"] = set()
    app["requested_device"] = args.device
    app.cleanup_ctx.append(runtime_context)
    app.router.add_get("/", index_handler)
    app.router.add_get("/api/health", health_handler)
    app.router.add_get("/ws", websocket_handler)
    app.router.add_static("/assets/", WEB_DIR, show_index=False)

    url = f"http://127.0.0.1:{args.port}"
    print("\n原琴律桥本地控制台")
    print(f"  地址：{url}")
    print("  仅绑定本机，不会发布到互联网。")
    print("  网页关闭不会导致按键卡住；Ctrl+C 会执行紧急释放。\n")
    if not args.no_browser:
        asyncio.get_event_loop().call_later(1.0, lambda: webbrowser.open(url))
    try:
        web.run_app(app, host="127.0.0.1", port=args.port, print=None)
    except OSError as error:
        print(f"本地端口启动失败：{error}")
        return 1
    finally:
        app["engine"].panic("程序退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
