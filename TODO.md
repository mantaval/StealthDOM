# StealthDOM TODO

## High Priority: Large Data Transfer Reliability
> [!NOTE]
> Based on real-world testing with Google SGE (research reports with large 1MB+ images), the current JSON/WebSocket pipe can hit payload limits and cause evaluation timeouts.

- [ ] **Native Response Streaming/Chunking**: Automatically split large `browser_evaluate` return values (e.g., > 512KB) into chunks at the extension level and reassemble them in the Python bridge.
- [ ] **Dedicated Asset Extraction API**: Implement `browser_extract_asset(selector)` to handle direct binary/base64 harvesting of images/files without manual user-side chunking.
- [ ] **Binary WebSocket Support**: Transition from JSON-wrapped Base64 (which adds 33% overhead) to raw binary frames for media assets.
- [ ] **Configurable Payload Limits**: Expose a `max_payload_size` setting in `bridge_server.py` and the extension manifest to allow larger one-shot transfers when safe.
- [ ] **Off-Pipe Transfer**: Implement a "staging" mechanism where massive assets (videos, 4K images) are saved to a temporary local directory or `indexedDB` and picked up by the bridge, bypassing the WebSocket pipe.

## General Roadmap
- [ ] Improve documentation for multi-browser routing.
- [ ] Add more examples for complex DOM interactions (Shadow DOM support).
- [ ] Implement a "Stealth Check" diagnostic tool to verify the extension is correctly bypassing common detection scripts.
- [ ] **Advanced Request Interception & Mocking**:
    - [ ] Implement `regexFilter` support via `declarativeNetRequest` for surgical targeting.
    - [ ] Create a "Mock Redirect" local handler to bypass MV3 body-replacement restrictions.
    - [ ] **Use Cases**: Anti-Telemetry Cloak (block `/log` pings), API Hijacking (injecting data into JSON responses), and Credential Shielding (blocking unauthorized secret transmission).

## API & Tool Maintenance
- [x] **Redundancy Audit & Pruning** *(completed 2026-05-03)*: Pruned 8 tools (57→49): `browser_get_title`, `browser_get_url`, `browser_list_connections`, `browser_check`, `browser_uncheck`, `browser_forward`, `browser_drag_and_drop`, `browser_list_windows`. Replacements documented in `stealth://capabilities` Tips section.
