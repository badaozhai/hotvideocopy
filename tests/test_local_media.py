from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from hotvideocopy import local_models
from hotvideocopy import local_music
from hotvideocopy.local_music import arrange_song_lyrics


class SongStructureTests(unittest.TestCase):
    def test_abba_expands_to_ordered_ace_step_tags(self) -> None:
        structure, lyrics = arrange_song_lyrics(
            "A-B-B-A",
            {"A": ["第一段主歌", "收束主歌"], "B": "重复副歌"},
        )

        self.assertEqual(structure, "ABBA")
        self.assertEqual(
            lyrics,
            "[Verse 1]\n第一段主歌\n\n"
            "[Chorus 1]\n重复副歌\n\n"
            "[Chorus 2]\n重复副歌\n\n"
            "[Verse 2]\n收束主歌",
        )

    def test_structure_requires_every_section(self) -> None:
        with self.assertRaisesRegex(ValueError, "缺少 B 段歌词"):
            arrange_song_lyrics("BAB", {"A": "主歌"})

    def test_music_startup_stops_below_disk_reserve(self) -> None:
        with mock.patch.object(
            local_music.shutil,
            "disk_usage",
            return_value=SimpleNamespace(free=local_models.MIN_FREE_RESERVE - 1),
        ):
            with self.assertRaisesRegex(RuntimeError, "模型启动.*低于 1 GiB"):
                local_music._require_disk_reserve("模型启动")


class ModelRetentionTests(unittest.TestCase):
    def test_purge_is_rejected_without_explicit_user_confirmation(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "模型永久保留策略已启用"):
            local_models.purge("voice", "custom")

    def test_repeated_install_reuses_cache_without_network(self) -> None:
        estimate = {
            "component": "voice",
            "variant": "custom",
            "models": ["qwen3-tts-custom-8bit"],
            "estimated_total_bytes": 1,
            "already_present_bytes": 1,
            "estimated_additional_bytes": 0,
            "free_bytes": local_models.MIN_FREE_RESERVE,
            "reserve_bytes": local_models.MIN_FREE_RESERVE,
            "enough_space": False,
        }
        with (
            mock.patch.object(local_models, "estimate_install", return_value=estimate),
            mock.patch.object(local_models, "model_installed", return_value=True),
            mock.patch.object(local_models, "install_guard", return_value=contextlib.nullcontext()),
            mock.patch.object(local_models, "_record_install"),
            mock.patch.object(local_models, "_install_voice") as downloader,
        ):
            result = local_models.install("voice", "custom")

        downloader.assert_not_called()
        self.assertTrue(result["reused_cache"])
        self.assertFalse(result["network_used"])
        self.assertEqual(result["download_routes"][0]["actual"], "cache")


class ModelQueueTests(unittest.TestCase):
    def test_lock_is_exclusive_across_processes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hvc_model_lock_") as directory:
            root = Path(directory)
            lock = root / ".local_ai" / ".model-task.lock"
            lock.parent.mkdir(parents=True)
            with mock.patch.object(local_models, "MODEL_TASK_LOCK", lock):
                owner = local_models._try_model_task_lock("unit-test-owner")
                self.assertIsNotNone(owner)
                blocked = self._child_lock_result(root)
                local_models._release_model_task_lock(owner)
                acquired = self._child_lock_result(root)

        self.assertEqual(blocked, "blocked")
        self.assertEqual(acquired, "acquired")

    @staticmethod
    def _child_lock_result(root: Path) -> str:
        code = (
            "from hotvideocopy.local_models import _release_model_task_lock, "
            "_try_model_task_lock; "
            "fd = _try_model_task_lock('child'); "
            "print('acquired' if fd is not None else 'blocked'); "
            "_release_model_task_lock(fd) if fd is not None else None"
        )
        env = os.environ.copy()
        env.update({
            "HVC_NO_DOTENV": "1",
            "HVC_WORKSPACE": str(root),
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        })
        completed = subprocess.run(
            [sys.executable, "-c", code],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        return completed.stdout.strip()


if __name__ == "__main__":
    unittest.main()
