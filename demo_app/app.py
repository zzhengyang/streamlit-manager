from __future__ import annotations

import io
import time

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st


st.set_page_config(page_title="Demo Streamlit App", page_icon="🧪", layout="wide")

st.title("Demo Streamlit App")
st.caption("用于验证托管平台：依赖安装、端口启动、日志、编辑/重启等功能。")

with st.sidebar:
    st.subheader("参数")
    n = st.slider("生成点数量", min_value=50, max_value=2000, value=300, step=50)
    seed = st.number_input("随机种子", min_value=0, max_value=9999, value=42, step=1)
    noise = st.slider("噪声", min_value=0.0, max_value=3.0, value=0.8, step=0.1)
    simulate = st.toggle("模拟耗时任务", value=False)

    st.divider()
    st.subheader("会话状态")
    if "counter" not in st.session_state:
        st.session_state.counter = 0
    c1, c2 = st.columns(2)
    with c1:
        if st.button("计数 +1", use_container_width=True):
            st.session_state.counter += 1
    with c2:
        if st.button("清空", use_container_width=True):
            st.session_state.counter = 0
    st.metric("counter", st.session_state.counter)


if simulate:
    with st.spinner("模拟耗时任务中..."):
        time.sleep(1.2)

np.random.seed(int(seed))
x = np.linspace(0, 10, int(n))
y = np.sin(x) + np.random.normal(scale=float(noise), size=int(n))
df = pd.DataFrame({"x": x, "y": y})

left, right = st.columns([1, 1], gap="large")

with left:
    st.subheader("数据预览")
    st.dataframe(df.head(100), use_container_width=True, height=420)
    st.download_button(
        "下载 CSV",
        data=df.to_csv(index=False).encode("utf-8"),
        file_name="demo.csv",
        mime="text/csv",
        use_container_width=True,
    )

with right:
    st.subheader("图表（Altair）")
    chart = (
        alt.Chart(df)
        .mark_line()
        .encode(x="x:Q", y="y:Q", tooltip=["x:Q", "y:Q"])
        .properties(height=420)
        .interactive()
    )
    st.altair_chart(chart, use_container_width=True)


st.divider()
st.subheader("上传并解析 CSV（演示文件上传）")
up = st.file_uploader("上传 CSV（任意列都可）", type=["csv"])
if up is not None:
    try:
        content = up.getvalue()
        df_up = pd.read_csv(io.BytesIO(content))
        st.success(f"读取成功：{df_up.shape[0]} 行 × {df_up.shape[1]} 列")
        st.dataframe(df_up.head(200), use_container_width=True, height=360)
    except Exception as e:
        st.error(f"解析失败：{e}")


st.divider()
st.subheader("服务信息")
st.write({"streamlit_version": st.__version__})


