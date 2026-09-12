#!/usr/bin/env python3
"""Claude -> Kiro review bridge.

Modes (argv[1]):
  prompt    UserPromptSubmit: if the prompt says "review from kiro", arm a
            per-session flag under runtime/.
  stop      Stop: if armed and project files changed since the last reviewed
            state, run one headless Kiro review, validate it, write the
            immutable artifact + LATEST.

Never blocks Claude: always exits 0, never emits decision/continue fields.
Runtime state lives under .review-channel/runtime/.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

EXCLUDED_DIRS = {".claude", ".kiro", ".review-channel", ".git",
                 # ponytail: caches, not implementation state
                 "node_modules", ".venv", "venv", "__pycache__",
                 ".pytest_cache", ".mypy_cache", ".ruff_cache"}
EXCLUDED_FILES = {".DS_Store"}
# Decision journal, regardless of eventual filename.
JOURNAL_RE = re.compile(r"(?i)journal|^decisions?([._\-]|$)")
TRIGGER_RE = re.compile(r"(?i)\breview\s+from\s+kiro\b")
REVIEW_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
REVIEW_KEYS = ("schema_version", "review_id", "created_at", "scope",
               "base_ref", "status", "summary", "findings")
FINDING_KEYS = ("id", "severity", "file", "line", "title", "evidence",
                "recommendation")
KIRO_BIN = os.environ.get("KIRO_BRIDGE_KIRO_BIN", "kiro-cli")  # test seam
KIRO_TIMEOUT = 840  # < 900s hook timeout
LOCK_STALE_SECS = 1800


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit(msg):
    print(json.dumps({"systemMessage": msg, "suppressOutput": True}))


class Bridge:
    def __init__(self, project_dir, session_id):
        self.root = Path(project_dir).resolve()
        self.session_id = session_id
        self.channel = self.root / ".review-channel"
        self.runtime = self.channel / "runtime"
        self.runtime.mkdir(parents=True, exist_ok=True)
        (self.channel / "reviews").mkdir(parents=True, exist_ok=True)
        self.arm_path = self.runtime / f"arm-{session_id}"
        self.last_reviewed_path = self.runtime / "last-reviewed.json"
        self.pending_path = self.runtime / "pending.json"
        self.reviewed_path = self.runtime / "reviewed.json"
        self.lock_path = self.runtime / "review.lock"
        self.log_path = self.runtime / "bridge.log"

    # ---- helpers -----------------------------------------------------------
    def log(self, msg):
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(f"{now_iso()} [{self.session_id}] {msg}\n")

    def read_json(self, path, default):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    def write_json_atomic(self, path, data):
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)

    # ---- fingerprint -------------------------------------------------------
    def fingerprint(self):
        files = {}
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames
                                 if d not in EXCLUDED_DIRS
                                 and not JOURNAL_RE.search(d)
                                 and not os.path.islink(os.path.join(dirpath, d)))
            for name in sorted(filenames):
                if name in EXCLUDED_FILES or JOURNAL_RE.search(name):
                    continue
                full = os.path.join(dirpath, name)
                if os.path.islink(full) or not os.path.isfile(full):
                    continue
                rel = os.path.relpath(full, self.root)
                h = hashlib.sha256()
                with open(full, "rb") as f:
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        h.update(chunk)
                files[rel] = h.hexdigest()
        combined = hashlib.sha256()
        for rel in sorted(files):
            combined.update(f"{rel}\0{files[rel]}\n".encode())
        return combined.hexdigest(), files

    def base_ref(self, last_fp):
        try:
            out = subprocess.run(["git", "-C", str(self.root), "rev-parse", "HEAD"],
                                 capture_output=True, text=True, timeout=10)
            if out.returncode == 0:
                return f"git:{out.stdout.strip()}"
        except (OSError, subprocess.SubprocessError):
            pass
        return f"fingerprint:{last_fp or 'initial'}"

    # ---- modes -------------------------------------------------------------
    def prompt_mode(self, text):
        if TRIGGER_RE.search(text or ""):
            self.arm_path.write_text(now_iso() + "\n", encoding="utf-8")
            self.log("armed by prompt trigger")

    def stop(self):
        if not self.arm_path.exists():
            return  # not requested this session; silent
        fp, files = self.fingerprint()
        last = self.read_json(self.last_reviewed_path, {"fingerprint": None, "files": {}})
        pending = self.read_json(self.pending_path, None)
        reviewed = self.read_json(self.reviewed_path, {})

        changed = sorted(
            k for k in set(files) | set(last["files"])
            if files.get(k) != last["files"].get(k))
        if not changed or fp in reviewed:
            why = "no change since last review" if not changed else f"already reviewed as {reviewed[fp]}"
            self.log(f"stop: {why} ({fp[:12]}), skip")
            emit(f"Kiro review skipped: {why}.")
            self.arm_path.unlink(missing_ok=True)
            if pending and pending.get("fingerprint") == fp:
                self.pending_path.unlink(missing_ok=True)
            return

        base_ref = self.base_ref(last["fingerprint"])
        pending = {"fingerprint": fp, "changed_files": changed, "base_ref": base_ref,
                   "attempts": (pending or {}).get("attempts", 0) + 1
                   if pending and pending.get("fingerprint") == fp else 1,
                   "updated_at": now_iso()}
        self.write_json_atomic(self.pending_path, pending)

        if not self.acquire_lock():
            self.log("stop: review lock held by another session, pending kept, still armed")
            return
        try:
            # Re-check dedupe under lock: another session may have just finished.
            if fp in self.read_json(self.reviewed_path, {}):
                self.pending_path.unlink(missing_ok=True)
                self.arm_path.unlink(missing_ok=True)
                return
            review_id = self.run_review(fp, changed, base_ref)
        except Exception as exc:  # keep pending + armed so a later Stop retries
            pending["last_error"] = str(exc)[:2000]
            self.write_json_atomic(self.pending_path, pending)
            self.log(f"stop: review failed, pending kept: {exc}")
            emit(f"Kiro review failed (will retry next Stop): {str(exc)[:200]}")
            return
        finally:
            self.lock_path.unlink(missing_ok=True)

        reviewed = self.read_json(self.reviewed_path, {})
        reviewed[fp] = review_id
        self.write_json_atomic(self.reviewed_path, reviewed)
        self.write_json_atomic(self.last_reviewed_path,
                               {"fingerprint": fp, "files": files, "review_id": review_id,
                                "at": now_iso()})
        self.pending_path.unlink(missing_ok=True)
        self.arm_path.unlink(missing_ok=True)
        self.log(f"stop: review {review_id} complete for {fp[:12]}")
        emit(f"Kiro review {review_id} ready; injected on next prompt.")

    # ---- lock --------------------------------------------------------------
    def acquire_lock(self):
        for _ in range(2):
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                with os.fdopen(fd, "w") as f:
                    json.dump({"pid": os.getpid(), "session_id": self.session_id,
                               "at": time.time()}, f)
                return True
            except FileExistsError:
                info = self.read_json(self.lock_path, {})
                pid, at = info.get("pid"), info.get("at", 0)
                alive = False
                if isinstance(pid, int):
                    try:
                        os.kill(pid, 0)
                        alive = True
                    except ProcessLookupError:
                        alive = False
                    except PermissionError:
                        alive = True
                if alive and time.time() - at < LOCK_STALE_SECS:
                    return False
                self.log("stale lock removed")
                self.lock_path.unlink(missing_ok=True)
        return False

    # ---- kiro --------------------------------------------------------------
    def run_review(self, fp, changed, base_ref):
        review_id = f"kiro-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{fp[:8]}"
        artifact = self.channel / "reviews" / f"{review_id}.json"
        scope = f"changed files since {base_ref}"
        prompt = self.prompt(review_id, scope, base_ref, changed)
        cmd = [KIRO_BIN, "chat", "--no-interactive", "--agent-engine", "v2",
               "--output-format", "stream-json", "--agent", "kiro-reviewer",
               "--trust-tools=fs_read", prompt]
        self.log(f"launching kiro review {review_id} for {len(changed)} files")
        proc = subprocess.run(cmd, cwd=self.root, capture_output=True, text=True,
                              timeout=KIRO_TIMEOUT, stdin=subprocess.DEVNULL)
        (self.runtime / "last-kiro-stdout.jsonl").write_text(proc.stdout, encoding="utf-8")
        (self.runtime / "last-kiro-stderr.txt").write_text(proc.stderr, encoding="utf-8")
        if proc.returncode != 0:
            raise RuntimeError(f"kiro-cli exit {proc.returncode}: {proc.stderr.strip()[:300]}")

        final_text = None
        for line in proc.stdout.splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") == "runFinished":
                data = ev.get("data", {})
                if data.get("status") != "success":
                    raise RuntimeError(f"kiro run status {data.get('status')}")
                final_text = data.get("finalText")
        if not final_text:
            raise RuntimeError("no runFinished.finalText in kiro output")

        review = self.parse_review(final_text)
        self.validate(review, review_id, base_ref)

        # Immutable artifact: create-exclusive, then read-only.
        fd = os.open(artifact, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o444)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(review, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.chmod(artifact, 0o444)
        if not artifact.is_file():
            raise RuntimeError("artifact missing after write")

        fd, tmp = tempfile.mkstemp(dir=self.channel, prefix=".LATEST-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(review_id + "\n")
        os.replace(tmp, self.channel / "LATEST")
        if (self.channel / "LATEST").read_text(encoding="utf-8").strip() != review_id:
            raise RuntimeError("LATEST does not point to new artifact")
        return review_id

    @staticmethod
    def parse_review(text):
        text = text.strip()
        m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
        if m:
            text = m.group(1)
        start = text.find("{")
        if start < 0:
            raise ValueError("kiro output contains no JSON object")
        dec = json.JSONDecoder()
        obj, _ = dec.raw_decode(text[start:])
        return obj

    @staticmethod
    def validate(review, review_id, base_ref):
        if not isinstance(review, dict):
            raise ValueError("review is not a JSON object")
        missing = [k for k in REVIEW_KEYS if k not in review]
        if missing:
            raise ValueError(f"review missing keys: {missing}")
        if review["schema_version"] != 1:
            raise ValueError("schema_version must be 1")
        if review["review_id"] != review_id:
            raise ValueError(f"review_id mismatch: {review['review_id']!r} != {review_id!r}")
        if review["base_ref"] != base_ref:
            raise ValueError("base_ref mismatch")
        for k in ("created_at", "scope", "status", "summary"):
            if not isinstance(review[k], str) or not review[k].strip():
                raise ValueError(f"{k} must be a non-empty string")
        if not isinstance(review["findings"], list):
            raise ValueError("findings must be an array")
        for i, f in enumerate(review["findings"]):
            if not isinstance(f, dict):
                raise ValueError(f"finding {i} is not an object")
            missing = [k for k in FINDING_KEYS if k not in f]
            if missing:
                raise ValueError(f"finding {i} missing keys: {missing}")
            if not isinstance(f["line"], int):
                raise ValueError(f"finding {i} line must be an integer")

    def prompt(self, review_id, scope, base_ref, changed):
        listing = "\n".join(f"- {p}" for p in changed)
        return f"""You are an independent code reviewer for this repository. You are a reviewer only.

Task: review the implementation state of the files listed below (they changed since the last review), plus any dependencies you need to read to understand them. Check the implementation against the product requirements in README.md and docs/architecture/02-hld.md.

Rules:
- Never modify, create, delete, or format any file. You have read-only access.
- Never access, read, review, summarize, rewrite, or comment on the owner's decision journal (any file whose name contains "journal" or starts with "decision"). If a listed path looks like a journal, skip it silently.
- Ignore .claude/, .kiro/, .review-channel/, .git/.
- Produce findings only. Claude Code decides whether and how to fix them. Do not propose patches as files.

Changed files:
{listing}

Output: respond with exactly ONE JSON object and nothing else (no prose, a ```json fence is acceptable). Use these exact values:
- "schema_version": 1
- "review_id": "{review_id}"
- "created_at": current UTC time, ISO 8601 like "2026-01-01T00:00:00Z"
- "scope": "{scope}"
- "base_ref": "{base_ref}"
- "status": "clean" if no findings, otherwise "findings"
- "summary": one paragraph string
- "findings": array; each finding has "id" (string like "F1"), "severity" (one of "critical","high","medium","low","info"), "file" (repo-relative path), "line" (integer, 0 if not line-specific), "title", "evidence" (what you observed, quote the code), "recommendation" (what Claude Code should consider).
"""


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        event = json.load(sys.stdin)
    except ValueError:
        event = {}
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd()
    session_id = re.sub(r"[^A-Za-z0-9._-]", "_", str(event.get("session_id") or "unknown"))
    bridge = Bridge(project_dir, session_id)
    try:
        if mode == "prompt":
            bridge.prompt_mode(event.get("prompt", ""))
        elif mode == "stop":
            if event.get("stop_hook_active"):
                bridge.log("stop: stop_hook_active, skip")
                return
            bridge.stop()
        else:
            bridge.log(f"unknown mode {mode!r}")
    except Exception as exc:
        bridge.log(f"{mode}: unhandled error: {exc}")
        emit(f"Kiro bridge {mode} error: {str(exc)[:200]}")


if __name__ == "__main__":
    main()
    sys.exit(0)
