"""
StealthDOM -- WebSocket Bridge Server
Hub that connects the browser extension to external control clients
(Python scripts, MCP server, AI agents).

Port 9877: Extension connects here (multiple browsers supported simultaneously)
Port 9878: Control clients (MCP, other tools) connect here

Multi-Browser Support:
    Multiple browsers can connect simultaneously. Each connection is identified
    by a label (e.g., 'brave', 'chrome') sent in the handshake message.
    Tab IDs are namespaced as "label:tabId" (e.g., "brave:12345") — Virtual Tab IDs.
    browser_list_tabs() returns tabs from ALL connected browsers in one flat list.
    Commands targeting a virtualId are automatically routed to the correct browser.
    Single-browser usage: numeric tab IDs still work (routes to the primary connection).
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any

import psutil
import websockets
from websockets.asyncio.server import serve

# Suppress noisy websockets library errors (stale connections send 0 bytes
# and trigger "opening handshake failed" tracebacks at the library level).
logging.getLogger('websockets').setLevel(logging.CRITICAL)

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('bridge')


class BridgeServer:
    """WebSocket hub bridging browser extensions <-> external control clients.

    Supports multiple simultaneous browser connections. Each browser extension
    is identified by a label sent in the handshake (e.g., 'brave', 'chrome').
    Tab IDs are virtualised as "label:realTabId" for transparent multi-browser routing.
    """

    def __init__(self, host: str = '127.0.0.1', port: int = 9877, control_port: int = 9878):
        self.host = host
        self.port = port
        self.control_port = control_port

        # Multi-browser connection registry
        self._connections: dict[str, Any] = {}       # label -> WebSocket
        self._primary_label: str | None = None        # First/fallback connection label
        self._any_connected = asyncio.Event()         # Set when ≥1 extension is connected

        self._server = None                           # Extension server instance
        self._control_server = None                   # Control port server instance
        self._pending: dict[str, asyncio.Future] = {} # cmd_id -> Future (global, UUID-keyed)
        self._ready = False

    @property
    def is_connected(self) -> bool:
        return len(self._connections) > 0

    async def start(self) -> None:
        """Start both WebSocket servers."""
        self._server = await serve(
            self._extension_handler,
            self.host,
            self.port,
        )
        logger.info("Extension port listening on ws://%s:%s", self.host, self.port)

        self._control_server = await serve(
            self._control_handler,
            self.host,
            self.control_port,
        )
        logger.info("Control port listening on ws://%s:%s", self.host, self.control_port)
        logger.info("Waiting for browser extension to connect...")

    async def wait_for_connection(self, timeout: float = 300):
        """Wait for at least one extension to connect."""
        try:
            await asyncio.wait_for(self._any_connected.wait(), timeout)
            logger.info("Extension connected!")
            return True
        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for extension connection.")
            return False

    async def send_command(self, action: str, label: str = None, _timeout: float = 30, **kwargs) -> dict:
        """Send a command to a specific extension connection and wait for response.

        Args:
            action:   Command name (e.g., 'querySelector', 'click')
            label:    Browser connection label (e.g., 'brave'). Defaults to primary.
            _timeout: Max seconds to wait for response
            **kwargs: Additional command parameters

        Returns:
            Response dict with 'success' and 'data' or 'error'
        """
        target_label = label or self._primary_label
        if not target_label:
            return {'success': False, 'error': 'No browser connected. Open your browser and ensure the StealthDOM extension is loaded.'}

        ws = self._connections.get(target_label)
        if ws is None:
            return {'success': False, 'error': f'Browser "{target_label}" not connected. Available: {list(self._connections.keys())}'}

        cmd_id = str(uuid.uuid4())[:8]
        msg = {'id': cmd_id, 'action': action, **kwargs}

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending[cmd_id] = future

        try:
            await ws.send(json.dumps(msg))
            result = await asyncio.wait_for(future, _timeout)
            return result
        except asyncio.TimeoutError:
            return {'success': False, 'error': f'Command {action} timed out after {_timeout}s'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
        finally:
            self._pending.pop(cmd_id, None)

    # ==========================================
    # Extension Handler (port 9877)
    # ==========================================

    async def _extension_handler(self, websocket) -> None:
        """Handle a browser extension connection. Supports multiple simultaneous browsers."""
        addr = websocket.remote_address
        logger.info("Extension connecting from %s...", addr)

        # Read handshake to get browser label
        label = 'default'
        try:
            raw = await asyncio.wait_for(websocket.recv(), timeout=10)
            hs = json.loads(raw)
            if hs.get('type') == 'handshake':
                label = hs.get('label', 'default')
                self._ready = True
                logger.info("Handshake from label='%s' url=%s", label, hs.get('url', 'unknown'))
            else:
                # Not a handshake — process it as a normal message
                await self._handle_extension_message(hs)
        except asyncio.TimeoutError:
            logger.warning("No handshake received in 10s from %s, using label='default'", addr)
        except Exception as e:
            logger.warning("Handshake parse error: %s, using label='default'", e)

        # Disconnect old connection with same label (replace)
        if label in self._connections:
            logger.info("Replacing existing connection for label='%s'", label)
            try:
                await self._connections[label].close()
            except Exception:
                pass

        self._connections[label] = websocket
        if self._primary_label is None:
            self._primary_label = label
        self._any_connected.set()
        logger.info("Browser '%s' connected. Active connections: %s", label, list(self._connections.keys()))

        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    await self._handle_extension_message(data)
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON from extension '%s': %s", label, message[:100])
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            logger.info("Browser '%s' disconnected.", label)
            self._connections.pop(label, None)

            # Update primary label if it disconnected
            if self._primary_label == label:
                self._primary_label = next(iter(self._connections), None)

            if not self._connections:
                self._any_connected.clear()

            # Fail any pending futures (they can't be fulfilled without a connection)
            # Note: we can't easily identify which futures belong to this connection
            # without per-connection tracking. Futures will timeout naturally.

    async def _handle_extension_message(self, data: dict) -> None:
        """Process a message from any extension connection."""
        msg_type = data.get('type', '')

        if msg_type == 'handshake':
            self._ready = True
            logger.info("Late handshake received from: %s", data.get('url', 'unknown'))

        elif msg_type == 'heartbeat':
            pass  # Keep-alive (silent)

        elif msg_type == 'response':
            cmd_id = data.get('id')
            if cmd_id and cmd_id in self._pending:
                future = self._pending[cmd_id]
                if not future.done():
                    future.set_result(data)
            else:
                logger.debug("Orphan response for id=%s", cmd_id)

        else:
            logger.debug("Unknown message type: %s", msg_type)

    # ==========================================
    # Control Handler (port 9878)
    # ==========================================

    async def _control_handler(self, websocket) -> None:
        """Handle an external control client (MCP server, scripts, etc.)."""
        addr = websocket.remote_address
        logger.info("Control client connected from %s", addr)

        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    result = await self._handle_control_command(data)
                    await websocket.send(json.dumps(result))
                except json.JSONDecodeError:
                    error = {'success': False, 'error': 'Invalid JSON'}
                    await websocket.send(json.dumps(error))
                except Exception as e:
                    error = {'success': False, 'error': str(e)}
                    await websocket.send(json.dumps(error))
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            logger.info("Control client disconnected from %s", addr)

    async def _handle_control_command(self, data: dict) -> dict:
        """Process a command from a control client.

        Handles:
        - Multi-browser routing via virtual tab IDs ("label:tabId")
        - Aggregated listTabs across all connected browsers
        """
        msg_id = data.pop('_msg_id', None)
        action = data.get('action', '')
        timeout = data.pop('_timeout', 30)

        if not action:
            result = {'success': False, 'error': 'Missing action field'}
            if msg_id:
                result['_msg_id'] = msg_id
            return result



        # ---- Check connection availability ----
        if not self.is_connected:
            result = self._build_not_connected_error()
            if msg_id:
                result['_msg_id'] = msg_id
            return result

        # ---- Aggregated multi-browser commands ----
        if action == 'listTabs':
            result = await self._cmd_list_tabs_all(timeout)
            if msg_id:
                result['_msg_id'] = msg_id
            return result

        # ---- Resolve routing label from virtual tab ID ----
        routing_label = self._primary_label
        tab_id_raw = data.get('tabId')
        if tab_id_raw is not None:
            str_tab_id = str(tab_id_raw)
            if ':' in str_tab_id:
                # Virtual tab ID: "brave:12345"
                virt_label, _, real_id_str = str_tab_id.partition(':')
                routing_label = virt_label
                try:
                    data['tabId'] = int(real_id_str)
                except ValueError:
                    data['tabId'] = real_id_str

        # ---- Forward command to the resolved connection ----
        kwargs = {k: v for k, v in data.items() if k != 'action'}
        result = await self.send_command(action, label=routing_label, _timeout=timeout, **kwargs)
        if msg_id:
            result['_msg_id'] = msg_id
        return result



    async def _cmd_list_tabs_all(self, timeout: float = 30) -> dict:
        """Aggregate tabs from ALL connected browsers into one flat list.

        Each tab gets:
        - browserId: the connection label (e.g., 'brave')
        - virtualId: namespaced tab ID string (e.g., 'brave:12345') — use this for all commands
        - id: original numeric tab ID from the browser (kept for reference)
        """
        all_tabs = []
        errors = []

        for label in list(self._connections.keys()):
            result = await self.send_command('listTabs', label=label, _timeout=timeout)
            if result.get('success'):
                tabs = result.get('data', [])
                for tab in tabs:
                    real_id = tab.get('id')
                    tab['browserId'] = label
                    tab['virtualId'] = f"{label}:{real_id}"
                    all_tabs.append(tab)
            else:
                errors.append(f"{label}: {result.get('error', 'unknown error')}")

        response: dict = {'success': True, 'data': all_tabs}
        if errors:
            response['warnings'] = errors
        return response

    def _build_not_connected_error(self) -> dict:
        """Build an informative error when no extension is connected."""
        browser_running = None
        try:
            browser_names = {'brave', 'chrome', 'msedge', 'chromium'}
            for proc in psutil.process_iter(['name']):
                name = (proc.info.get('name') or '').lower()
                if any(b in name for b in browser_names):
                    browser_running = True
                    break
            if browser_running is None:
                browser_running = False
        except Exception:
            browser_running = None

        if browser_running is False:
            return {'success': False, 'error': (
                'Extension not connected. No supported browser is running. '
                'Tell the user to open their Chromium browser (Chrome, Brave, Edge, etc.). '
                'The StealthDOM extension will auto-connect once the browser is open with any page loaded.'
            )}
        else:
            return {'success': False, 'error': (
                'Extension not connected. A browser appears to be running but the '
                'extension has not connected yet. Tell the user to refresh any '
                'open tab, or check that the StealthDOM extension is '
                'enabled in the browser\'s extensions page.'
            )}

    # ==========================================
    # Shutdown
    # ==========================================

    async def shutdown(self) -> None:
        """Clean shutdown of both servers and all extension connections."""
        for label, ws in list(self._connections.items()):
            try:
                await ws.close()
            except Exception:
                pass
        self._connections.clear()

        if self._server:
            self._server.close()
            await self._server.wait_closed()
        if self._control_server:
            self._control_server.close()
            await self._control_server.wait_closed()
        logger.info("Bridge server shut down.")


if __name__ == "__main__":
    async def main():
        bridge = BridgeServer()
        await bridge.start()
        logger.info("Waiting for extension... (open any page in your browser)")
        await bridge.wait_for_connection(timeout=600)
        logger.info("Ready! Bridge is live. Keeping alive for commands...")
        try:
            await asyncio.sleep(999999)
        except asyncio.CancelledError:
            pass
        finally:
            await bridge.shutdown()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[Bridge] Stopped.")
