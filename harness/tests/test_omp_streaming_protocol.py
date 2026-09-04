"""Behavioral and architecture checks for the OMP event transport."""

import json
import os
import shutil
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
ADAPTER = REPO / "harness" / "bin" / "omp_role_adapter.ts"


def test_adapter_streams_versioned_jsonl_without_accumulating_events() -> None:
    source = ADAPTER.read_text(encoding="utf-8")

    assert 'record_type: "header"' in source
    assert 'protocol_version: 2' in source
    assert 'record_type: "event"' in source
    assert 'record_type: "terminal"' in source
    assert "writeSync(1" in source
    assert "written !== Buffer.byteLength(line)" in source
    assert "events.push(" not in source
    assert "const events:" not in source


def test_adapter_never_serializes_the_request_or_auth_token() -> None:
    source = ADAPTER.read_text(encoding="utf-8")
    wire_protocol = source.split("type WireRecord =", 1)[1].split(";\n", 1)[0]

    assert "writeRecord(request" not in source
    assert "JSON.stringify(request)" not in source
    assert "auth_token" not in wire_protocol


def test_adapter_exits_only_after_durable_terminal_record() -> None:
    """Require one unconditional final exit after cleanup and durable terminal IO."""
    source = ADAPTER.read_text(encoding="utf-8")

    cleanup = source.rindex("await session.dispose()")
    terminal_write = source.rindex('record_type: "terminal"')
    explicit_exit = source.rindex("process.exit(0)")

    assert source.count("process.exit(0)") == 1
    assert cleanup < terminal_write < explicit_exit
    assert source.rstrip().endswith("process.exit(0);")


def _controlled_adapter(tmp_path: Path) -> tuple[Path, Path]:
    fake_sdk = tmp_path / "fake_omp.ts"
    sentinel = tmp_path / "disposed"
    fake_sdk.write_text(
        """
export const VERSION = "18.1.4";
export class AgentRegistry {}
export class AuthStorage {
  static async create(_path: string) { return new AuthStorage(); }
  setRuntimeApiKey(_provider: string, _token: string) {}
  close() {}
}
export class ModelRegistry {
  constructor(..._args: unknown[]) {}
  find(provider: string, model: string) { return { provider, id: model }; }
}
export class SessionManager { static inMemory(_cwd: string) { return {}; } }
export class Settings { static isolated(_settings: object) { return {}; } }
export async function createAgentSession(_options: object) {
  let listener: ((event: unknown) => void) | undefined;
  return { session: {
    subscribe(callback: (event: unknown) => void) {
      listener = callback;
      return () => {};
    },
    async prompt() {
      listener?.({
        type: "message_end",
        message: {
          role: "assistant",
          content: [{ type: "text", text: "controlled answer" }],
          provider: "anthropic",
          model: "claude-haiku-4-5",
          responseId: "controlled-response",
          usage: {
            input: 3, output: 2, cacheRead: 0, cacheWrite: 0,
            totalTokens: 5, cost: { total: 0.0001 },
          },
          stopReason: "stop",
        },
      });
      listener?.({ type: "agent_end", isTerminal: true });
      return true;
    },
    async dispose() {
      if (process.env.ESCAPEMENT_FAKE_DISPOSE_REJECT === "1") {
        throw new Error("controlled dispose failure");
      }
      await Bun.write(process.env.ESCAPEMENT_FAKE_SENTINEL!, "disposed");
      setInterval(() => {}, 1000);
    },
  }};
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    adapter = tmp_path / "controlled_adapter.ts"
    adapter.write_text(
        ADAPTER.read_text(encoding="utf-8").replace(
            'from "@oh-my-pi/pi-coding-agent";', 'from "./fake_omp.ts";'
        ),
        encoding="utf-8",
    )
    return adapter, sentinel


def _controlled_request(tmp_path: Path) -> str:
    return json.dumps(
        {
            "protocol_version": 1,
            "role": "generator",
            "prompt": "produce one answer",
            "system_prompt": "return one answer",
            "provider": "anthropic",
            "model": "claude-haiku-4-5",
            "auth_token": "test-only-token",
            "cwd": str(tmp_path / "cwd"),
            "agent_dir": str(tmp_path / "agent"),
        }
    )


def test_adapter_cleanup_precedes_terminal_and_lingering_handle_cannot_hang(
    tmp_path: Path,
) -> None:
    bun = shutil.which("bun")
    assert bun is not None
    adapter, sentinel = _controlled_adapter(tmp_path)
    environment = {**os.environ, "ESCAPEMENT_FAKE_SENTINEL": str(sentinel)}

    completed = subprocess.run(
        (bun, str(adapter)),
        input=_controlled_request(tmp_path),
        text=True,
        capture_output=True,
        check=False,
        cwd=tmp_path,
        env=environment,
        timeout=2,
    )

    records = [json.loads(line) for line in completed.stdout.splitlines()]
    assert completed.returncode == 0
    assert completed.stderr == ""
    assert sentinel.read_text(encoding="utf-8") == "disposed"
    assert [row["record_type"] for row in records].count("terminal") == 1
    assert records[-1]["record_type"] == "terminal"


def test_adapter_cleanup_failure_never_emits_success_terminal(
    tmp_path: Path,
) -> None:
    bun = shutil.which("bun")
    assert bun is not None
    adapter, _ = _controlled_adapter(tmp_path)
    environment = {**os.environ, "ESCAPEMENT_FAKE_DISPOSE_REJECT": "1"}

    completed = subprocess.run(
        (bun, str(adapter)),
        input=_controlled_request(tmp_path),
        text=True,
        capture_output=True,
        check=False,
        cwd=tmp_path,
        env=environment,
        timeout=2,
    )

    records = [json.loads(line) for line in completed.stdout.splitlines()]
    assert completed.returncode != 0
    assert "controlled dispose failure" in completed.stderr
    assert all(row["record_type"] != "terminal" for row in records)
