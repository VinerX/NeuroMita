from styles.theme import get_theme


def get_gallery_stylesheet():
    theme = get_theme()
    return f"""
    QWidget#GalleryPage, QDialog#GalleryViewer {{ background: {theme['bg_root']}; }}
    QListView#GalleryGrid, QGraphicsView#GalleryImageView {{
        background: transparent; border: none; padding: 0;
    }}
    QLabel#GalleryTitle {{ font-size: 24px; font-weight: 700; color: {theme['text']}; }}
    QLabel#GalleryMuted {{ color: {theme['muted']}; background: transparent; border: none; }}
    QLabel#GalleryError {{ color: {theme['warn_text']}; background: transparent; border: none; }}
    QLabel#GalleryIcon {{ background: {theme['chip_hover']}; border-radius: 14px; }}
    QLabel#GalleryCount {{
        color: {theme['muted']}; background: {theme['chip_bg']};
        border-radius: 10px; padding: 6px 12px;
    }}
    QWidget#GalleryPage QPushButton, QDialog#GalleryViewer QPushButton {{
        min-height: 24px; padding: 6px 12px;
    }}
    QFrame#GalleryEmpty {{ background: transparent; border: none; }}
    """
