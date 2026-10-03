#!/usr/bin/env python3
"""A dependency-free local MCP App for native Codex themes."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

from themes import library, save_import, export_theme, share_code
import runtime

ROOT = Path(__file__).resolve().parent
VERSION = "0.1.2"
APP_URI = "ui://codex-native-themes/v0.1.2/panel.html"
MIME = "text/html;profile=mcp-app"
UI_META = {"ui": {"resourceUri": APP_URI}, "openai/outputTemplate": APP_URI,
           "openai/ui": {"entrypoints": [{"type": "global"}, {"type": "thread"}]}}
READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}


def library_result(opened=False):
    data = library()
    data["runtime"] = runtime.runtime_status()
    data["preferences"] = runtime.current_preferences(include_image=True)
    result = {"content": [{"type": "text", "text": f"皮肤工作室已准备好：{len(data['themes'])} 套主题。应用时保存 Codex 原生配色，普通重启仍会保留颜色；壁纸和玻璃效果需要运行时连接。"}],
              "structuredContent": {"themeCount": len(data["themes"]), "dshCurrentId": data["dshCurrentId"],
                                    "hostApply": "local-runtime", "wallpaperSupported": True,
                                    "runtime": data["runtime"]},
              "_meta": {"theme_library": data}}
    if opened:
        result["_meta"]["openai/outputTemplate"] = APP_URI
    return result


def tool_specs():
    return [
        {"name": "open_theme_studio", "title": "打开皮肤工作室",
         "description": "打开 Codex 内置插件面板，选择 DSH Dream Skin 的 8 套皮肤及本地导入包，设置配色、壁纸和玻璃效果。插件内的运行时引擎通过本地调试连接换肤，不需要独立外置皮肤 App。",
         "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
         "annotations": READ_ONLY, "_meta": UI_META},
        {"name": "get_theme_library", "title": "刷新主题库",
         "description": "读取 DSH 主题选择和主题包以及插件本地主题库。仅返回配色数据。",
         "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
         "annotations": READ_ONLY, "_meta": {"ui": {"visibility": ["app"]}}},
        {"name": "export_native_theme", "title": "生成原生主题导入码",
         "description": "按主题 id 生成已校验的 codex-theme-v1 导入码，可调整背景、文字、强调色、层次对比和代码配色。不直接更改宿主设置。",
         "inputSchema": {"type": "object", "properties": {
             "theme_id": {"type": "string"}, "overrides": {"type": "object", "properties": {
                 "surface": {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"},
                 "ink": {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"},
                 "accent": {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"},
                 "contrast": {"type": "integer", "minimum": 0, "maximum": 100},
                 "opaqueWindows": {"type": "boolean"}, "codeThemeId": {"type": "string"}}, "additionalProperties": False}},
                         "required": ["theme_id"], "additionalProperties": False},
         "annotations": READ_ONLY},
        {"name": "import_theme_pack", "title": "导入 DSH 或 Codex 主题",
         "description": "把用户提供的 DSH 主题包 JSON、DSH 分享链接或 Codex 原生导入码转换并保存到插件本地主题库。仅写插件自己的主题库，不更改 DSH 或 Codex 外观设置。",
         "inputSchema": {"type": "object", "properties": {"content": {"type": "string", "maxLength": 512000}, "name": {"type": "string", "maxLength": 160}},
                         "required": ["content"], "additionalProperties": False},
         "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
         "_meta": {"ui": {"visibility": ["app"]}}},
        {"name": "get_skin_status", "title": "查看换肤连接状态",
         "description": "读取插件自己的运行时状态和已保存外观选项。",
         "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
         "annotations": READ_ONLY, "_meta": {"ui": {"visibility": ["app"]}}},
        {"name": "apply_skin", "title": "应用皮肤到 Codex",
         "description": "通过已有运行时连接直接应用主题、壁纸与玻璃，并保存原生配色；日常换肤默认不重启。未连接时仅保存配置，不声称当前窗口生效。首次连接需要正常重新打开一次 Codex，只有用户明确选择「重开并自动应用」才传入 restart_when_needed=true。",
         "inputSchema": {"type": "object", "properties": {"theme_id": {"type": "string"},
                         "overrides": {"type": "object"}, "options": {"type": "object"},
                         "restart_when_needed": {"type": "boolean", "default": False}},
                         "required": ["theme_id"], "additionalProperties": False},
         "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}},
        {"name": "pause_skin", "title": "暂停皮肤并还原窗口",
         "description": "停止插件自动恢复换肤，移除自身注入的样式与壁纸层。恢复插件修改前的原生配色；用户后来自行修改的设置会保留。",
         "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
         "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}},
    ]


def call_tool(name, arguments):
    if not isinstance(arguments, dict):
        raise ValueError("工具参数需要对象")
    if name in {"open_theme_studio", "get_theme_library"}:
        return library_result(name == "open_theme_studio")
    if name == "export_native_theme":
        data = export_theme(arguments.get("theme_id"), arguments.get("overrides"))
        return {"content": [{"type": "text", "text": data["shareCode"]}], "structuredContent": data}
    if name == "import_theme_pack":
        record = save_import(arguments.get("content"), arguments.get("name", "导入主题"))
        result = library_result()
        result["structuredContent"]["importedId"] = record["id"]
        result["content"] = [{"type": "text", "text": f"已导入「{record['name']}」到本地主题库。"}]
        return result
    if name in {"apply_skin", "pause_skin", "get_skin_status"}:
        if name == "apply_skin":
            data = runtime.apply_skin(arguments.get("theme_id"), arguments.get("overrides"), arguments.get("options"),
                                      arguments.get("restart_when_needed", False))
        elif name == "pause_skin":
            data = runtime.pause_skin()
        else:
            data = runtime.runtime_status()
        return {"content": [{"type": "text", "text": data["message"]}], "structuredContent": data}
    raise ValueError("未知工具")


def handle(method, params):
    if method == "initialize":
        return {"protocolVersion": params.get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}, "resources": {}},
                "serverInfo": {"name": "codex-native-themes", "version": VERSION}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": tool_specs()}
    if method == "tools/call":
        try:
            return call_tool(params.get("name"), params.get("arguments") or {})
        except (ValueError, OSError, TypeError) as exc:
            return {"isError": True, "content": [{"type": "text", "text": str(exc) if isinstance(exc, ValueError) else "主题库读写失败，原始主题数据已保留"}]}
    if method == "resources/list":
        return {"resources": [{"uri": APP_URI, "name": "皮肤工作室", "mimeType": MIME}]}
    if method == "resources/templates/list":
        return {"resourceTemplates": []}
    if method == "resources/read":
        if params.get("uri") != APP_URI:
            raise ValueError("未知资源")
        return {"contents": [{"uri": APP_URI, "mimeType": MIME, "text": render_panel(),
                              "_meta": {"ui": {"prefersBorder": False, "csp": {"connectDomains": [], "resourceDomains": []}},
                                        "openai/widgetDescription": "DSH 兼容皮肤工作室：配色、壁纸与玻璃效果。运行时换肤需本地调试连接。",
                                        "openai/widgetPrefersBorder": False,
                                        "openai/ui": {"availableDisplayModes": ["inline", "fullscreen"]}}}]}
    raise ValueError("未知方法")


def render_panel():
    # Inline the same pure styling module used by the runtime, avoiding CDN dependencies.
    module = (ROOT / "skin.mjs").read_text().replace("export ", "")
    return (ROOT / "panel.html").read_text().replace("/* __SKIN_MODULE__ */", module)


def stdio():
    for line in sys.stdin:
        request = None
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("请求需要对象")
            if "id" not in request:
                continue
            result = handle(request.get("method"), request.get("params") or {})
            response = {"jsonrpc": "2.0", "id": request["id"], "result": result}
        except json.JSONDecodeError:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        except Exception as exc:
            response = {"jsonrpc": "2.0", "id": request.get("id") if isinstance(request, dict) else None,
                        "error": {"code": -32601 if isinstance(exc, ValueError) else -32603,
                                  "message": str(exc) if isinstance(exc, ValueError) else "Internal error"}}
        print(json.dumps(response, ensure_ascii=False, separators=(",", ":")), flush=True)


class PreviewHandler(BaseHTTPRequestHandler):
    def allowed(self):
        origins = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if self.headers.get("Host") not in origins or self.headers.get("Sec-Fetch-Site") == "cross-site":
            self.send_error(403)
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://{host}" for host in origins}:
            self.send_error(403)
            return False
        return True

    def reply(self, data, mime="application/json; charset=utf-8", status=200):
        body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.allowed():
            return
        route = urlsplit(self.path).path
        if route in {"/", "/panel.html"}:
            self.reply(render_panel().encode(), "text/html; charset=utf-8")
        elif route == "/library":
            self.reply(library_result()["_meta"]["theme_library"])
        else:
            self.send_error(404)

    def do_POST(self):
        if not self.allowed():
            return
        if urlsplit(self.path).path != "/tool" or not self.headers.get("Content-Type", "").startswith("application/json"):
            self.send_error(400)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length < 1_100_000:
                raise ValueError("请求大小无效")
            data = json.loads(self.rfile.read(length))
            self.reply(call_tool(data.get("name"), data.get("arguments") or {}))
        except (ValueError, OSError, TypeError, AttributeError) as exc:
            self.reply({"isError": True, "content": [{"type": "text", "text": str(exc) if isinstance(exc, ValueError) else "操作失败"}]}, status=400)

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", type=int, help="local preview only; native plugin uses stdio")
    parser.add_argument("--studio", type=int, help="local studio; applies or restarts only after its button is clicked")
    parser.add_argument("--export-dir", type=Path, help="write native import files for the current library")
    args = parser.parse_args()
    if args.export_dir:
        args.export_dir.mkdir(parents=True, exist_ok=True)
        for item in library()["themes"]:
            stem = item["id"].replace(":", "-")
            # Only use safe generated filenames, never arbitrary IDs as paths.
            if not all(c.isascii() and (c.isalnum() or c == "-") for c in stem):
                import hashlib
                stem = "theme-" + hashlib.sha256(stem.encode()).hexdigest()[:12]
            (args.export_dir / (stem + ".txt")).write_text(share_code(item["native"]) + "\n")
        print(f"Exported {len(library()['themes'])} themes", file=sys.stderr)
    elif args.http or args.studio:
        # Preview exercises UI and conversion, never attaches to the running host.
        import os
        if args.http:
            os.environ["CODEX_SKIN_PREVIEW"] = "1"
        else:
            os.environ.pop("CODEX_SKIN_PREVIEW", None)
        port = args.http or args.studio
        httpd = ThreadingHTTPServer(("127.0.0.1", port), PreviewHandler)
        print(f"Theme {'preview' if args.http else 'studio'}: http://127.0.0.1:{port}", file=sys.stderr, flush=True)
        httpd.serve_forever()
    else:
        runtime.initialize()
        stdio()
