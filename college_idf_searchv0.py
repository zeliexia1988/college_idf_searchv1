import streamlit as st
import pandas as pd
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
import pydeck as pdk 
import os

# --- 1. 页面配置 ---
st.set_page_config(page_title="法国中学智能选择系统", layout="wide")

# --- 2. 地理编码函数 ---
@st.cache_data
def get_coords_from_address(address):
    try:
        geolocator = Nominatim(user_agent="france_college_locator_v6")
        location = geolocator.geocode(address + ", France") 
        if location:
            return (location.latitude, location.longitude)
        return None
    except Exception:
        return None

# --- 3. 数据加载与预处理 ---
@st.cache_data
def load_data():
    target_file = "fr-en-college-idf-language.xlsx"
    if not os.path.exists(target_file):
        files = [f for f in os.listdir('.') if f.endswith('.xlsx')]
        if files: target_file = files[0]
        else: return None

    try:
        df = pd.read_excel(target_file, engine='openpyxl')
        df.columns = [str(c).strip().replace('\n', '').replace('\r', '') for c in df.columns]
        
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
            'name': find_col(['Libellé']), 
            'commune': find_col(['Commune']),
            'adresse': find_col(['Adresse'])
        }

        df['final_lat'] = pd.to_numeric(df[cols['lat']], errors='coerce')
        df['final_lon'] = pd.to_numeric(df[cols['lon']], errors='coerce')
        
        if cols['ips']:
            df['final_ips'] = pd.to_numeric(df[cols['ips']].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
        else:
            df['final_ips'] = 0

        def assign_color(row):
            secteur_val = str(row[cols['secteur']]).lower()
            return [0, 180, 0, 180] if 'public' in secteur_val else [230, 0, 0, 180]

        df['marker_color'] = df.apply(assign_color, axis=1)
        
        # 提取唯一语种列表
        all_langs = set()
        if cols['lang']:
            for val in df[cols['lang']].dropna().astype(str):
                for l in val.replace(';', ',').split(','):
                    all_langs.add(l.strip())
        df.attrs['unique_langs'] = sorted(list(all_langs))
        df.attrs['cols_config'] = cols
        return df.dropna(subset=['final_lat', 'final_lon'])
    except Exception as e:
        st.error(f"加载数据出错: {e}")
        return None

# --- 4. 侧边栏交互 ---
st.sidebar.header("📍 1. 中心地址")
address_str = st.sidebar.text_input("输入您的地址/家", "Paris")

home_coords = get_coords_from_address(address_str)
if not home_coords:
    home_coords = (48.8566, 2.3522)

search_radius = st.sidebar.slider("搜索半径 (km)", 1, 50, 10)

df_data = load_data()

if df_data is not None:
    cfg = df_data.attrs['cols_config']
    unique_langs = df_data.attrs['unique_langs']
    
    st.sidebar.markdown("---")
    st.sidebar.header("🎯 2. 筛选过滤")
    
    all_secteurs = df_data[cfg['secteur']].unique().tolist() if cfg['secteur'] else []
    sel_secteurs = st.sidebar.multiselect("学校性质", all_secteurs, default=all_secteurs)
    
    min_v, max_v = float(df_data['final_ips'].min()), float(df_data['final_ips'].max())
    sel_ips = st.sidebar.slider("IPS 评分", min_v, max_v, (min_v, max_v))

    # --- 核心改进：三语种筛选逻辑 ---
    st.sidebar.subheader("📖 教学语种筛选")
    
    # 语言一：必填 (默认尝试匹配 Anglais)
    default_lang1 = "Anglais" if "Anglais" in unique_langs else unique_langs[0]
    lang1 = st.sidebar.selectbox("语言一 (必填)", unique_langs, index=unique_langs.index(default_lang1))
    
    # 语言二/三：可选
    options_optional = ["无 (Optional)"] + unique_langs
    lang2 = st.sidebar.selectbox("语言二 (选填)", options_optional, index=0)
    lang3 = st.sidebar.selectbox("语言三 (选填)", options_optional, index=0)

    # 计算距离
    df_data['dist_km'] = df_data.apply(lambda r: geodesic(home_coords, (r['final_lat'], r['final_lon'])).km, axis=1)

    # 基础过滤 (距离 + IPS + 性质)
    mask = (df_data['dist_km'] <= search_radius) & \
           (df_data['final_ips'] >= sel_ips[0]) & \
           (df_data['final_ips'] <= sel_ips[1])
    
    if sel_secteurs:
        mask &= df_data[cfg['secteur']].isin(sel_secteurs)
    
    # --- 核心改进：执行多重语言筛选 (AND 逻辑) ---
    if cfg['lang']:
        # 必须满足语言一
        mask &= df_data[cfg['lang']].str.contains(lang1, case=False, na=False)
        # 如果选了语言二，则必须也满足
        if lang2 != "无 (Optional)":
            mask &= df_data[cfg['lang']].str.contains(lang2, case=False, na=False)
        # 如果选了语言三，则必须也满足
        if lang3 != "无 (Optional)":
            mask &= df_data[cfg['lang']].str.contains(lang3, case=False, na=False)

    df_filtered = df_data[mask].sort_values("dist_km")

    # --- 5. 展示界面 ---
    st.title("🏫 法国中学智能选择系统")
    
    col_l, col_r = st.columns([3, 2])

    with col_l:
        st.subheader("📋 筛选清单")
        disp_cols = [cfg['name'], cfg['commune'], cfg['secteur'], 'final_ips', 'dist_km', cfg['lang']]
        actual_disp = [c for c in disp_cols if c and c in df_filtered.columns]
        
        st.dataframe(
            df_filtered[actual_disp].rename(columns={cfg['name']: '学校', 'final_ips': 'IPS', 'dist_km': '距离(km)'}),
            use_container_width=True, 
            height=600,
            hide_index=True 
        )

    with col_r:
        st.subheader("🗺️ 地理分布 (🔵家 🟢公立 🔴私立)")
        if not df_filtered.empty:
            school_layer = pdk.Layer(
                "ScatterplotLayer",
                df_filtered,
                get_position=["final_lon", "final_lat"],
                get_color="marker_color",
                get_radius=180,
                pickable=True,
            )
            
            home_layer = pdk.Layer(
                "ScatterplotLayer",
                pd.DataFrame([{"lon": home_coords[1], "lat": home_coords[0]}]),
                get_position=["lon", "lat"],
                get_color=[0, 100, 255, 255],
                get_radius=350,
                pickable=False,
            )
            
            tooltip_content = {
                "html": f"<b>学校:</b> {{{cfg['name']}}}<br/>"
                        f"<b>地址:</b> {{{cfg['adresse']}}}<br/>"
                        f"<b>城市:</b> {{{cfg['commune']}}}<br/>"
                        f"<b>距离:</b> {{dist_km:.2f}} km",
                "style": {"color": "white"}
            }
            
            st.pydeck_chart(pdk.Deck(
                layers=[school_layer, home_layer],
                initial_view_state=pdk.ViewState(latitude=home_coords[0], longitude=home_coords[1], zoom=11),
                tooltip=tooltip_content
            ))
        else:
            st.info("💡 没有学校同时满足这三种语言组合。请尝试减少选填语言或扩大半径。")

    if not df_filtered.empty:
        csv = df_filtered.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 下载结果", csv, "results.csv", "text/csv")
else:
    st.error("数据加载失败。")

