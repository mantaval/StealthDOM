"""
StealthDOM -- WebSocket Bridge Server
Hub that connects the browser extension to external control clients
(Python scripts, MCP server, AI agents).

Port 9877: Extension connects here
Port 9878: Control clients (MCP, other tools) connect here
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any

import websockets
from websockets.asyncio.server import serve

# Suppress noisy websockets library errors (stale connections send 0 bytes
# and trigger "opening handshake failed" tracebacks at the library level).
# Our handler code logs connection events ourselves.
logging.getLogger('websockets').setLevel(logging.CRITICAL)


def log(msg: str):
    ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f'[{ts}] {msg}')


class BridgeServer:
    """WebSocket hub bridging extension <-> external clients."""
    
    def __init__(self, host: str = '127.0.0.1', port: int = 9877, control_port: int = 9878):
        self.host = host
        self.port = port
        self.control_port = control_port
        self._ws = None                    # Extension WebSocket connection
        self._server = None                # Extension server instance
        self._control_server = None        # Control port server instance
        self._connected = asyncio.Event()  # Set when extension connects
        self._pending: dict[str, asyncio.Future] = {}  # id -> Future for responses
        self._ready = False
    
    @property
    def is_connected(self) -> bool:
        return self._ws is not None and self._ws.state.name != 'CLOSED'
    
    async def start(self):
        """Start both WebSocket servers."""
        # Extension port
        self._server = await serve(
            self._extension_handler,
            self.host,
            self.port,
        )
        log(f"Extension port listening on ws://{self.host}:{self.port}")
        
        # Control port for MCP and external clients
        self._control_server = await serve(
            self._control_handler,
            self.host,
            self.control_port,
        )
        log(f"Control port listening on ws://{self.host}:{self.control_port}")
        log("Waiting for browser extension to connect...")
    
    async def wait_for_connection(self, timeout: float = 300):
        """Wait for the extension to connect.
        
        Args:
            timeout: Max seconds to wait (default 5 minutes)
        """
        try:
            await asyncio.wait_for(self._connected.wait(), timeout)
            log("Extension connected!")
            return True
        except asyncio.TimeoutError:
            log("Timeout waiting for extension connection.")
            return False
    
    async def send_command(self, action: str, _timeout: float = 30, **kwargs) -> dict:
        """Send a command to the extension and wait for response.
        
        Args:
            action: Command name (e.g., 'querySelector', 'click')
            _timeout: Max seconds to wait for response
            **kwargs: Additional command parameters
            
        Returns:
            Response dict with 'success' and 'data' or 'error'
        """
        if not self.is_connected:
            return {'success': False, 'error': 'Extension not connected'}
        
        # Create unique ID for this command
        cmd_id = str(uuid.uuid4())[:8]
        
        # Prepare message
        msg = {'id': cmd_id, 'action': action, **kwargs}
        
        # Create future for response
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending[cmd_id] = future
        
        try:
            await self._ws.send(json.dumps(msg))
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
    
    async def _extension_handler(self, websocket):
        """Handle the browser extension connection."""
        log(f"Extension connected from {websocket.remote_address}")
        
        # Only allow one extension at a time
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
        
        self._ws = websocket
        self._connected.set()
        
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    await self._handle_extension_message(data)
                except json.JSONDecodeError:
                    log(f"Invalid JSON from extension: {message[:100]}")
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            log("Extension disconnected.")
            self._ws = None
            self._connected.clear()
            
            # Fail all pending futures
            for cmd_id, future in list(self._pending.items()):
                if not future.done():
                    future.set_result({'success': False, 'error': 'Extension disconnected'})
            self._pending.clear()
    
    async def _handle_extension_message(self, data: dict):
        """Process a message from the extension."""
        msg_type = data.get('type', '')
        
        if msg_type == 'handshake':
            self._ready = True
            url = data.get('url', 'unknown')
            log(f"Handshake received from: {url}")
        
        elif msg_type == 'heartbeat':
            pass  # Keep-alive (silent)
        
        elif msg_type == 'response':
            cmd_id = data.get('id')
            if cmd_id and cmd_id in self._pending:
                future = self._pending[cmd_id]
                if not future.done():
                    future.set_result(data)
            else:
                print(f"[Bridge] Orphan response for id={cmd_id}")
        
        else:
            print(f"[Bridge] Unknown message type: {msg_type}")
    
    # ==========================================
    # Control Handler (port 9878)
    # ==========================================
    
    async def _control_handler(self, websocket):
        """Handle an external control client (MCP server, etc.)."""
        addr = websocket.remote_address
        print(f"[Bridge] Control client connected from {addr}")
        
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    # Forward command to extension and return response
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
            print(f"[Bridge] Control client disconnected from {addr}")
    
    async def _handle_control_command(self, data: dict) -> dict:
        """Process a command from a control client by forwarding to extension."""
        # Extract MCP correlation ID (echoed back for response matching)
        msg_id = data.pop('_msg_id', None)
        action = data.get('action', '')
        timeout = data.pop('_timeout', 30)
        
        if not action:
            result = {'success': False, 'error': 'Missing action field'}
            if msg_id:
                result['_msg_id'] = msg_id
            return result
        
        if not self.is_connected:
            # Check if any supported Chromium browser is running
            import subprocess
            browser_running = None
            try:
                result = subprocess.run(
                    ['tasklist', '/NH'],
                    capture_output=True, text=True, timeout=3
                )
                output = result.stdout.lower()
                browser_running = any(b in output for b in ['brave.exe', 'chrome.exe', 'msedge.exe'])
            except Exception:
                browser_running = None  # Unknown
            
            if browser_running is False:
                result = {'success': False, 'error': (
                    'Extension not connected. No supported browser is running. '
                    'Tell the user to open their Chromium browser (Chrome, Brave, Edge, etc.). '
                    'The StealthDOM extension will auto-connect once the browser is open with any page loaded.'
                )}
            else:
                result = {'success': False, 'error': (
                    'Extension not connected. A browser appears to be running but the '
                    'extension has not connected yet. Tell the user to refresh any '
                    'open tab, or check that the StealthDOM extension is '
                    'enabled in the browser\'s extensions page.'
                )}
            if msg_id:
                result['_msg_id'] = msg_id
            return result
        
        # Forward to extension via send_command
        # Extract action and pass everything else as kwargs
        kwargs = {k: v for k, v in data.items() if k != 'action'}
        result = await self.send_command(action, _timeout=timeout, **kwargs)
        if msg_id:
            result['_msg_id'] = msg_id
        return result
    
    # ==========================================
    # Shutdown
    # ==========================================
    
    async def shutdown(self):
        """Clean shutdown of both servers."""
        if self._ws:
            await self._ws.close()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        if self._control_server:
            self._control_server.close()
            await self._control_server.wait_closed()
        print("[Bridge] Server shut down.")


if __name__ == "__main__":
    async def main():
        bridge = BridgeServer()
        await bridge.start()
        log("Waiting for extension... (open any page in your browser)")
        await bridge.wait_for_connection(timeout=600)
        log("Ready! Bridge is live. Keeping alive for commands...")
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

