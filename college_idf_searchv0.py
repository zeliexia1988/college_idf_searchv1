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
        geolocator = Nominatim(user_agent="france_college_pivot_v1")
        location = geolocator.geocode(address + ", France") 
        if location: return (location.latitude, location.longitude)
        return None
    except Exception: return None

# --- 3. 核心数据透视逻辑 ---
@st.cache_data
def load_and_pivot_data():
    target_file = "fr-en-college-idf-language.xlsx"
    if not os.path.exists(target_file):
        files = [f for f in os.listdir('.') if f.endswith('.xlsx')]
        if files: target_file = files[0]
        else: return None

    try:
        df_raw = pd.read_excel(target_file, engine='openpyxl')
        df_raw.columns = [str(c).strip() for c in df_raw.columns]
        
        # 自动识别关键列名
        col_ens = next(c for c in df_raw.columns if 'enseignement' in c.lower())
        col_lang = next(c for c in df_raw.columns if 'langue' in c.lower())
        col_name = next(c for c in df_raw.columns if 'libellé' in c.lower())
        col_ips = next(c for c in df_raw.columns if 'ips' in c.lower())
        col_lat = next(c for c in df_raw.columns if 'latitude' in c.lower())
        col_lon = next(c for c in df_raw.columns if 'longitude' in c.lower())
        col_sect = next(c for c in df_raw.columns if 'secteur' in c.lower())
        col_comm = next(c for c in df_raw.columns if 'commune' in c.lower())
        col_addr = next((c for c in df_raw.columns if 'adresse' in c.lower()), col_comm)

        # --- 核心步骤：将多行学校数据合并为一行 ---
        # 1. 提取每个学校的基础信息（去重）
        base_info = df_raw[[col_name, col_comm, col_sect, col_ips, col_lat, col_lon, col_addr]].drop_duplicates(subset=[col_name])
        
        # 2. 分类提取语种
        def get_lang_list(ens_type):
            subset = df_raw[df_raw[col_ens].str.contains(ens_type, case=False, na=False)]
            return subset.groupby(col_name)[col_lang].apply(lambda x: list(set(x.astype(str).str.capitalize()))).reset_index()

        lv1_df = get_lang_list("LV1")
        lv2_df = get_lang_list("LV2")
        lca_df = get_lang_list("LCA")

        # 3. 合并所有信息到主表
        df = base_info.merge(lv1_df, on=col_name, how='left').rename(columns={col_lang: 'lv1_list'})
        df = df.merge(lv2_df, on=col_name, how='left').rename(columns={col_lang: 'lv2_list'})
        df = df.merge(lca_df, on=col_name, how='left').rename(columns={col_lang: 'lca_list'})

        # 填充空值
        for c in ['lv1_list', 'lv2_list', 'lca_list']:
            df[c] = df[c].apply(lambda x: x if isinstance(x, list) else [])

        # 转换坐标和IPS
        df['final_lat'] = pd.to_numeric(df[col_lat], errors='coerce')
        df['final_lon'] = pd.to_numeric(df[col_lon], errors='coerce')
        df['final_ips'] = pd.to_numeric(df[col_ips].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)

        # 提取菜单
        menus = {
            'lv1': sorted(list(set([l for sub in df['lv1_list'] for l in sub]))),
            'lv2': sorted(list(set([l for sub in df['lv2_list'] for l in sub]))),
            'lca': sorted(list(set([l for sub in df['lca_list'] for l in sub])))
        }

        # 颜色
        df['marker_color'] = df[col_sect].apply(lambda x: [0, 180, 0, 180] if 'public' in str(x).lower() else [230, 0, 0, 180])
        
        df.attrs.update({'cols': {'name': col_name, 'comm': col_comm, 'sect': col_sect, 'addr': col_addr}, 'menus': menus})
        return df.dropna(subset=['final_lat', 'final_lon'])
    except Exception as e:
        st.error(f"数据处理失败: {e}")
        return None

# --- 4. 界面渲染 ---
df = load_and_pivot_data()
st.sidebar.header("📍 1. 位置")
addr = st.sidebar.text_input("中心地址", "Paris")
home_coords = get_coords_from_address(addr) or (48.8566, 2.3522)
radius = st.sidebar.slider("半径 (km)", 1, 50, 10)

if df is not None:
    m = df.attrs['menus']
    c = df.attrs['cols']
    
    st.sidebar.markdown("---")
    st.sidebar.header("🎯 2. 课程筛选")
    l1 = st.sidebar.selectbox("语言一 (LV1 - 必选)", m['lv1'], index=m['lv1'].index("Anglais") if "Anglais" in m['lv1'] else 0)
    l2 = st.sidebar.selectbox("语言二 (LV2 - 选填)", ["无"] + m['lv2'])
    l3 = st.sidebar.selectbox("语言三 (LCA - 选填)", ["无"] + m['lca'])

    st.sidebar.markdown("---")
    st.sidebar.header("📊 3. 其他")
    sel_sect = st.sidebar.multiselect("性质", df[c['sect']].unique().tolist(), default=df[c['sect']].unique().tolist())
    sel_ips = st.sidebar.slider("IPS", float(df['final_ips'].min()), float(df['final_ips'].max()), (float(df['final_ips'].min()), float(df['final_ips'].max())))

    # --- 5. 过滤 ---
    df['dist'] = df.apply(lambda r: geodesic(home_coords, (r['final_lat'], r['final_lon'])).km, axis=1)
    
    mask = (df['dist'] <= radius) & (df['final_ips'] >= sel_ips[0]) & (df['final_ips'] <= sel_ips[1]) & (df[c['sect']].isin(sel_sect))
    mask &= df['lv1_list'].apply(lambda x: l1 in x)
    if l2 != "无": mask &= df['lv2_list'].apply(lambda x: l2 in x)
    if l3 != "无": mask &= df['lca_list'].apply(lambda x: l3 in x)
    
    res = df[mask].sort_values("dist")

    # --- 6. 展示 ---
    st.title("🏫 法国中学智能选择系统")
    cl, cr = st.columns([3, 2])
    
    with cl:
        st.subheader(f"清单 ({len(res)})")
        res['LV1'] = res['lv1_list'].apply(lambda x: ", ".join(x))
        res['LV2'] = res['lv2_list'].apply(lambda x: ", ".join(x))
        res['LCA'] = res['lca_list'].apply(lambda x: ", ".join(x))
        disp = [c['name'], c['comm'], c['sect'], 'final_ips', 'dist', 'LV1', 'LV2', 'LCA']
        st.dataframe(res[disp].rename(columns={'final_ips': 'IPS', 'dist': '距离(km)'}), use_container_width=True, hide_index=True)

    with cr:
        st.subheader("地图 (🟢公立 🔴私立)")
        if not res.empty:
            st.pydeck_chart(pdk.Deck(
                layers=[
                    pdk.Layer("ScatterplotLayer", res, get_position=["final_lon", "final_lat"], get_color="marker_color", get_radius=200, pickable=True),
                    pdk.Layer("ScatterplotLayer", pd.DataFrame([{"ln": home_coords[1], "lt": home_coords[0]}]), get_position=["ln", "lt"], get_color=[0, 100, 255], get_radius=400)
                ],
                initial_view_state=pdk.ViewState(latitude=home_coords[0], longitude=home_coords[1], zoom=11),
                tooltip={"text": "{"+c['name']+"}\nLV1: {LV1}\nLV2: {LV2}\nLCA: {LCA}\n地址: {"+c['addr']+"}"}
            ))
else:
    st.error("数据加载失败。")


