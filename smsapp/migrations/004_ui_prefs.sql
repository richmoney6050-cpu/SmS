-- Per-user appearance preferences (theme, light/dark mode, rainbow mode, custom colours) stored as JSON.
ALTER TABLE users ADD COLUMN ui_prefs TEXT;
