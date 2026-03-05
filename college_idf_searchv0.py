import streamlit as st
import pandas as pd
from geopy.distance import geodesic
from geopy.geocoders import Nominatim # 新增：用于地址转坐标
import os

# --- 1. 页面配置 ---
st.set_page_config(page_title="法国中学智能选择系统", layout="wide")

# --- 2. 地理编码函数 (地址转经纬度) ---
@st.cache_data
def get_coords_from_address(address):
    try:
        # 加上 user_agent 是为了符合 Nominatim 的使用政策
        geolocator = Nominatim(user_agent="college_search_app")
        location = geolocator.geocode(address)
        if location:
            return (location.latitude, location.longitude)
        return None
    except Exception as e:
        return None

# --- 3. 数据加载函数 (保持之前的容错逻辑) ---
@st.cache_data
def load_data():
    files = [f for f in os.listdir('.') if f.endswith('.xlsx')]
    target_file = "fr-en-college-idf-language.xlsx"
    
    if target_file not in files:
        if len(files) > 0: target_file = files[0]
        else: return None

    try:
        df = pd.read_excel(target_file, engine='openpyxl')
        df.columns = [str(c).strip().replace('\n', '').replace('\r', '') for c in df.columns]
        
        def get_col(keywords):
            for col in df.columns:
                if any(k.lower() in col.lower() for k in keywords):
                    return col
            return None

        cols = {
            'ips': get_col(['IPS']),
            'secteur': get_col(['Secteur']),
            'lat': get_col(['Latitude']),
            'lon': get_col(['Longitude']),
            'lang': get_col(['Langues']),
            'name': get_col(['Libellé', 'Nom']),
            'commune': get_col(['Commune'])
        }

        # 转换数字格式
        df['final_lat'] = pd.to_numeric(df[cols['lat']], errors='coerce')
        df['final_lon'] = pd.to_numeric(df[cols['lon']], errors='coerce')
        if cols['ips']:
            df['final_ips'] = pd.to_numeric(df[cols['ips']].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
        else:
            df['final_ips'] = 0

        df.attrs['cols'] = cols
        return df.dropna(subset=['final_lat', 'final_lon'])
    except Exception:
        return None

# --- 4. 侧边栏：地址输入 ---
st.sidebar.header("📍 1. 您的位置")
address_input = st.sidebar.text_input("请输入您的地址 (例如: Paris, Versailles, 或具体街道)", "Paris")

# 解析地址
coords = get_coords_from_address(address_input)

if coords:
    home_lat, home_lon = coords
    st.sidebar.success(f"已定位: {home_lat:.4f}, {home_lon:.4f}")
else:
    st.sidebar.warning("找不到该地址，已使用默认坐标 (巴黎)")
    home_lat, home_lon = 48.8566, 2.3522

home_coords = (home_lat, home_lon)
search_radius = st.sidebar.slider("搜索半径 (km)", 1, 50, 10)

# --- 5. 数据处理与筛选 ---
df_raw = load_data()

if df_raw is not None:
    c = df_raw.attrs['cols']
    
    st.sidebar.markdown("---")
    st.sidebar.header("🎯 2. 筛选条件")

    # 筛选：性质
    sel_secteur = []
    if c['secteur']:
        all_s = df_raw[c['secteur']].unique().tolist()
        sel_secteur = st.sidebar.multiselect("学校性质", all_s, default=all_s)

    # 筛选：IPS
    min_i, max_i = float(df_raw['final_ips'].min()), float(df_raw['final_ips'].max())
    if min_i == max_i: max_i += 1
    sel_ips = st.sidebar.slider("IPS 范围", min_i, max_i, (min_i, max_i))

    # 筛选：语言
    search_lang = st.sidebar.text_input("🔍 搜索语种 (如: Chinois)")

    # 计算距离
    df_raw['Distance_KM'] = df_raw.apply(lambda r: geodesic(home_coords, (r['final_lat'], r['final_lon'])).km, axis=1)

    # 过滤逻辑
    mask = (df_raw['Distance_KM'] <= search_radius) & (df_raw['final_ips'] >= sel_ips[0]) & (df_raw['final_ips'] <= sel_ips[1])
    if sel_secteur and c['secteur']:
        mask &= df







