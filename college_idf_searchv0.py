import streamlit as st
import pandas as pd
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
import pydeck as pdk 
import os
import re

# --- 1. 页面配置 ---
st.set_page_config(page_title="法国中学智能选择系统", layout="wide")

# --- 2. 地理编码函数 ---
@st.cache_data
def get_coords_from_address(address):
    try:
        geolocator = Nominatim(user_agent="france_college_locator_v8")
        location = geolocator.geocode(address + ", France") 
        if location:
            return (location.latitude, location.longitude)
        return None
    except Exception:
        return None

# --- 3. 数据加载与核心解析逻辑 ---
@st.cache_data
def load_data():
    target_file = "fr-en-college-idf-language.xlsx"
    if not os.path.exists(target_file):
        files = [f for f in os.listdir('.') if f.endswith('.xlsx')]
        if files: target_file = files[0]
        else: return None

    try:
        df = pd.read_excel(target_file, engine='openpyxl')
        df.columns = [str(c).strip() for c in df.columns]
        
        def find_col(keywords):
            for col in df.columns:
                if any(k.lower() in col.lower() for k in keywords):
                    return col
            return None

        cols = {
            'ens': find_col(['Enseignements']),
            'ips': find_col(['IPS']),
            'secteur': find_col(['Secteur']),
            'lat': find_col(['Latitude']),
            'lon': find_col(['Longitude']),
            'name': find_col(['Libellé']), 
            'commune': find_col(['Commune']),
            'adresse': find_col(['Adresse'])
        }

        # --- 增强版解析逻辑：支持 LV1, LV2, LCA ---
        def parse_languages(text, category):
            if pd.isna(text): return []
            # category 可以是 LV1, LV2 或 LCA
            pattern = rf"{category}\s*[:：]\s*([^;|\n|/]+)"
            matches = re.findall(pattern, str(text), re.IGNORECASE)
            langs = []
            for m in matches:
                # 处理常见的连接词，统一转为列表
                for l in m.replace('ET', ',').replace('&', ',').split(','):
                    clean_l = l.strip().capitalize()
                    if clean_l: langs.append(clean_l)
            return list(set(langs))

        df['lv1_list'] = df[cols['ens']].apply(lambda x: parse_languages(x, "LV1"))
        df['lv2_list'] = df[cols['ens']].apply(lambda x: parse_languages(x, "LV2"))
        df['lca_list'] = df[cols['ens']].apply(lambda x: parse_languages(x, "LCA"))

        # 汇总各分类的语种菜单
        all_lv1 = sorted(list(set([lang for sublist in df['lv1_list'] for lang in sublist])))
        all_lv2 = sorted(list(set([lang for sublist in df['lv2_list'] for lang in sublist])))
        all_lca = sorted(list(set([lang for sublist in df['lca_list'] for lang in sublist])))

        # 基础数据转换
        df['final_lat'] = pd.to_numeric(df[cols['lat']], errors='coerce')
        df['final_lon'] = pd.to_numeric(df[cols['lon']], errors='coerce')
        df['final_ips'] = pd.to_numeric(df[cols['ips']].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)

        # 颜色逻辑
        def assign_color(row):
            s = str(row[cols['secteur']]).lower()
            return [0, 180, 0, 180] if 'public' in s else [230, 0, 0, 180]
        df['marker_color'] = df.apply(assign_color, axis=1)

        df.attrs.update({
            'cols': cols, 
            'lv1_menu': all_lv1, 
            'lv2_menu': all_lv2,
            'lca_menu': all_lca
        })
        return df.dropna(subset=['final_lat', 'final_lon'])
    except Exception as e:
        st.error(f"解析出错: {e}")
        return None

# --- 4. 侧边栏 ---
df_data = load_data()
st.sidebar.header("📍 1. 位置与半径")
address_str = st.sidebar.text_input("输入中心点", "Paris")
home_coords = get_coords_from_address(address_str) or (48.8566, 2.3522)
search_radius = st.sidebar.slider("半径 (km)", 1, 50, 10)

if df_data is not None:
    cfg = df_data.attrs['cols']
    st.sidebar.markdown("---")
    st.sidebar.header("🎯 2. 精确课程筛选")
    
    # 语言一 (必填) -> LV1
    lv1_menu = df_data.attrs['lv1_menu']
    lang1 = st.sidebar.selectbox("语言一 (必选 - LV1)", lv1_menu, 
                                index=lv1_menu.index("Anglais") if "Anglais" in lv1_menu else 0)
    
    # 语言二 (选填) -> LV2
    lv2_menu = ["无 (Optional)"] + df_data.attrs['lv2_menu']
    lang2 = st.sidebar.selectbox("语言二 (选填 - LV2)", lv2_menu, index=0)
    
    # 语言三 (选填) -> LCA (古代语言)
    lca_menu = ["无 (Optional)"] + df_data.attrs['lca_menu']
    lang3 = st.sidebar.selectbox("语言三 (选填 - LCA)", lca_menu, index=0)

    st.sidebar.markdown("---")
    st.sidebar.header("📊 3. 辅助筛选")
    all_s = df_data[cfg['secteur']].unique().tolist()
    sel_s = st.sidebar.multiselect("性质", all_s, default=all_s)
    min_i, max_i = float(df_data['final_ips'].min()), float(df_data['final_ips'].max())
    sel_ips = st.sidebar.slider("IPS 评分", min_i, max_i, (min_i, max_i))

    # --- 5. 计算与过滤 ---
    df_data['dist_km'] = df_data.apply(lambda r: geodesic(home_coords, (r['final_lat'], r['final_lon'])).km, axis=1)

    mask = (df_data['dist_km'] <= search_radius) & \
           (df_data['final_ips'] >= sel_ips[0]) & \
           (df_data['final_ips'] <= sel_ips[1]) & \
           (df_data[cfg['secteur']].isin(sel_s))
    
    # 精确匹配三个分类
    mask &= df_data['lv1_list'].apply(lambda x: lang1 in x)
    if lang2 != "无 (Optional)":
        mask &= df_data['lv2_list'].apply(lambda x: lang2 in x)
    if lang3 != "无 (Optional)":
        mask &= df_data['lca_list'].apply(lambda x: lang3 in x)

    res = df_data[mask].sort_values("dist_km")

    # --- 6. 展示 ---
    st.title("🏫 法国中学智能选择系统 (LV/LCA 增强版)")
    
    c1, c2 = st.columns([3, 2])
    with c1:
        st.subheader(f"📋 满足条件的学校 ({len(res)})")
        # 格式化显示
        res['LV1'] = res['lv1_list'].apply(lambda x: ", ".join(x))
        res['LV2'] = res['lv2_list'].apply(lambda x: ", ".join(x))
        res['LCA'] = res['lca_list'].apply(lambda x: ", ".join(x))
        
        show_cols = [cfg['name'], cfg['commune'], cfg['secteur'], 'final_ips', 'dist_km', 'LV1', 'LV2', 'LCA']
        st.dataframe(
            res[show_cols].rename(columns={cfg['name']: '学校', 'final_ips': 'IPS', 'dist_km': '距离(km)'}),
            use_container_width=True, height=600, hide_index=True 
        )

    with c2:
        st.subheader("🗺️ 地理分布 (🔵家 🟢公立 🔴私立)")
        if not res.empty:
            view = pdk.ViewState(latitude=home_coords[0], longitude=home_coords[1], zoom=11)
            layers = [
                pdk.Layer("ScatterplotLayer", res, get_position=["final_lon", "final_lat"], get_color="marker_color", get_radius=200, pickable=True),
                pdk.Layer("ScatterplotLayer", pd.DataFrame([{"ln": home_coords[1], "lt": home_coords[0]}]), get_position=["ln", "lt"], get_color=[0, 100, 255], get_radius=400)
            ]
            st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=view, 
                tooltip={"html": "<b>{Libellé}</b><br/>LV1: {LV1}<br/>LV2: {LV2}<br/>LCA: {LCA}<br/>地址: {Adresse}"}))
        else:
            st.info("💡 提示：没有学校同时满足该 LV1+LV2+LCA 的组合。")

    if not res.empty:
        st.download_button("📥 下载结果", res.to_csv(index=False).encode('utf-8-sig'), "college_results.csv")
else:
    st.error("无法加载数据。")


