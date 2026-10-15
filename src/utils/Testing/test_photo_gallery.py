import os
import threading
import time
from datetime import datetime
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, QTimer
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QApplication, QStackedWidget, QWidget

from controllers.gui.gallery_page_view_model import (
    GalleryPageViewModel,
    read_gallery_image,
)
from controllers.gui.main_window_coordinator import MainWindowCoordinator
from services.photo_gallery import PhotoGallery
from ui.pages.gallery_page import GalleryPage
from ui.widgets.launcher_shell_sidebar import DEFAULT_SIDEBAR_SECTIONS
from ui.pages.gallery_presentation import GalleryPhotoLoaded, LoadGalleryPhoto
from updater import _copy_preserved_unity_data

_APP = None


@pytest.fixture
def app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    yield _APP
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def wait_for(app, predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert predicate()


def make_photo(directory, name="selfie_20260927_025102113.png"):
    directory.mkdir(parents=True, exist_ok=True)
    image = QImage(800, 450, QImage.Format.Format_RGB32)
    image.fill(QColor("#b74b7d"))
    path = directory / name
    assert image.save(str(path))
    return path


def test_directory_uses_shared_unity_install_location(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROMITA_BASE_DIR", str(tmp_path))
    gallery = PhotoGallery()
    assert gallery.directory() == tmp_path / "NeuroMita-Unity" / "Gallery"
    assert (
        gallery.directory(str(tmp_path / "CustomGame"))
        == tmp_path / "CustomGame" / "Gallery"
    )
    assert gallery.scan(tmp_path / "missing") == ()
    assert not (tmp_path / "missing").exists()


def test_gallery_is_in_sidebar_after_releases_and_built_by_coordinator(app):
    keys = [section.key for section in DEFAULT_SIDEBAR_SECTIONS]
    assert keys[keys.index("news") + 1] == "gallery"
    host = QWidget()
    host.page_map = {}
    host.page_stack = QStackedWidget(host)
    host._ensure_settings_animation = lambda: None
    presentation = SimpleNamespace(
        view_models=SimpleNamespace(
            gallery_page=lambda _: GalleryPageViewModel(settings={})
        )
    )
    coordinator = MainWindowCoordinator(host, presentation)
    try:
        page = coordinator.ensure_page("gallery", eager=True)
        assert isinstance(page, GalleryPage)
        assert host.gallery_page is page
        assert host.page_stack.indexOf(page) >= 0
        page._view_model.close()
    finally:
        host.deleteLater()


def test_scan_uses_capture_time_even_after_copying_and_sorts_newest_first(tmp_path):
    first = tmp_path / "selfie_20260818_205349615.png"
    second = tmp_path / "selfie_20260927_025102113.PNG"
    first.write_bytes(b"old")
    second.write_bytes(b"new")
    os.utime(first, (time.time() + 10000, time.time() + 10000))
    (tmp_path / "ignore.txt").write_text("ignored")
    (tmp_path / "not-a-photo.png").mkdir()
    photos = PhotoGallery().scan(tmp_path)
    assert [photo.path for photo in photos] == [second, first]
    assert photos[0].captured_at == datetime(2026, 9, 27, 2, 51, 2, 113000)
    assert all(photo.capture_time_known for photo in photos)


def test_non_selfie_or_invalid_timestamp_uses_file_date(tmp_path):
    path = tmp_path / "selfie_20269999_999999999.png"
    path.write_bytes(b"sample")
    (photo,) = PhotoGallery().scan(tmp_path)
    assert not photo.capture_time_known
    assert photo.captured_at == datetime.fromtimestamp(path.stat().st_mtime)


def test_open_folder_creates_only_gallery_inside_an_existing_installation(tmp_path):
    gallery = PhotoGallery()
    with pytest.raises(FileNotFoundError):
        gallery.ensure_directory(tmp_path / "MissingGame" / "Gallery")
    assert not (tmp_path / "MissingGame").exists()
    game = tmp_path / "Game"
    game.mkdir()
    assert gallery.ensure_directory(game / "Gallery") == game / "Gallery"
    assert (game / "Gallery").is_dir()


def test_thumbnail_is_small_and_broken_photo_does_not_fail_scan(tmp_path, app):
    path = make_photo(tmp_path)
    bad = tmp_path / "broken.png"
    bad.write_bytes(b"bad image")
    photos = {photo.path: photo for photo in PhotoGallery().scan(tmp_path)}
    image, error = read_gallery_image(photos[path], thumbnail=True)
    assert not error
    assert image.width() <= 640 and image.height() <= 420
    image, error = read_gallery_image(photos[bad], thumbnail=True)
    assert image.isNull() and error


def test_gallery_scan_keeps_qt_responsive_and_presents_results(tmp_path, app):
    folder = tmp_path / "Game" / "Gallery"
    make_photo(folder)
    entered = threading.Event()
    release = threading.Event()
    scan_threads = []

    class SlowGallery(PhotoGallery):
        def scan(self, directory):
            scan_threads.append(threading.get_ident())
            entered.set()
            release.wait(3)
            return super().scan(directory)

    vm = GalleryPageViewModel(
        settings={"UNITY_INSTALL_DIR": str(folder.parent)}, gallery=SlowGallery()
    )
    parent = QWidget()
    page = GalleryPage(parent, vm)
    try:
        page.on_activated()
        wait_for(app, entered.is_set)
        assert vm.state.loading
        assert (
            scan_threads == [scan_threads[0]]
            and scan_threads[0] != threading.get_ident()
        )
        ticks = []
        QTimer.singleShot(0, lambda: ticks.append(True))
        wait_for(app, lambda: bool(ticks))
        release.set()
        wait_for(app, lambda: not vm.state.loading)
        assert page.model.rowCount() == 1
        assert page.stack.currentIndex() == 0
        page.model.data(page.model.index(0), role=1)
        wait_for(app, lambda: bool(page.model._cache))
    finally:
        release.set()
        vm.close()
        parent.deleteLater()


def test_newer_photo_request_wins_when_previous_finishes_later(
    tmp_path, app, monkeypatch
):
    first = make_photo(tmp_path, "selfie_20260927_025102113.png")
    second = make_photo(tmp_path, "selfie_20260928_025102113.png")
    photos = {photo.path: photo for photo in PhotoGallery().scan(tmp_path)}
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def read(photo, **kwargs):
        if photo.path == first:
            entered.set()
            release.wait(3)
            finished.set()
        return QImage(2, 2, QImage.Format.Format_RGB32), ""

    monkeypatch.setattr(
        "controllers.gui.gallery_page_view_model.read_gallery_image", read
    )
    vm = GalleryPageViewModel(settings={})
    effects = []
    vm.effect_emitted.connect(effects.append)
    try:
        vm.dispatch(LoadGalleryPhoto(photos[first]))
        wait_for(app, entered.is_set)
        vm.dispatch(LoadGalleryPhoto(photos[second]))
        wait_for(app, lambda: bool(effects))
        release.set()
        wait_for(app, finished.is_set)
        app.processEvents()
        assert all(
            isinstance(effect, GalleryPhotoLoaded) and effect.photo.path == second
            for effect in effects
        )
    finally:
        release.set()
        vm.close()
        vm.deleteLater()


def test_unity_update_preserves_gallery_even_without_user_data(tmp_path):
    source = tmp_path / "Game"
    stage = tmp_path / "Stage"
    (source / "Gallery").mkdir(parents=True)
    (source / "Gallery" / "selfie.png").write_bytes(b"saved photo")
    stage.mkdir()
    _copy_preserved_unity_data(source, stage)
    assert (stage / "Gallery" / "selfie.png").read_bytes() == b"saved photo"


def test_gallery_detects_a_new_photo_without_manual_refresh(tmp_path, app):
    folder = tmp_path / "Game" / "Gallery"
    make_photo(folder)
    vm = GalleryPageViewModel(settings={"UNITY_INSTALL_DIR": str(folder.parent)})
    parent = QWidget()
    page = GalleryPage(parent, vm)
    try:
        page.on_activated()
        wait_for(app, lambda: not vm.state.loading)
        assert page.model.rowCount() == 1
        make_photo(folder, "selfie_20260928_025102113.png")
        wait_for(app, lambda: page.model.rowCount() == 2)
        assert page.model.photos[0].path.name == "selfie_20260928_025102113.png"
    finally:
        vm.close()
        parent.deleteLater()


def test_viewer_opens_navigates_and_supports_zoom(tmp_path, app):
    folder = tmp_path / "Game" / "Gallery"
    make_photo(folder)
    make_photo(folder, "selfie_20260928_025102113.png")
    vm = GalleryPageViewModel(settings={"UNITY_INSTALL_DIR": str(folder.parent)})
    parent = QWidget()
    page = GalleryPage(parent, vm)
    try:
        page.on_activated()
        wait_for(app, lambda: not vm.state.loading)
        page._open_photo(page.model.index(0))
        viewer = page._viewer
        wait_for(app, lambda: viewer.stack.currentIndex() == 1)
        assert viewer.index == 0
        viewer.navigate(1)
        wait_for(app, lambda: viewer.stack.currentIndex() == 1)
        assert viewer.index == 1
        assert not viewer.next.isEnabled()
        before = viewer.image_view.transform().m11()
        viewer.image_view.zoom(1.2)
        assert viewer.image_view.transform().m11() > before
        viewer.image_view.fit_image()
        assert viewer.image_view._fit
        viewer._update_metadata("EN")
        assert "800 × 450" in viewer.metadata.text()
        viewer.close()
        assert page._viewer is None
    finally:
        vm.close()
        parent.deleteLater()
