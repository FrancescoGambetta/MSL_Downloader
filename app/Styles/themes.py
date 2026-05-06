DARK_THEMES = {
    "mars": {
        "bg": "#1a1814",
        "bg1": "rgba(200, 80, 20, 0.07)",
        "bg2": "rgba(255, 140, 40, 0.04)",
        "accent": "#c86020",
        "accent_soft": "#e8834a",
        "panel": "#221f1a",
        "surface": "#1e1b17",
        "text": "#f0ebe4",
    },
    "arctic": {
        "bg": "#101821",
        "bg1": "rgba(80, 170, 255, 0.11)",
        "bg2": "rgba(100, 220, 220, 0.07)",
        "accent": "#2e8fc7",
        "accent_soft": "#5ab9f0",
        "panel": "#18232e",
        "surface": "#15212b",
        "text": "#e8f4fb",
    },
    "sand": {
        "bg": "#241f17",
        "bg1": "rgba(210, 155, 65, 0.10)",
        "bg2": "rgba(255, 205, 120, 0.08)",
        "accent": "#be8b2f",
        "accent_soft": "#e2b25b",
        "panel": "#30281d",
        "surface": "#2a2319",
        "text": "#f6eddc",
    },
    "nebula": {
        "bg": "#11131c",
        "bg1": "rgba(90, 120, 255, 0.10)",
        "bg2": "rgba(50, 200, 230, 0.07)",
        "accent": "#4c76d8",
        "accent_soft": "#79a3ff",
        "panel": "#1a2030",
        "surface": "#171d2a",
        "text": "#e8eefc",
    },
}

LIGHT_THEMES = {
    "paper": {
        "bg": "#f4f1ea",
        "bg1": "rgba(220, 170, 90, 0.20)",
        "bg2": "rgba(180, 210, 245, 0.16)",
        "accent": "#9a5a1f",
        "accent_soft": "#b7753b",
        "panel": "#fff9ef",
        "surface": "#f8f4eb",
        "text": "#2a221b",
    },
    "ice": {
        "bg": "#eef5fa",
        "bg1": "rgba(90, 170, 225, 0.16)",
        "bg2": "rgba(110, 210, 210, 0.12)",
        "accent": "#2f7296",
        "accent_soft": "#4f8eb0",
        "panel": "#f7fbff",
        "surface": "#f1f8ff",
        "text": "#1e2a35",
    },
    "sage_light": {
        "bg": "#edf3ee",
        "bg1": "rgba(100, 170, 120, 0.14)",
        "bg2": "rgba(170, 210, 150, 0.12)",
        "accent": "#4d7f5e",
        "accent_soft": "#69977a",
        "panel": "#f6fbf7",
        "surface": "#edf5ef",
        "text": "#203027",
    },
}

MODE_THEMES = {
    "dark": DARK_THEMES,
    "light": LIGHT_THEMES,
}

DEFAULT_MODE = "dark"
DEFAULT_THEME_BY_MODE = {
    "dark": "mars",
    "light": "paper",
}


def normalize_mode(mode_name):
    return mode_name if mode_name in MODE_THEMES else DEFAULT_MODE


def theme_names(mode_name):
    mode = normalize_mode(mode_name)
    return list(MODE_THEMES[mode].keys())


def get_theme(mode_name, theme_name):
    mode = normalize_mode(mode_name)
    themes = MODE_THEMES[mode]
    default_theme = DEFAULT_THEME_BY_MODE[mode]
    return themes.get(theme_name, themes[default_theme])
