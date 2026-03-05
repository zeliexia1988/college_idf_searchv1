import streamlit as st
import pandas as pd
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
import os

# --- 1. 页面配置 ---
st.set_page_config(page_title="法国中学智能选择系统", layout="wide")

# --- 2. 地理编码函数 (地址转经纬度) ---
@st.cache_data
def get_coords_from_address(address):
    try:
        # Nominatim 需要 user_agent 避免 403 错误
        geolocator = Nominatim(user_agent="france_college_locator_v1")
        location = geolocator.geocode(address + ", France") # 自动限定在法国范围内
        if location:
            return (location.latitude, location.longitude)
        return None
    except Exception:
        return None

# --- 3. 增强型数据加载函数 ---
@st.cache_data
def load_data():
    target_file = "fr-en-college-idf-language.xlsx"
    # 如果找不到特定文件，寻找目录下第一个 .xlsx
    if not os.path.exists(target_file):
        files = [f for f in os.listdir('.') if f.endswith('.xlsx')]
        if files: target_file = files[0]
        else: return None

    try:
        df = pd.read_excel(target_file, engine='openpyxl')
        # 彻底清洗列名
        df.columns = [str(c).strip().replace('\n', '').replace('\r', '') for c in df.columns]
        
        # 智能对齐列名，避免 KeyError
        def find_col(keywords):
            for col in df.columns:
                if any(k.lower() in col.lower() for k in keywords):
                    return col
            return None

        cols = {
            'ips': find_col(['IPS']),
            'secteur': find_col(['Secteur']),
            'lat': find_col(['Latitude']),
            'lon': find_col(['Longitude']),
            'lang': find_col(['Langues']),
            'name': find_col(['Libellé', 'Nom', 'UAI']),
            'commune': find_col(['Commune'])
        }

        # 数据预处理
        df['final_lat'] = pd.to_numeric(df[cols['lat']], errors='coerce')
        df['final_lon'] = pd.to_numeric(df[cols['lon']], errors='coerce')
        
        if cols['ips']:
            # 处理法国格式数字 (如 120,5 -> 120.5)
            df['final_ips'] = pd.to_numeric(df[cols['ips']].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
        else:
            df['final_ips'] = 0

        # 将列名配置存入 DataFrame
        df.attrs['cols_config'] = cols
        return df.dropna(subset=['final_lat', 'final_lon'])
    except Exception as e:
        st.error(f"加载数据出错: {e}")
        return None

# --- 4. 侧边栏交互 ---
st.sidebar.header("📍 1. 中心地址")
address_str = st.sidebar.text_input("输入中心点 (地址、邮编或城市)", "Paris")

# 获取坐标
home_coords = get_coords_from_address(address_str)
if home_coords:
    st.sidebar.success(f"定位成功: {home_coords[0]:.4f}, {home_coords[1]:.4f}")
else:
    st.sidebar.warning("找不到该地址，已使用巴黎默认坐标")
    home_coords = (48.8566, 2.3522)

search_radius = st.sidebar.slider("搜索半径 (km)", 1, 50, 10)

# --- 5. 数据处理 ---
df_data = load_data()

if df_data is not None:
    cfg = df_data.attrs['cols_config']
    
    st.sidebar.markdown("---")
    st.sidebar.header("🎯 2. 筛选过滤")

    # 学校性质筛选
    all_secteurs = df_data[cfg['secteur']].unique().tolist() if cfg['secteur'] else []
    sel_secteurs = st.sidebar.multiselect("学校性质", all_secteurs, default=all_secteurs)

    # IPS 范围筛选
    min_v = float(df_data['final_ips'].min())
    max_v = float(df_data['final_ips'].max())
    sel_ips = st.sidebar.slider("IPS 评分", min_v, max_v, (min_v, max_v))

    # 语种关键词搜索
    search_lang = st.sidebar.text_input("🔍 搜语种 (如: Chinois)")

    # --- 核心计算与过滤 ---
    # 计算所有点到中心点的距离
    df_data['dist_km'] = df_data.apply(lambda r: geodesic(home_coords, (r['final_lat'], r['final_lon'])).km, axis=1)

    # 逻辑过滤：确保每一条都是布尔序列
    mask = (df_data['dist_km'] <= search_radius) & \
           (df_data['final_ips'] >= sel_ips[0]) & \
           (df_data['final_ips'] <= sel_ips[1])
    
    if sel_secteurs and cfg['secteur']:
        mask = mask & (df_data[cfg['secteur']].isin(sel_secteurs))
    
    if search_lang and cfg['lang']:
        mask = mask & (df_data[cfg['lang']].str.contains(search_lang, case=False, na=False))

    # 应用过滤结果
    df_filtered = df_data[mask].sort_values("dist_km")

    # --- 6. 结果展示 ---
    st.title("🏫 法国中学智能选择系统")
    
    m1, m2, m3 = st.columns(3)
    m1.metric("匹配学校", len(df_filtered))
    m2.metric("当前中心", address_str)
    if not df_filtered.empty:
        m3.metric("最近距离", f"{df_filtered['dist_km'].min():.2f} km")

    st.markdown("---")
    c_left, c_right = st.columns([3, 2])

    with c_left:
        st.subheader("📋 详细信息清单")
        # 组装展示列
        disp_cols = [cfg['name'], cfg['commune'], cfg['secteur'], 'final_ips', 'dist_km', cfg['lang']]
        actual_disp = [c for c in disp_cols if c and c in df_filtered.columns]
        
        st.dataframe(
            df_filtered[actual_disp].rename(columns={'final_ips': 'IPS', 'dist_km': '距离(km)'}),
            use_container_width=True,
            height=500
        )

    with c_right:
        st.subheader("🗺️ 地理分布图")
        if not df_filtered.empty:
            map_data = df_filtered.rename(columns={'final_lat': 'lat', 'final_lon': 'lon'})[['lat', 'lon']]
            st.map(map_data)
        else:
            st.info("该范围内没有符合条件的学校。")

    if not df_filtered.empty:
        csv = df_filtered.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 下载筛选出的数据 (CSV)", csv, "search_results.csv", "text/csv")
else:
    st.error("无法加载 Excel 数据，请检查文件名称和 GitHub 路径。")



