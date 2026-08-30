# -*- coding: utf-8 -*-
"""特許カジノ — Streamlit配信用ラッパー

    streamlit run app.py

ゲーム本体は index.html（src/template.html から build.py で生成）にある。
Streamlit のウィジェットで組み直すと、1タップごとにサーバー往復と全画面再描画が
入ってテンポが死ぬため、ここでは HTML をそのまま埋め込んで配信するだけにしている。

問題データを増やしたら data/ に JSON を置いて `python3 build.py` を実行すること。
"""
import io
import os

import streamlit as st
import streamlit.components.v1 as components

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.join(HERE, "index.html")

st.set_page_config(page_title="特許カジノ", page_icon="🎰",
                   layout="wide", initial_sidebar_state="collapsed")

# Streamlit 側の余白を消してゲームを画面いっぱいに出す
st.markdown("""
<style>
  .stApp { background:#071f18; }
  header[data-testid="stHeader"] { display:none; }
  .block-container { padding:0 !important; max-width:100% !important; }
  footer { display:none; }
  iframe { border:none; }
</style>
""", unsafe_allow_html=True)

if not os.path.exists(GAME):
    st.error("index.html がありません。`python3 build.py` を実行してください。")
    st.stop()

with io.open(GAME, encoding="utf-8") as f:
    html = f.read()

# スマホ縦画面が収まる高さ。iframe 内でスクロールさせる
components.html(html, height=1000, scrolling=True)
