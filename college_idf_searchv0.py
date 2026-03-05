import streamlit as st
import pandas as pd
from geopy.distance import geodesic
import os

# --- 页面配置 ---
st.set_page_config(page_title="法国中学智能选择系统", layout="wide")

# --- 容错文件读取函数 ---
@st.cache_data
def load_data():
    # 尝试在当前目录下寻找所有可能的 Excel 文件
    files = [f for f in os.listdir('.') if f.endswith('.xlsx')]
    target_file = "fr-en-college-idf-language.xlsx"
    
    if target_file not in files:
        if len(files) > 0:
            st.warning(f"找不到 {target_file}，尝试读取目录下的其他文件: {files[0]}")
            target_file = files[0]
        else:
            st.error("❌ 仓库根目录下未找到任何 .xlsx 文件！")
            return None

    try:
        df = pd.read_excel(target_file, engine='openpyxl')
        # 深度清洗列名：去除空格、换行符、统一引号
        df.columns = [str(c).strip().replace('\n', '').replace('\r', '') for c in df.columns]
        
        # 模糊定位列名函数
        def get_col(keywords):
            for col in df.columns:
                if any(k.lower() in col.lower() for k in keywords):
                    return col
            return None

        # 核心列名对齐
        cols = {
            'ips': get_col(['IPS']),
            'secteur': get_col(['Secteur']),
            'lat': get_col(['Latitude']),
            'lon': get_col(['Longitude']),
            'lang': get_col(['Langues']),
            'name': get_col(['Libellé', 'Nom', 'UAI']),
            'commune': get_col(['Commune'])
        }

        # 数据清洗：坐标与 IPS 转为数字
        if cols['lat'] and cols['lon']:
            df['final_lat'] = pd.to_numeric(df[cols['lat']], errors='coerce')
            df['final_lon'] = pd.to_numeric(df[cols['lon']], errors='coerce')
        else:
            st.error(f"❌ 找不到坐标列。当前检测到的列有：{df.columns.tolist()}")
            return None

        if cols['ips']:
            df['final_ips'] = pd.to_numeric(df[cols['ips']].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
        else:
            df['final_ips'] = 0

        df.attrs['cols'] = cols
        return df.dropna(subset=['final_lat', 'final_lon'])
    except Exception as e:
        st.error(f"❌ 加载失败: {e}")
        return None

# --- 执行加载 ---
df_raw = load_data()

if df_raw is not None:
    c = df_raw.attrs['cols']
    
    # --- 侧边栏 ---
    st.sidebar.header("📍 1. 您的位置")
    home_lat = st.sidebar.number_input("纬度", value=48.8566, format="%.6f")
    home_lon = st.sidebar.number_input("经度", value=2.3522, format="%.6f")
    search_radius = st.sidebar.slider("半径 (km)", 1, 50, 10)

    st.sidebar.markdown("---")
    st.sidebar.header("🎯 2. 筛选条件")

    # 动态筛选：Secteur
    sel_secteur = []
    if c['secteur']:
        all_s = df_raw[c['secteur']].unique().tolist()
        sel_secteur = st.sidebar.multiselect("学校性质", all_s, default=all_s)

    # 动态筛选：IPS
    min_i, max_i = float(df_raw['final_ips'].min()), float(df_raw['final_ips'].max())
    if min_i == max_i: max_i += 1
    sel_ips = st.sidebar.slider("IPS 范围", min_i, max_i, (min_i, max_i))

    # 语言搜索
    search_lang = st.sidebar.text_input("🔍 搜索语种 (如: Anglais)")

    # --- 距离计算 ---
    df_raw['Distance_KM'] = df_raw.apply(lambda r: geodesic((home_lat, home_lon), (r['final_lat'], r['final_lon'])).km, axis=1)

    # --- 过滤逻辑 ---
    mask = (df_raw['Distance_KM'] <= search_radius) & (df_raw['final_ips'] >= sel_ips[0]) & (df_raw['final_ips'] <= sel_ips[1])
    if sel_secteur and c['secteur']:
        mask &= df_raw[c['secteur']].isin(sel_secteur)
    if search_lang and c['lang']:
        mask &= df_raw[c['lang']].str.contains(search_lang, case=False, na=False)

    res = df_raw[mask].sort_values("Distance_KM")

    # --- 展示 ---
    st.title("🏫 法国中学智能选择系统")
    m1, m2 = st.columns(2)
    m1.metric("匹配学校", len(res))
    if not res.empty: m2.metric("最近距离", f"{res['Distance_KM'].min():.2f} km")

    col_l, col_r = st.columns([3, 2])
    with col_l:
        display_list = [c['name'], c['commune'], c['secteur'], 'final_ips', 'Distance_KM', c['lang']]
        actual_list = [i for i in display_list if i and i in res.columns]
        st.dataframe(res[actual_list].rename(columns={'final_ips': 'IPS'}), use_container_width=True, height=500)

    with col_r:
        if not res.empty:
            st.map(res.rename(columns={'final_lat': 'lat', 'final_lon': 'lon'})[['lat', 'lon']])
        else:
            st.info("无匹配结果")






