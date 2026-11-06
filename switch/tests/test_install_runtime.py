from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
import importlib.util
import io
import json
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "install_runtime.py"
SPEC = importlib.util.spec_from_file_location("install_runtime", MODULE_PATH)
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="arena installer ' ")
        self.addCleanup(self.temporary.cleanup)
        self.state = Path(self.temporary.name) / "engine state"
        for slot in ("a", "b"):
            root = self.state / "workers" / slot
            (root / "worktree" / ".git").mkdir(parents=True)
            (root / ".arena").mkdir()
            (root / ".arena" / "slot.token").write_text("DO_NOT_READ_OR_PRINT_TEST_SECRET")
        self.url = "http://127.0.0.1:8765"

    def root(self, slot="a"):
        return self.state / "workers" / slot

    def test_installs_only_role_b_materials_with_concrete_values_and_safe_commands(self):
        result = installer.install(self.state, self.url)
        self.assertEqual(result["mode"], "installed")
        self.assertEqual(result["native_smoke"], "not_run")
        self.assertEqual(result["shell_commands_use"], "POSIX")
        self.assertEqual(result["slots"]["a"]["instructions_file"], str(self.root() / ".arena" / "console-instructions.md"))
        for slot in ("a", "b"):
            root = self.root(slot)
            content = (root / ".arena" / "console-instructions.md").read_text()
            self.assertIn(f"Slot: `{slot}`", content)
            self.assertIn(str(root / ".arena" / "slot.token"), content)
            self.assertIn("MATCH_ID_PROVIDED_BY_OPERATOR", content)
            self.assertNotIn("DO_NOT_READ_OR_PRINT_TEST_SECRET", content)
            self.assertTrue((root / ".arena" / "bin" / "arena_client.py").is_file())
            self.assertTrue((root / ".arena" / "prompts" / "build.md").is_file())
            self.assertEqual(list((root / "worktree").iterdir()), [root / "worktree" / ".git"])
            for line in content.splitlines():
                if line.startswith("python3 "):
                    arguments = shlex.split(line)
                    self.assertEqual(arguments[0], "python3")
                    if "--expected-root" in arguments:
                        self.assertEqual(arguments[-1], str(root))
        self.assertFalse(result["credentials_read"])

    def test_check_does_not_write_or_create_destination_directories(self):
        result = installer.install(self.state, self.url, check=True)
        self.assertEqual(result["mode"], "check")
        self.assertTrue(all(item["action"] == "create" for item in result["files"]))
        for slot in ("a", "b"):
            self.assertEqual([p.name for p in (self.root(slot) / ".arena").iterdir()], ["slot.token"])

    def test_preflights_both_slots_before_any_write(self):
        (self.root("b") / ".arena" / "slot.token").unlink()
        with self.assertRaises(OSError):
            installer.install(self.state, self.url)
        self.assertFalse((self.root() / ".arena" / "bin").exists())

    def test_conflict_in_second_slot_prevents_first_slot_changes(self):
        destination = self.root("b") / ".arena" / "bin" / "arena_client.py"
        destination.parent.mkdir()
        destination.write_text("operator edited this")
        with self.assertRaises(installer.InstallError):
            installer.install(self.state, self.url)
        self.assertFalse((self.root() / ".arena" / "bin").exists())
        self.assertEqual(destination.read_text(), "operator edited this")

    def test_identical_install_is_idempotent_and_changed_files_need_replace(self):
        installer.install(self.state, self.url)
        result = installer.install(self.state, self.url)
        self.assertTrue(all(item["action"] == "unchanged" for item in result["files"]))
        changed = self.root() / ".arena" / "prompts" / "build.md"
        changed.write_text("changed")
        with self.assertRaises(installer.InstallError):
            installer.install(self.state, self.url)
        installer.install(self.state, self.url, replace=True)
        self.assertNotEqual(changed.read_text(), "changed")

    def test_symlink_destination_directory_or_file_is_refused_even_with_replace(self):
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        for location in [self.root() / ".arena" / "bin", self.root() / ".arena" / "console-instructions.md"]:
            with self.subTest(location=location):
                location.symlink_to(outside, target_is_directory=True)
                with self.assertRaises(installer.InstallError):
                    installer.install(self.state, self.url, replace=True)
                location.unlink()
        self.assertEqual(list(outside.iterdir()), [])

    def test_symlinked_slot_root_and_token_are_refused_without_read(self):
        token = self.root() / ".arena" / "slot.token"
        token.unlink()
        token.symlink_to(self.root("b") / ".arena" / "slot.token")
        with self.assertRaises(installer.InstallError):
            installer.install(self.state, self.url)
        self.assertFalse((self.root() / ".arena" / "bin").exists())

    def test_no_token_contents_are_read_or_printed(self):
        original = Path.read_bytes
        def safe_read(path):
            if path.name == "slot.token":
                raise AssertionError("token content read")
            return original(path)
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(Path, "read_bytes", safe_read), redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(installer.main(["--state-dir", str(self.state), "--api-url", self.url]), 0)
        self.assertNotIn("DO_NOT_READ_OR_PRINT_TEST_SECRET", output.getvalue() + errors.getvalue())
        self.assertFalse(json.loads(output.getvalue())["credentials_read"])

    def test_input_paths_and_urls_are_validated_without_writes(self):
        for path in [Path("relative-state"), self.state / ".." / "engine state", self.state / "missing"]:
            with self.subTest(path=path), self.assertRaises(installer.InstallError):
                installer.install(path, self.url)
        for url in ["ftp://host", "http://user:secret@host", "http://host:0", "http://host:99999", "http://host/api/v2", "http://host/api/v1?token=x", "http://host/#fragment", "http://bad host", "/api/v1"]:
            with self.subTest(url=url), self.assertRaises(installer.InstallError):
                installer.install(self.state, url)
        self.assertFalse((self.root() / ".arena" / "bin").exists())
        self.assertEqual(installer.api_url("https://EXAMPLE.test:8765/api/v1/"), "https://example.test:8765/api/v1")


if __name__ == "__main__":
    unittest.main()
