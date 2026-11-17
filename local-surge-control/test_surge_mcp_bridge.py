#!/usr/bin/env python3
"""Unit tests for the loopback-only, stdin-authenticated Surge MCP bridge."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent
BRIDGE = ROOT / "scripts" / "surge-mcp-bridge.py"


class SurgeMcpBridgeTest(unittest.TestCase):
    def test_refuses_non_loopback_host_and_insecure_tls(self) -> None:
        for extra_env, expected in (
            ({"SURGE_MCP_HOST": "192.0.2.10"}, "loopback"),
            ({"SURGE_MCP_HOST": "0.0.0.0"}, "loopback"),
            ({"SURGE_HTTP_INSECURE": "1"}, "SURGE_HTTP_INSECURE is refused"),
            ({"SURGE_HTTP_CA": "bad\nca"}, "newline"),
        ):
            with self.subTest(env=extra_env):
                env = {k: v for k, v in os.environ.items() if not k.startswith("SURGE_")}
                env.update(extra_env)
                result = subprocess.run(
                    [sys.executable, str(BRIDGE)],
                    input="",
                    text=True,
                    capture_output=True,
                    env=env,
                    check=False,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn(expected, result.stderr)

    def test_stdio_roundtrip_passes_key_via_stdin_never_argv_and_cleans_temp(self) -> None:
        secret_key = "synthetic-mcp-secret-key"
        with tempfile.TemporaryDirectory() as temporary:
            temp_dir = Path(temporary)
            bin_dir = temp_dir / "bin"
            log_dir = temp_dir / "log"
            tmp_dir = temp_dir / "tmp"
            for directory in (bin_dir, log_dir, tmp_dir):
                directory.mkdir()

            profile = temp_dir / "DMIT-Mac.conf"
            profile.write_text(f"http-api = {secret_key}@127.0.0.1:1132\n", encoding="utf-8")

            fake_curl = bin_dir / "curl"
            fake_curl.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, re, sys\n"
                "from pathlib import Path\n"
                "cfg = sys.stdin.read()\n"
                "log = Path(os.environ['SURGE_TEST_LOG'])\n"
                "idx = len(list(log.glob('call-*.args')))\n"
                "(log / f'call-{idx}.args').write_text(' '.join(sys.argv[1:]), encoding='utf-8')\n"
                "(log / f'call-{idx}.cfg').write_text(cfg, encoding='utf-8')\n"
                "m = re.search(r'data-binary = \"@([^\"]+)\"', cfg)\n"
                "req = json.loads(Path(m.group(1)).read_text(encoding='utf-8'))\n"
                "if req.get('method') == 'notifications/initialized':\n"
                "    sys.stdout.write('\\n202')\n"
                "elif req.get('method') == 'initialize':\n"
                "    resp = {'jsonrpc': '2.0', 'id': req['id'], 'result': {'protocolVersion': '2025-03-26'}}\n"
                "    sys.stdout.write(json.dumps(resp) + '\\n200')\n"
                "elif req.get('method') == 'tools/list':\n"
                "    resp = {'jsonrpc': '2.0', 'id': req['id'], 'result': {'tools': [{'name': 'get_status'}]}}\n"
                "    sys.stdout.write('event: message\\ndata: ' + json.dumps(resp) + '\\n\\n200')\n",
                encoding="utf-8",
            )
            fake_curl.chmod(0o700)

            env = {k: v for k, v in os.environ.items() if not k.startswith("SURGE_")}
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "SURGE_MAC_PROFILE": str(profile),
                    "SURGE_TEST_LOG": str(log_dir),
                    "TMPDIR": str(tmp_dir),
                }
            )
            stdin_lines = "\n".join(
                [
                    json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
                    json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                    json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
                ]
            ) + "\n"

            result = subprocess.run(
                [sys.executable, str(BRIDGE)],
                input=stdin_lines,
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            out_lines = [json.loads(line) for line in result.stdout.strip().splitlines()]
            self.assertEqual(len(out_lines), 2)
            self.assertEqual(out_lines[0]["id"], 1)
            self.assertEqual(out_lines[1]["result"]["tools"][0]["name"], "get_status")

            for args_file in log_dir.glob("call-*.args"):
                args_text = args_file.read_text(encoding="utf-8")
                self.assertTrue(args_text.startswith("-q --noproxy * --config -"))
                self.assertNotIn(secret_key, args_text)
                self.assertIn("https://127.0.0.1:1132/v1/mcp", args_text)
            for cfg_file in log_dir.glob("call-*.cfg"):
                cfg_text = cfg_file.read_text(encoding="utf-8")
                self.assertIn(f'header = "X-Key: {secret_key}"', cfg_text)
                self.assertNotIn("insecure", cfg_text)

            self.assertEqual(list(tmp_dir.iterdir()), [])

    def test_auth_failure_does_not_leak_credential_or_raw_body(self) -> None:
        secret_key = "sensitive-denied-key"
        with tempfile.TemporaryDirectory() as temporary:
            temp_dir = Path(temporary)
            bin_dir = temp_dir / "bin"
            bin_dir.mkdir()
            profile = temp_dir / "DMIT-Mac.conf"
            profile.write_text(f"http-api = {secret_key}@127.0.0.1:1132\n", encoding="utf-8")

            fake_curl = bin_dir / "curl"
            fake_curl.write_text(
                "#!/bin/sh\n"
                "cat >/dev/null\n"
                "printf 'secret-server-body-%s\\n403' '" + secret_key + "'\n",
                encoding="utf-8",
            )
            fake_curl.chmod(0o700)

            env = {k: v for k, v in os.environ.items() if not k.startswith("SURGE_")}
            env.update({"PATH": f"{bin_dir}:{env['PATH']}", "SURGE_MAC_PROFILE": str(profile)})
            result = subprocess.run(
                [sys.executable, str(BRIDGE)],
                input='{"jsonrpc":"2.0","id":9,"method":"tools/list"}\n',
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            self.assertEqual(result.returncode, 0)
            combined = result.stdout + result.stderr
            self.assertNotIn(secret_key, combined)
            self.assertNotIn("secret-server-body", combined)
            payload = json.loads(result.stdout.strip())
            self.assertEqual(payload["id"], 9)
            self.assertIn("http-api-mcp = true", payload["error"]["message"])


if __name__ == "__main__":
    unittest.main()
