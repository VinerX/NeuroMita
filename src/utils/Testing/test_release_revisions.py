from __future__ import annotations

import copy
import hashlib
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.publish_python_revision import PublicationError, embedded_version, publication_plan, publish_revision
from services.release_catalog import build_release_manifest, discover_release_catalog, parse_release_manifest
from services.release_revisions import parse_build_version, release_news_entries, release_tag_for_channel
from utils.release_assets import find_latest_unity_asset, parse_release, pick_from_release
import updater
from scripts import build_release_manifest as manifest_script


BASE = "v2026.10.15"
BUILD = "2026.10.15.1"
REPO = "Atm4x/NeuroMita"


def asset(name, asset_id=1, payload=b"old"):
    return {"id": asset_id, "name": name, "state": "uploaded", "size": len(payload),
            "digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
            "browser_download_url": f"https://github.com/{REPO}/releases/download/{BASE}/{name}"}


def release(*assets):
    return {"id": 100, "tag_name": BASE, "name": "NeuroMita 0.1.1 Alpha",
            "draft": False, "prerelease": False, "published_at": "2026-10-15T12:00:00Z",
            "html_url": f"https://github.com/{REPO}/releases/tag/{BASE}", "assets": list(assets)}


def revised_release():
    return release(asset(f"PythonBuild-v{BUILD}.zip"), asset(f"UnityBuild-{BASE}.zip", 2))


@pytest.mark.parametrize("version", ["2026.02.30", "2026.10.15.0", "2026.10.15.01", "2026.10.15-beta", "1.2.3", "2026.10.15.1.2"])
def test_publication_versions_are_unambiguous(version):
    assert parse_build_version(version) is None


def test_revision_order_is_numeric():
    assert parse_build_version("2026.10.15.10") > parse_build_version("2026.10.15.2")


def test_manifest_projects_python_revision_without_bumping_unity():
    manifest = build_release_manifest(REPO, [revised_release()], stable_tag=BASE)
    assert manifest["schema"] == 1
    assert manifest["channels"]["stable"] == "v" + BUILD
    assert release_tag_for_channel(manifest, "stable") == BASE
    python, unity = manifest["releases"]
    assert python["tag_name"] == "v" + BUILD
    assert python["release_tag"] == BASE
    assert python["component"] == "python"
    assert [item["name"] for item in python["assets"]] == [f"PythonBuild-v{BUILD}.zip"]
    assert unity["tag_name"] == BASE
    assert [item["name"] for item in unity["assets"]] == [f"UnityBuild-{BASE}.zip"]
    selected, _ = find_latest_unity_asset([parse_release(item) for item in manifest["releases"]], "stable")
    assert selected.tag == BASE


def test_repeated_rebuilds_and_parsing_keep_revision():
    raw = revised_release()
    first = build_release_manifest(REPO, [raw], stable_tag=BASE, generated_at="fixed")
    assert build_release_manifest(REPO, [raw], stable_tag=BASE, generated_at="fixed") == first
    assert parse_release_manifest(first, expected_repository=REPO) == first["releases"]
    assert build_release_manifest(REPO, first["releases"], stable_tag=BASE, generated_at="fixed") == first
    assert raw["tag_name"] == BASE


def test_partial_replacement_selects_highest_revision_and_discards_obsolete_patch():
    raw = release(asset(f"PythonBuild-{BASE}.zip"), asset(f"PythonBuild-{BASE}-Patch.zip", 2),
                  asset(f"PythonBuild-{BASE}.2.zip", 3), asset(f"PythonBuild-{BASE}.10.zip", 4))
    entries = build_release_manifest(REPO, [raw])["releases"]
    picked = pick_from_release(parse_release(entries[0]))
    assert entries[0]["tag_name"] == BASE + ".10"
    assert picked.python_full.name == f"PythonBuild-{BASE}.10.zip"
    assert picked.python_patch is None


def test_foreign_build_date_does_not_change_release_version():
    raw = release(asset("PythonBuild-v2026.12.01.1.zip"))
    assert build_release_manifest(REPO, [raw])["releases"][0]["tag_name"] == BASE


def test_unknown_schema_falls_back_to_api_and_still_discovers_revision():
    class Client:
        def get(self, url, **kwargs):
            data = {"schema": 999} if "latest/download" in url else [revised_release()]
            return SimpleNamespace(status_code=200, json=lambda: data)
    catalog = discover_release_catalog(REPO, client=Client())
    assert catalog.source == "github-api"
    assert catalog.releases[0]["tag_name"] == "v" + BUILD


def test_schema_one_consumer_can_compare_and_download_revision():
    manifest = build_release_manifest(REPO, [revised_release()])
    known_fields = {"tag_name", "name", "body", "prerelease", "published_at", "assets", "html_url"}
    legacy = [{key: value for key, value in entry.items() if key in known_fields} for entry in manifest["releases"]]
    python = next(parse_release(entry) for entry in legacy if pick_from_release(parse_release(entry)).python_full)
    assert updater._is_newer(python.tag, "2026.10.15")
    assert updater._is_newer(python.tag, "2026.08.31.1")
    assert not updater._is_newer(python.tag, BUILD)
    assert f"/download/{BASE}/" in pick_from_release(python).python_full.url


def test_updater_uses_effective_revision_from_manifest_or_api(monkeypatch):
    monkeypatch.setattr(updater, "_fetch_releases", lambda repo: build_release_manifest(REPO, [revised_release()])["releases"])
    monkeypatch.setattr(updater, "_get_update_target", lambda: SimpleNamespace(repo=REPO, channel="stable"))
    monkeypatch.setattr(updater, "_get_current_version", lambda: "2026.10.15")
    info = updater.get_python_update_info()
    assert info["available"]
    assert info["latest_version"] == "v" + BUILD
    assert info["release_tag"] == BASE


def test_news_keep_one_card_for_real_release():
    entries = build_release_manifest(REPO, [revised_release()])["releases"]
    news = release_news_entries(entries)
    assert len(news) == 1
    assert news[0]["tag_name"] == BASE
    assert news[0]["html_url"].endswith("/tag/" + BASE)
    assert len(news[0]["assets"]) == 2


def test_manifest_script_upload_output_keeps_physical_tag(tmp_path, monkeypatch):
    output = tmp_path / "manifest.json"
    github_output = tmp_path / "outputs.txt"
    monkeypatch.setattr(manifest_script, "fetch_all_releases", lambda *args: [revised_release()])
    monkeypatch.setattr(manifest_script, "fetch_latest_tag", lambda *args: BASE)
    monkeypatch.setattr(sys, "argv", ["build_release_manifest", "--repository", REPO,
                                     "--output", str(output), "--github-output", str(github_output)])
    assert manifest_script.main() == 0
    assert f"stable_tag={BASE}\n" in github_output.read_text()
    assert f"stable_tag=v{BUILD}\n" not in github_output.read_text()


def test_workflows_serialize_publication_and_preserve_the_full_build_path():
    import yaml

    workflow = yaml.load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    manifest = yaml.load((ROOT / ".github/workflows/release-manifest.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    job = workflow["jobs"]["build"]
    assert job["concurrency"]["group"] == manifest["concurrency"]["group"]
    assert list(workflow["jobs"]) == ["build"]
    assert workflow["on"]["push"]["branches"] == ["releases"]
    steps = {step["name"]: step for step in job["steps"]}
    assert "publication_mode == 'release'" in steps["Create GitHub Release"]["if"]
    assert "publication_mode == 'release'" in steps["Build changelog"]["if"]
    assert "publish_python_revision.py publish" in steps["Replace the Python archive in the existing release"]["run"]
    assert "BUILD_MODE=full" in steps["Create build.env"]["run"]
    checkout = manifest["jobs"]["rebuild"]["steps"][0]
    assert "'Atm4x/NeuroMita' && 'releases'" in checkout["with"]["ref"]


def test_publication_plan_targets_existing_release_without_creating_revision_tag():
    plan = publication_plan(BUILD, [release(asset(f"PythonBuild-{BASE}.zip"))])
    assert plan.should_release and plan.mode == "revision"
    assert plan.release_tag == BASE and plan.build_tag == "v" + BUILD


def test_revision_cannot_accidentally_create_a_new_release():
    with pytest.raises(PublicationError, match="existing published release"):
        publication_plan(BUILD, [])


def test_missing_revision_asset_is_not_confused_with_release_base_tag():
    assert publication_plan(BUILD, [release()]).should_release


def test_duplicate_revision_recovers_publication_without_rebuilding():
    plan = publication_plan(BUILD, [revised_release()])
    assert not plan.should_release
    assert plan.recover_revision


def test_plan_skips_downgrades_and_keeps_new_date_as_normal_release():
    raw = release(asset(f"PythonBuild-{BASE}.2.zip"))
    plan = publication_plan(BUILD, [raw])
    assert not plan.should_release and not plan.recover_revision
    assert publication_plan("2026.10.16", [raw]).mode == "release"
    assert publication_plan("2026.10.16", [raw]).should_release


def make_archive(path: Path, version=BUILD):
    pyz = io.BytesIO()
    with zipfile.ZipFile(pyz, "w") as application:
        application.writestr("__main__.py", "pass\n")
        application.writestr("_version.py", f'__version__ = "{version}"\n')
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("NeuroMita.pyz", pyz.getvalue())
        for name in ("requirements.txt", "run.py", "run.bat", "Launcher.exe", "libs/python/python.exe",
                     "Prompts/default.txt", "assets/icon.png"):
            package.writestr(name, "test")


class FakeAPI:
    def __init__(self, raw, *, bad_upload=False, fail_delete=False):
        self.raw = copy.deepcopy(raw)
        self.calls = []
        self.bad_upload = bad_upload
        self.fail_delete = fail_delete

    def release(self, tag):
        assert tag == BASE
        return copy.deepcopy(self.raw)

    def upload(self, tag, path):
        self.calls.append(("upload", path.name))
        uploaded = asset(path.name, 99, path.read_bytes())
        if self.bad_upload:
            uploaded["digest"] = "sha256:" + "0" * 64
        self.raw["assets"].append(uploaded)

    def delete(self, asset_id):
        self.calls.append(("delete", asset_id))
        if self.fail_delete:
            raise PublicationError("Interrupted deletion")
        self.raw["assets"] = [asset for asset in self.raw["assets"] if asset["id"] != asset_id]


def test_publish_uploads_verified_full_build_before_removing_old_python_assets(tmp_path):
    path = tmp_path / f"PythonBuild-v{BUILD}.zip"
    make_archive(path)
    api = FakeAPI(release(asset(f"PythonBuild-{BASE}.zip"), asset(f"PythonBuild-{BASE}-Patch.zip", 2),
                          asset(f"UnityBuild-{BASE}.zip", 3), asset("releases-manifest.json", 4)))
    publish_revision(api, BUILD, path)
    assert api.calls == [("upload", path.name), ("delete", 1), ("delete", 2)]
    assert {asset["id"] for asset in api.raw["assets"]} == {3, 4, 99}
    assert api.raw["tag_name"] == BASE


def test_failed_upload_verification_never_deletes_previous_build(tmp_path):
    path = tmp_path / f"PythonBuild-v{BUILD}.zip"
    make_archive(path)
    api = FakeAPI(release(asset(f"PythonBuild-{BASE}.zip")), bad_upload=True)
    with pytest.raises(PublicationError, match="differs"):
        publish_revision(api, BUILD, path)
    assert api.calls == [("upload", path.name)]
    assert api.raw["assets"][0]["id"] == 1


def test_interrupted_publication_can_be_recovered_without_local_archive(tmp_path):
    path = tmp_path / f"PythonBuild-v{BUILD}.zip"
    make_archive(path)
    api = FakeAPI(release(asset(f"PythonBuild-{BASE}.zip")), fail_delete=True)
    with pytest.raises(PublicationError, match="Interrupted"):
        publish_revision(api, BUILD, path)
    path.unlink()
    api.fail_delete = False
    publish_revision(api, BUILD, path)
    assert [asset["name"] for asset in api.raw["assets"]] == [path.name]


@pytest.mark.parametrize("version", ["2026.10.15", "2026.10.15.2"])
def test_mismatched_embedded_version_never_uploads(tmp_path, version):
    path = tmp_path / f"PythonBuild-v{BUILD}.zip"
    make_archive(path, version)
    api = FakeAPI(release(asset(f"PythonBuild-{BASE}.zip")))
    with pytest.raises(PublicationError, match="Embedded version"):
        publish_revision(api, BUILD, path)
    assert api.calls == []


def test_invalid_full_archive_is_rejected_before_upload(tmp_path):
    path = tmp_path / f"PythonBuild-v{BUILD}.zip"
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("only-a-patch.py", "pass")
    api = FakeAPI(release())
    with pytest.raises(PublicationError, match="contract"):
        publish_revision(api, BUILD, path)
    assert api.calls == []


def test_immutable_release_is_rejected_before_any_mutation(tmp_path):
    raw = release()
    raw["immutable"] = True
    with pytest.raises(PublicationError, match="immutable"):
        publication_plan(BUILD, [raw])
    api = FakeAPI(raw)
    with pytest.raises(PublicationError, match="mutable"):
        publish_revision(api, BUILD, tmp_path / f"PythonBuild-v{BUILD}.zip")
    assert api.calls == []


def test_remote_missing_digest_cannot_authorize_deleting_old_archive(tmp_path):
    raw = revised_release()
    raw["assets"][0].pop("digest")
    raw["assets"].append(asset(f"PythonBuild-{BASE}.zip", 3))
    api = FakeAPI(raw)
    with pytest.raises(PublicationError, match="SHA-256"):
        publish_revision(api, BUILD, tmp_path / f"PythonBuild-v{BUILD}.zip")
    assert api.calls == []


def test_newer_revision_is_never_replaced(tmp_path):
    api = FakeAPI(release(asset(f"PythonBuild-{BASE}.2.zip")))
    with pytest.raises(PublicationError, match="newer"):
        publish_revision(api, BUILD, tmp_path / f"PythonBuild-v{BUILD}.zip")
    assert api.calls == []


def test_newer_revision_appearing_during_upload_is_retained(tmp_path):
    class ConcurrentAPI(FakeAPI):
        def upload(self, tag, path):
            super().upload(tag, path)
            self.raw["assets"].append(asset(f"PythonBuild-{BASE}.2.zip", 101))
    path = tmp_path / f"PythonBuild-v{BUILD}.zip"
    make_archive(path)
    api = ConcurrentAPI(release(asset(f"PythonBuild-{BASE}.zip")))
    with pytest.raises(PublicationError, match="newer Python build appeared"):
        publish_revision(api, BUILD, path)
    assert api.calls == [("upload", path.name)]
