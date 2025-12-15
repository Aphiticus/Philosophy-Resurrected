-- schema.sql - SQLite schema for Philosophy Resurrected site

PRAGMA foreign_keys = ON;

-- albums: collection of album objects
CREATE TABLE IF NOT EXISTS albums (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    cover_path TEXT,   -- filename inside uploads/
    position INTEGER DEFAULT 0,
    created_at TEXT
);

-- tracks: audio files associated with an album
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    album_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    file_path TEXT NOT NULL,  -- filename in uploads/
    position INTEGER DEFAULT 0,
    created_at TEXT,
    FOREIGN KEY (album_id) REFERENCES albums(id) ON DELETE CASCADE
);

-- videos: music videos (file or external links can be stored in file_path)
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    file_path TEXT NOT NULL,
    thumbnail_path TEXT,
    description TEXT, -- Added for frontend compatibility
    position INTEGER DEFAULT 0,
    created_at TEXT
);

-- media: general uploaded images/banners/other assets
CREATE TABLE IF NOT EXISTS media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    file_path TEXT NOT NULL,
    kind TEXT,   -- image|audio|video
    position INTEGER DEFAULT 0,
    created_at TEXT
);

-- homepage_layout: ordered blocks for the homepage
-- type: 'hero', 'album', 'video', 'media', 'banner' etc.
CREATE TABLE IF NOT EXISTS homepage_layout (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    reference_id INTEGER,   -- references album/video/media id when applicable
    position INTEGER DEFAULT 0,
    created_at TEXT
);
