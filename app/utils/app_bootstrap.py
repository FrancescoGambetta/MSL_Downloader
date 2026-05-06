from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

UTILS_DIR = Path(__file__).resolve().parent
APP_DIR = UTILS_DIR.parent
PROJECT_ROOT = APP_DIR.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from i18n_helper import load_i18n, translate

CORE_DIR = PROJECT_ROOT / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from catalog_runner import CatalogUpdateOptions, run_catalog_update  # type: ignore

st.set_page_config(page_title="DWNAPP Real Dashboard Bootstrap", layout="wide")
I18N = load_i18n(str(APP_DIR / "i18n_app.json"))


def t(key: str, **kwargs) -> str:
    lang = st.session_state.get("lang", "en")
    try:
        return translate(I18N, lang, key, **kwargs)
    except Exception:
        return key.format(**kwargs) if kwargs else key


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def resolve_runtime_paths() -> dict:
    cfg = load_json(PROJECT_ROOT / "config" / "runtime_paths.json")
    return {
        "catalog_json": (PROJECT_ROOT / cfg.get("catalog_json", "data/catalog/catalog.json")).resolve(),
        "catalog_parquet": (PROJECT_ROOT / cfg.get("catalog_parquet", "data/catalog/catalog.parquet")).resolve(),
        "intent_config": (PROJECT_ROOT / cfg.get("intent_config", "config/intent_config.json")).resolve(),
        "msl_catalog_config": (PROJECT_ROOT / cfg.get("msl_catalog_config", "config/msl_catalog_config.json")).resolve(),
    }


def load_catalog_df(parquet_path: Path) -> pd.DataFrame:
    if not parquet_path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(parquet_path)
    except Exception:
        return pd.DataFrame()


def main() -> None:
    st.title(t("bootstrap_title"))

    runtime = resolve_runtime_paths()
    df = load_catalog_df(runtime["catalog_parquet"])

    c1, c2, c3 = st.columns(3)
    c1.metric(t("bootstrap_rows"), int(len(df)))
    c2.metric(t("bootstrap_columns"), int(len(df.columns)))
    c3.metric(t("bootstrap_catalog_exists"), t("yes_label") if runtime["catalog_parquet"].exists() else t("no_label"))

    with st.expander(t("bootstrap_resolved_paths"), expanded=True):
        st.code("\n".join(f"{k}: {v}" for k, v in runtime.items()))

    st.subheader(t("bootstrap_catalog_update_trigger"))
    uc1, uc2, uc3 = st.columns(3)
    sol_start = uc1.number_input(t("sol_start"), min_value=0, value=3300, step=1)
    sol_end = uc2.number_input(t("sol_end"), min_value=0, value=3305, step=1)
    workers = uc3.number_input(t("bootstrap_workers"), min_value=1, value=8, step=1)

    cameras = st.multiselect(
        t("bootstrap_cameras"),
        options=["mastcam", "mahli", "navcam", "mardi", "hazcam"],
        default=["mastcam"],
    )

    if st.button(t("bootstrap_run_catalog_update"), width="stretch"):
        logs: list[str] = []

        def on_event(ev: dict) -> None:
            msg = str(ev.get("message", ""))
            if msg:
                logs.append(msg)

        with st.spinner(t("bootstrap_running_catalog_update")):
            res = run_catalog_update(
                project_root=PROJECT_ROOT,
                options=CatalogUpdateOptions(
                    config_path=runtime["msl_catalog_config"],
                    cameras=cameras or None,
                    sol_start=int(sol_start),
                    sol_end=int(sol_end),
                    workers=int(workers),
                ),
                event_callback=on_event,
            )

        if res.get("ok"):
            st.success(t("bootstrap_catalog_update_ok", code=res.get("return_code")))
        else:
            st.error(t("bootstrap_catalog_update_failed", code=res.get("return_code")))
        st.text("\n".join(logs[-40:]))

    st.subheader(t("bootstrap_data_preview"))
    if len(df) == 0:
        st.info(t("bootstrap_catalog_unavailable"))
    else:
        st.dataframe(df.head(30), width="stretch")


if __name__ == "__main__":
    main()
