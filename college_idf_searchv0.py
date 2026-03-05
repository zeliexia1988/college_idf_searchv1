import streamlit as st
import pandas as pd
from geopy.distance import geodesic

# --- 1. 页面配置 ---
st.set_page_config(page_title="法国中学智能选择系统", layout="wide")

# --- 2. 增强型数据加载函数 ---
@st.cache_data
def load_data(file_name):
    try:
        # 读取 Excel
        df = pd.read_excel(file_name, engine='openpyxl')
        
        # 【关键修复】清洗列名：去除空格、换行符、特殊引号
        df.columns = [
            str(c).strip().replace('\n', '').replace('\r', '').replace("’", "'") 
            for c in df.columns
        ]

        # 模糊匹配函数，解决 KeyError
        def find_col(keywords):
            for col in df.columns:
                if any(k.lower() in col.lower() for k in keywords):
                    return col
            return None

        # 智能对齐你的新列名
        col_ips = find_col(['IPS'])
        col_lat = find_col(['Latitude']) # 适配你新改的 Latitude
        col_lon = find_col(['Longitude']) # 适配你新改的 Longitude
        col_secteur = find_col(['Secteur']) # 适配 Secteur
        col_lang = find_col(['Langues'])
        col_name = find_col(['Libellé', 'Nom'])

        # 检查坐标列是否存在
        if not col_lat or not col_lon:
            st.error(f"❌ 找不到坐标列。当前检测到的列有：{df.columns.tolist()}")
            return None

        # --- 数据清洗 ---
        # 1. 坐标转数字
        df['final_lat'] = pd.to_numeric(df[col_lat], errors='coerce')
        df['final_lon'] = pd.to_numeric(df[col_lon], errors='coerce')
        
        # 2. IPS 转数字（处理法国逗号小数点）
        if col_ips:
            df['final_ips'] = pd.to_numeric(df[col_ips].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
        else:
            df['final_ips'] = 0

        # 3. 记录实际列名供后续 UI 使用
        df.attrs['actual_cols'] = {
            'secteur': col_secteur,
            'lang': col_lang,
            'name': col_name
        }

        # 移除无效行
        df = df.dropna(subset=['final_lat', 'final_lon'])
        return df

    except Exception as e:
        st.error(f"❌ 加载失败: {e}")
        return None

# --- 3. 初始化 ---
FILE_NAME = "fr-en-college-idf-language.xlsx"
df_raw = load_data(FILE_NAME)

if df_raw is not None:
    actual_cols = df_raw.attrs['actual_cols']
    
    # --- 4. 侧边栏 ---
    st.sidebar.header("📍 1. 您的位置")
    home_lat = st.sidebar.number_input("纬度 (Latitude)", value=48.8566, format="%.6f")
    home_lon = st.sidebar.number_input("经度 (Longitude)", value=2.3522, format="%.6f")
    home_coords = (home_lat, home_lon)

    search_radius = st.sidebar.slider("搜索半径 (km)", 1, 50, 10)

    st.sidebar.markdown("---")
    st.sidebar.header("🎯 2. 筛选条件")

    # 公私立筛选
    s_col = actual_cols['secteur']
    selected_secteur = []
    if s_col:
        all_secteurs = df_raw[s_col].unique().tolist()
        selected_secteur = st.sidebar.multiselect("学校性质", all_secteurs, default=all_secteurs)

    # IPS 筛选
    min_ips = float(df_raw['final_ips'].min())
    max_ips = float(df_raw['final_ips'].max())
    if min_ips == max_ips: max_ips += 1
    selected_ips = st.sidebar.slider("IPS 评分范围", min_ips, max_ips, (min_ips, max_ips))

    # 语言搜索
    search_lang = st.sidebar.text_input("🔍 搜索语种 (如: Anglais, Chinois)", "")

    # --- 5. 距离计算 ---
    def get_dist(row):
        return geodesic(home_coords, (row['final_lat'], row['final_lon'])).km

    df_raw['Distance_KM'] = df_raw.apply(get_dist, axis=1)

    # --- 6. 过滤逻辑 ---
    mask = (
        (df_raw['Distance_KM'] <= search_radius) &
        (df_raw['final_ips'] >= selected_ips[0]) &
        (df_raw['final_ips'] <= selected_ips[1])
    )
    
    if selected_secteur and s_col:
        mask = mask & df_raw[s_col].isin(selected_secteur)

    l_col = actual_cols['lang']
    if search_lang and l_col:
        mask = mask & df_raw[l_col].str.contains(search_lang, case=False, na=False)

    filtered_df = df_raw[mask].sort_values("Distance_KM")

    # --- 7. UI 展示 ---
    st.title("🏫 法国中学智能选择系统")
    
    m1, m2, m3 = st.columns(3)
    m1.metric("匹配学校", len(filtered_df))
    m2.metric("最大半径", f"{search_radius} km")
    if not filtered_df.empty:
        m3.metric("最近距离", f"{filtered_df['Distance_KM'].min():.2f} km")

    st.markdown("---")
    col_l, col_r = st.columns([3, 2])

    with col_l:
        st.subheader("📋 筛选清单")
        # 动态组装要显示的列
        show_cols = [actual_cols['name'], 'Commune', s_col, 'final_ips', 'Distance_KM', l_col]
        actual_show = [c for c in show_cols if c and c in filtered_df.columns]
        
        st.dataframe(
            filtered_df[actual_show].rename(columns={'final_ips': 'IPS'}),
            use_container_width=True,
            height=500
        )

    with col_r:
        st.subheader("🗺️ 地理分布")
        if not filtered_df.empty:
            map_data = filtered_df.rename(columns={'final_lat': 'lat', 'final_lon': 'lon'})
            st.map(map_data[['lat', 'lon']])
        else:
            st.info("无匹配结果。")

    if not filtered_df.empty:
        csv = filtered_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 下载结果 (CSV)", csv, "results.csv", "text/csv")
else:
    st.error(f"未能找到数据文件: {FILE_NAME}，请确保它在 GitHub 仓库根目录。")






